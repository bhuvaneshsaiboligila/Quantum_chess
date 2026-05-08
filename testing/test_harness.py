"""
testing/test_harness.py – Automated game simulation and validation harness.

Usage (from project root):
    python main.py --test

Standalone:
    from testing.test_harness import QuantumChessTester
    from engine.board import QuantumBoard
    tester = QuantumChessTester(QuantumBoard)
    tester.run_all_tests()
"""

import random
import traceback
import time
from typing import Optional, Type

import chess

from engine.board import QuantumBoard
from engine.move import Move, MoveType
from testing.config import (
    NUM_GAMES, MAX_MOVES_PER_GAME, QUANTUM_MOVE_PROBABILITY,
    MAX_SPLIT_CANDIDATES, MAX_MERGE_CANDIDATES, RANDOM_SEED,
)
from testing.logger import GameLogger
from testing.analyzer import GameAnalyzer

# Piece values used by the heuristic AI
_PIECE_VALUE = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100,
}


class QuantumChessTester:
    """
    Runs automated simulations of Quantum Chess and validates game state
    after every move.

    Parameters
    ----------
    board_class : callable that returns a fresh QuantumBoard
    num_games   : number of simulations (default from config)
    """

    def __init__(self, board_class: Type[QuantumBoard] = QuantumBoard,
                 num_games: int = NUM_GAMES):
        self._board_class = board_class
        self._num_games = num_games
        if RANDOM_SEED is not None:
            random.seed(RANDOM_SEED)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_all_tests(self) -> None:
        print("\n" + "=" * 70)
        print("  QUANTUM CHESS – AUTOMATED TEST HARNESS")
        print(f"  Simulations: {self._num_games}  |  Max moves/game: {MAX_MOVES_PER_GAME}")
        print(f"  Quantum move probability: {QUANTUM_MOVE_PROBABILITY:.0%}")
        print("=" * 70 + "\n")

        game_summaries = []
        for gid in range(1, self._num_games + 1):
            summary = self._run_game(gid)
            game_summaries.append(summary)
            self._print_game_summary(gid, summary)

        print("\n" + "-" * 70)
        print("  All simulations complete.  Generating analysis report …")
        print("-" * 70)

        analyzer = GameAnalyzer()
        analyzer.print_report()

    # ------------------------------------------------------------------
    # Single game simulation
    # ------------------------------------------------------------------

    def _run_game(self, game_id: int) -> dict:
        logger = GameLogger(game_id)
        board: QuantumBoard = self._board_class()
        move_number = 0
        result = None
        termination = "unknown"

        print(f"[Game {game_id}] Starting …")

        try:
            while move_number < MAX_MOVES_PER_GAME:
                # --- check game-over before the move ---
                if board.is_game_over():
                    result = board.game_result()
                    termination = "king_captured"
                    break

                current_player = board.turn

                # --- choose a move ---
                move = self._choose_move(board, current_player)
                if move is None:
                    termination = "no_legal_moves"
                    result = board.game_result()
                    break

                move_number += 1

                # --- record pre-move events ---
                events: list[str] = []
                pre_measurement_count = len(board.measurement_log)

                # --- apply the move ---
                try:
                    success = board.apply_move(move)
                except AssertionError as exc:
                    err_msg = f"AssertionError in apply_move: {exc}"
                    logger.log_error("engine_exception", err_msg, move_number,
                                     traceback.format_exc())
                    print(f"  [!] Game {game_id}, move {move_number}: {err_msg}")
                    termination = "engine_crash"
                    break
                except Exception as exc:
                    err_msg = f"{type(exc).__name__}: {exc}"
                    logger.log_error("engine_exception", err_msg, move_number,
                                     traceback.format_exc())
                    print(f"  [!] Game {game_id}, move {move_number}: {err_msg}")
                    termination = "engine_crash"
                    break

                if not success:
                    # Distinguish quantum NDO physics (measurement happened during
                    # the attempt) from genuine engine failures (no measurement).
                    ndo_occurred = len(board.measurement_log) > pre_measurement_count
                    if ndo_occurred:
                        # Correct quantum behaviour: NDO collapse blocked destination.
                        events.append(f"NDO_BLOCKED:{move!r}")
                    else:
                        logger.log_error(
                            "move_failed",
                            f"apply_move returned False for {move!r} (player={_cn(current_player)})",
                            move_number,
                        )
                        events.append("MOVE_FAILED")
                    # Continue with a fallback classical move in both cases
                    fallback = self._fallback_classical(board, current_player)
                    if fallback is not None:
                        try:
                            board.apply_move(fallback)
                            events.append(f"FALLBACK_USED:{fallback!r}")
                        except Exception:
                            pass

                # Collect collapse events from measurement log
                new_measurements = board.measurement_log[-5:]
                for mres in new_measurements:
                    sq_name = chess.square_name(mres.chosen_square)
                    events.append(
                        f"COLLAPSED:{mres.piece}→{sq_name}"
                        + (f" (discarded: {[chess.square_name(s) for s in mres.discarded_squares]})"
                           if mres.discarded_squares else "")
                    )

                # --- validate state ---
                issues = self._validate_state(board)

                # --- log the move ---
                logger.log_move(
                    move_number=move_number,
                    player=current_player,
                    move=move,
                    board_before=board,   # logging after (pre not stored to keep memory low)
                    board_after=board,
                    events=events,
                    validation_issues=issues,
                )

                # --- check game-over after the move ---
                if board.is_game_over():
                    result = board.game_result()
                    termination = "king_captured"
                    break

            else:
                # Reached move limit
                logger.log_error(
                    "move_limit",
                    f"Game exceeded {MAX_MOVES_PER_GAME} moves without a result",
                    move_number,
                )
                termination = "move_limit"
                result = board.game_result()  # might still be None

        except Exception as exc:
            logger.log_error("harness_exception", str(exc),
                             move_number, traceback.format_exc())
            termination = "harness_crash"
            print(f"  [!!] Harness exception in game {game_id}: {exc}")

        # --- finalize and save ---
        logger.finalize(result, termination)
        log_path = logger.save()
        print(f"[Game {game_id}] {termination.upper()} | result={result} "
              f"| moves={move_number} | errors={logger.error_count} "
              f"| issues={logger.issue_count} → {log_path}")

        return {
            "game_id": game_id,
            "result": result,
            "termination": termination,
            "moves": move_number,
            "errors": logger.error_count,
            "issues": logger.issue_count,
        }

    # ------------------------------------------------------------------
    # Move selection – heuristic AI for both colours
    # ------------------------------------------------------------------

    def _choose_move(self, board: QuantumBoard, color: chess.Color) -> Optional[Move]:
        """
        Heuristic move selection.
        Priority: king capture > best capture > quantum (35% chance) > safe > random.
        """
        rules = board.rules
        cb = board.classical_board

        classical = rules.legal_classical_moves(color)
        if not classical:
            return None

        # 1. Always prioritise capturing the enemy king
        enemy = chess.BLACK if color == chess.WHITE else chess.WHITE
        for m in classical:
            victim = cb.piece_at(m.to_square)
            if victim and victim.piece_type == chess.KING and victim.color == enemy:
                return m

        # 2. Best capture by material value
        captures = []
        for m in classical:
            victim = cb.piece_at(m.to_square)
            if victim and victim.color == enemy:
                val = _PIECE_VALUE.get(victim.piece_type, 0)
                captures.append((val, m))
        if captures:
            captures.sort(key=lambda x: -x[0])
            top_val = captures[0][0]
            best = [mv for val, mv in captures if val == top_val]
            return random.choice(best)

        # 3. Quantum moves (~35% of remaining turns)
        if random.random() < QUANTUM_MOVE_PROBABILITY:
            qmove = self._pick_quantum_move(board, color)
            if qmove is not None:
                return qmove

        # 4. Safe classical moves (don't land on an attacked square)
        safe = []
        for m in classical:
            try:
                tmp = cb.copy()
                chess_move = chess.Move(m.from_square, m.to_square, m.promotion)
                if chess_move in tmp.pseudo_legal_moves:
                    tmp.push(chess_move)
                    if not tmp.is_attacked_by(enemy, m.to_square):
                        safe.append(m)
            except Exception as e:
                import traceback
                self.logger.log_error("move_eval_exception", f"Move evaluation exception: {e}",
                                      0, traceback.format_exc())
                print(f"[HARNESS ERROR] {e}")
                traceback.print_exc()
                # Mark this as a failed move in the log
        if safe:
            return random.choice(safe)

        return random.choice(classical)

    def _pick_quantum_move(self, board: QuantumBoard, color: chess.Color) -> Optional[Move]:
        """Try to pick a merge or split move; return None if none available."""
        rules = board.rules

        # Merge first (more powerful – concentrates force)
        merges = rules.legal_merge_moves(color)
        if merges:
            sample = merges[:MAX_MERGE_CANDIDATES]
            return random.choice(sample)

        splits = rules.legal_split_moves(color)
        if splits:
            sample = splits[:MAX_SPLIT_CANDIDATES]
            # Prefer splitting pieces that are not in danger
            cb = board.classical_board
            enemy = chess.BLACK if color == chess.WHITE else chess.WHITE
            safe_splits = [
                m for m in sample
                if not cb.is_attacked_by(enemy, m.from_square)
            ]
            if safe_splits:
                return random.choice(safe_splits)
            return random.choice(sample)

        return None

    def _fallback_classical(self, board: QuantumBoard,
                             color: chess.Color) -> Optional[Move]:
        """Emergency fallback: any classical move."""
        try:
            moves = board.rules.legal_classical_moves(color)
            return random.choice(moves) if moves else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # State validation
    # ------------------------------------------------------------------

    def _validate_state(self, board: QuantumBoard) -> list[dict]:
        """Return a list of discovered validation issues (empty = clean)."""
        issues: list[dict] = []
        cb = board.classical_board
        qs = board.quantum_state

        # 1. Quantum piece normalization
        for qid, qp in qs.pieces.items():
            total = qp.total_existence_probability()
            if abs(total - 1.0) > 0.01:
                issues.append({
                    "type": "quantum_normalization",
                    "qid": qid,
                    "total_prob": round(total, 6),
                    "message": (
                        f"Quantum piece id={qid} ({qp.piece}) "
                        f"has total probability {total:.4f}, expected 1.0"
                    ),
                })

        # 2. NDO (No Double Occupancy) check
        for sq, qids in qs._sq_index.items():
            classical_piece = cb.piece_at(sq)
            for qid in qids:
                qp = qs.get(qid)
                if qp is None:
                    issues.append({
                        "type": "stale_index",
                        "square": chess.square_name(sq),
                        "qid": qid,
                        "message": (
                            f"Square index has stale qid={qid} "
                            f"at {chess.square_name(sq)}"
                        ),
                    })
                elif classical_piece is not None and classical_piece.color == qp.piece.color:
                    issues.append({
                        "type": "ndo_violation",
                        "square": chess.square_name(sq),
                        "message": (
                            f"NDO violation at {chess.square_name(sq)}: "
                            f"classical {classical_piece} and quantum {qp.piece} "
                            f"(same colour)"
                        ),
                    })

        # 4. Square index vs piece positions consistency
        expected: dict = {}
        for qid, qp in qs.pieces.items():
            for sq in qp.positions:
                expected.setdefault(sq, []).append(qid)
        if set(qs._sq_index.keys()) != set(expected.keys()):
            issues.append({
                "type": "index_inconsistency",
                "message": (
                    "Square index keys mismatch piece positions. "
                    f"Index: {sorted(chess.square_name(s) for s in qs._sq_index)}, "
                    f"Expected: {sorted(chess.square_name(s) for s in expected)}"
                ),
            })

        # 5. King existence sanity
        for color, name in ((chess.WHITE, "white"), (chess.BLACK, "black")):
            prob = board.measurement.king_existence_probability(color)
            if prob < 0.0 or prob > 1.0 + 1e-9:
                issues.append({
                    "type": "king_prob_out_of_range",
                    "color": name,
                    "probability": round(prob, 4),
                    "message": f"{name} king existence probability is {prob:.4f} (expected 0–1)",
                })

        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _print_game_summary(game_id: int, summary: dict) -> None:
        status = "PASS" if summary["errors"] == 0 and summary["issues"] == 0 else "FAIL"
        print(f"  ├─ Game {game_id}: [{status}] "
              f"result={summary['result']}, "
              f"moves={summary['moves']}, "
              f"errors={summary['errors']}, "
              f"issues={summary['issues']}")


# ---------------------------------------------------------------------------
# Tiny helper
# ---------------------------------------------------------------------------

def _cn(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"
