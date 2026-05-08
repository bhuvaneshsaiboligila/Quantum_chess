from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import chess
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.board import QuantumBoard
from engine.move import Move, MoveType
from gui.gui import AI_THINK_TIME, QuantumAI


app = Flask(__name__)
CORS(app)
game_lock = threading.Lock()
ai = QuantumAI()
ai_job_counter = 0


def _init_board_metadata(board: QuantumBoard) -> QuantumBoard:
    board.api_mode = "normal"
    board.api_last_move = None
    board.api_captured_white = []
    board.api_captured_black = []
    board.api_ai_thinking = False
    return board


game_board = _init_board_metadata(QuantumBoard())


@app.route("/")
def index():
    return send_from_directory(app.root_path, "index.html")


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _round_float(value: float) -> float:
    return round(float(value), 10)


def _move_to_string(move: Move | None) -> str | None:
    if move is None:
        return None

    if move.move_type == MoveType.CLASSICAL:
        chess_move = move.to_chess_move()
        return chess_move.uci() if chess_move is not None else None

    if move.move_type == MoveType.SPLIT:
        from_sq = chess.square_name(move.from_square)
        to1, to2 = move.targets
        return (
            f"split:{from_sq}:{chess.square_name(to1)}:{chess.square_name(to2)}"
        )

    from1, from2 = move.sources
    return (
        f"merge:{chess.square_name(from1)}:{chess.square_name(from2)}:"
        f"{chess.square_name(move.to_square)}"
    )


def _move_color(board: QuantumBoard, move: Move) -> chess.Color | None:
    if move.move_type in (MoveType.CLASSICAL, MoveType.SPLIT):
        piece = board.classical_board.piece_at(move.from_square)
        return piece.color if piece is not None else None

    qids = board.quantum_state.ids_at(move.sources[0])
    if not qids:
        return None

    qp = board.quantum_state.get(qids[0])
    return qp.piece.color if qp is not None else None


def _record_capture(board: QuantumBoard, piece: chess.Piece) -> None:
    if piece.color == chess.BLACK:
        board.api_captured_white.append(piece.symbol())
    else:
        board.api_captured_black.append(piece.symbol())


def _record_direct_capture(
    board: QuantumBoard,
    before_board: chess.Board,
    move: Move,
    mover_color: chess.Color | None,
) -> None:
    if mover_color is None or move.to_square is None:
        return

    if move.move_type == MoveType.CLASSICAL:
        chess_move = move.to_chess_move()
        if chess_move is not None and before_board.is_en_passant(chess_move):
            _record_capture(board, chess.Piece(chess.PAWN, not mover_color))
            return

    if move.move_type not in (MoveType.CLASSICAL, MoveType.MERGE):
        return

    victim = before_board.piece_at(move.to_square)
    if victim is not None and victim.color != mover_color:
        _record_capture(board, victim)


def _apply_and_track_move(board: QuantumBoard, move: Move) -> bool:
    before_board = board.classical_board.copy(stack=True)
    measurement_log_size = len(board.measurement_log)
    mover_color = _move_color(board, move)

    success = board.apply_move(move)
    if not success:
        return False

    for result in board.measurement_log[measurement_log_size:]:
        if result.captured_piece is not None:
            _record_capture(board, result.captured_piece)

    _record_direct_capture(board, before_board, move, mover_color)
    board.api_last_move = move
    return True


def _schedule_ai_turn(board: QuantumBoard) -> None:
    global ai_job_counter

    if board.api_ai_thinking or board.turn != chess.BLACK or board.is_game_over():
        return

    board.api_ai_thinking = True
    ai_job_counter += 1
    job_id = ai_job_counter
    worker = threading.Thread(
        target=_run_ai_turn,
        args=(board, job_id),
        daemon=True,
    )
    worker.start()


def _run_ai_turn(board: QuantumBoard, job_id: int) -> None:
    time.sleep(AI_THINK_TIME / 1000)

    with game_lock:
        if game_board is not board or board.turn != chess.BLACK or board.is_game_over():
            board.api_ai_thinking = False
            return

        move = ai.choose_move(board)
        if move is not None and _apply_and_track_move(board, move):
            board.api_ai_thinking = False
            return

        # Mirror the GUI fallback path: if the preferred move fails,
        # retry a few pseudo-legal classical moves before giving up.
        for fallback in _fallback_ai_moves(board, attempts=5):
            if _apply_and_track_move(board, fallback):
                board.api_ai_thinking = False
                return

        board.api_ai_thinking = False


def _fallback_ai_moves(board: QuantumBoard, attempts: int) -> list[Move]:
    import random

    board.classical_board.turn = chess.BLACK
    pseudo_legal = list(board.classical_board.pseudo_legal_moves)
    if not pseudo_legal:
        return []

    moves = []
    for _ in range(attempts):
        candidate = random.choice(pseudo_legal)
        promo = chess.QUEEN if (
            board.classical_board.piece_at(candidate.from_square)
            and board.classical_board.piece_at(candidate.from_square).piece_type == chess.PAWN
            and chess.square_rank(candidate.to_square) in (0, 7)
        ) else candidate.promotion
        moves.append(Move.classical(candidate.from_square, candidate.to_square, promo))
    return moves


def _parse_square(value: Any, field_name: str) -> chess.Square:
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a square string like 'e2'")
    try:
        return chess.parse_square(value)
    except ValueError as exc:
        raise ValueError(f"'{field_name}' must be a valid square name") from exc


def _parse_promotion(value: Any) -> int | None:
    if value is None:
        return None

    if isinstance(value, int):
        if value in {
            chess.QUEEN,
            chess.ROOK,
            chess.BISHOP,
            chess.KNIGHT,
        }:
            return value
        raise ValueError("promotion must be a valid python-chess piece type")

    if isinstance(value, str):
        lookup = {
            "q": chess.QUEEN,
            "r": chess.ROOK,
            "b": chess.BISHOP,
            "n": chess.KNIGHT,
        }
        promotion = lookup.get(value.lower())
        if promotion is not None:
            return promotion

    raise ValueError("promotion must be one of q, r, b, n or a matching piece type")


def _build_move(payload: dict[str, Any]) -> Move:
    move_type = payload.get("type")

    if move_type == "classical":
        return Move.classical(
            _parse_square(payload.get("from"), "from"),
            _parse_square(payload.get("to"), "to"),
            _parse_promotion(payload.get("promotion")),
        )

    if move_type == "split":
        return Move.split(
            _parse_square(payload.get("from"), "from"),
            _parse_square(payload.get("to1"), "to1"),
            _parse_square(payload.get("to2"), "to2"),
        )

    if move_type == "merge":
        return Move.merge(
            _parse_square(payload.get("from1"), "from1"),
            _parse_square(payload.get("from2"), "from2"),
            _parse_square(payload.get("to"), "to"),
        )

    raise ValueError("type must be one of: classical, split, merge")


def board_to_json(board: QuantumBoard) -> dict[str, Any]:
    classical_pieces = []
    for square, piece in sorted(board.classical_board.piece_map().items()):
        classical_pieces.append(
            {
                "square": chess.square_name(square),
                "piece": piece.symbol(),
                "color": _color_name(piece.color),
            }
        )

    quantum_pieces = []
    for qp in sorted(
        board.quantum_state.pieces.values(),
        key=lambda piece: (min(piece.positions), piece.id),
    ):
        quantum_pieces.append(
            {
                "squares": [chess.square_name(square) for square in qp.positions],
                "piece": qp.piece.symbol(),
                "color": _color_name(qp.piece.color),
                "probabilities": [_round_float(prob) for prob in qp.probabilities()],
            }
        )

    return {
        "turn": _color_name(board.turn),
        "mode": getattr(board, "api_mode", "normal"),
        "classical_pieces": classical_pieces,
        "quantum_pieces": quantum_pieces,
        "legal_moves": [
            move_text
            for move_text in (
                _move_to_string(move)
                for move in board.rules.all_legal_moves(board.turn)
            )
            if move_text is not None
        ],
        "white_king_prob": _round_float(
            board.measurement.king_existence_probability(chess.WHITE)
        ),
        "black_king_prob": _round_float(
            board.measurement.king_existence_probability(chess.BLACK)
        ),
        "game_over": board.is_game_over(),
        "winner": board.game_result(),
        "last_move": _move_to_string(getattr(board, "api_last_move", None)),
        "captured_white": list(getattr(board, "api_captured_white", [])),
        "captured_black": list(getattr(board, "api_captured_black", [])),
        "move_history": [
            move_text
            for move_text in (_move_to_string(move) for move in board.move_history)
            if move_text is not None
        ],
    }


@app.get("/api/state")
def get_state():
    with game_lock:
        return jsonify(board_to_json(game_board))


@app.post("/api/move")
def apply_move():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    try:
        move = _build_move(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with game_lock:
        if not _apply_and_track_move(game_board, move):
            return jsonify(
                {
                    "error": "Illegal or unsuccessful move",
                    "state": board_to_json(game_board),
                }
            ), 400

        if game_board.turn == chess.BLACK and not game_board.is_game_over():
            _schedule_ai_turn(game_board)

        return jsonify(board_to_json(game_board))


@app.post("/api/reset")
def reset_game():
    global game_board
    with game_lock:
        game_board = _init_board_metadata(QuantumBoard())
        return jsonify(board_to_json(game_board))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
