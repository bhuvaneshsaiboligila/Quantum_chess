"""
quantum_chess.py – Core game engine, quantum layer, and AI.
"""

import random
import math
import chess
from typing import Optional


# ---------------------------------------------------------------------------
# Quantum State
# ---------------------------------------------------------------------------

class QuantumPiece:
    """
    A piece in superposition across multiple squares.

    positions     – list of chess.Square
    probabilities – list of floats that sum to 1.0
    piece         – chess.Piece (colour + type carried along)
    entangled_id  – id of another QuantumPiece that collapses together
    """

    _next_id = 0

    def __init__(self, piece: chess.Piece, positions: list, probabilities: list):
        self.id = QuantumPiece._next_id
        QuantumPiece._next_id += 1
        self.piece = piece
        self.positions: list[chess.Square] = list(positions)
        self.probabilities: list[float] = list(probabilities)
        self.entangled_id: Optional[int] = None
        self._normalize()

    def _normalize(self):
        total = sum(self.probabilities)
        if total > 0:
            self.probabilities = [p / total for p in self.probabilities]

    def collapse(self) -> chess.Square:
        """Randomly collapse to one square using probability distribution."""
        r = random.random()
        cumulative = 0.0
        for sq, prob in zip(self.positions, self.probabilities):
            cumulative += prob
            if r <= cumulative:
                return sq
        return self.positions[-1]  # safety

    def remove_position(self, sq: chess.Square):
        """Remove a square (used when a position is captured or nullified)."""
        if sq in self.positions:
            idx = self.positions.index(sq)
            self.positions.pop(idx)
            self.probabilities.pop(idx)
            self._normalize()

    def __repr__(self):
        parts = [f"{chess.square_name(s)}({p:.2f})"
                 for s, p in zip(self.positions, self.probabilities)]
        return f"QP({self.piece}, [{', '.join(parts)}])"


# ---------------------------------------------------------------------------
# Quantum Board
# ---------------------------------------------------------------------------

class QuantumBoard:
    """
    Manages the full game state:
      - classical_board  : chess.Board  (only fully-collapsed pieces)
      - quantum_pieces   : dict[int, QuantumPiece]
      - quantum_squares  : set of squares that are occupied by at least one
                           quantum piece (used for fast lookup)
    """

    def __init__(self):
        self.classical_board = chess.Board()
        self.quantum_pieces: dict[int, QuantumPiece] = {}
        # Maps square -> list of quantum piece ids present there
        self._sq_to_qids: dict[chess.Square, list[int]] = {}
        self.move_history: list[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_sq_map(self):
        self._sq_to_qids = {}
        for qid, qp in self.quantum_pieces.items():
            for sq in qp.positions:
                self._sq_to_qids.setdefault(sq, []).append(qid)

    def quantum_squares(self) -> set:
        return set(self._sq_to_qids.keys())

    def quantum_pieces_at(self, sq: chess.Square) -> list[int]:
        return list(self._sq_to_qids.get(sq, []))

    def is_quantum_square(self, sq: chess.Square) -> bool:
        return sq in self._sq_to_qids

    # ------------------------------------------------------------------
    # Superposition
    # ------------------------------------------------------------------

    def put_in_superposition(self, sq: chess.Square, targets: list[chess.Square],
                              probabilities: Optional[list] = None) -> Optional[int]:
        """
        Take a classical piece off *sq* and create a QuantumPiece spread
        across *targets*.  Returns the new quantum piece id, or None on failure.
        """
        piece = self.classical_board.piece_at(sq)
        if piece is None:
            return None
        if len(targets) < 2:
            return None

        # Equal probability if not specified
        if probabilities is None:
            n = len(targets)
            probabilities = [1.0 / n] * n

        if len(probabilities) != len(targets):
            return None

        # Remove from classical board
        self.classical_board.remove_piece_at(sq)

        qp = QuantumPiece(piece, targets, probabilities)
        self.quantum_pieces[qp.id] = qp
        self._rebuild_sq_map()
        return qp.id

    # ------------------------------------------------------------------
    # Collapse
    # ------------------------------------------------------------------

    def collapse_piece(self, qid: int) -> Optional[chess.Square]:
        """
        Collapse quantum piece *qid*.  The piece lands on the chosen square
        (if not already occupied classically) and is placed on the classical
        board.  Returns the collapsed square.
        """
        qp = self.quantum_pieces.pop(qid, None)
        if qp is None:
            return None

        # Handle entanglement first
        partner_id = qp.entangled_id
        if partner_id is not None and partner_id in self.quantum_pieces:
            partner = self.quantum_pieces[partner_id]
            partner.entangled_id = None

        landed = qp.collapse()

        # If the landing square has a classical piece, remove it (capture)
        self.classical_board.remove_piece_at(landed)
        self.classical_board.set_piece_at(landed, qp.piece)

        self._rebuild_sq_map()

        # Entanglement: collapse partner to its most probable remaining square
        if partner_id is not None and partner_id in self.quantum_pieces:
            self.collapse_piece(partner_id)

        return landed

    def collapse_at_square(self, sq: chess.Square):
        """Collapse all quantum pieces that include *sq* in their positions."""
        qids = list(self._sq_to_qids.get(sq, []))
        for qid in qids:
            if qid in self.quantum_pieces:
                self.collapse_piece(qid)

    def collapse_all(self):
        """Collapse every quantum piece (end-of-game cleanup)."""
        for qid in list(self.quantum_pieces.keys()):
            self.collapse_piece(qid)

    # ------------------------------------------------------------------
    # Entanglement
    # ------------------------------------------------------------------

    def entangle(self, qid1: int, qid2: int) -> bool:
        """Link two quantum pieces so that collapsing one collapses the other."""
        if qid1 not in self.quantum_pieces or qid2 not in self.quantum_pieces:
            return False
        self.quantum_pieces[qid1].entangled_id = qid2
        self.quantum_pieces[qid2].entangled_id = qid1
        return True

    # ------------------------------------------------------------------
    # Classical move
    # ------------------------------------------------------------------

    def apply_classical_move(self, move: chess.Move) -> bool:
        """
        Apply a legal classical move.
        Before moving, collapse any quantum pieces on source or destination.
        """
        # Collapse quantum pieces on destination (capture scenario)
        if self.is_quantum_square(move.to_square):
            self.collapse_at_square(move.to_square)

        # Collapse quantum pieces on source (shouldn't normally happen, but be safe)
        if self.is_quantum_square(move.from_square):
            self.collapse_at_square(move.from_square)

        # Re-check legality after collapse
        if move in self.classical_board.legal_moves:
            self.classical_board.push(move)
            self.move_history.append(move.uci())
            return True

        # Try any legal move from that square as fallback
        for m in self.classical_board.legal_moves:
            if m.from_square == move.from_square and m.to_square == move.to_square:
                self.classical_board.push(m)
                self.move_history.append(m.uci())
                return True

        return False

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def is_game_over(self) -> bool:
        return self.classical_board.is_game_over()

    def outcome_text(self) -> str:
        outcome = self.classical_board.outcome()
        if outcome is None:
            return ""
        if outcome.winner is None:
            return "Draw"
        return "White wins" if outcome.winner == chess.WHITE else "Black wins"

    def turn(self) -> chess.Color:
        return self.classical_board.turn

    def legal_moves_from(self, sq: chess.Square) -> list[chess.Move]:
        return [m for m in self.classical_board.legal_moves
                if m.from_square == sq]

    def piece_at(self, sq: chess.Square) -> Optional[chess.Piece]:
        return self.classical_board.piece_at(sq)


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

class QuantumChessAI:
    """
    Simple heuristic AI for Black.
    Priority: checkmate > captures > checks > safe moves > random.
    Quantum: occasionally puts pieces in superposition.
    """

    PIECE_VALUE = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
    }

    def __init__(self, color: chess.Color = chess.BLACK):
        self.color = color

    def choose_move(self, qboard: QuantumBoard) -> Optional[chess.Move]:
        board = qboard.classical_board
        if not list(board.legal_moves):
            return None

        moves = list(board.legal_moves)

        # 1. Checkmate in one
        for m in moves:
            board.push(m)
            if board.is_checkmate():
                board.pop()
                return m
            board.pop()

        # 2. Captures, scored by captured piece value
        captures = []
        for m in moves:
            victim = board.piece_at(m.to_square)
            if victim is not None:
                val = self.PIECE_VALUE.get(victim.piece_type, 0)
                captures.append((val, m))
        if captures:
            captures.sort(key=lambda x: -x[0])
            return captures[0][1]

        # 3. Checks
        for m in moves:
            board.push(m)
            if board.is_check():
                board.pop()
                return m
            board.pop()

        # 4. Safe moves (don't hang pieces)
        safe = []
        for m in moves:
            board.push(m)
            attacked = board.is_attacked_by(chess.WHITE, m.to_square)
            board.pop()
            if not attacked:
                safe.append(m)

        if safe:
            return random.choice(safe)

        return random.choice(moves)

    def should_superpose(self, qboard: QuantumBoard) -> Optional[tuple]:
        """
        Occasionally decide to put a piece into superposition.
        Returns (from_sq, [target1, target2]) or None.
        """
        if random.random() > 0.15:  # 15% chance per turn
            return None

        board = qboard.classical_board
        pieces = [(sq, board.piece_at(sq))
                  for sq in chess.SQUARES
                  if board.piece_at(sq) is not None
                  and board.piece_at(sq).color == self.color
                  and board.piece_at(sq).piece_type != chess.KING]

        random.shuffle(pieces)
        for sq, piece in pieces:
            legal = qboard.legal_moves_from(sq)
            targets = list({m.to_square for m in legal})
            if len(targets) >= 2:
                chosen = random.sample(targets, 2)
                return (sq, chosen)
        return None
