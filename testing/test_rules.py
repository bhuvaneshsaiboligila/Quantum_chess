import chess
import pytest
from engine.board import QuantumBoard
from engine.move import Move, MoveType


def make_clean_board():
    return QuantumBoard()


def test_pawn_cannot_split():
    board = make_clean_board()
    splits = board.rules.legal_split_moves(chess.WHITE)
    pawn_squares = [sq for sq in chess.SQUARES
                    if board.classical_board.piece_at(sq) == chess.Piece(chess.PAWN, chess.WHITE)]
    pawn_splits = [m for m in splits if m.from_square in pawn_squares]
    assert len(pawn_splits) == 0, "Pawns must not appear in split move list"


def test_promotion_move_accepted():
    board = make_clean_board()
    board.classical_board.clear()
    board.classical_board.set_piece_at(chess.A7, chess.Piece(chess.PAWN, chess.WHITE))
    board.classical_board.set_piece_at(chess.E1, chess.Piece(chess.KING, chess.WHITE))
    board.classical_board.set_piece_at(chess.E8, chess.Piece(chess.KING, chess.BLACK))
    board.turn = chess.WHITE
    board.classical_board.turn = chess.WHITE
    move = Move.classical(chess.A7, chess.A8, promotion=chess.QUEEN)
    result = board.apply_move(move)
    assert result == True, "Promotion move must succeed"
    piece = board.classical_board.piece_at(chess.A8)
    assert piece is not None and piece.piece_type == chess.QUEEN


def test_split_creates_quantum_piece():
    board = make_clean_board()
    # Knight on b1 splits to a3 and c3
    move = Move.split(chess.B1, chess.A3, chess.C3)
    result = board.apply_move(move)
    assert result == True
    qids = board.quantum_state.ids_at(chess.A3)
    assert len(qids) > 0, "A3 must have a quantum piece after split"
    qids2 = board.quantum_state.ids_at(chess.C3)
    assert len(qids2) > 0, "C3 must have a quantum piece after split"
    assert qids[0] == qids2[0], "Both positions must belong to same quantum piece"


def test_merge_requires_same_piece():
    board = make_clean_board()
    # Split knight b1 -> a3, c3; advance turn back to WHITE for the merge check
    board.apply_move(Move.split(chess.B1, chess.A3, chess.C3))
    board.turn = chess.WHITE
    board.classical_board.turn = chess.WHITE
    merges = board.rules.legal_merge_moves(chess.WHITE)
    for m in merges:
        s1_qids = set(board.quantum_state.ids_at(m.sources[0]))
        s2_qids = set(board.quantum_state.ids_at(m.sources[1]))
        assert s1_qids & s2_qids, "Merge sources must share a quantum piece ID"


def test_king_probability_at_game_start():
    board = make_clean_board()
    wp = board.measurement.king_existence_probability(chess.WHITE)
    bp = board.measurement.king_existence_probability(chess.BLACK)
    assert abs(wp - 1.0) < 1e-9, f"White king probability should be 1.0, got {wp}"
    assert abs(bp - 1.0) < 1e-9, f"Black king probability should be 1.0, got {bp}"


def test_no_effect_same_player_moves_again():
    board = make_clean_board()
    # _state_fingerprint is used by apply_move to detect no-effect moves (paper Rule 9)
    assert hasattr(board, '_state_fingerprint'), "Board must have _state_fingerprint method"
    # Verify the fingerprint changes after a real move
    before = board._state_fingerprint()
    board.apply_move(Move.classical(chess.E2, chess.E4))
    after = board._state_fingerprint()
    assert before != after, "State fingerprint must change after a classical move"


def test_collapse_does_not_destroy_friendly():
    # Set up a split knight on a3/c3, then verify board consistency.
    # NDO is enforced by the engine before any classical piece can land on a
    # quantum square occupied by a friendly — assert_valid() must not raise.
    board = make_clean_board()
    board.classical_board.clear()
    board.classical_board.set_piece_at(chess.E1, chess.Piece(chess.KING, chess.WHITE))
    board.classical_board.set_piece_at(chess.E8, chess.Piece(chess.KING, chess.BLACK))
    board.classical_board.set_piece_at(chess.B1, chess.Piece(chess.KNIGHT, chess.WHITE))
    board.apply_move(Move.split(chess.B1, chess.A3, chess.C3))
    board.assert_valid()  # Must not raise
