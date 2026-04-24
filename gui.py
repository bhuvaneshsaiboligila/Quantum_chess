"""
gui.py – Pygame rendering, input handling, and main game loop.

Controls
--------
  Click          – select piece / move
  Q              – enter quantum mode (then click piece + two target squares)
  E              – entangle two quantum pieces (click each in sequence)
  R              – restart game
  ESC            – quit
"""

import sys
import math
import pygame
import chess
from quantum_chess import QuantumBoard, QuantumChessAI

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOW_W, WINDOW_H = 720, 760
BOARD_SIZE = 640
SQUARE_SIZE = BOARD_SIZE // 8
BOARD_OFFSET_X = (WINDOW_W - BOARD_SIZE) // 2
BOARD_OFFSET_Y = 20
INFO_HEIGHT = WINDOW_H - BOARD_OFFSET_Y - BOARD_SIZE

FPS = 60

# Colours
C_LIGHT     = (240, 217, 181)
C_DARK      = (181, 136,  99)
C_SELECTED  = (100, 200, 100, 180)
C_LEGAL     = ( 50, 150,  50, 120)
C_Q_OVERLAY = ( 80,  80, 220, 140)   # quantum ghost squares
C_ENTANGLE  = (200,  50, 200, 160)
C_CHECK     = (220,  30,  30, 160)
C_LAST_MOVE = (200, 180,  60,  90)
C_BG        = ( 30,  30,  40)
C_INFO_BG   = ( 20,  20,  30)
C_TEXT      = (220, 220, 220)
C_Q_TEXT    = (120, 180, 255)
C_WARN      = (255, 120,  40)

PIECE_SYMBOLS = {
    (chess.PAWN,   chess.WHITE): '♙',
    (chess.KNIGHT, chess.WHITE): '♘',
    (chess.BISHOP, chess.WHITE): '♗',
    (chess.ROOK,   chess.WHITE): '♖',
    (chess.QUEEN,  chess.WHITE): '♕',
    (chess.KING,   chess.WHITE): '♔',
    (chess.PAWN,   chess.BLACK): '♟',
    (chess.KNIGHT, chess.BLACK): '♞',
    (chess.BISHOP, chess.BLACK): '♝',
    (chess.ROOK,   chess.BLACK): '♜',
    (chess.QUEEN,  chess.BLACK): '♛',
    (chess.KING,   chess.BLACK): '♚',
}

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def sq_to_pixel(sq: chess.Square) -> tuple[int, int]:
    """Return top-left pixel corner of a square."""
    file = chess.square_file(sq)
    rank = 7 - chess.square_rank(sq)
    x = BOARD_OFFSET_X + file * SQUARE_SIZE
    y = BOARD_OFFSET_Y + rank * SQUARE_SIZE
    return x, y

def pixel_to_sq(px: int, py: int) -> chess.Square | None:
    """Return the chess.Square under pixel position, or None."""
    bx = px - BOARD_OFFSET_X
    by = py - BOARD_OFFSET_Y
    if 0 <= bx < BOARD_SIZE and 0 <= by < BOARD_SIZE:
        file = bx // SQUARE_SIZE
        rank = 7 - (by // SQUARE_SIZE)
        return chess.square(file, rank)
    return None

def draw_alpha_rect(surface: pygame.Surface, color: tuple, rect: tuple):
    """Draw a rectangle with alpha onto *surface*."""
    surf = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    surf.fill(color)
    surface.blit(surf, (rect[0], rect[1]))

def pulsing_alpha(base: int, amp: int, freq: float, t: float) -> int:
    v = base + int(amp * math.sin(t * freq))
    return max(0, min(255, v))

# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class Renderer:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        # Fonts – fall back gracefully
        self._init_fonts()
        self._piece_cache: dict[tuple, pygame.Surface] = {}

    def _init_fonts(self):
        available = pygame.font.get_fonts()
        candidates_large = ["dejavusans", "freesans", "liberationsans",
                             "notosans", "arial", "unifont"]
        candidates_small = candidates_large[:]
        chosen_large = None
        chosen_small = None
        for c in candidates_large:
            if c in available:
                chosen_large = c
                chosen_small = c
                break
        try:
            self.font_piece  = pygame.font.SysFont(chosen_large, 48, bold=False)
            self.font_prob   = pygame.font.SysFont(chosen_small, 13, bold=True)
            self.font_info   = pygame.font.SysFont(chosen_small, 17)
            self.font_status = pygame.font.SysFont(chosen_large, 22, bold=True)
        except Exception:
            self.font_piece  = pygame.font.Font(None, 52)
            self.font_prob   = pygame.font.Font(None, 18)
            self.font_info   = pygame.font.Font(None, 20)
            self.font_status = pygame.font.Font(None, 26)

    def _piece_surface(self, piece: chess.Piece, alpha: int = 255) -> pygame.Surface:
        key = (piece.piece_type, piece.color, alpha)
        if key not in self._piece_cache:
            sym = PIECE_SYMBOLS[(piece.piece_type, piece.color)]
            color = (255, 255, 255) if piece.color == chess.WHITE else (30, 30, 30)
            surf = self.font_piece.render(sym, True, color)
            if alpha < 255:
                surf = surf.copy()
                surf.set_alpha(alpha)
            self._piece_cache[key] = surf
        return self._piece_cache[key]

    # ------------------------------------------------------------------
    # Board
    # ------------------------------------------------------------------

    def draw_board(self, qboard: QuantumBoard, selected_sq, legal_sqs,
                   last_move, q_targets, entangle_mode, t: float):
        scr = self.screen

        # Background
        scr.fill(C_BG)

        # Squares
        for sq in chess.SQUARES:
            x, y = sq_to_pixel(sq)
            file = chess.square_file(sq)
            rank = chess.square_rank(sq)
            light = (file + rank) % 2 == 0
            base_col = C_LIGHT if light else C_DARK
            pygame.draw.rect(scr, base_col, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Last move highlight
        if last_move:
            for sq in (last_move.from_square, last_move.to_square):
                x, y = sq_to_pixel(sq)
                draw_alpha_rect(scr, C_LAST_MOVE, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Check highlight
        if qboard.classical_board.is_check():
            king_sq = qboard.classical_board.king(qboard.turn())
            if king_sq is not None:
                x, y = sq_to_pixel(king_sq)
                draw_alpha_rect(scr, C_CHECK, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Selected square
        if selected_sq is not None:
            x, y = sq_to_pixel(selected_sq)
            draw_alpha_rect(scr, C_SELECTED, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Legal moves
        for sq in legal_sqs:
            x, y = sq_to_pixel(sq)
            draw_alpha_rect(scr, C_LEGAL, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Quantum target squares (during selection)
        for sq in q_targets:
            x, y = sq_to_pixel(sq)
            draw_alpha_rect(scr, C_Q_OVERLAY, (x, y, SQUARE_SIZE, SQUARE_SIZE))

        # Quantum piece overlays
        for qid, qp in qboard.quantum_pieces.items():
            alpha = pulsing_alpha(90, 55, 3.0, t)
            col = C_ENTANGLE if entangle_mode else C_Q_OVERLAY
            for sq, prob in zip(qp.positions, qp.probabilities):
                x, y = sq_to_pixel(sq)
                draw_alpha_rect(scr, (*col[:3], alpha), (x, y, SQUARE_SIZE, SQUARE_SIZE))

                # Ghost piece
                ps = self._piece_surface(qp.piece, 140)
                px = x + (SQUARE_SIZE - ps.get_width()) // 2
                py = y + (SQUARE_SIZE - ps.get_height()) // 2
                scr.blit(ps, (px, py))

                # Probability label
                label = self.font_prob.render(f"{prob:.0%}", True, C_Q_TEXT)
                scr.blit(label, (x + 3, y + SQUARE_SIZE - 17))

                # Entanglement indicator
                if qp.entangled_id is not None:
                    pygame.draw.rect(scr, (200, 50, 200),
                                     (x + 1, y + 1, SQUARE_SIZE - 2, SQUARE_SIZE - 2), 2)

        # Classical pieces
        for sq in chess.SQUARES:
            piece = qboard.piece_at(sq)
            if piece is None:
                continue
            ps = self._piece_surface(piece, 255)
            x, y = sq_to_pixel(sq)
            # Shadow
            shadow = self.font_piece.render(
                PIECE_SYMBOLS[(piece.piece_type, piece.color)], True,
                (0, 0, 0) if piece.color == chess.WHITE else (180, 180, 180))
            shadow.set_alpha(60)
            scr.blit(shadow, (x + (SQUARE_SIZE - ps.get_width()) // 2 + 2,
                               y + (SQUARE_SIZE - ps.get_height()) // 2 + 2))
            scr.blit(ps, (x + (SQUARE_SIZE - ps.get_width()) // 2,
                           y + (SQUARE_SIZE - ps.get_height()) // 2))

        # Rank / file labels
        for i in range(8):
            # Files a-h at bottom
            file_label = self.font_prob.render(chess.FILE_NAMES[i], True, C_TEXT)
            scr.blit(file_label,
                     (BOARD_OFFSET_X + i * SQUARE_SIZE + SQUARE_SIZE - 11,
                      BOARD_OFFSET_Y + BOARD_SIZE - 14))
            # Ranks 1-8 on left
            rank_label = self.font_prob.render(str(i + 1), True, C_TEXT)
            scr.blit(rank_label,
                     (BOARD_OFFSET_X + 2,
                      BOARD_OFFSET_Y + (7 - i) * SQUARE_SIZE + 2))

    # ------------------------------------------------------------------
    # Info panel
    # ------------------------------------------------------------------

    def draw_info(self, qboard: QuantumBoard, mode: str, status: str,
                  q_step: int, q_src, q_targets, entangle_mode: bool,
                  entangle_step: int):
        y0 = BOARD_OFFSET_Y + BOARD_SIZE + 4
        pygame.draw.rect(self.screen, C_INFO_BG,
                         (0, y0, WINDOW_W, INFO_HEIGHT))

        turn_text = "White" if qboard.turn() == chess.WHITE else "Black"
        q_count = len(qboard.quantum_pieces)

        lines = []

        if mode == "quantum":
            if q_step == 0:
                lines.append(("QUANTUM MODE  –  click the piece to split", C_Q_TEXT))
            elif q_step == 1:
                lines.append((f"QUANTUM  –  src={chess.square_name(q_src)}  "
                               f"click 1st target (need 2)", C_Q_TEXT))
            elif q_step == 2:
                tnames = [chess.square_name(s) for s in q_targets]
                lines.append((f"QUANTUM  –  targets={tnames}  click 2nd target", C_Q_TEXT))
        elif entangle_mode:
            msg = "ENTANGLE  –  click 1st quantum piece" if entangle_step == 0 \
                  else "ENTANGLE  –  click 2nd quantum piece"
            lines.append((msg, (200, 50, 200)))
        else:
            lines.append((f"Turn: {turn_text}   Quantum pieces: {q_count}", C_TEXT))

        if status:
            lines.append((status, C_WARN))

        lines.append(("[Q] Superpose  [E] Entangle  [R] Restart  [ESC] Quit", C_TEXT))

        for i, (text, col) in enumerate(lines):
            surf = self.font_info.render(text, True, col)
            self.screen.blit(surf, (10, y0 + 5 + i * 20))

        # Game-over overlay
        if qboard.is_game_over():
            outcome = qboard.outcome_text()
            self._draw_overlay(f"Game Over  –  {outcome}  (R to restart)")

    def _draw_overlay(self, text: str):
        surf = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 150))
        self.screen.blit(surf, (0, 0))
        label = self.font_status.render(text, True, (255, 220, 80))
        x = (WINDOW_W - label.get_width()) // 2
        y = (WINDOW_H - label.get_height()) // 2
        self.screen.blit(label, (x, y))


# ---------------------------------------------------------------------------
# Game Controller
# ---------------------------------------------------------------------------

class Game:
    def __init__(self, screen: pygame.Surface):
        self.screen    = screen
        self.renderer  = Renderer(screen)
        self.qboard    = QuantumBoard()
        self.ai        = QuantumChessAI(chess.BLACK)
        self._reset_state()

    def _reset_state(self):
        self.selected_sq    = None
        self.legal_sqs      = []
        self.last_move      = None
        self.status_msg     = ""

        # Quantum split state machine
        self.mode           = "normal"   # "normal" | "quantum" | "entangle"
        self.q_step         = 0          # 0=select piece, 1=first target, 2=second target
        self.q_src          = None
        self.q_targets      = []

        # Entangle state
        self.entangle_step  = 0
        self.entangle_qid1  = None

    def restart(self):
        self.qboard = QuantumBoard()
        self._reset_state()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.KEYDOWN:
            self._handle_key(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            sq = pixel_to_sq(*event.pos)
            if sq is not None:
                self._handle_click(sq)

    def _handle_key(self, key: int):
        if key == pygame.K_ESCAPE:
            pygame.quit()
            sys.exit()

        if key == pygame.K_r:
            self.restart()
            return

        if self.qboard.is_game_over():
            return

        if key == pygame.K_q:
            if self.mode == "quantum":
                self.mode   = "normal"
                self.q_step = 0
                self.q_src  = None
                self.q_targets = []
            else:
                self.mode   = "quantum"
                self.q_step = 0
                self.q_src  = None
                self.q_targets = []
            self.status_msg = ""

        elif key == pygame.K_e:
            if self.mode == "entangle":
                self.mode          = "normal"
                self.entangle_step = 0
                self.entangle_qid1 = None
            else:
                self.mode          = "entangle"
                self.entangle_step = 0
                self.entangle_qid1 = None
            self.status_msg = ""

    def _handle_click(self, sq: chess.Square):
        if self.qboard.is_game_over():
            return

        # Only allow interaction on player (WHITE) turn
        if self.qboard.turn() != chess.WHITE:
            return

        if self.mode == "quantum":
            self._handle_quantum_click(sq)
        elif self.mode == "entangle":
            self._handle_entangle_click(sq)
        else:
            self._handle_normal_click(sq)

    # ------------------------------------------------------------------
    # Normal click handler
    # ------------------------------------------------------------------

    def _handle_normal_click(self, sq: chess.Square):
        board = self.qboard.classical_board

        if self.selected_sq is None:
            # Select piece
            piece = self.qboard.piece_at(sq)
            if piece is not None and piece.color == chess.WHITE:
                self.selected_sq = sq
                self.legal_sqs   = [m.to_square for m in self.qboard.legal_moves_from(sq)]
            else:
                self.status_msg = ""
        else:
            # Attempt move
            if sq in self.legal_sqs:
                # Check promotion
                piece = self.qboard.piece_at(self.selected_sq)
                promo = None
                if piece and piece.piece_type == chess.PAWN:
                    if (piece.color == chess.WHITE and chess.square_rank(sq) == 7) or \
                       (piece.color == chess.BLACK and chess.square_rank(sq) == 0):
                        promo = chess.QUEEN  # auto-promote to queen

                move = chess.Move(self.selected_sq, sq, promotion=promo)
                ok = self.qboard.apply_classical_move(move)
                if ok:
                    self.last_move  = move
                    self.status_msg = ""
                else:
                    self.status_msg = "Move failed (quantum collapse changed board)"
                self.selected_sq = None
                self.legal_sqs   = []
            elif self.qboard.piece_at(sq) is not None and \
                 self.qboard.piece_at(sq).color == chess.WHITE:
                # Re-select
                self.selected_sq = sq
                self.legal_sqs   = [m.to_square for m in self.qboard.legal_moves_from(sq)]
            else:
                self.selected_sq = None
                self.legal_sqs   = []

    # ------------------------------------------------------------------
    # Quantum click handler
    # ------------------------------------------------------------------

    def _handle_quantum_click(self, sq: chess.Square):
        if self.q_step == 0:
            # Choose source piece
            piece = self.qboard.piece_at(sq)
            if piece is None or piece.color != chess.WHITE:
                self.status_msg = "Select a white piece to put in superposition."
                return
            if piece.piece_type == chess.KING:
                self.status_msg = "Cannot put the King in superposition."
                return
            self.q_src  = sq
            self.q_step = 1
            self.status_msg = ""

        elif self.q_step == 1:
            # First target
            if sq == self.q_src:
                self.status_msg = "Choose a different square."
                return
            self.q_targets = [sq]
            self.q_step    = 2
            self.status_msg = ""

        elif self.q_step == 2:
            # Second target – execute superposition
            if sq in self.q_targets or sq == self.q_src:
                self.status_msg = "Choose a different square."
                return
            self.q_targets.append(sq)

            qid = self.qboard.put_in_superposition(self.q_src, self.q_targets)
            if qid is None:
                self.status_msg = "Superposition failed – is there a piece there?"
            else:
                self.status_msg = f"Superposition created (id={qid})"
                # Count this as using the turn – switch sides by making a null-like
                # action; we simply flip the turn via a workaround.
                # Actually, we advance the turn by passing the board turn.
                # We manually toggle the turn so Black can move.
                self.qboard.classical_board.turn = chess.BLACK

            self.mode      = "normal"
            self.q_step    = 0
            self.q_src     = None
            self.q_targets = []

    # ------------------------------------------------------------------
    # Entangle click handler
    # ------------------------------------------------------------------

    def _handle_entangle_click(self, sq: chess.Square):
        qids = self.qboard.quantum_pieces_at(sq)
        if not qids:
            self.status_msg = "No quantum piece at that square."
            return

        qid = qids[0]

        if self.entangle_step == 0:
            self.entangle_qid1 = qid
            self.entangle_step = 1
            self.status_msg    = f"Selected quantum piece {qid}. Click second piece."
        else:
            if qid == self.entangle_qid1:
                self.status_msg = "Same piece – click a different quantum piece."
                return
            ok = self.qboard.entangle(self.entangle_qid1, qid)
            if ok:
                self.status_msg = f"Entangled pieces {self.entangle_qid1} and {qid}."
            else:
                self.status_msg = "Entanglement failed."
            self.mode          = "normal"
            self.entangle_step = 0
            self.entangle_qid1 = None

    # ------------------------------------------------------------------
    # AI turn
    # ------------------------------------------------------------------

    def run_ai_turn(self):
        if self.qboard.turn() != chess.BLACK:
            return
        if self.qboard.is_game_over():
            return

        # Try superposition occasionally
        sp = self.ai.should_superpose(self.qboard)
        if sp:
            src, targets = sp
            qid = self.qboard.put_in_superposition(src, targets)
            if qid is not None:
                # Toggle turn back so we can choose the AI move next frame
                self.qboard.classical_board.turn = chess.WHITE
                # Switch back to BLACK immediately to pick classical move
                self.qboard.classical_board.turn = chess.BLACK

        move = self.ai.choose_move(self.qboard)
        if move:
            ok = self.qboard.apply_classical_move(move)
            if ok:
                self.last_move = move

    # ------------------------------------------------------------------
    # Main update / draw
    # ------------------------------------------------------------------

    def update(self, t: float):
        if self.qboard.turn() == chess.BLACK and not self.qboard.is_game_over():
            self.run_ai_turn()

    def draw(self, t: float):
        self.renderer.draw_board(
            self.qboard,
            self.selected_sq,
            self.legal_sqs,
            self.last_move,
            self.q_targets,
            self.mode == "entangle",
            t,
        )
        self.renderer.draw_info(
            self.qboard,
            self.mode,
            self.status_msg,
            self.q_step,
            self.q_src,
            self.q_targets,
            self.mode == "entangle",
            self.entangle_step,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Quantum Chess")
    clock  = pygame.time.Clock()

    # Try to set a nice icon (no asset required)
    try:
        icon = pygame.Surface((32, 32))
        icon.fill((40, 40, 80))
        pygame.display.set_icon(icon)
    except Exception:
        pass

    game = Game(screen)
    t = 0.0

    while True:
        dt = clock.tick(FPS) / 1000.0
        t += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            game.handle_event(event)

        game.update(t)
        game.draw(t)
        pygame.display.flip()


if __name__ == "__main__":
    main()
