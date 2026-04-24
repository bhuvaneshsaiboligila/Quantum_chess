"""
engine/move.py – Move types: classical, split, and merge.

Three move types (from the research paper):
  CLASSICAL  : standard chess move; one source → one destination
  SPLIT      : one source → two destinations (50/50 probability split)
  MERGE      : two sources → one destination (amplitude recombination)

Split amplitude rule: each target gets amplitude = source_amplitude / sqrt(2)
Merge amplitude rule: destination gets sum of both source amplitudes (interference)
"""

from __future__ import annotations
import math
import chess
from enum import Enum, auto
from typing import Optional


class MoveType(Enum):
    CLASSICAL = auto()
    SPLIT     = auto()
    MERGE     = auto()


class Move:
    """
    Represents any quantum chess move.

    Classical:  from_square → to_square
    Split:      from_square → (target1, target2)
    Merge:      (source1, source2) → to_square
    """

    def __init__(self,
                 move_type: MoveType,
                 from_square: Optional[chess.Square] = None,
                 to_square: Optional[chess.Square] = None,
                 sources: Optional[tuple[chess.Square, chess.Square]] = None,
                 targets: Optional[tuple[chess.Square, chess.Square]] = None,
                 promotion: Optional[int] = None):

        self.move_type: MoveType = move_type
        self.promotion: Optional[int] = promotion

        if move_type == MoveType.CLASSICAL:
            assert from_square is not None and to_square is not None, (
                "Classical move requires from_square and to_square"
            )
            self.from_square: Optional[chess.Square] = from_square
            self.to_square: Optional[chess.Square] = to_square
            self.sources: Optional[tuple[chess.Square, chess.Square]] = None
            self.targets: Optional[tuple[chess.Square, chess.Square]] = None

        elif move_type == MoveType.SPLIT:
            assert from_square is not None and targets is not None, (
                "Split move requires from_square and targets"
            )
            assert len(targets) == 2, "Split move requires exactly 2 targets"
            self.from_square = from_square
            self.to_square = None
            self.sources = None
            self.targets = tuple(targets)  # type: ignore[assignment]

        elif move_type == MoveType.MERGE:
            assert sources is not None and to_square is not None, (
                "Merge move requires sources and to_square"
            )
            assert len(sources) == 2, "Merge move requires exactly 2 sources"
            self.from_square = None
            self.to_square = to_square
            self.sources = tuple(sources)  # type: ignore[assignment]
            self.targets = None

        else:
            raise ValueError(f"Unknown MoveType: {move_type}")

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def classical(cls, from_sq: chess.Square, to_sq: chess.Square,
                  promotion: Optional[int] = None) -> "Move":
        return cls(MoveType.CLASSICAL, from_square=from_sq,
                   to_square=to_sq, promotion=promotion)

    @classmethod
    def split(cls, from_sq: chess.Square,
              target1: chess.Square, target2: chess.Square) -> "Move":
        return cls(MoveType.SPLIT, from_square=from_sq,
                   targets=(target1, target2))

    @classmethod
    def merge(cls, src1: chess.Square, src2: chess.Square,
              to_sq: chess.Square) -> "Move":
        return cls(MoveType.MERGE, sources=(src1, src2), to_square=to_sq)

    # ------------------------------------------------------------------
    # Amplitude rules
    # ------------------------------------------------------------------

    @staticmethod
    def split_amplitude(source_amplitude: complex) -> complex:
        """Each split target receives amplitude / sqrt(2)."""
        return source_amplitude / math.sqrt(2)

    @staticmethod
    def merge_amplitude(amp1: complex, amp2: complex) -> complex:
        """Merged destination gets sum of both amplitudes (interference)."""
        return amp1 + amp2

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_chess_move(self) -> Optional[chess.Move]:
        """Convert to python-chess Move if classical, else None."""
        if self.move_type == MoveType.CLASSICAL:
            assert self.from_square is not None and self.to_square is not None
            return chess.Move(self.from_square, self.to_square, self.promotion)
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def assert_valid(self):
        if self.move_type == MoveType.CLASSICAL:
            assert self.from_square is not None
            assert self.to_square is not None
            assert self.from_square != self.to_square, "Move from/to must differ"

        elif self.move_type == MoveType.SPLIT:
            assert self.from_square is not None
            assert self.targets is not None
            t1, t2 = self.targets
            assert t1 != t2, "Split targets must be different squares"
            assert self.from_square != t1
            assert self.from_square != t2

        elif self.move_type == MoveType.MERGE:
            assert self.sources is not None
            assert self.to_square is not None
            s1, s2 = self.sources
            assert s1 != s2, "Merge sources must be different squares"

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        if self.move_type == MoveType.CLASSICAL:
            return (f"Move.classical({chess.square_name(self.from_square)}"
                    f"→{chess.square_name(self.to_square)})")
        elif self.move_type == MoveType.SPLIT:
            t1, t2 = self.targets
            return (f"Move.split({chess.square_name(self.from_square)}"
                    f"→{chess.square_name(t1)},{chess.square_name(t2)})")
        else:
            s1, s2 = self.sources
            return (f"Move.merge({chess.square_name(s1)},{chess.square_name(s2)}"
                    f"→{chess.square_name(self.to_square)})")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Move):
            return False
        if self.move_type != other.move_type:
            return False
        if self.move_type == MoveType.CLASSICAL:
            return (self.from_square == other.from_square and
                    self.to_square == other.to_square and
                    self.promotion == other.promotion)
        elif self.move_type == MoveType.SPLIT:
            return (self.from_square == other.from_square and
                    set(self.targets) == set(other.targets))
        else:
            return (set(self.sources) == set(other.sources) and
                    self.to_square == other.to_square)

    def __hash__(self) -> int:
        if self.move_type == MoveType.CLASSICAL:
            return hash((self.move_type, self.from_square, self.to_square, self.promotion))
        elif self.move_type == MoveType.SPLIT:
            return hash((self.move_type, self.from_square, frozenset(self.targets)))
        else:
            return hash((self.move_type, frozenset(self.sources), self.to_square))
