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
from engine.move_classifier import classify, Variant, path_squares


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

    def _state_fingerprint(self) -> tuple:
        """Lightweight state snapshot for no-effect detection (paper Rule 9)."""
        board_fen = self.classical_board.board_fen()
        qdata = tuple(
            (qp.id,
             tuple(sorted(qp.positions)),
             tuple(round(abs(a) ** 2, 8) for a in qp.amplitudes))
            for qp in sorted(self.quantum_state.pieces.values(), key=lambda x: x.id)
        )
        return (board_fen, qdata)

    def apply_move(self, move: Move) -> bool:
        """
        Apply any legal move.  Returns True on success.
        Handles NDO check, collapse, and turn advancement.
        """
        move.assert_valid()

        # Ensure cb.turn matches board.turn before legality/execution
        self.classical_board.turn = self.turn

        before = self._state_fingerprint()

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
        else:
            return False

        if success:
            # No-effect: state unchanged → player must retry (paper Rule 9)
            if self._state_fingerprint() == before:
                return False
            self.move_history.append(move)
            self.turn = chess.BLACK if self.turn == chess.WHITE else chess.WHITE
            self.classical_board.turn = self.turn

        return success

    # ------------------------------------------------------------------
    # Classical move
    # ------------------------------------------------------------------

    def _apply_classical(self, move: Move) -> bool:
        cb = self.classical_board
        from_sq = move.from_square
        to_sq = move.to_square

        variant = classify(from_sq, to_sq, cb)

        # Castling: delegate to dedicated handler
        if variant in (Variant.CASTLE_KINGSIDE, Variant.CASTLE_QUEENSIDE):
            return self._apply_castling(move, variant)

        # Slide variants: measure quantum pieces on the path (quantum blockers)
        if variant in (Variant.STANDARD_SLIDE, Variant.CAPTURE_SLIDE, Variant.BLOCKED_SLIDE):
            for psq in path_squares(from_sq, to_sq):
                if self.is_quantum_square(psq):
                    results = self.measurement.resolve_ndo(psq)
                    self.measurement_log.extend(results)
            # After collapse: if path is classically blocked, slide fails
            for psq in path_squares(from_sq, to_sq):
                if cb.piece_at(psq) is not None:
                    return False

        # NDO: collapse quantum pieces at destination
        if self.is_quantum_square(to_sq):
            results = self.measurement.resolve_ndo(to_sq)
            self.measurement_log.extend(results)

        # NDO: collapse quantum pieces at source (edge case)
        if self.is_quantum_square(from_sq):
            results = self.measurement.resolve_ndo(from_sq)
            self.measurement_log.extend(results)

        # Pseudo-legal only — no check/checkmate filtering (paper rule)
        for m in cb.pseudo_legal_moves:
            if m.from_square == from_sq and m.to_square == to_sq:
                if m.promotion == move.promotion:
                    cb.push(m)
                    return True

        return False

    # ------------------------------------------------------------------
    # Castling move
    # ------------------------------------------------------------------

    def _apply_castling(self, move: Move, variant: Variant) -> bool:
        cb = self.classical_board
        from_sq = move.from_square
        to_sq = move.to_square
        rank = chess.square_rank(from_sq)

        # Path squares that must be empty for castling to proceed
        if variant == Variant.CASTLE_KINGSIDE:
            path = [chess.square(5, rank), chess.square(6, rank)]      # f, g files
        else:
            path = [chess.square(1, rank), chess.square(2, rank),      # b, c, d files
                    chess.square(3, rank)]

        # Measure any quantum pieces on the castling path
        for sq in path:
            if self.is_quantum_square(sq):
                results = self.measurement.resolve_ndo(sq)
                self.measurement_log.extend(results)

        # M0: any path square classically occupied after collapse → fail
        for sq in path:
            if cb.piece_at(sq) is not None:
                return False

        # Path clear → apply castling
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
        amp_each = Move.split_amplitude(source_amp)  # i/sqrt(2) per paper eq. 8a

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

        qids1 = qs.ids_at(s1)
        qids2 = qs.ids_at(s2)
        if not qids1 or not qids2:
            return False

        # Same-lineage only: both source squares must belong to the same quantum piece
        if qids1[0] != qids2[0]:
            return False

        qid1 = qids1[0]
        qp1 = qs.get(qid1)
        if qp1 is None:
            return False
        if qp1.piece.color != self.turn:
            return False

        # Retrieve amplitudes at source squares (same piece → use qp1 for both)
        amp1 = (qp1.amplitudes[qp1.positions.index(s1)]
                if s1 in qp1.positions else complex(0))
        amp2 = (qp1.amplitudes[qp1.positions.index(s2)]
                if s2 in qp1.positions else complex(0))

        # Paper Umerge (eq. 10): target = -i(α+β)/√2, residual at s2 = (α-β)/√2
        target_amp   = Move.merge_target_amplitude(amp1, amp2)
        residual_amp = Move.merge_residual_amplitude(amp1, amp2)
        target_prob   = abs(target_amp) ** 2
        residual_prob = abs(residual_amp) ** 2

        piece_to_place = qp1.piece

        # NDO check on destination
        if self.is_quantum_square(to_sq):
            results = self.measurement.resolve_ndo(to_sq)
            self.measurement_log.extend(results)

        # Remove source positions from the single quantum piece
        qp1.remove_position(s1)
        qp1.remove_position(s2)

        # Remove quantum piece if now empty
        if len(qp1.positions) == 0:
            qs.remove(qid1)

        # Full destructive interference → piece annihilates
        if target_prob < 1e-9 and residual_prob < 1e-9:
            qs._rebuild_index()
            return True

        # Build output: collect non-negligible positions and amplitudes
        out_positions = []
        out_amplitudes = []
        if target_prob >= 1e-9:
            out_positions.append(to_sq)
            out_amplitudes.append(target_amp)
        if residual_prob >= 1e-9:
            out_positions.append(s2)
            out_amplitudes.append(residual_amp)

        if len(out_positions) == 1:
            # Single outcome → collapse to classical
            existing = cb.piece_at(out_positions[0])
            if existing is not None:
                cb.remove_piece_at(out_positions[0])
            cb.set_piece_at(out_positions[0], piece_to_place)
        else:
            # Superposition survives (unequal source amplitudes) → quantum piece
            total_prob = sum(abs(a) ** 2 for a in out_amplitudes)
            norm = math.sqrt(total_prob)
            normed = [a / norm for a in out_amplitudes]
            qs.create_superposition(piece_to_place, out_positions, normed)

        qs._rebuild_index()
        return True

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
