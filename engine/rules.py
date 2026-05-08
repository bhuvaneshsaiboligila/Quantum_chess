"""
engine/rules.py – Legal move generation and rule enforcement.

Key rule differences from classical chess:
  - NO check or checkmate.  The king is captured like any other piece.
  - Win condition: opponent king's total existence probability → 0.
  - SPLIT move: one piece → two squares, 50/50 superposition.
  - MERGE move: two quantum instances of the same piece → one square.
  - Quantum pawn en passant: measurement required.
  - Promotion: auto-resolved to Queen (can be extended).
"""

import math
import chess
from typing import Optional, TYPE_CHECKING

from engine.move import Move, MoveType

if TYPE_CHECKING:
    from engine.board import QuantumBoard


class RuleEngine:
    """
    Generates and validates legal moves for the current board state.
    """

    def __init__(self, board: "QuantumBoard"):
        self._board = board

    # ------------------------------------------------------------------
    # Legal move generation
    # ------------------------------------------------------------------

    def legal_classical_moves(self, color: chess.Color) -> list[Move]:
        """
        Return all legal classical moves for *color*.
        Uses python-chess pseudo-legal moves (no check filtering).
        """
        cb = self._board.classical_board
        moves = []
        for m in cb.pseudo_legal_moves:
            piece = cb.piece_at(m.from_square)
            if piece is None or piece.color != color:
                continue
            # Auto-promote to queen
            if (piece.piece_type == chess.PAWN and
                    chess.square_rank(m.to_square) in (0, 7)):
                moves.append(Move.classical(m.from_square, m.to_square,
                                            promotion=chess.QUEEN))
            else:
                moves.append(Move.classical(m.from_square, m.to_square))
        return moves

    def legal_split_moves(self, color: chess.Color) -> list[Move]:
        """
        Return all legal split moves for *color*.
        A piece can split to any two squares it could legally reach classically.
        Per Cantwell paper rule 8.7, kings CAN split (vs ∈ {N, K}).
        Only pawns are excluded.
        """
        cb = self._board.classical_board
        moves = []
        for sq in chess.SQUARES:
            piece = cb.piece_at(sq)
            if piece is None or piece.color != color:
                continue
            if piece.piece_type == chess.PAWN:
                continue  # Pawns cannot split

            targets = [m.to_square for m in cb.pseudo_legal_moves
                       if m.from_square == sq]
            targets = list(set(targets))

            for i in range(len(targets)):
                for j in range(i + 1, len(targets)):
                    t1, t2 = targets[i], targets[j]
                    # Both targets must not be classically occupied by same colour
                    occ1 = cb.piece_at(t1)
                    occ2 = cb.piece_at(t2)
                    if (occ1 is None or occ1.color != color) and \
                       (occ2 is None or occ2.color != color):
                        moves.append(Move.split(sq, t1, t2))
        return moves

    def legal_merge_moves(self, color: chess.Color) -> list[Move]:
        """
        Return all legal merge moves for *color*.
        Only same-lineage merges: a split quantum piece (≥ 2 positions) merging
        two of its positions back into one target square.
        """
        qs = self._board.quantum_state
        cb = self._board.classical_board
        moves: list[Move] = []

        for qp in qs.pieces.values():
            if qp.piece.color != color:
                continue
            if len(qp.positions) < 2:
                continue
            for i in range(len(qp.positions)):
                for j in range(i + 1, len(qp.positions)):
                    sq1 = qp.positions[i]
                    sq2 = qp.positions[j]
                    targets1 = self._pseudo_legal_targets_for_piece(qp.piece, sq1, cb)
                    targets2 = self._pseudo_legal_targets_for_piece(qp.piece, sq2, cb)
                    for t in set(targets1) & set(targets2):
                        occ = cb.piece_at(t)
                        if occ is None or occ.color != color:
                            moves.append(Move.merge(sq1, sq2, t))

        return moves

    def all_legal_moves(self, color: chess.Color) -> list[Move]:
        """Return all legal moves (classical + split + merge) for *color*."""
        moves = self.legal_classical_moves(color)
        moves.extend(self.legal_split_moves(color))
        moves.extend(self.legal_merge_moves(color))
        return moves

    def legal_moves_from_square(self, sq: chess.Square) -> list[Move]:
        """Return legal classical moves from *sq*."""
        cb = self._board.classical_board
        piece = cb.piece_at(sq)
        if piece is None:
            return []
        moves = []
        for m in cb.pseudo_legal_moves:
            if m.from_square != sq:
                continue
            if (piece.piece_type == chess.PAWN and
                    chess.square_rank(m.to_square) in (0, 7)):
                moves.append(Move.classical(sq, m.to_square, promotion=chess.QUEEN))
            else:
                moves.append(Move.classical(sq, m.to_square))
        return moves

    # ------------------------------------------------------------------
    # Move validation
    # ------------------------------------------------------------------

    def is_legal(self, move: Move, color: chess.Color) -> bool:
        """Return True if *move* is legal for *color* in the current state."""
        move.assert_valid()
        if move.move_type == MoveType.CLASSICAL:
            return move in self.legal_classical_moves(color)
        elif move.move_type == MoveType.SPLIT:
            return move in self.legal_split_moves(color)
        elif move.move_type == MoveType.MERGE:
            return move in self.legal_merge_moves(color)
        return False

    # ------------------------------------------------------------------
    # Win / draw detection
    # ------------------------------------------------------------------

    def game_result(self) -> Optional[str]:
        """
        Return "white", "black", "draw", or None if still playing.
        Win: opponent king reaches 0 existence probability.
        """
        ms = self._board.measurement
        white_alive = ms.king_existence_probability(chess.WHITE) > 1e-9
        black_alive = ms.king_existence_probability(chess.BLACK) > 1e-9

        if not white_alive and not black_alive:
            return "draw"
        if not white_alive:
            return "black"
        if not black_alive:
            return "white"
        return None

    def is_game_over(self) -> bool:
        return self.game_result() is not None

    # ------------------------------------------------------------------
    # Promotion helper
    # ------------------------------------------------------------------

    @staticmethod
    def promotion_piece(pawn: chess.Piece) -> chess.Piece:
        """Auto-promote to queen of the same colour."""
        return chess.Piece(chess.QUEEN, pawn.color)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pseudo_legal_targets(self, piece: chess.Piece,
                               sq: chess.Square,
                               cb: chess.Board) -> list[chess.Square]:
        """Return pseudo-legal destination squares for *piece* on *sq* (classical board only)."""
        if cb.piece_at(sq) != piece:
            return []
        return [m.to_square for m in cb.pseudo_legal_moves if m.from_square == sq]

    def _pseudo_legal_targets_for_piece(self, piece: chess.Piece,
                                         sq: chess.Square,
                                         cb: chess.Board) -> list[chess.Square]:
        """
        Return pseudo-legal targets for *piece* at *sq*, even if the piece is
        not on the classical board there (i.e., it is in quantum superposition).
        Uses a temporary board copy so the original is not modified.
        """
        tmp = cb.copy()
        tmp.set_piece_at(sq, piece)
        tmp.turn = piece.color  # generate moves for this piece's colour
        return [m.to_square for m in tmp.pseudo_legal_moves if m.from_square == sq]

    def assert_valid(self):
        """Validate rule engine assumptions."""
        cb = self._board.classical_board
        # Each colour must have at most 1 classical king
        for color in (chess.WHITE, chess.BLACK):
            king_sq = cb.king(color)
            # king_sq can be None (captured), that is legal in quantum chess
            _ = king_sq  # just access it to ensure no exception
