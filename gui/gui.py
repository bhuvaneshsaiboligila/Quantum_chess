"""
gui/gui.py – Pygame GUI for Quantum Chess (research-paper ruleset).

Controls
--------
  Left-click      : select / move (classical)
  Q + click       : start a split move (click two targets)
  E + click       : start an entangle operation (click two quantum pieces)
  R               : restart game
  Escape          : cancel current selection

Visual conventions
------------------
  - Classical pieces: solid icons with shadow
  - Quantum ghost pieces: semi-transparent, opacity pulses with sin()
  - Probability label: shown on each ghost square ("%d%%" of existence)
  - Entangled pieces: dashed teal outline
  - Last move: pale yellow highlight
  - Selected square: bright green highlight
  - Legal move targets: dot overlay
"""

import sys
import math
import time
import chess
import pygame
from typing import Optional

from engine.board import QuantumBoard
from engine.quantum_state import QuantumPiece
from engine.move import Move, MoveType
from engine.rules import RuleEngine

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

WINDOW_W  = 760
WINDOW_H  = 800
BOARD_PX  = 640
SQ        = BOARD_PX // 8          # 80 px per square
BX        = (WINDOW_W - BOARD_PX) // 2   # board x offset  = 60
BY        = 20                       # board y offset

INFO_H    = WINDOW_H - BY - BOARD_PX - 10   # ~130 px bottom panel

FPS = 60

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

C_LIGHT    = (240, 217, 181)
C_DARK     = (181, 136,  99)
C_SELECT   = ( 80, 200,  80, 160)
C_LEGAL    = (  0, 120, 255, 100)
C_LAST_MV  = (255, 255,   0,  70)
C_CHECK    = (255,  50,  50, 140)
C_QUANTUM  = ( 80, 140, 255)        # blue tint for quantum overlays
C_ENTANGLE = ( 30, 220, 200)        # teal for entanglement
C_BG       = ( 30,  30,  40)
C_TEXT     = (230, 230, 230)
C_WARN     = (255, 180,  50)
C_WIN      = ( 60, 220, 100)

# ---------------------------------------------------------------------------
# Unicode piece symbols  (white/black sets)
# ---------------------------------------------------------------------------

PIECE_UNICODE = {
    (chess.PAWN,   chess.WHITE): "♙",
    (chess.KNIGHT, chess.WHITE): "♘",
    (chess.BISHOP, chess.WHITE): "♗",
    (chess.ROOK,   chess.WHITE): "♖",
    (chess.QUEEN,  chess.WHITE): "♕",
    (chess.KING,   chess.WHITE): "♔",
    (chess.PAWN,   chess.BLACK): "♟",
    (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK,   chess.BLACK): "♜",
    (chess.QUEEN,  chess.BLACK): "♛",
    (chess.KING,   chess.BLACK): "♚",
}


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def sq_to_pixel(sq: chess.Square) -> tuple[int, int]:
    """Return top-left pixel of *sq* (white's perspective)."""
    file = chess.square_file(sq)
    rank = 7 - chess.square_rank(sq)
    return BX + file * SQ, BY + rank * SQ


def pixel_to_sq(px: int, py: int) -> Optional[chess.Square]:
    bx, by = px - BX, py - BY
    if 0 <= bx < BOARD_PX and 0 <= by < BOARD_PX:
        return chess.square(bx // SQ, 7 - (by // SQ))
    return None


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class Renderer:
    """Handles all drawing.  Stateless except for font/surface caches."""

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.font_piece = pygame.font.SysFont("segoeuisymbol,symbola,unifont", 58)
        self.font_label = pygame.font.SysFont("monospace", 11)
        self.font_info  = pygame.font.SysFont("monospace", 15)
        self.font_big   = pygame.font.SysFont("monospace", 28, bold=True)
        self._piece_cache: dict[tuple, pygame.Surface] = {}

    # ------------------------------------------------------------------
    # Master draw
    # ------------------------------------------------------------------

    def draw(self, state: "GameState", tick: int):
        self.screen.fill(C_BG)
        self._draw_squares()
        self._draw_highlights(state)
        self._draw_quantum_pieces(state, tick)
        self._draw_classical_pieces(state)
        self._draw_labels()
        self._draw_info_panel(state)
        if state.game_over_text:
            self._draw_game_over(state.game_over_text)
        pygame.display.flip()

    # ------------------------------------------------------------------
    # Board squares
    # ------------------------------------------------------------------

    def _draw_squares(self):
        for sq in chess.SQUARES:
            x, y = sq_to_pixel(sq)
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            color = C_LIGHT if (file + rank) % 2 == 1 else C_DARK
            pygame.draw.rect(self.screen, color, (x, y, SQ, SQ))

    # ------------------------------------------------------------------
    # Highlights
    # ------------------------------------------------------------------

    def _draw_highlights(self, state: "GameState"):
        overlay = pygame.Surface((SQ, SQ), pygame.SRCALPHA)

        # Last move
        if state.last_move:
            mv = state.last_move
            squares_to_tint = []
            if mv.move_type == MoveType.CLASSICAL:
                squares_to_tint = [mv.from_square, mv.to_square]
            elif mv.move_type == MoveType.SPLIT:
                squares_to_tint = [mv.from_square] + list(mv.targets)
            elif mv.move_type == MoveType.MERGE:
                squares_to_tint = list(mv.sources) + [mv.to_square]

            overlay.fill(C_LAST_MV)
            for sq in squares_to_tint:
                x, y = sq_to_pixel(sq)
                self.screen.blit(overlay, (x, y))

        # Selected square
        if state.selected_sq is not None:
            overlay.fill(C_SELECT)
            x, y = sq_to_pixel(state.selected_sq)
            self.screen.blit(overlay, (x, y))

        # Legal move dots
        overlay.fill((0, 0, 0, 0))
        dot_surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        for sq in state.legal_targets:
            x, y = sq_to_pixel(sq)
            dot_surf.fill((0, 0, 0, 0))
            pygame.draw.circle(dot_surf, C_LEGAL,
                               (SQ // 2, SQ // 2), SQ // 7)
            self.screen.blit(dot_surf, (x, y))

        # Split first-target marker
        if state.split_first_target is not None:
            sq = state.split_first_target
            x, y = sq_to_pixel(sq)
            t_surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
            t_surf.fill((0, 0, 0, 0))
            pygame.draw.rect(t_surf, (*C_QUANTUM, 180), (4, 4, SQ - 8, SQ - 8), 3)
            self.screen.blit(t_surf, (x, y))

    # ------------------------------------------------------------------
    # Quantum ghost pieces
    # ------------------------------------------------------------------

    def _draw_quantum_pieces(self, state: "GameState", tick: int):
        board = state.board
        t = tick / FPS  # seconds

        for qp in board.quantum_state.pieces.values():
            probs = qp.probabilities()
            is_entangled = qp.entangled_with is not None

            for sq, prob in zip(qp.positions, probs):
                x, y = sq_to_pixel(sq)

                # Pulsing alpha: base 80, oscillates ±50
                pulse = math.sin(t * 3.0 + qp.id * 0.7) * 50
                alpha = int(max(30, min(200, 80 + pulse)))

                ghost = self._render_piece(qp.piece, alpha=alpha)
                self.screen.blit(ghost, (x, y))

                # Probability label
                pct = int(round(prob * 100))
                label = self.font_label.render(f"{pct}%", True, C_QUANTUM)
                lx = x + SQ - label.get_width() - 3
                ly = y + SQ - label.get_height() - 2
                self.screen.blit(label, (lx, ly))

                # Entanglement outline
                if is_entangled:
                    e_surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                    pygame.draw.rect(e_surf, (*C_ENTANGLE, 200),
                                     (2, 2, SQ - 4, SQ - 4), 2)
                    self.screen.blit(e_surf, (x, y))

    # ------------------------------------------------------------------
    # Classical pieces
    # ------------------------------------------------------------------

    def _draw_classical_pieces(self, state: "GameState"):
        cb = state.board.classical_board
        for sq in chess.SQUARES:
            piece = cb.piece_at(sq)
            if piece is None:
                continue
            x, y = sq_to_pixel(sq)
            surf = self._render_piece(piece, alpha=255)
            self.screen.blit(surf, (x, y))

    def _render_piece(self, piece: chess.Piece, alpha: int = 255) -> pygame.Surface:
        key = (piece.piece_type, piece.color, alpha)
        if key in self._piece_cache:
            return self._piece_cache[key]

        symbol = PIECE_UNICODE[(piece.piece_type, piece.color)]
        fg = (255, 255, 255) if piece.color == chess.WHITE else (20, 20, 20)
        outline = (30, 30, 30) if piece.color == chess.WHITE else (180, 180, 180)

        surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        # Shadow / outline
        for dx, dy in ((-1, 1), (1, 1), (0, 2)):
            sh = self.font_piece.render(symbol, True, outline)
            sh.set_alpha(min(alpha, 120))
            rect = sh.get_rect(center=(SQ // 2 + dx, SQ // 2 + dy))
            surf.blit(sh, rect)

        # Main glyph
        glyph = self.font_piece.render(symbol, True, fg)
        glyph.set_alpha(alpha)
        rect = glyph.get_rect(center=(SQ // 2, SQ // 2))
        surf.blit(glyph, rect)

        self._piece_cache[key] = surf
        return surf

    # ------------------------------------------------------------------
    # Rank / file labels
    # ------------------------------------------------------------------

    def _draw_labels(self):
        files = "abcdefgh"
        ranks = "87654321"
        for i in range(8):
            # File label bottom
            lbl = self.font_label.render(files[i], True, C_TEXT)
            x = BX + i * SQ + SQ - lbl.get_width() - 3
            y = BY + BOARD_PX - lbl.get_height() - 2
            self.screen.blit(lbl, (x, y))
            # Rank label left
            lbl = self.font_label.render(ranks[i], True, C_TEXT)
            x = BX - lbl.get_width() - 4
            y = BY + i * SQ + 3
            self.screen.blit(lbl, (x, y))

    # ------------------------------------------------------------------
    # Info panel
    # ------------------------------------------------------------------

    def _draw_info_panel(self, state: "GameState"):
        panel_y = BY + BOARD_PX + 8
        board = state.board

        # Turn indicator
        turn_str = "WHITE" if board.turn == chess.WHITE else "BLACK"
        turn_color = (255, 255, 255) if board.turn == chess.WHITE else (160, 160, 255)
        turn_lbl = self.font_info.render(f"Turn: {turn_str}", True, turn_color)
        self.screen.blit(turn_lbl, (BX, panel_y))

        # Mode indicator
        mode_str = state.mode_label()
        mode_lbl = self.font_info.render(f"Mode: {mode_str}", True, C_WARN)
        self.screen.blit(mode_lbl, (BX + 160, panel_y))

        # King existence probabilities
        white_kp = board.measurement.king_existence_probability(chess.WHITE)
        black_kp = board.measurement.king_existence_probability(chess.BLACK)
        wp_lbl = self.font_info.render(
            f"♔ {white_kp * 100:.0f}%", True, (255, 255, 255))
        bp_lbl = self.font_info.render(
            f"♚ {black_kp * 100:.0f}%", True, (160, 160, 255))
        self.screen.blit(wp_lbl, (BX + 380, panel_y))
        self.screen.blit(bp_lbl, (BX + 470, panel_y))

        # Quantum piece count
        qcount = len(board.quantum_state)
        q_lbl = self.font_info.render(f"Quantum pieces: {qcount}", True, C_QUANTUM)
        self.screen.blit(q_lbl, (BX, panel_y + 22))

        # Controls hint
        hint = "[Q]split  [E]entangle  [R]restart  [Esc]cancel"
        hint_lbl = self.font_label.render(hint, True, (160, 160, 160))
        self.screen.blit(hint_lbl, (BX, panel_y + 46))

        # Last measurement events
        if board.measurement_log:
            recent = board.measurement_log[-2:]
            for i, res in enumerate(recent):
                sq_name = chess.square_name(res.chosen_square)
                msg = f"Collapsed: {res.piece} → {sq_name}"
                m_lbl = self.font_label.render(msg, True, C_WARN)
                self.screen.blit(m_lbl, (BX, panel_y + 66 + i * 14))

    # ------------------------------------------------------------------
    # Game over overlay
    # ------------------------------------------------------------------

    def _draw_game_over(self, text: str):
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        lbl = self.font_big.render(text, True, C_WIN)
        rect = lbl.get_rect(center=(WINDOW_W // 2, WINDOW_H // 2 - 20))
        self.screen.blit(lbl, rect)

        sub = self.font_info.render("Press R to restart", True, C_TEXT)
        rect2 = sub.get_rect(center=(WINDOW_W // 2, WINDOW_H // 2 + 20))
        self.screen.blit(sub, rect2)


# ---------------------------------------------------------------------------
# Input state machine
# ---------------------------------------------------------------------------

class InputMode:
    NORMAL   = "Normal"
    SPLIT    = "Split"
    ENTANGLE = "Entangle"


# ---------------------------------------------------------------------------
# GameState  (MVC: model + view state)
# ---------------------------------------------------------------------------

class GameState:
    def __init__(self):
        self.board = QuantumBoard()
        self.selected_sq: Optional[chess.Square] = None
        self.legal_targets: list[chess.Square] = []
        self.last_move: Optional[Move] = None
        self.mode: str = InputMode.NORMAL
        self.split_source: Optional[chess.Square] = None
        self.split_first_target: Optional[chess.Square] = None
        self.entangle_first_sq: Optional[chess.Square] = None
        self.game_over_text: str = ""
        self.ai_thinking: bool = False

    def mode_label(self) -> str:
        if self.mode == InputMode.SPLIT:
            if self.split_source is None:
                return "Split – select piece"
            if self.split_first_target is None:
                return "Split – select target 1"
            return "Split – select target 2"
        if self.mode == InputMode.ENTANGLE:
            if self.entangle_first_sq is None:
                return "Entangle – click piece 1"
            return "Entangle – click piece 2"
        return "Normal"

    def reset(self):
        self.__init__()


# ---------------------------------------------------------------------------
# AI (heuristic, plays Black)
# ---------------------------------------------------------------------------

class QuantumAI:
    """Heuristic AI: checkmate > capture > check > safe > random.
       Occasionally performs split moves (15% chance)."""

    PIECE_VALUE = {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100,
    }

    def __init__(self):
        import random as _r
        self._rng = _r.Random()

    def choose_move(self, board: QuantumBoard) -> Optional[Move]:
        import random
        cb = board.classical_board
        rules = board.rules
        color = chess.BLACK

        classical = rules.legal_classical_moves(color)
        if not classical:
            return None

        # Try split occasionally
        if random.random() < 0.15:
            splits = rules.legal_split_moves(color)
            if splits:
                return random.choice(splits)

        # 1. King capture (highest priority in no-check variant)
        for m in classical:
            victim = cb.piece_at(m.to_square)
            if victim and victim.piece_type == chess.KING:
                return m

        # 2. Best capture by value
        captures = []
        for m in classical:
            victim = cb.piece_at(m.to_square)
            if victim and victim.color != color:
                captures.append((self.PIECE_VALUE.get(victim.piece_type, 0), m))
        if captures:
            captures.sort(key=lambda x: -x[0])
            return captures[0][1]

        # 3. Safe moves
        safe = []
        for m in classical:
            tmp = cb.copy()
            tmp.push(chess.Move(m.from_square, m.to_square, m.promotion))
            if not tmp.is_attacked_by(chess.WHITE, m.to_square):
                safe.append(m)
        if safe:
            return random.choice(safe)

        return random.choice(classical)


# ---------------------------------------------------------------------------
# Game controller
# ---------------------------------------------------------------------------

class Game:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.renderer = Renderer(screen)
        self.state = GameState()
        self.ai = QuantumAI()
        self._tick = 0

    # ------------------------------------------------------------------
    # Main loop step
    # ------------------------------------------------------------------

    def step(self):
        self._tick += 1

        # AI turn
        if (not self.state.game_over_text and
                self.state.board.turn == chess.BLACK and
                not self.state.ai_thinking):
            self._ai_turn()

        self.renderer.draw(self.state, self._tick)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            self._handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            sq = pixel_to_sq(*event.pos)
            if sq is not None:
                self._handle_click(sq)

    def _handle_key(self, key: int):
        state = self.state

        if key == pygame.K_r:
            state.reset()
            return

        if key == pygame.K_ESCAPE:
            state.mode = InputMode.NORMAL
            state.selected_sq = None
            state.legal_targets = []
            state.split_source = None
            state.split_first_target = None
            state.entangle_first_sq = None
            return

        if key == pygame.K_q and not state.game_over_text:
            if state.board.turn == chess.WHITE:
                state.mode = InputMode.SPLIT
                state.split_source = None
                state.split_first_target = None
            return

        if key == pygame.K_e and not state.game_over_text:
            if state.board.turn == chess.WHITE:
                state.mode = InputMode.ENTANGLE
                state.entangle_first_sq = None
            return

    def _handle_click(self, sq: chess.Square):
        state = self.state
        board = state.board

        if state.game_over_text:
            return

        if board.turn != chess.WHITE:
            return

        if state.mode == InputMode.SPLIT:
            self._handle_split_click(sq)
        elif state.mode == InputMode.ENTANGLE:
            self._handle_entangle_click(sq)
        else:
            self._handle_normal_click(sq)

    # ------------------------------------------------------------------
    # Normal click: select + move
    # ------------------------------------------------------------------

    def _handle_normal_click(self, sq: chess.Square):
        state = self.state
        board = state.board
        cb = board.classical_board

        # If a square is already selected, attempt a move
        if state.selected_sq is not None:
            if sq in state.legal_targets:
                move = Move.classical(state.selected_sq, sq)
                success = board.apply_move(move)
                if success:
                    state.last_move = move
                    state._check_game_over()
                state.selected_sq = None
                state.legal_targets = []
                return

            # Reselect a different own piece
            piece = cb.piece_at(sq)
            if piece and piece.color == chess.WHITE:
                state.selected_sq = sq
                state.legal_targets = [m.to_square
                                        for m in board.rules.legal_moves_from_square(sq)]
                return

            # Clicked empty or enemy with nothing pending
            state.selected_sq = None
            state.legal_targets = []
            return

        # Fresh selection
        piece = cb.piece_at(sq)
        if piece and piece.color == chess.WHITE:
            state.selected_sq = sq
            state.legal_targets = [m.to_square
                                    for m in board.rules.legal_moves_from_square(sq)]

    # ------------------------------------------------------------------
    # Split click FSM: select piece → target1 → target2
    # ------------------------------------------------------------------

    def _handle_split_click(self, sq: chess.Square):
        state = self.state
        board = state.board
        cb = board.classical_board

        if state.split_source is None:
            piece = cb.piece_at(sq)
            if piece and piece.color == chess.WHITE and piece.piece_type != chess.KING:
                state.split_source = sq
                state.legal_targets = list(set(
                    m.to_square for m in board.rules.legal_moves_from_square(sq)
                ))
            return

        if state.split_first_target is None:
            if sq in state.legal_targets and sq != state.split_source:
                state.split_first_target = sq
            return

        # Second target
        if sq in state.legal_targets and sq != state.split_source \
                and sq != state.split_first_target:
            move = Move.split(state.split_source,
                              state.split_first_target, sq)
            success = board.apply_move(move)
            if success:
                state.last_move = move
                state._check_game_over()

        # Reset split state regardless
        state.mode = InputMode.NORMAL
        state.split_source = None
        state.split_first_target = None
        state.legal_targets = []

    # ------------------------------------------------------------------
    # Entangle click FSM: click qpiece1 → click qpiece2
    # ------------------------------------------------------------------

    def _handle_entangle_click(self, sq: chess.Square):
        state = self.state
        board = state.board

        # Verify there is a white quantum piece at this square
        qids = board.quantum_state.ids_at(sq)
        if not qids:
            return
        qp = board.quantum_state.get(qids[0])
        if qp is None or qp.piece.color != chess.WHITE:
            return

        if state.entangle_first_sq is None:
            state.entangle_first_sq = sq
            return

        if sq != state.entangle_first_sq:
            move = Move.entangle(state.entangle_first_sq, sq)
            success = board.apply_move(move)
            if success:
                state.last_move = move
                state._check_game_over()

        state.mode = InputMode.NORMAL
        state.entangle_first_sq = None

    # ------------------------------------------------------------------
    # AI turn
    # ------------------------------------------------------------------

    def _ai_turn(self):
        board = self.state.board
        move = self.ai.choose_move(board)
        if move is None:
            return
        success = board.apply_move(move)
        if success:
            self.state.last_move = move
            self.state._check_game_over()


# Monkey-patch GameState with game-over check
def _check_game_over(self):
    result = self.board.game_result()
    if result == "white":
        self.game_over_text = "White wins! (Black king captured)"
    elif result == "black":
        self.game_over_text = "Black wins! (White king captured)"
    elif result == "draw":
        self.game_over_text = "Draw — both kings gone"

GameState._check_game_over = _check_game_over


# ---------------------------------------------------------------------------
# Entry point (called from main.py)
# ---------------------------------------------------------------------------

def run():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Quantum Chess")
    clock = pygame.time.Clock()

    game = Game(screen)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            game.handle_event(event)

        game.step()
        clock.tick(FPS)
