"""
engine/measurement.py – Measurement and collapse system.

Measurement is triggered by:
  1. A classical piece moves onto a quantum square (No Double Occupancy).
  2. A quantum piece collapses by user action or AI decision.
  3. A split or merge move resolves its probability distribution.

The result of a measurement is always a definite classical square for the
collapsed piece.  If the piece was a king and it collapses to a square
occupied by an enemy piece, the enemy piece is captured.  If the king
collapses to a square occupied by a friendly piece, the king is instead
annihilated (treated as captured – unusual but theoretically possible in
the quantum model; we treat it as the king ceasing to exist).

Win detection: a king is "gone" if (a) it has no quantum superposition and
no classical presence, or (b) its total existence probability is 0.
"""

import random
import chess
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from engine.board import QuantumBoard


class MeasurementResult:
    """Record of a single collapse event."""

    def __init__(self, qid: int, chosen_square: chess.Square,
                 piece: chess.Piece, discarded_squares: list[chess.Square],
                 captured_piece: Optional[chess.Piece] = None):
        self.qid = qid
        self.chosen_square = chosen_square
        self.piece = piece
        self.discarded_squares = discarded_squares
        self.captured_piece = captured_piece

    def __repr__(self) -> str:
        import chess as _chess
        cap = (f", captured={self.captured_piece}" if self.captured_piece is not None else "")
        return (f"MeasurementResult(qid={self.qid}, "
                f"piece={self.piece}, "
                f"landed={_chess.square_name(self.chosen_square)}{cap})")


class MeasurementSystem:
    """
    Handles all measurement / collapse logic for the quantum board.
    """

    def __init__(self, board: "QuantumBoard"):
        self._board = board

    # ------------------------------------------------------------------
    # Primary entry points
    # ------------------------------------------------------------------

    def measure_square(self, sq: chess.Square) -> list[MeasurementResult]:
        """
        Trigger measurement of all quantum pieces that include *sq*.
        Returns a list of results (one per collapsed piece).
        Called when No Double Occupancy is violated or a capture is attempted.
        """
        results = []
        qids = self._board.quantum_state.ids_at(sq)
        for qid in list(qids):
            if qid in self._board.quantum_state:
                result = self._collapse_one(qid)
                if result is not None:
                    results.append(result)
        return results

    def measure_piece(self, qid: int) -> Optional[MeasurementResult]:
        """
        Collapse a specific quantum piece by its id.
        Returns the result or None if the piece doesn't exist.
        """
        return self._collapse_one(qid)

    def measure_all(self) -> list[MeasurementResult]:
        """Collapse every quantum piece (end-of-game cleanup)."""
        results = []
        for qid in list(self._board.quantum_state.pieces.keys()):
            if qid in self._board.quantum_state:
                result = self._collapse_one(qid)
                if result is not None:
                    results.append(result)
        return results

    # ------------------------------------------------------------------
    # No Double Occupancy check
    # ------------------------------------------------------------------

    def check_ndo(self, sq: chess.Square) -> bool:
        """
        Return True if moving a classical piece to *sq* would violate
        No Double Occupancy (i.e., there is a quantum piece at that square).
        If True, the caller must trigger measurement before proceeding.
        """
        return self._board.quantum_state.ids_at(sq) != []

    def resolve_ndo(self, sq: chess.Square) -> list[MeasurementResult]:
        """
        Resolve a No Double Occupancy conflict at *sq*.
        Collapses all quantum pieces at that square.
        """
        assert self.check_ndo(sq), f"No NDO conflict at {chess.square_name(sq)}"
        return self.measure_square(sq)

    # ------------------------------------------------------------------
    # En passant measurement
    # ------------------------------------------------------------------

    def measure_en_passant_target(self, ep_square: chess.Square) -> list[MeasurementResult]:
        """
        Quantum en passant: measure quantum pieces at the en passant target
        square and the square behind it (where the captured pawn would be).
        """
        results = self.measure_square(ep_square)
        # The actual pawn is one rank behind the ep square
        file = chess.square_file(ep_square)
        rank = chess.square_rank(ep_square)
        behind_rank = rank - 1 if rank > 0 else rank + 1
        behind_sq = chess.square(file, behind_rank)
        results.extend(self.measure_square(behind_sq))
        return results

    # ------------------------------------------------------------------
    # Internal collapse logic
    # ------------------------------------------------------------------

    def _collapse_one(self, qid: int) -> Optional[MeasurementResult]:
        qs = self._board.quantum_state
        qp = qs.get(qid)
        if qp is None:
            return None

        discarded = list(qp.positions)
        chosen = qs.collapse_piece(qid)  # removes from quantum state
        discarded = [sq for sq in discarded if sq != chosen]

        # Place the piece on the classical board
        cb = self._board.classical_board
        collapsed_piece = qp.piece
        existing = cb.piece_at(chosen)

        captured: Optional[chess.Piece] = None
        if existing is not None:
            if existing.color == collapsed_piece.color:
                raise AssertionError(
                    f"Collapse onto friendly piece at {chess.square_name(chosen)} — NDO failed upstream"
                )
            # Enemy capture: remove the enemy before placing
            captured = existing
            cb.remove_piece_at(chosen)

        cb.set_piece_at(chosen, collapsed_piece)
        qs._rebuild_index()

        return MeasurementResult(qid, chosen, collapsed_piece, discarded, captured_piece=captured)

    # ------------------------------------------------------------------
    # Existence probability helpers
    # ------------------------------------------------------------------

    def king_existence_probability(self, color: chess.Color) -> float:
        """
        Return the total probability that the *color* king still exists.
        Accounts for both classical presence and quantum superposition.
        """
        cb = self._board.classical_board
        # Check classical board
        king_sq = cb.king(color)
        classical_king_exists = king_sq is not None
        classical_prob = 1.0 if classical_king_exists else 0.0

        # Sum quantum contributions
        quantum_prob = 0.0
        quantum_king_exists = False
        for qp in self._board.quantum_state.pieces.values():
            if qp.piece.color == color and qp.piece.piece_type == chess.KING:
                quantum_king_exists = True
                quantum_prob += qp.total_existence_probability()

        # Classical and quantum king must never coexist — that means NDO failed
        assert not (classical_king_exists and quantum_king_exists), (
            f"Classical and quantum {'white' if color else 'black'} king coexist — invalid state"
        )

        # A king can exist either classically or in superposition, not both
        # (the moment it collapses from quantum it appears on classical board)
        return classical_prob + quantum_prob

    def check_win_condition(self) -> Optional[chess.Color]:
        """
        Return the winner if a king has 0 existence probability, else None.
        Draws (both kings gone) return chess.WHITE arbitrarily; caller can
        check for draw by comparing existence probabilities of both sides.
        """
        white_alive = self.king_existence_probability(chess.WHITE) > 1e-9
        black_alive = self.king_existence_probability(chess.BLACK) > 1e-9

        if not white_alive and not black_alive:
            return None  # Draw — caller must handle
        if not white_alive:
            return chess.BLACK
        if not black_alive:
            return chess.WHITE
        return None

    def assert_valid(self):
        """Validate that measurement state is consistent with board state."""
        cb = self._board.classical_board
        qs = self._board.quantum_state

        # No quantum piece should occupy a square that is classically occupied
        # by a piece of the same colour (would be NDO violation)
        for sq, qids in qs._sq_index.items():
            classical_piece = cb.piece_at(sq)
            for qid in qids:
                qp = qs.get(qid)
                if qp is None:
                    continue
                if classical_piece is not None:
                    assert classical_piece.color != qp.piece.color, (
                        f"NDO violation: classical {classical_piece} and "
                        f"quantum {qp.piece} both at {chess.square_name(sq)}"
                    )
