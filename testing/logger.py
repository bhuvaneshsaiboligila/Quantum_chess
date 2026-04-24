"""
testing/logger.py – Structured per-game JSON logger.

Each game produces:  logs/game_<id>.json
"""

import json
import os
import datetime
from typing import Optional, TYPE_CHECKING

import chess

if TYPE_CHECKING:
    from engine.board import QuantumBoard
    from engine.move import Move

from testing.config import LOG_DIR


class GameLogger:
    """Records all move/state/event data for one game simulation."""

    def __init__(self, game_id: int):
        self.game_id = game_id
        self._record: dict = {
            "game_id": game_id,
            "start_time": datetime.datetime.utcnow().isoformat(),
            "end_time": None,
            "result": None,
            "termination": None,
            "total_moves": 0,
            "quantum_moves": 0,
            "errors": [],
            "validation_issues": [],
            "moves": [],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_move(self,
                 move_number: int,
                 player: chess.Color,
                 move: "Move",
                 board_before: "QuantumBoard",
                 board_after: "QuantumBoard",
                 events: list[str],
                 validation_issues: list[dict]) -> None:
        from engine.move import MoveType

        is_quantum = move.move_type in (MoveType.SPLIT, MoveType.MERGE)

        entry = {
            "move_number": move_number,
            "player": _color_name(player),
            "move_type": move.move_type.name.lower(),
            "move": _serialize_move(move),
            "board_state": _serialize_board(board_after),
            "events": events,
            "validation_issues": validation_issues,
        }

        self._record["moves"].append(entry)
        self._record["total_moves"] = move_number

        if is_quantum:
            self._record["quantum_moves"] += 1

        if validation_issues:
            for issue in validation_issues:
                issue["move_number"] = move_number
                self._record["validation_issues"].append(issue)

    def log_error(self, error_type: str, message: str,
                  move_number: Optional[int] = None,
                  exc_info: Optional[str] = None) -> None:
        self._record["errors"].append({
            "error_type": error_type,
            "message": message,
            "move_number": move_number,
            "exc_info": exc_info,
        })

    def finalize(self, result: Optional[str], termination: str) -> None:
        self._record["end_time"] = datetime.datetime.utcnow().isoformat()
        self._record["result"] = result
        self._record["termination"] = termination

    def save(self) -> str:
        """Write log to disk; return the file path."""
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f"game_{self.game_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._record, f, indent=2, default=_json_fallback)
        return path

    @property
    def error_count(self) -> int:
        return len(self._record["errors"])

    @property
    def issue_count(self) -> int:
        return len(self._record["validation_issues"])


# ---------------------------------------------------------------------------
# Serialization helpers (all return JSON-safe types)
# ---------------------------------------------------------------------------

def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _serialize_move(move: "Move") -> dict:
    from engine.move import MoveType
    if move.move_type == MoveType.CLASSICAL:
        return {
            "type": "classical",
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
            "promotion": chess.piece_name(move.promotion) if move.promotion else None,
        }
    elif move.move_type == MoveType.SPLIT:
        t1, t2 = move.targets
        return {
            "type": "split",
            "from": chess.square_name(move.from_square),
            "targets": [chess.square_name(t1), chess.square_name(t2)],
        }
    else:  # MERGE
        s1, s2 = move.sources
        return {
            "type": "merge",
            "sources": [chess.square_name(s1), chess.square_name(s2)],
            "to": chess.square_name(move.to_square),
        }


def _serialize_board(board: "QuantumBoard") -> dict:
    cb = board.classical_board
    qs = board.quantum_state
    ms = board.measurement

    piece_map = {}
    for sq in chess.SQUARES:
        p = cb.piece_at(sq)
        if p:
            piece_map[chess.square_name(sq)] = {
                "type": chess.piece_name(p.piece_type),
                "color": _color_name(p.color),
            }

    quantum_list = []
    for qid, qp in qs.pieces.items():
        probs = qp.probabilities()
        quantum_list.append({
            "id": qid,
            "piece_type": chess.piece_name(qp.piece.piece_type),
            "color": _color_name(qp.piece.color),
            "positions": [chess.square_name(sq) for sq in qp.positions],
            "probabilities": [round(p, 4) for p in probs],
            "entangled_with": qp.entangled_with,
        })

    return {
        "fen": cb.fen(),
        "turn": _color_name(board.turn),
        "classical_pieces": piece_map,
        "quantum_pieces": quantum_list,
        "white_king_prob": round(ms.king_existence_probability(chess.WHITE), 4),
        "black_king_prob": round(ms.king_existence_probability(chess.BLACK), 4),
        "quantum_piece_count": len(qs),
    }


def _json_fallback(obj):
    """Fallback for any non-serializable objects that slip through."""
    return str(obj)
