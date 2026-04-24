"""
engine/quantum_state.py – Quantum superposition, entanglement, and amplitude tracking.

Design principles (from the research paper):
  - Each QuantumPiece stores amplitudes (complex numbers) or probability weights.
  - Amplitudes enable interference: when two paths lead to the same square,
    their amplitudes add before squaring to get probability.
  - Entanglement: linked pieces collapse together (correlated measurement).
  - Normalization is enforced after every mutation.
"""

import random
import math
import cmath
from typing import Optional
import chess


class QuantumPiece:
    """
    A chess piece in superposition across one or more squares.

    Attributes
    ----------
    id          : unique integer identifier
    piece       : chess.Piece (type + colour)
    positions   : list of chess.Square
    amplitudes  : list of complex numbers (one per position)
    entangled_with : Optional[int]  — id of entangled partner
    """

    _next_id: int = 0

    def __init__(self, piece: chess.Piece,
                 positions: list[chess.Square],
                 amplitudes: Optional[list[complex]] = None):
        self.id: int = QuantumPiece._next_id
        QuantumPiece._next_id += 1
        self.piece: chess.Piece = piece
        self.positions: list[chess.Square] = list(positions)
        self.entangled_with: Optional[int] = None

        if amplitudes is None:
            # Equal superposition with real positive amplitudes
            n = len(positions)
            assert n >= 1, "QuantumPiece must have at least one position"
            amp = math.sqrt(1.0 / n)
            self.amplitudes: list[complex] = [complex(amp, 0.0)] * n
        else:
            assert len(amplitudes) == len(positions), (
                f"amplitudes length {len(amplitudes)} != positions length {len(positions)}"
            )
            self.amplitudes = [complex(a) for a in amplitudes]
            self._normalize()

    # ------------------------------------------------------------------
    # Probability helpers
    # ------------------------------------------------------------------

    def probability(self, sq: chess.Square) -> float:
        """Return P(piece is at sq) = |amplitude|^2."""
        if sq not in self.positions:
            return 0.0
        idx = self.positions.index(sq)
        return abs(self.amplitudes[idx]) ** 2

    def probabilities(self) -> list[float]:
        """Return list of |amplitude|^2 for each position."""
        return [abs(a) ** 2 for a in self.amplitudes]

    def total_existence_probability(self) -> float:
        """Sum of all |amplitude|^2 — should be 1.0 after normalisation."""
        return sum(abs(a) ** 2 for a in self.amplitudes)

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalize(self):
        total = sum(abs(a) ** 2 for a in self.amplitudes)
        if total < 1e-12:
            return
        scale = 1.0 / math.sqrt(total)
        self.amplitudes = [a * scale for a in self.amplitudes]

    # ------------------------------------------------------------------
    # Collapse
    # ------------------------------------------------------------------

    def collapse(self) -> chess.Square:
        """
        Probabilistic collapse.  Sample a position according to |amplitude|^2.
        Returns the chosen square.
        """
        probs = self.probabilities()
        r = random.random()
        cumulative = 0.0
        for sq, p in zip(self.positions, probs):
            cumulative += p
            if r <= cumulative:
                return sq
        return self.positions[-1]  # numerical safety

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_position(self, sq: chess.Square, amplitude: complex):
        """
        Add a new position with a given amplitude, or add amplitudes if
        the square already exists (interference).
        """
        if sq in self.positions:
            idx = self.positions.index(sq)
            self.amplitudes[idx] += amplitude
        else:
            self.positions.append(sq)
            self.amplitudes.append(amplitude)
        self._normalize()

    def remove_position(self, sq: chess.Square):
        """Remove a position (e.g., capture confirmed that piece is not there)."""
        if sq in self.positions:
            idx = self.positions.index(sq)
            self.positions.pop(idx)
            self.amplitudes.pop(idx)
            if self.amplitudes:
                self._normalize()

    def set_amplitude(self, sq: chess.Square, amplitude: complex):
        """Set amplitude for an existing position directly."""
        assert sq in self.positions, f"Square {chess.square_name(sq)} not in positions"
        idx = self.positions.index(sq)
        self.amplitudes[idx] = amplitude
        self._normalize()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        parts = [
            f"{chess.square_name(sq)}(|a|={abs(a):.3f}, p={abs(a)**2:.2f})"
            for sq, a in zip(self.positions, self.amplitudes)
        ]
        return f"QP(id={self.id}, {self.piece}, [{', '.join(parts)}])"


# ---------------------------------------------------------------------------
# QuantumState: container for all quantum pieces + global invariant checks
# ---------------------------------------------------------------------------

class QuantumState:
    """
    Manages the collection of all QuantumPiece objects.

    Responsibilities:
      - Create/destroy quantum pieces
      - Build and maintain a square→qid index
      - Enforce: no double occupancy of the same classical square by two pieces
        of the SAME colour (different colour = capture scenario, measured)
      - Track entanglement pairs
    """

    def __init__(self):
        self._pieces: dict[int, QuantumPiece] = {}
        self._sq_index: dict[chess.Square, list[int]] = {}  # sq -> [qid, ...]

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def pieces(self) -> dict[int, QuantumPiece]:
        return self._pieces

    def get(self, qid: int) -> Optional[QuantumPiece]:
        return self._pieces.get(qid)

    def ids_at(self, sq: chess.Square) -> list[int]:
        return list(self._sq_index.get(sq, []))

    def occupied_squares(self) -> set[chess.Square]:
        return set(self._sq_index.keys())

    def __contains__(self, qid: int) -> bool:
        return qid in self._pieces

    def __len__(self) -> int:
        return len(self._pieces)

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    def _rebuild_index(self):
        self._sq_index = {}
        for qid, qp in self._pieces.items():
            for sq in qp.positions:
                self._sq_index.setdefault(sq, []).append(qid)

    # ------------------------------------------------------------------
    # Piece lifecycle
    # ------------------------------------------------------------------

    def add(self, qp: QuantumPiece):
        """Register a new QuantumPiece."""
        assert qp.id not in self._pieces, f"Duplicate qid {qp.id}"
        assert len(qp.positions) >= 1
        self._pieces[qp.id] = qp
        for sq in qp.positions:
            self._sq_index.setdefault(sq, []).append(qp.id)

    def remove(self, qid: int) -> Optional[QuantumPiece]:
        """Remove and return a QuantumPiece by id."""
        qp = self._pieces.pop(qid, None)
        if qp is None:
            return None
        self._rebuild_index()
        return qp

    def create_superposition(self, piece: chess.Piece,
                              positions: list[chess.Square],
                              amplitudes: Optional[list[complex]] = None) -> QuantumPiece:
        """
        Create a new QuantumPiece in superposition and register it.
        """
        assert len(positions) >= 2, "Superposition requires at least 2 positions"
        qp = QuantumPiece(piece, positions, amplitudes)
        self.add(qp)
        return qp

    def collapse_piece(self, qid: int) -> Optional[chess.Square]:
        """
        Collapse a quantum piece to a definite square (chosen probabilistically).
        Removes the piece from the quantum state; caller must place it on
        the classical board.

        Returns the chosen square, or None if qid doesn't exist.
        """
        qp = self._pieces.get(qid)
        if qp is None:
            return None

        chosen = qp.collapse()

        # Break entanglement link on partner
        if qp.entangled_with is not None:
            partner = self._pieces.get(qp.entangled_with)
            if partner is not None:
                partner.entangled_with = None

        partner_id = qp.entangled_with
        self.remove(qid)

        # Cascade: collapse entangled partner
        if partner_id is not None and partner_id in self._pieces:
            self.collapse_piece(partner_id)

        return chosen

    # ------------------------------------------------------------------
    # Entanglement
    # ------------------------------------------------------------------

    def entangle(self, qid1: int, qid2: int) -> bool:
        """Create a symmetric entanglement link between two pieces."""
        if qid1 not in self._pieces or qid2 not in self._pieces:
            return False
        self._pieces[qid1].entangled_with = qid2
        self._pieces[qid2].entangled_with = qid1
        return True

    def disentangle(self, qid: int):
        """Remove entanglement for *qid* and its partner."""
        qp = self._pieces.get(qid)
        if qp is None:
            return
        if qp.entangled_with is not None:
            partner = self._pieces.get(qp.entangled_with)
            if partner:
                partner.entangled_with = None
        qp.entangled_with = None

    # ------------------------------------------------------------------
    # Interference
    # ------------------------------------------------------------------

    def apply_interference(self, qid: int, sq: chess.Square,
                            delta_amplitude: complex):
        """
        Adjust the amplitude of *qid* at *sq* to model interference.
        Amplitudes from two paths to the same square add (constructive or
        destructive depending on phase).
        """
        qp = self._pieces.get(qid)
        if qp is None or sq not in qp.positions:
            return
        idx = qp.positions.index(sq)
        qp.amplitudes[idx] += delta_amplitude
        qp._normalize()

    # ------------------------------------------------------------------
    # Invariant validation
    # ------------------------------------------------------------------

    def assert_valid(self):
        """
        Validate internal consistency.  Call after every state mutation
        during testing.
        """
        for qid, qp in self._pieces.items():
            assert len(qp.positions) == len(qp.amplitudes), (
                f"qid={qid}: positions/amplitudes length mismatch"
            )
            total = qp.total_existence_probability()
            assert abs(total - 1.0) < 1e-6, (
                f"qid={qid}: total probability {total:.6f} != 1.0"
            )
            if qp.entangled_with is not None:
                partner = self._pieces.get(qp.entangled_with)
                assert partner is not None, (
                    f"qid={qid} references missing partner qid={qp.entangled_with}"
                )
                assert partner.entangled_with == qid, (
                    f"Entanglement asymmetry: {qid} <-> {qp.entangled_with}"
                )

        # Rebuild index and check consistency
        expected_index: dict[chess.Square, list[int]] = {}
        for qid, qp in self._pieces.items():
            for sq in qp.positions:
                expected_index.setdefault(sq, []).append(qid)
        assert set(self._sq_index.keys()) == set(expected_index.keys()), (
            "Square index keys mismatch"
        )

    def __repr__(self) -> str:
        return f"QuantumState({len(self._pieces)} pieces)"
