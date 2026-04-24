"""
engine/piece.py – Piece type definitions and movement rules.

In Quantum Chess there is NO check/checkmate. Kings are captured like any
other piece. Win condition: opponent king reaches 0 probability of existing.
"""

import chess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.board import QuantumBoard

# Piece type constants re-exported for convenience
PAWN   = chess.PAWN
KNIGHT = chess.KNIGHT
BISHOP = chess.BISHOP
ROOK   = chess.ROOK
QUEEN  = chess.QUEEN
KING   = chess.KING

# Piece values for AI heuristics
PIECE_VALUE: dict[int, int] = {
    PAWN:   1,
    KNIGHT: 3,
    BISHOP: 3,
    ROOK:   5,
    QUEEN:  9,
    KING:   100,  # high value so AI prioritises king captures
}


def classical_targets(piece: chess.Piece, sq: chess.Square,
                      board: "QuantumBoard") -> list[chess.Square]:
    """
    Return squares reachable by *piece* from *sq* using only the classical
    (fully-collapsed) board state.  Does NOT filter for check (there is none).
    Returns an empty list if the piece is not on *sq* classically.
    """
    cb = board.classical_board
    if cb.piece_at(sq) != piece:
        return []

    # Generate pseudo-legal moves (no check filtering needed)
    targets = []
    for move in cb.pseudo_legal_moves:
        if move.from_square == sq:
            targets.append(move.to_square)
    return targets


def reachable_squares(piece: chess.Piece, sq: chess.Square,
                      board: "QuantumBoard") -> list[chess.Square]:
    """
    Return all squares a piece *could* move to, accounting for the quantum
    board state.  Quantum pieces on intermediate squares may block or may not
    depending on their probabilities — we return all squares reachable assuming
    quantum pieces *might* be absent (optimistic set for move generation).
    """
    cb = board.classical_board

    # Temporarily remove the piece so chess.Board generates moves from empty board
    existing = cb.piece_at(sq)
    if existing is None:
        return []

    targets = set()

    # Use python-chess pseudo-legal move generation
    for move in cb.pseudo_legal_moves:
        if move.from_square == sq:
            targets.add(move.to_square)

    # Additionally consider squares blocked only by quantum pieces
    # (since those might collapse away, paths are not necessarily blocked)
    for qsq in board.quantum_squares():
        if qsq in targets:
            continue
        # Check if sliding piece path to qsq is otherwise clear
        if _would_reach(piece, sq, qsq, cb):
            targets.add(qsq)

    return list(targets)


def _would_reach(piece: chess.Piece, src: chess.Square,
                 dst: chess.Square, cb: chess.Board) -> bool:
    """
    Heuristic: could *piece* on *src* reach *dst* if that square were empty?
    Uses a temporary board clone to test.
    """
    if src == dst:
        return False
    tmp = cb.copy()
    tmp.remove_piece_at(dst)
    for m in tmp.pseudo_legal_moves:
        if m.from_square == src and m.to_square == dst:
            return True
    return False


def split_targets(piece: chess.Piece, sq: chess.Square,
                  board: "QuantumBoard") -> list[chess.Square]:
    """
    Return squares suitable as split-move targets for *piece* on *sq*.
    Excludes squares already occupied classically by friendly pieces.
    """
    color = piece.color
    targets = reachable_squares(piece, sq, board)
    cb = board.classical_board
    result = []
    for t in targets:
        occupant = cb.piece_at(t)
        if occupant is None or occupant.color != color:
            result.append(t)
    return result


def merge_sources(piece: chess.Piece, qid: int,
                  board: "QuantumBoard") -> list[chess.Square]:
    """
    Return squares from which *piece* could merge into a target square.
    *qid* is the quantum piece id of one of the sources; the other source
    must be a quantum instance of the same piece type.
    """
    qp = board.quantum_state.get(qid)
    if qp is None:
        return []
    result = []
    for sq in qp.positions:
        for other_sq in split_targets(qp.piece, sq, board):
            result.append(other_sq)
    return list(set(result))
