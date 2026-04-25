"""
engine/move_classifier.py – Classify classical moves into paper variants.
Paper: Cantwell 2019, §8.1–8.12
"""

import chess
from enum import Enum, auto
from typing import Optional


class Variant(Enum):
    STANDARD_JUMP    = auto()   # §8.1  N/K, empty target
    BLOCKED_JUMP     = auto()   # §8.2  N/K, same-color target
    CAPTURE_JUMP     = auto()   # §8.3  N/K, enemy target
    STANDARD_SLIDE   = auto()   # §8.4  B/R/Q, empty target
    BLOCKED_SLIDE    = auto()   # §8.5  B/R/Q, same-color target
    CAPTURE_SLIDE    = auto()   # §8.6  B/R/Q, enemy target
    PAWN_STEP        = auto()   # §8.11.1
    BLOCKED_STEP     = auto()   # §8.11.2
    PAWN_TWO_STEP    = auto()   # §8.11.3
    BLOCKED_TWO_STEP = auto()   # §8.11.4
    PAWN_CAPTURE     = auto()   # §8.11.5
    EP_STANDARD      = auto()   # §8.11.6
    EP_BLOCKED       = auto()   # §8.11.7
    EP_CAPTURE       = auto()   # §8.11.8
    CASTLE_KINGSIDE  = auto()   # §8.12.1
    CASTLE_QUEENSIDE = auto()   # §8.12.2


def classify(from_sq: chess.Square, to_sq: chess.Square,
             cb: chess.Board) -> Optional[Variant]:
    """
    Classify the move from_sq→to_sq using the classical board cb.
    cb.turn must be set to the moving color before calling.
    Returns None if unrecognizable.
    """
    piece = cb.piece_at(from_sq)
    if piece is None:
        return None
    color = piece.color
    target = cb.piece_at(to_sq)
    pt = piece.piece_type

    # Castling: king moves horizontally 2 squares
    if pt == chess.KING:
        df = chess.square_file(to_sq) - chess.square_file(from_sq)
        if abs(df) == 2:
            return Variant.CASTLE_KINGSIDE if df > 0 else Variant.CASTLE_QUEENSIDE

    if pt == chess.PAWN:
        return _classify_pawn(from_sq, to_sq, cb, color, target)

    # Jump: Knight, King
    if pt in (chess.KNIGHT, chess.KING):
        if target is None:
            return Variant.STANDARD_JUMP
        if target.color == color:
            return Variant.BLOCKED_JUMP
        return Variant.CAPTURE_JUMP

    # Slide: Bishop, Rook, Queen
    if pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        if target is not None and target.color == color:
            return Variant.BLOCKED_SLIDE
        if target is not None:
            return Variant.CAPTURE_SLIDE
        return Variant.STANDARD_SLIDE

    return None


def _classify_pawn(from_sq: chess.Square, to_sq: chess.Square,
                   cb: chess.Board, color: chess.Color,
                   target: Optional[chess.Piece]) -> Optional[Variant]:
    ff, fr = chess.square_file(from_sq), chess.square_rank(from_sq)
    tf, tr = chess.square_file(to_sq),   chess.square_rank(to_sq)
    df = abs(tf - ff)
    dr = abs(tr - fr)

    if df == 1:
        # Diagonal: en passant or capture
        if cb.ep_square == to_sq:
            return Variant.EP_STANDARD
        if target is not None and target.color != color:
            return Variant.PAWN_CAPTURE
        return None

    if df == 0:
        if dr == 1:
            return Variant.PAWN_STEP if target is None else Variant.BLOCKED_STEP
        if dr == 2:
            inter_sq = chess.square(ff, (fr + tr) // 2)
            if target is None and cb.piece_at(inter_sq) is None:
                return Variant.PAWN_TWO_STEP
            return Variant.BLOCKED_TWO_STEP

    return None


def path_squares(from_sq: chess.Square, to_sq: chess.Square) -> list[chess.Square]:
    """
    Intermediate squares for a sliding piece move (excludes from_sq and to_sq).
    Returns [] for jump pieces or same-square edge cases.
    """
    fr, ff = chess.square_rank(from_sq), chess.square_file(from_sq)
    tr, tf = chess.square_rank(to_sq),   chess.square_file(to_sq)

    dr = 0 if tr == fr else (1 if tr > fr else -1)
    df = 0 if tf == ff else (1 if tf > ff else -1)

    if dr == 0 and df == 0:
        return []

    squares: list[chess.Square] = []
    r, f = fr + dr, ff + df
    while (r, f) != (tr, tf):
        squares.append(chess.square(f, r))
        r += dr
        f += df
    return squares
