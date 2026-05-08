"""
gui/gui.py – Pygame GUI for Quantum Chess (research-paper ruleset).

Controls
--------
  Left-click             : select / move (classical)
  Left-click quantum sq  : auto-enter merge mode with that square as source 1
  Q + click              : start a split move (click two targets)
  M + click              : start a merge move manually
  R                      : restart game
  Escape                 : cancel current selection

Visual conventions
------------------
  - Classical pieces: solid icons with shadow
  - Quantum ghost pieces: semi-transparent, opacity pulses with sin()
  - Probability label: shown on each ghost square ("%d%%" of existence)
  - Last move: pale yellow highlight
  - Selected square: yellow if moves available, red if no moves
  - Legal move targets: green dot overlay
  - Quantum square badge: cyan "Q" in top-left corner
  - Status bar: mode / selection info / key hints at bottom of window
"""

import os
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
# Asset path
# ---------------------------------------------------------------------------

_PIECES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "assets", "pieces")

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PANEL_W    = 220          # side panel width
PANEL_PAD  = 12          # padding inside side panel

WINDOW_H   = 800

AI_THINK_TIME = 1800     # milliseconds the AI "thinks" before playing

STATUS_H   = 90          # three-row status bar at the bottom
BY         = 6           # top margin above board
BX         = 28          # fixed left margin (board left edge)
SQ         = (WINDOW_H - STATUS_H - BY) // 8   # 88 px per square
BOARD_PX   = SQ * 8                             # 704 px
PANEL_X    = BX + BOARD_PX                      # 732 — left edge of side panel
WINDOW_W   = PANEL_X + PANEL_W                  # 952
BOARD_CX   = BX + BOARD_PX // 2                 # 380 — horizontal centre of board
STATUS_Y   = BY + BOARD_PX                      # 710

# Status-bar row geometry (3 rows packed into STATUS_H = 90 px)
ROW3_Y, ROW3_H = STATUS_Y,          25   # context message
ROW2_Y, ROW2_H = STATUS_Y + 25,     35   # game state (turn / mode / king %)
ROW1_Y, ROW1_H = STATUS_Y + 60,     30   # key hints

FPS = 60

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

C_LIGHT        = (240, 217, 181)
C_DARK         = (181, 136,  99)
C_SELECT       = ( 80, 200,  80, 160)   # legacy — replaced by dynamic selection
C_SELECT_OK    = (255, 255,   0, 120)   # yellow: selected, moves available
C_SELECT_NONE  = (255,  50,  50, 120)   # red: selected, no legal moves here
C_LEGAL        = (  0, 200,   0, 160)   # green dots for valid destinations
C_LAST_MV      = (255, 255,   0,  70)
C_CHECK        = (255,  50,  50, 140)
C_QUANTUM      = ( 80, 140, 255)        # blue tint for quantum overlays
C_QUANTUM_BADGE = (  0, 255, 255)       # cyan "Q" badge on quantum squares
C_STATUS_BG    = ( 18,  18,  28)        # status bar background
C_BG           = ( 30,  30,  40)
C_TEXT         = (230, 230, 230)
C_WARN         = (255, 180,  50)
C_WIN          = ( 60, 220, 100)

# ---------------------------------------------------------------------------
# Piece asset mapping and fallback letter map
# ---------------------------------------------------------------------------

PIECE_IMAGE_FILES = {
    (chess.KING,   chess.WHITE): "white-king.png",
    (chess.QUEEN,  chess.WHITE): "white-queen.png",
    (chess.ROOK,   chess.WHITE): "white-rook.png",
    (chess.BISHOP, chess.WHITE): "white-bishop.png",
    (chess.KNIGHT, chess.WHITE): "white-knight.png",
    (chess.PAWN,   chess.WHITE): "white-pawn.png",
    (chess.KING,   chess.BLACK): "black-king.png",
    (chess.QUEEN,  chess.BLACK): "black-queen.png",
    (chess.ROOK,   chess.BLACK): "black-rook.png",
    (chess.BISHOP, chess.BLACK): "black-bishop.png",
    (chess.KNIGHT, chess.BLACK): "black-knight.png",
    (chess.PAWN,   chess.BLACK): "black-pawn.png",
}

PIECE_LETTERS = {
    chess.KING: "K", chess.QUEEN: "Q", chess.ROOK: "R",
    chess.BISHOP: "B", chess.KNIGHT: "N", chess.PAWN: "P",
}

_PIECE_PREFIX = {
    chess.KING: "K", chess.QUEEN: "Q", chess.ROOK: "R",
    chess.BISHOP: "B", chess.KNIGHT: "N",
    # PAWN intentionally omitted — no prefix in algebraic notation
}


def _build_move_notation(move: Move, cb: chess.Board) -> str:
    """Short algebraic-style label for a move (called before apply_move)."""
    if move.move_type == MoveType.SPLIT:
        frm = chess.square_name(move.from_square)
        t1, t2 = chess.square_name(move.targets[0]), chess.square_name(move.targets[1])
        return f"Q-{frm}>{t1},{t2}"
    if move.move_type == MoveType.MERGE:
        s1, s2 = chess.square_name(move.sources[0]), chess.square_name(move.sources[1])
        return f"M-{s1},{s2}>{chess.square_name(move.to_square)}"
    # CLASSICAL
    piece = cb.piece_at(move.from_square)
    prefix = _PIECE_PREFIX.get(piece.piece_type, "") if piece else ""
    cap = "x" if cb.piece_at(move.to_square) else ""
    promo = f"={PIECE_LETTERS[move.promotion]}" if move.promotion else ""
    return f"{prefix}{chess.square_name(move.from_square)}{cap}{chess.square_name(move.to_square)}{promo}"


def _clip_text(text: str, max_w: int, font: pygame.font.Font) -> str:
    """Truncate *text* so its rendered width fits within *max_w* pixels."""
    if font.size(text)[0] <= max_w:
        return text
    while len(text) > 0 and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return (text + "…") if text else ""


# ---------------------------------------------------------------------------
# Promotion overlay helpers (module-level so Game and Renderer share them)
# ---------------------------------------------------------------------------

_PROMO_PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]


def _promotion_overlay_rects() -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) for each of the 4 promotion-choice squares."""
    total_w = len(_PROMO_PIECES) * SQ
    start_x = BX + (BOARD_PX - total_w) // 2
    start_y = BY + (BOARD_PX - SQ) // 2
    return [(start_x + i * SQ, start_y, SQ, SQ) for i in range(len(_PROMO_PIECES))]


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
        self.font_label         = pygame.font.SysFont("monospace", 11)
        self.font_coord         = pygame.font.SysFont("arial,freesansbold", 14)
        self.font_info          = pygame.font.SysFont("monospace", 15)
        self.font_status        = pygame.font.SysFont("monospace", 18)
        self.font_big           = pygame.font.SysFont("monospace", 28, bold=True)
        self.font_piece_fallback = pygame.font.SysFont("arial,freesansbold", 34, bold=True)
        self.font_tiny          = pygame.font.SysFont("arial,freesansbold", 10, bold=True)
        self._piece_cache: dict[tuple, pygame.Surface] = {}

        # Try Option A: load piece images from assets/
        self._piece_images: dict[tuple, pygame.Surface] = {}
        self._use_images = False
        try:
            for key, filename in PIECE_IMAGE_FILES.items():
                path = os.path.join(_PIECES_DIR, filename)
                img = pygame.image.load(path).convert_alpha()
                img = pygame.transform.smoothscale(img, (SQ - 8, SQ - 8))
                self._piece_images[key] = img
            self._use_images = True
            print("[Renderer] Option A: piece images loaded from assets/pieces/")
        except Exception as e:
            print(f"[Renderer] Option A failed ({e}); falling back to Option B (shapes)")
            self._use_images = False

    # ------------------------------------------------------------------
    # Master draw
    # ------------------------------------------------------------------

    def draw(self, state: "GameState", tick: int):
        self.screen.fill(C_BG)
        self._draw_squares()
        self._draw_highlights(state)
        self._draw_quantum_pieces(state, tick)
        self._draw_classical_pieces(state)
        self._draw_quantum_badges(state)
        self._draw_labels()
        self._draw_side_panel(state)
        self._draw_status_bar(state)
        if state.promotion_pending:
            self._draw_promotion_overlay()
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

        # Selected square — yellow when moves exist, red when none
        if state.selected_sq is not None:
            sel_color = C_SELECT_OK if state.legal_targets else C_SELECT_NONE
            overlay.fill(sel_color)
            x, y = sq_to_pixel(state.selected_sq)
            self.screen.blit(overlay, (x, y))

        # Legal move dots — green circles at each valid destination
        dot_surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        for sq in state.legal_targets:
            x, y = sq_to_pixel(sq)
            dot_surf.fill((0, 0, 0, 0))
            pygame.draw.circle(dot_surf, C_LEGAL, (SQ // 2, SQ // 2), SQ // 7)
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

            for sq, prob in zip(qp.positions, probs):
                x, y = sq_to_pixel(sq)

                # Pulsing alpha: base 80, oscillates ±50
                pulse = math.sin(t * 3.0 + qp.id * 0.7) * 50
                alpha = int(max(30, min(200, 80 + pulse)))

                ghost = self._render_piece(qp.piece, alpha=alpha)
                self.screen.blit(ghost, (x, y))

                # Probability label (bottom-right)
                pct = int(round(prob * 100))
                label = self.font_label.render(f"{pct}%", True, C_QUANTUM)
                lx = x + SQ - label.get_width() - 3
                ly = y + SQ - label.get_height() - 2
                self.screen.blit(label, (lx, ly))

    # ------------------------------------------------------------------
    # Quantum square badge ("Q" in top-left corner of each quantum square)
    # ------------------------------------------------------------------

    def _draw_quantum_badges(self, state: "GameState"):
        board = state.board
        seen: set[chess.Square] = set()
        for qp in board.quantum_state.pieces.values():
            for sq in qp.positions:
                if sq not in seen:
                    seen.add(sq)
                    x, y = sq_to_pixel(sq)
                    badge = self.font_label.render("Q", True, C_QUANTUM_BADGE)
                    self.screen.blit(badge, (x + 3, y + 3))

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
        if self._use_images:
            return self._render_piece_image(piece, alpha)
        return self._render_piece_shape(piece, alpha)

    def _render_piece_image(self, piece: chess.Piece, alpha: int) -> pygame.Surface:
        base = self._piece_images[(piece.piece_type, piece.color)]
        if alpha == 255:
            key = (piece.piece_type, piece.color)
            if key not in self._piece_cache:
                surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                surf.fill((0, 0, 0, 0))
                surf.blit(base, (4, 4))
                self._piece_cache[key] = surf
            return self._piece_cache[key]
        # Ghost frame: modulate alpha via BLEND_RGBA_SUB; don't cache (alpha varies)
        surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        ghost = base.copy()
        mod = pygame.Surface(ghost.get_size(), pygame.SRCALPHA)
        mod.fill((0, 0, 0, 255 - alpha))
        ghost.blit(mod, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
        surf.blit(ghost, (4, 4))
        return surf

    def _render_piece_shape(self, piece: chess.Piece, alpha: int) -> pygame.Surface:
        key = (piece.piece_type, piece.color, alpha)
        if key in self._piece_cache:
            return self._piece_cache[key]
        surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        if piece.color == chess.WHITE:
            fill_c, border_c, text_c = (245, 245, 245), (40, 40, 40), (30, 30, 30)
        else:
            fill_c, border_c, text_c = (55, 55, 65), (200, 200, 200), (240, 240, 240)
        cx, cy, r = SQ // 2, SQ // 2, SQ // 2 - 6
        pygame.draw.circle(surf, (*border_c, alpha), (cx, cy), r + 2)
        pygame.draw.circle(surf, (*fill_c,   alpha), (cx, cy), r)
        lbl = self.font_piece_fallback.render(PIECE_LETTERS[piece.piece_type], True, text_c)
        lbl.set_alpha(alpha)
        surf.blit(lbl, lbl.get_rect(center=(cx, cy)))
        self._piece_cache[key] = surf
        return surf

    def _render_tiny_piece(self, piece: chess.Piece, size: int = 18) -> pygame.Surface:
        """Return a *size*×*size* surface for *piece*, cached."""
        key = ("tiny", piece.piece_type, piece.color, size)
        if key in self._piece_cache:
            return self._piece_cache[key]
        if self._use_images:
            base = self._piece_images[(piece.piece_type, piece.color)]
            surf = pygame.transform.smoothscale(base, (size, size))
        else:
            surf = pygame.Surface((size, size), pygame.SRCALPHA)
            surf.fill((0, 0, 0, 0))
            if piece.color == chess.WHITE:
                fill_c, border_c, text_c = (245, 245, 245), (40, 40, 40), (30, 30, 30)
            else:
                fill_c, border_c, text_c = (55, 55, 65), (200, 200, 200), (240, 240, 240)
            r = size // 2 - 1
            cx, cy = size // 2, size // 2
            pygame.draw.circle(surf, border_c, (cx, cy), r + 1)
            pygame.draw.circle(surf, fill_c,   (cx, cy), r)
            lbl = self.font_tiny.render(PIECE_LETTERS[piece.piece_type], True, text_c)
            surf.blit(lbl, lbl.get_rect(center=(cx, cy)))
        self._piece_cache[key] = surf
        return surf

    # ------------------------------------------------------------------
    # Rank / file labels
    # ------------------------------------------------------------------

    def _draw_labels(self):
        files = "abcdefgh"
        ranks = "87654321"
        lbl_color = (160, 130, 100)
        for i in range(8):
            # File letter — bottom-right inside the lowest rank square
            lbl = self.font_coord.render(files[i], True, lbl_color)
            x = BX + i * SQ + SQ - lbl.get_width() - 3
            y = BY + BOARD_PX - lbl.get_height() - 2
            self.screen.blit(lbl, (x, y))
            # Rank number — top-left in left margin
            lbl = self.font_coord.render(ranks[i], True, lbl_color)
            x = max(0, BX - lbl.get_width() - 4)
            y = BY + i * SQ + 3
            self.screen.blit(lbl, (x, y))

    # ------------------------------------------------------------------
    # Side panel (captured pieces + move history)
    # ------------------------------------------------------------------

    def _draw_side_panel(self, state: "GameState"):
        pad = PANEL_PAD
        x0  = PANEL_X + pad
        iw  = PANEL_W - 2 * pad   # inner width: 196 px

        # Background + left border
        pygame.draw.rect(self.screen, (38, 38, 50),
                         (PANEL_X, 0, PANEL_W, STATUS_Y))
        pygame.draw.line(self.screen, (70, 70, 90),
                         (PANEL_X, 0), (PANEL_X, STATUS_Y), 1)

        y = BY + pad  # 18

        # ── CAPTURED PIECES ──────────────────────────────────────────
        hdr = self.font_label.render("CAPTURED", True, (140, 140, 160))
        self.screen.blit(hdr, (x0, y))
        y += hdr.get_height() + 5

        y = self._draw_captured_row(state.captured_by_white, chess.BLACK,
                                    x0, y, iw, label="W")
        y += 4
        y = self._draw_captured_row(state.captured_by_black, chess.WHITE,
                                    x0, y, iw, label="B")
        y += 10

        pygame.draw.line(self.screen, (60, 60, 80),
                         (x0, y), (x0 + iw, y), 1)
        y += 8

        # ── MOVE HISTORY ─────────────────────────────────────────────
        hdr2 = self.font_label.render("MOVES", True, (140, 140, 160))
        self.screen.blit(hdr2, (x0, y))
        y += hdr2.get_height() + 4

        log = state.move_log
        pairs: list[tuple[str, str]] = []
        i = 0
        while i < len(log):
            wm = log[i]
            bm = log[i + 1] if i + 1 < len(log) else ""
            pairs.append((wm, bm))
            i += 2

        row_h   = 15
        avail_h = STATUS_Y - y - pad
        max_rows = max(1, avail_h // row_h)
        visible  = pairs[-max_rows:]
        start_num = len(pairs) - len(visible) + 1

        num_w = self.font_label.size("99. ")[0]
        col_w = (iw - num_w) // 2

        for ridx, (wm, bm) in enumerate(visible):
            move_num = start_num + ridx
            ry = y + ridx * row_h

            if ridx == len(visible) - 1 and pairs:
                pygame.draw.rect(self.screen, (55, 55, 75),
                                 (x0 - 4, ry - 1, iw + 8, row_h))

            num_lbl = self.font_label.render(f"{move_num}.", True, (90, 90, 110))
            self.screen.blit(num_lbl, (x0, ry))

            wx = x0 + num_w
            bx = wx + col_w

            wm_lbl = self.font_label.render(
                _clip_text(wm, col_w - 2, self.font_label), True, (220, 220, 220))
            self.screen.blit(wm_lbl, (wx, ry))

            bm_lbl = self.font_label.render(
                _clip_text(bm, col_w - 2, self.font_label), True, (150, 150, 255))
            self.screen.blit(bm_lbl, (bx, ry))

    def _draw_captured_row(self, pieces: list, piece_color: chess.Color,
                           x: int, y: int, w: int, label: str) -> int:
        """Draw one row of captured pieces; returns the y after the row."""
        lc  = (220, 220, 220) if label == "W" else (150, 150, 255)
        lbl = self.font_label.render(f"{label}:", True, lc)
        self.screen.blit(lbl, (x, y + 4))

        cx = x + lbl.get_width() + 6

        counts: dict[int, int] = {}
        for p in pieces:
            counts[p.piece_type] = counts.get(p.piece_type, 0) + 1

        for ptype in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN):
            cnt = counts.get(ptype, 0)
            if cnt == 0:
                continue
            tiny = self._render_tiny_piece(chess.Piece(ptype, piece_color))
            if cx + tiny.get_width() > x + w:
                break
            self.screen.blit(tiny, (cx, y))
            cx += tiny.get_width() + 2
            if cnt > 1:
                cnt_s = self.font_label.render(f"×{cnt}", True, (160, 160, 160))
                if cx + cnt_s.get_width() <= x + w:
                    self.screen.blit(cnt_s, (cx, y + 4))
                    cx += cnt_s.get_width() + 3

        return y + 22

    # ------------------------------------------------------------------
    # Status bar  (three rows, STATUS_H = 90 px, starts at STATUS_Y)
    # ------------------------------------------------------------------

    def _draw_status_bar(self, state: "GameState"):
        board = state.board

        # Dark background for entire status area
        pygame.draw.rect(self.screen, C_STATUS_BG,
                         (0, STATUS_Y, WINDOW_W, STATUS_H))
        pygame.draw.line(self.screen, (60, 60, 80),
                         (0, STATUS_Y), (WINDOW_W, STATUS_Y), 1)

        def blit_left(text, color, font, row_y, row_h):
            lbl = font.render(text, True, color)
            cy = row_y + row_h // 2
            r = lbl.get_rect(midleft=(8, cy))
            if r.right < WINDOW_W - 5:
                self.screen.blit(lbl, r)

        def blit_center(text, color, font, row_y, row_h):
            lbl = font.render(text, True, color)
            cy = row_y + row_h // 2
            r = lbl.get_rect(center=(BOARD_CX, cy))
            self.screen.blit(lbl, r)

        def blit_right(text, color, font, row_y, row_h):
            lbl = font.render(text, True, color)
            rx = WINDOW_W - lbl.get_width() - 10
            if rx > 5:
                self.screen.blit(lbl, (rx, row_y + (row_h - lbl.get_height()) // 2))

        # ── Row 3 (context message) ──────────────────────────────────
        if state.status_message:
            blit_center(state.status_message, C_QUANTUM_BADGE,
                        self.font_info, ROW3_Y, ROW3_H)
        elif state.selected_sq is not None:
            piece = board.classical_board.piece_at(state.selected_sq)
            if piece is not None:
                cname = "White" if piece.color == chess.WHITE else "Black"
                tname = chess.piece_name(piece.piece_type).capitalize()
                sname = chess.square_name(state.selected_sq).upper()
                msg   = f"Selected: {cname} {tname} on {sname}"
            else:
                msg = f"Selected: {chess.square_name(state.selected_sq).upper()}"
            blit_center(msg, C_TEXT, self.font_info, ROW3_Y, ROW3_H)
        else:
            # Show last collapse event if any, else quantum count
            if board.measurement_log:
                res     = board.measurement_log[-1]
                sq_name = chess.square_name(res.chosen_square)
                msg     = f"Collapsed: {res.piece} → {sq_name}"
                blit_center(msg, C_WARN, self.font_info, ROW3_Y, ROW3_H)
            else:
                qcount = len(board.quantum_state)
                msg    = (f"Quantum pieces in play: {qcount}"
                          if qcount else "Click a piece to select")
                blit_center(msg, (140, 140, 140), self.font_info, ROW3_Y, ROW3_H)

        # ── Row 2 (game state) ───────────────────────────────────────
        if state.ai_thinking:
            dots = "." * (1 + (pygame.time.get_ticks() // 500) % 3)
            turn_txt, turn_col = f"Thinking{dots}", (160, 160, 255)
        elif board.turn == chess.WHITE:
            turn_txt, turn_col = "White to move", (255, 255, 255)
        else:
            turn_txt, turn_col = "Black to move", (160, 160, 255)
        blit_left(turn_txt, turn_col, self.font_status, ROW2_Y, ROW2_H)

        mode_txt = f"Mode: {state.mode_label()}"
        blit_center(mode_txt, C_WARN, self.font_status, ROW2_Y, ROW2_H)

        wkp = board.measurement.king_existence_probability(chess.WHITE)
        bkp = board.measurement.king_existence_probability(chess.BLACK)
        kp_txt = f"K {wkp * 100:.0f}%  k {bkp * 100:.0f}%"
        blit_right(kp_txt, (200, 200, 200), self.font_status, ROW2_Y, ROW2_H)

        # ── Row 1 (key hints) ────────────────────────────────────────
        hints = "[Q]Split  [M]Merge  [R]Restart  [Esc]Cancel"
        blit_center(hints, (130, 130, 130), self.font_label, ROW1_Y, ROW1_H)

    # ------------------------------------------------------------------
    # Promotion overlay
    # ------------------------------------------------------------------

    def _draw_promotion_overlay(self):
        """Draw the 4-piece promotion choice overlay centred on the board."""
        # Dim the board area
        dim = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        self.screen.blit(dim, (BX, BY))

        rects = _promotion_overlay_rects()
        color = chess.WHITE  # human always plays White

        # "Promote to:" label above the squares
        hdr = self.font_info.render("Promote to:", True, (230, 230, 230))
        cx  = BX + BOARD_PX // 2
        self.screen.blit(hdr, hdr.get_rect(center=(cx, rects[0][1] - 20)))

        for (x, y, w, h), ptype in zip(rects, _PROMO_PIECES):
            pygame.draw.rect(self.screen, (55, 55, 80),    (x, y, w, h))
            pygame.draw.rect(self.screen, (140, 140, 180), (x, y, w, h), 2)
            piece = chess.Piece(ptype, color)
            self.screen.blit(self._render_piece(piece, alpha=255), (x, y))

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
    NORMAL = "Normal"
    SPLIT  = "Split"
    MERGE  = "Merge"


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
        self.merge_source1: Optional[chess.Square] = None
        self.merge_source2: Optional[chess.Square] = None
        self.game_over_text: str = ""
        self.ai_thinking: bool = False
        self.ai_think_start: int = 0
        self.ai_pending_move: Optional[Move] = None
        self.ai_stall_count: int = 0
        self.status_message: str = ""
        self.captured_by_white: list[chess.Piece] = []  # black pieces taken by white
        self.captured_by_black: list[chess.Piece] = []  # white pieces taken by black
        self.move_log: list[str] = []                    # formatted half-move strings
        self.promotion_pending: bool = False
        self.promotion_from: Optional[chess.Square] = None
        self.promotion_to:   Optional[chess.Square] = None

    def mode_label(self) -> str:
        if self.mode == InputMode.SPLIT:
            if self.split_source is None:
                return "SPLIT (select source)"
            if self.split_first_target is None:
                return "SPLIT (select target 1)"
            return "SPLIT (select target 2)"
        if self.mode == InputMode.MERGE:
            if self.merge_source1 is None:
                return "MERGE (select source 1)"
            if self.merge_source2 is None:
                return "MERGE (select source 2)"
            return "MERGE (select target)"
        return "NORMAL"

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
        splits = rules.legal_split_moves(color)
        merges = rules.legal_merge_moves(color)

        if not classical and not splits and not merges:
            return None

        # Weighted random selection across non-empty categories
        weights = []
        buckets = []
        if classical:
            buckets.append(('classical', classical))
            weights.append(70)
        if splits:
            buckets.append(('split', splits))
            weights.append(20)
        if merges:
            buckets.append(('merge', merges))
            weights.append(10)
        total = sum(weights)
        weights = [w / total for w in weights]
        chosen_bucket = random.choices(buckets, weights=weights, k=1)[0][1]
        # For classical moves the heuristic below overrides the random pick;
        # for quantum moves just return a random choice immediately.
        if chosen_bucket is not classical:
            return random.choice(chosen_bucket)

        # classical bucket: fall through to heuristic ranking below

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

        # 3. Safe moves (simulate on temp board to check for danger)
        safe = []
        for m in classical:
            try:
                tmp = cb.copy()
                cm = chess.Move(m.from_square, m.to_square, m.promotion)
                if cm in tmp.pseudo_legal_moves:
                    tmp.push(cm)
                    if not tmp.is_attacked_by(chess.WHITE, m.to_square):
                        safe.append(m)
            except Exception as e:
                import traceback
                print(f"[GUI ERROR] Move evaluation failed: {e}")
                traceback.print_exc()
                # Still continue — do not crash the GUI
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

        if not self.state.game_over_text and self.state.board.turn == chess.BLACK:
            if not self.state.ai_thinking:
                # Phase 1: start thinking — compute and stash the move immediately
                self.state.ai_thinking = True
                self.state.ai_think_start = pygame.time.get_ticks()
                self.state.ai_pending_move = self.ai.choose_move(self.state.board)
            else:
                # Phase 2: apply after the think delay has elapsed
                elapsed = pygame.time.get_ticks() - self.state.ai_think_start
                if elapsed >= AI_THINK_TIME:
                    self._apply_ai_move()

        self.renderer.draw(self.state, self._tick)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            # R (reset) is always allowed
            if event.key == pygame.K_r:
                self.state.reset()
                return
            # All other keys blocked while AI is thinking or promotion dialog is open
            if self.state.ai_thinking or self.state.promotion_pending:
                return
            self._handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state.ai_thinking:
                return
            if self.state.promotion_pending:
                self._handle_promotion_click(*event.pos)
                return
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
            state.merge_source1 = None
            state.merge_source2 = None
            state.status_message = ""
            return

        if key == pygame.K_q and not state.game_over_text:
            if state.board.turn == chess.WHITE:
                state.mode = InputMode.SPLIT
                state.split_source = None
                state.split_first_target = None
            return

        if key == pygame.K_m and not state.game_over_text:
            if state.board.turn == chess.WHITE:
                state.mode = InputMode.MERGE
                state.merge_source1 = None
                state.merge_source2 = None
                state.legal_targets = []
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
        elif state.mode == InputMode.MERGE:
            self._handle_merge_click(sq)
        else:
            self._handle_normal_click(sq)

    # ------------------------------------------------------------------
    # Normal click: select + move
    # ------------------------------------------------------------------

    def _handle_normal_click(self, sq: chess.Square):
        state = self.state
        board = state.board
        cb = board.classical_board

        has_classical = cb.piece_at(sq) is not None
        has_quantum   = len(board.quantum_state.ids_at(sq)) > 0

        # A pending selection clicking a legal target always completes the move first
        if state.selected_sq is not None and sq in state.legal_targets:
            from_sq = state.selected_sq
            piece = cb.piece_at(from_sq)
            # Pawn reaching the last rank → show promotion dialog
            if (piece and piece.piece_type == chess.PAWN
                    and chess.square_rank(sq) in (0, 7)):
                state.promotion_from    = from_sq
                state.promotion_to      = sq
                state.promotion_pending = True
                state.selected_sq       = None
                state.legal_targets     = []
                state.status_message    = ""
                return
            move = Move.classical(from_sq, sq)
            victim   = cb.piece_at(sq)
            notation = _build_move_notation(move, cb)
            success = board.apply_move(move)
            if success:
                state.last_move = move
                state._check_game_over()
                state.move_log.append(notation)
                if victim is not None:
                    state.captured_by_white.append(victim)
            state.selected_sq = None
            state.legal_targets = []
            state.status_message = ""
            return

        # Auto-merge: quantum-only square belonging to current player.
        # Classical piece on the same square means classical logic takes priority (below).
        if has_quantum and not has_classical:
            qids = board.quantum_state.ids_at(sq)
            qp   = board.quantum_state.get(qids[0])
            if qp is not None and qp.piece.color == chess.WHITE:
                state.mode          = InputMode.MERGE
                state.merge_source1 = sq
                state.merge_source2 = None
                state.legal_targets = []
                state.selected_sq   = None
                state.status_message = (
                    "Quantum piece selected — click second source square to merge"
                )
                return

        # Classical piece present (may also have quantum — classical takes priority)
        if has_classical:
            piece = cb.piece_at(sq)
            if piece.color == chess.WHITE:
                state.selected_sq   = sq
                state.legal_targets = [m.to_square
                                        for m in board.rules.legal_moves_from_square(sq)]
                state.status_message = ""
            else:
                # Enemy piece not in legal targets — clear selection
                state.selected_sq   = None
                state.legal_targets = []
                state.status_message = ""
            return

        # Truly empty square
        state.selected_sq   = None
        state.legal_targets = []
        state.status_message = "Empty square"

    # ------------------------------------------------------------------
    # Split click FSM: select piece → target1 → target2
    # ------------------------------------------------------------------

    def _handle_split_click(self, sq: chess.Square):
        state = self.state
        board = state.board
        cb = board.classical_board

        if state.split_source is None:
            piece = cb.piece_at(sq)
            if piece and piece.color == chess.WHITE and piece.piece_type != chess.PAWN:
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
            notation = _build_move_notation(move, board.classical_board)
            success = board.apply_move(move)
            if success:
                state.last_move = move
                state._check_game_over()
                state.move_log.append(notation)

        # Reset split state regardless
        state.mode = InputMode.NORMAL
        state.split_source = None
        state.split_first_target = None
        state.legal_targets = []

    # ------------------------------------------------------------------
    # Merge click FSM: click quantum source1 → source2 → destination
    # ------------------------------------------------------------------

    def _handle_merge_click(self, sq: chess.Square):
        state = self.state
        board = state.board

        def _is_white_quantum(square: chess.Square) -> bool:
            qids = board.quantum_state.ids_at(square)
            if not qids:
                return False
            qp = board.quantum_state.get(qids[0])
            return qp is not None and qp.piece.color == chess.WHITE

        if state.merge_source1 is None:
            if _is_white_quantum(sq):
                state.merge_source1 = sq
            return

        if state.merge_source2 is None:
            if _is_white_quantum(sq) and sq != state.merge_source1:
                state.merge_source2 = sq
                # Show legal merge destinations reachable from both sources
                rules = board.rules
                merges = rules.legal_merge_moves(chess.WHITE)
                state.legal_targets = list({
                    m.to_square for m in merges
                    if set(m.sources) == {state.merge_source1, state.merge_source2}
                })
            return

        # Third click: destination
        if sq in state.legal_targets:
            move = Move.merge(state.merge_source1, state.merge_source2, sq)
            notation = _build_move_notation(move, board.classical_board)
            success = board.apply_move(move)
            if success:
                state.last_move = move
                state._check_game_over()
                state.move_log.append(notation)

        state.mode = InputMode.NORMAL
        state.merge_source1 = None
        state.merge_source2 = None
        state.legal_targets = []

    # ------------------------------------------------------------------
    # Promotion dialog handler
    # ------------------------------------------------------------------

    def _handle_promotion_click(self, px: int, py: int):
        """Called when the player clicks while the promotion overlay is visible."""
        state = self.state
        board = state.board

        chosen_type: Optional[int] = None
        for (x, y, w, h), ptype in zip(_promotion_overlay_rects(), _PROMO_PIECES):
            if x <= px < x + w and y <= py < y + h:
                chosen_type = ptype
                break

        if chosen_type is None:
            return  # click outside the overlay — keep waiting

        from_sq = state.promotion_from
        to_sq   = state.promotion_to
        state.promotion_pending = False
        state.promotion_from    = None
        state.promotion_to      = None

        move     = Move.classical(from_sq, to_sq, promotion=chosen_type)
        victim   = board.classical_board.piece_at(to_sq)
        notation = _build_move_notation(move, board.classical_board)
        success  = board.apply_move(move)
        if success:
            state.last_move = move
            state._check_game_over()
            state.move_log.append(notation)
            if victim is not None:
                state.captured_by_white.append(victim)

    # ------------------------------------------------------------------
    # AI turn (called after think delay)
    # ------------------------------------------------------------------

    def _apply_ai_move(self):
        import random
        board = self.state.board

        # Consume the pre-computed move and clear thinking state
        move = self.state.ai_pending_move
        self.state.ai_thinking = False
        self.state.ai_pending_move = None

        if move is None:
            self.state.ai_stall_count += 1
            if self.state.ai_stall_count >= 3:
                self.state.game_over_text = "No legal moves — draw"
                self.state.ai_stall_count = 0
            return
        self.state.ai_stall_count = 0

        # Try AI's preferred move; on failure retry up to 5 times with random moves
        for attempt in range(5):
            if attempt > 0:
                # Fallback: pick any pseudo-legal classical move
                board.classical_board.turn = chess.BLACK
                pm = list(board.classical_board.pseudo_legal_moves)
                if not pm:
                    break
                m = random.choice(pm)
                promo = chess.QUEEN if (
                    board.classical_board.piece_at(m.from_square) and
                    board.classical_board.piece_at(m.from_square).piece_type == chess.PAWN and
                    chess.square_rank(m.to_square) in (0, 7)
                ) else m.promotion
                move = Move.classical(m.from_square, m.to_square, promo)
            victim = (board.classical_board.piece_at(move.to_square)
                      if move.move_type == MoveType.CLASSICAL and move.to_square is not None
                      else None)
            notation = _build_move_notation(move, board.classical_board)
            success = board.apply_move(move)
            if success:
                self.state.last_move = move
                self.state._check_game_over()
                self.state.move_log.append(notation)
                if victim is not None:
                    self.state.captured_by_black.append(victim)
                return

        # Truly stuck after all retries: increment stall counter
        self.state.ai_stall_count += 1
        if self.state.ai_stall_count >= 3:
            self.state.game_over_text = "No legal moves — draw"
            self.state.ai_stall_count = 0


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
