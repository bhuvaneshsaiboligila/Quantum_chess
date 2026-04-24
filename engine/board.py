"""
engine/board.py – QuantumBoard: the central game state.

Wires together:
  - classical_board  (chess.Board)  – only fully-collapsed pieces
  - quantum_state    (QuantumState) – superposed pieces
  - measurement      (MeasurementSystem)
  - rules            (RuleEngine)

Apply-move methods are the only authorised way to mutate game state.
"""

import math
import chess
from typing import Optional

from engine.quantum_state import QuantumState, QuantumPiece
from engine.move import Move, MoveType
from engine.measurement import MeasurementSystem
from engine.rules import RuleEngine


class QuantumBoard:
    """
    Central game state container.

    Turn management:
      self.turn: chess.Color  – whose turn it is
    """

    def __init__(self):
        self.classical_board = chess.Board()
        self.quantum_state = QuantumState()
        self.measurement = MeasurementSystem(self)
        self.rules = RuleEngine(self)
        self.turn: chess.Color = chess.WHITE
        self.move_history: list[Move] = []
        self.measurement_log: list = []  # MeasurementResult list

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def piece_at(self, sq: chess.Square) -> Optional[chess.Piece]:
        """Classical piece at *sq*, or None."""
        return self.classical_board.piece_at(sq)

    def quantum_pieces_at(self, sq: chess.Square) -> list[QuantumPiece]:
        """Return quantum pieces whose superposition includes *sq*."""
        qids = self.quantum_state.ids_at(sq)
        return [self.quantum_state.get(qid) for qid in qids
                if self.quantum_state.get(qid) is not None]

    def quantum_squares(self) -> set[chess.Square]:
        return self.quantum_state.occupied_squares()

    def is_quantum_square(self, sq: chess.Square) -> bool:
        return sq in self.quantum_state.occupied_squares()

    def legal_moves_from(self, sq: chess.Square) -> list[Move]:
        return self.rules.legal_moves_from_square(sq)

    # ------------------------------------------------------------------
    # Apply moves
    # ------------------------------------------------------------------

    def apply_move(self, move: Move) -> bool:
        """
        Apply any legal move.  Returns True on success.
        Handles NDO check, collapse, and turn advancement.
        """
        move.assert_valid()

        # Ensure cb.turn matches board.turn before legality/execution
        self.classical_board.turn = self.turn

        if move.move_type == MoveType.CLASSICAL:
            success = self._apply_classical(move)
        elif move.move_type == MoveType.SPLIT:
            if not self.rules.is_legal(move, self.turn):
                return False
            success = self._apply_split(move)
        elif move.move_type == MoveType.MERGE:
            if not self.rules.is_legal(move, self.turn):
                return False
            success = self._apply_merge(move)
        elif move.move_type == MoveType.ENTANGLE:
            success = self._apply_entangle(move)
        else:
            return False

        if success:
            self.move_history.append(move)
            self.turn = chess.BLACK if self.turn == chess.WHITE else chess.WHITE
            # Keep cb.turn in sync: cb.push() already advances it for CLASSICAL,
            # but split/merge/entangle never call push().
            self.classical_board.turn = self.turn

        return success

    # ------------------------------------------------------------------
    # Classical move
    # ------------------------------------------------------------------

    def _apply_classical(self, move: Move) -> bool:
        cb = self.classical_board
        from_sq = move.from_square
        to_sq = move.to_square

        # NDO: if destination has quantum pieces, collapse them first
        if self.is_quantum_square(to_sq):
            results = self.measurement.resolve_ndo(to_sq)
            self.measurement_log.extend(results)

        # NDO: if source has quantum pieces, collapse them too
        if self.is_quantum_square(from_sq):
            results = self.measurement.resolve_ndo(from_sq)
            self.measurement_log.extend(results)

        # Also collapse quantum pieces at destination (again, post-NDO cascade)
        if self.is_quantum_square(to_sq):
            results = self.measurement.measure_square(to_sq)
            self.measurement_log.extend(results)

        # Build python-chess Move
        chess_move = chess.Move(from_sq, to_sq, move.promotion)

        # Try exact move first
        if chess_move in cb.legal_moves:
            cb.push(chess_move)
            return True

        # Try pseudo-legal (no check filter needed)
        for m in cb.pseudo_legal_moves:
            if m.from_square == from_sq and m.to_square == to_sq:
                cb.push(m)
                return True

        return False

    # ------------------------------------------------------------------
    # Split move
    # ------------------------------------------------------------------

    def _apply_split(self, move: Move) -> bool:
        cb = self.classical_board
        from_sq = move.from_square
        t1, t2 = move.targets

        piece = cb.piece_at(from_sq)
        if piece is None:
            return False
        if piece.color != self.turn:
            return False

        # NDO check on targets: collapse any quantum pieces there first
        for t in (t1, t2):
            if self.is_quantum_square(t):
                results = self.measurement.resolve_ndo(t)
                self.measurement_log.extend(results)

        # After NDO resolution a friendly piece may have collapsed onto a target.
        # If so, the split cannot proceed to that square.
        for t in (t1, t2):
            occupant = cb.piece_at(t)
            if occupant is not None and occupant.color == piece.color:
                return False

        # Remove piece from classical board
        cb.remove_piece_at(from_sq)

        # Source amplitude: 1.0 (piece was definite)
        source_amp = complex(1.0, 0.0)
        amp_each = Move.split_amplitude(source_amp)  # 1/sqrt(2)

        # Handle classical pieces at target squares (captures)
        for t in (t1, t2):
            target_piece = cb.piece_at(t)
            if target_piece is not None and target_piece.color != piece.color:
                # This split-onto-occupied triggers a measurement, which
                # means we note the capture possibility but keep it quantum.
                # The piece might or might not be there when collapsed.
                pass  # handled at collapse time

        # Create quantum piece in superposition
        qp = self.quantum_state.create_superposition(
            piece, [t1, t2], [amp_each, amp_each]
        )

        # Entangle with quantum pieces that were at the targets before split
        # (creates correlation: if we split onto an entangled piece's square)

        self.quantum_state._rebuild_index()
        return True

    # ------------------------------------------------------------------
    # Merge move
    # ------------------------------------------------------------------

    def _apply_merge(self, move: Move) -> bool:
        qs = self.quantum_state
        cb = self.classical_board
        s1, s2 = move.sources
        to_sq = move.to_square

        # Find quantum pieces at s1 and s2
        qids1 = qs.ids_at(s1)
        qids2 = qs.ids_at(s2)

        if not qids1 or not qids2:
            return False

        qid1 = qids1[0]
        qid2 = qids2[0]
        same_piece = (qid1 == qid2)  # merging two positions of the same quantum piece

        qp1 = qs.get(qid1)
        qp2 = qs.get(qid2)

        if qp1 is None or qp2 is None:
            return False
        if qp1.piece.color != self.turn:
            return False
        if not same_piece and qp1.piece.piece_type != qp2.piece.piece_type:
            return False

        # Retrieve amplitudes at the source squares
        amp1 = (qp1.amplitudes[qp1.positions.index(s1)]
                if s1 in qp1.positions else complex(0))
        if same_piece:
            amp2 = (qp1.amplitudes[qp1.positions.index(s2)]
                    if s2 in qp1.positions else complex(0))
        else:
            amp2 = (qp2.amplitudes[qp2.positions.index(s2)]
                    if s2 in qp2.positions else complex(0))

        merged_amp = Move.merge_amplitude(amp1, amp2)
        merged_prob = abs(merged_amp) ** 2

        # Save piece type before any removals
        piece_to_place = qp1.piece

        # NDO check on destination
        if self.is_quantum_square(to_sq):
            results = self.measurement.resolve_ndo(to_sq)
            self.measurement_log.extend(results)

        # Remove source positions (order matters for same-piece case: remove s1 first)
        qp1.remove_position(s1)
        if same_piece:
            # qp1 == qp2; remove s2 from the same object after s1 is gone
            qp1.remove_position(s2)
        else:
            qp2.remove_position(s2)

        # Remove quantum pieces that became empty
        if len(qp1.positions) == 0:
            qs.remove(qid1)
        if not same_piece:
            qp2_live = qs.get(qid2)
            if qp2_live is not None and len(qp2_live.positions) == 0:
                qs.remove(qid2)

        # Destructive interference: piece annihilates, nothing placed classically
        if merged_prob < 1e-9:
            qs._rebuild_index()
            return True

        # Constructive merge: collapse to classical at destination
        existing = cb.piece_at(to_sq)
        if existing is not None:
            cb.remove_piece_at(to_sq)
        cb.set_piece_at(to_sq, piece_to_place)

        qs._rebuild_index()
        return True

    # ------------------------------------------------------------------
    # Entangle move
    # ------------------------------------------------------------------

    def _apply_entangle(self, move: Move) -> bool:
        sq1, sq2 = move.sources
        qids1 = self.quantum_state.ids_at(sq1)
        qids2 = self.quantum_state.ids_at(sq2)
        if not qids1 or not qids2:
            return False
        qid1 = qids1[0]
        qid2 = qids2[0]
        if qid1 == qid2:
            return False  # cannot entangle a piece with itself
        qp1 = self.quantum_state.get(qid1)
        qp2 = self.quantum_state.get(qid2)
        if qp1 is None or qp2 is None:
            return False
        if qp1.piece.color != self.turn or qp2.piece.color != self.turn:
            return False
        return self.quantum_state.entangle(qid1, qid2)

    # ------------------------------------------------------------------
    # Superposition (user-facing helper for GUI)
    # ------------------------------------------------------------------

    def put_in_superposition(self, sq: chess.Square,
                              targets: list[chess.Square],
                              amplitudes: Optional[list] = None) -> Optional[int]:
        """
        Convenience: take a classical piece off *sq* and create a QuantumPiece
        across *targets*.  Returns quantum piece id or None.
        """
        piece = self.classical_board.piece_at(sq)
        if piece is None or len(targets) < 2:
            return None

        self.classical_board.remove_piece_at(sq)

        if amplitudes is None:
            n = len(targets)
            amp = complex(math.sqrt(1.0 / n))
            amplitudes = [amp] * n

        qp = QuantumPiece(piece, targets, amplitudes)
        self.quantum_state.add(qp)
        return qp.id

    # ------------------------------------------------------------------
    # Collapse helpers (for GUI / AI)
    # ------------------------------------------------------------------

    def collapse_piece(self, qid: int) -> Optional[chess.Square]:
        """Collapse one quantum piece.  Returns landing square or None."""
        result = self.measurement.measure_piece(qid)
        if result:
            self.measurement_log.append(result)
            return result.chosen_square
        return None

    def collapse_all(self):
        """Collapse every quantum piece (end-of-game)."""
        results = self.measurement.measure_all()
        self.measurement_log.extend(results)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_game_over(self) -> bool:
        return self.rules.is_game_over()

    def game_result(self) -> Optional[str]:
        return self.rules.game_result()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def assert_valid(self):
        """Run all internal consistency checks."""
        self.quantum_state.assert_valid()
        self.measurement.assert_valid()
        self.rules.assert_valid()

    def __repr__(self) -> str:
        return (f"QuantumBoard(turn={self.turn}, "
                f"quantum_pieces={len(self.quantum_state)}, "
                f"moves={len(self.move_history)})")
