"""
main.py – Entry point for Quantum Chess (research-paper ruleset).

Run with:
    python main.py           – launch the GUI
    python main.py --test    – run automated test simulations
"""

import sys


def _run_tests() -> None:
    from testing.test_harness import QuantumChessTester
    from engine.board import QuantumBoard
    tester = QuantumChessTester(QuantumBoard)
    tester.run_all_tests()


if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
    else:
        from gui.gui import run
        run()
