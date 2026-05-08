# Quantum Chess

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Based on](https://img.shields.io/badge/based%20on-Cantwell%202019-purple)

A fully playable implementation of Quantum Chess — the variant defined in
Chris Cantwell's 2019 research paper — with a Pygame GUI, a heuristic AI
opponent, and a simulation-based test harness.

---

## What is Quantum Chess?

In Quantum Chess, pieces can exist in quantum superposition across multiple
squares simultaneously. A **split move** sends a piece into two locations at
once; a **merge move** recombines those branches, and the resulting
amplitudes interfere just as they would in quantum mechanics. When a
classical piece tries to enter a square occupied by a quantum piece, the
quantum piece is **measured** and collapses to a definite location before
the interaction resolves. There is no check or checkmate — the game ends
when a king's total probability of existence reaches zero.

---

## Features

- **Split moves** — place any non-pawn piece into an equal superposition
  across two reachable squares (`i/√2` amplitude each, paper eq. 8a)
- **Merge moves** — recombine two branches of the same quantum piece into
  one target, with constructive/destructive amplitude interference
  (paper eq. 10)
- **Probabilistic measurement** — quantum pieces collapse when No Double
  Occupancy would be violated; collapse probabilities are proportional to
  `|amplitude|²`
- **No-effect detection** — moves that leave the board state unchanged are
  rejected, matching paper Rule 9
- **Path-aware quantum blocking** — sliding pieces measure and collapse
  any quantum occupants along their path before moving
- **Heuristic AI opponent** — plays Black with king-capture priority,
  material evaluation, safe-move filtering, and weighted quantum move
  selection (split/merge at configurable frequency)
- **Side panel** — live move history with algebraic-style notation and
  captured-piece display
- **Promotion dialog** — interactive overlay for choosing the promotion
  piece when a pawn reaches the back rank

---

## Getting Started

### Prerequisites

```
Python 3.10+
pip install pygame python-chess
```

### Run the game

```bash
python main.py
```

### Run the automated test harness

```bash
python main.py --test
```

The harness simulates multiple AI-vs-AI games, validates quantum state
invariants after every move, and prints a per-game summary with error and
issue counts.

To run the deterministic unit tests:

```bash
pytest testing/test_rules.py -v
```

---

## Controls

| Key / Action | Effect |
|---|---|
| **Left-click** a piece | Select it and show legal move targets |
| **Left-click** a target square | Execute the move |
| **Left-click** a quantum square | Auto-enter Merge mode with that square as source 1 |
| **Q** then clicks | Split mode — pick source, then two target squares |
| **M** then clicks | Merge mode — pick two source squares, then destination |
| **R** | Restart game |
| **Esc** | Cancel current selection or mode |

---

## Architecture

All game-state mutation flows through a single pipeline in `engine/board.py`.

| Module | Responsibility |
|---|---|
| `engine/board.py` | `QuantumBoard` — central state container; wires all subsystems; the only authorised mutation point |
| `engine/quantum_state.py` | `QuantumState` + `QuantumPiece` — stores each piece as a list of (square, complex amplitude) pairs; enforces normalisation |
| `engine/measurement.py` | `MeasurementSystem` — probabilistic collapse, NDO resolution, en-passant measurement, king existence probability |
| `engine/rules.py` | `RuleEngine` — generates legal classical, split, and merge moves; detects win/draw conditions |
| `engine/move.py` | `Move` dataclass — encapsulates all three move types; implements the paper's amplitude formulas as static helpers |
| `engine/move_classifier.py` | `classify()` — maps a classical move to its Cantwell §8.x variant (standard/capture/blocked slide or jump, pawn variants, castling) for path-clearing logic |
| `engine/piece.py` | Piece-type constants, heuristic reachability helpers, AI piece values |

The GUI (`gui/gui.py`) is a single-file Pygame front-end that owns all
rendering and input-handling logic. It is deliberately decoupled from the
engine — it never mutates board state directly and only calls
`board.apply_move()`.

---

## Technical Stack

| Component | Technology |
|---|---|
| Game engine | Pure Python 3.10+ |
| GUI & rendering | [Pygame](https://www.pygame.org/) 2.x |
| Move generation & board representation | [python-chess](https://python-chess.readthedocs.io/) |
| Quantum rules | Cantwell, C. (2019). *Quantum Chess*. arXiv:1906.05836 |
| Unit tests | pytest |

---

## License

MIT License. See `LICENSE` for details.
