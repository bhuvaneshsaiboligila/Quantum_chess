"""Testing configuration constants."""

import pathlib

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
LOG_DIR = str(_PROJECT_ROOT / "logs")

# Number of full game simulations to run
NUM_GAMES = 3

# Safety valve: abort a game after this many half-moves
MAX_MOVES_PER_GAME = 250

# Probability of attempting a quantum move (split/merge) each turn
QUANTUM_MOVE_PROBABILITY = 0.35

# Cap on how many split candidates are considered (avoids O(n²) blow-up)
MAX_SPLIT_CANDIDATES = 12

# Cap on merge candidates
MAX_MERGE_CANDIDATES = 6

# Random seed for reproducibility; None = non-deterministic
RANDOM_SEED = None
