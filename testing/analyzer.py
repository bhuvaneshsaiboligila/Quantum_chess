"""
testing/analyzer.py – Post-simulation log reader and report generator.

Usage:
    from testing.analyzer import GameAnalyzer
    analyzer = GameAnalyzer()
    analyzer.print_report()
"""

import json
import os
from collections import defaultdict
from typing import Optional

from testing.config import LOG_DIR

# Maps known issue types to human-readable descriptions and fix suggestions
_ISSUE_HINTS: dict[str, tuple[str, str]] = {
    "quantum_normalization": (
        "Quantum piece probability does not sum to 1.0",
        "Call qp._normalize() after every amplitude mutation",
    ),
    "broken_entanglement": (
        "Quantum piece references a partner that no longer exists",
        "Clear entangled_with when a partner is removed from QuantumState",
    ),
    "asymmetric_entanglement": (
        "Entanglement link is one-directional",
        "Ensure entangle() sets both pieces' entangled_with fields",
    ),
    "ndo_violation": (
        "No-Double-Occupancy rule violated: classical and quantum piece of same colour share a square",
        "Trigger measurement before placing a classical piece on a quantum square",
    ),
    "stale_index": (
        "Square index references a quantum piece id that no longer exists",
        "Always call _rebuild_index() after removing a QuantumPiece",
    ),
    "index_inconsistency": (
        "Square-to-qid index is out of sync with piece positions",
        "Rebuild the index after every state mutation",
    ),
    "move_failed": (
        "A legal move returned False from apply_move()",
        "Check _apply_classical / _apply_split / _apply_merge for edge cases",
    ),
    "engine_exception": (
        "An unhandled exception was raised during move application",
        "Add error handling around the offending engine code path",
    ),
    "move_limit": (
        "Game reached the move limit without a result",
        "Verify is_game_over() and game_result() cover all terminal states",
    ),
}


class GameAnalyzer:
    """Reads all JSON logs and produces a structured test report."""

    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        self._logs: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_logs(self) -> list[dict]:
        """Load all game_*.json files from log_dir."""
        self._logs = []
        if not os.path.isdir(self.log_dir):
            return self._logs
        for fname in sorted(os.listdir(self.log_dir)):
            if fname.startswith("game_") and fname.endswith(".json"):
                path = os.path.join(self.log_dir, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        self._logs.append(json.load(f))
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[analyzer] Warning: could not read {fname}: {e}")
        return self._logs

    def analyze(self) -> dict:
        """Compute all metrics and return a structured report dict."""
        if not self._logs:
            self.load_logs()

        games = self._logs
        n = len(games)

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        results = defaultdict(int)
        terminations = defaultdict(int)
        total_moves = []
        quantum_ratios = []
        error_counts = []
        issue_counts = []

        for g in games:
            results[g.get("result", "unknown")] += 1
            terminations[g.get("termination", "unknown")] += 1
            m = g.get("total_moves", 0)
            total_moves.append(m)
            qm = g.get("quantum_moves", 0)
            quantum_ratios.append(qm / m if m > 0 else 0.0)
            error_counts.append(len(g.get("errors", [])))
            issue_counts.append(len(g.get("validation_issues", [])))

        summary = {
            "total_games": n,
            "results": dict(results),
            "terminations": dict(terminations),
            "avg_moves": round(sum(total_moves) / n, 1) if n else 0,
            "min_moves": min(total_moves) if total_moves else 0,
            "max_moves": max(total_moves) if total_moves else 0,
            "avg_quantum_ratio": round(sum(quantum_ratios) / n, 3) if n else 0,
            "total_errors": sum(error_counts),
            "total_validation_issues": sum(issue_counts),
            "clean_games": sum(1 for e, i in zip(error_counts, issue_counts) if e == 0 and i == 0),
        }

        # ------------------------------------------------------------------
        # Bug report
        # ------------------------------------------------------------------
        all_errors: list[dict] = []
        for g in games:
            for err in g.get("errors", []):
                all_errors.append({"game_id": g["game_id"], **err})

        # ------------------------------------------------------------------
        # Validation issue breakdown
        # ------------------------------------------------------------------
        issue_by_type: dict[str, list[dict]] = defaultdict(list)
        for g in games:
            for issue in g.get("validation_issues", []):
                issue_by_type[issue.get("type", "unknown")].append(
                    {"game_id": g["game_id"], **issue}
                )

        logic_issues = {
            itype: {
                "count": len(entries),
                "description": _ISSUE_HINTS.get(itype, ("Unknown issue type", "Investigate manually"))[0],
                "examples": entries[:3],
            }
            for itype, entries in issue_by_type.items()
        }

        # ------------------------------------------------------------------
        # Edge cases
        # ------------------------------------------------------------------
        edge_cases = []
        if total_moves:
            min_g = min(games, key=lambda g: g.get("total_moves", 9999))
            edge_cases.append({
                "type": "shortest_game",
                "game_id": min_g["game_id"],
                "moves": min_g.get("total_moves", 0),
                "result": min_g.get("result"),
            })
            max_g = max(games, key=lambda g: g.get("total_moves", 0))
            edge_cases.append({
                "type": "longest_game",
                "game_id": max_g["game_id"],
                "moves": max_g.get("total_moves", 0),
                "result": max_g.get("result"),
            })

        most_quantum = max(games, key=lambda g: g.get("quantum_moves", 0), default=None)
        if most_quantum:
            edge_cases.append({
                "type": "most_quantum_moves",
                "game_id": most_quantum["game_id"],
                "quantum_moves": most_quantum.get("quantum_moves", 0),
            })

        error_games = [g for g in games if g.get("errors")]
        if error_games:
            edge_cases.append({
                "type": "games_with_errors",
                "count": len(error_games),
                "game_ids": [g["game_id"] for g in error_games],
            })

        # ------------------------------------------------------------------
        # Suggested fixes
        # ------------------------------------------------------------------
        suggested_fixes = []
        seen_types = set(issue_by_type.keys())
        for err in all_errors:
            etype = err.get("error_type", "")
            if etype not in seen_types:
                seen_types.add(etype)

        for itype in seen_types:
            if itype in _ISSUE_HINTS:
                desc, fix = _ISSUE_HINTS[itype]
                suggested_fixes.append({"issue": itype, "description": desc, "fix": fix})

        return {
            "summary": summary,
            "bug_report": all_errors,
            "logic_issues": logic_issues,
            "edge_cases": edge_cases,
            "suggested_fixes": suggested_fixes,
        }

    def print_report(self) -> None:
        """Print a human-readable report to stdout."""
        report = self.analyze()

        _section("TEST SUMMARY")
        s = report["summary"]
        print(f"  Games run         : {s['total_games']}")
        print(f"  Results           : {s['results']}")
        print(f"  Terminations      : {s['terminations']}")
        print(f"  Avg / Min / Max moves: {s['avg_moves']} / {s['min_moves']} / {s['max_moves']}")
        print(f"  Avg quantum ratio : {s['avg_quantum_ratio']:.1%}")
        print(f"  Clean games       : {s['clean_games']} / {s['total_games']}")
        print(f"  Total errors      : {s['total_errors']}")
        print(f"  Total val. issues : {s['total_validation_issues']}")

        _section("BUG REPORT")
        errors = report["bug_report"]
        if not errors:
            print("  No engine errors detected.")
        else:
            for err in errors:
                gid = err.get("game_id", "?")
                mn = err.get("move_number", "?")
                etype = err.get("error_type", "?")
                msg = err.get("message", "")
                print(f"  [Game {gid}, Move {mn}] {etype}: {msg}")

        _section("LOGIC ISSUES")
        logic = report["logic_issues"]
        if not logic:
            print("  No validation issues detected.")
        else:
            for itype, data in logic.items():
                print(f"  [{itype}] × {data['count']}")
                print(f"    → {data['description']}")
                for ex in data["examples"]:
                    msg = ex.get("message", str(ex))
                    print(f"      Game {ex.get('game_id','?')} move {ex.get('move_number','?')}: {msg}")

        _section("EDGE CASE FINDINGS")
        for ec in report["edge_cases"]:
            etype = ec.pop("type")
            parts = ", ".join(f"{k}={v}" for k, v in ec.items())
            print(f"  [{etype}] {parts}")

        _section("SUGGESTED FIXES")
        fixes = report["suggested_fixes"]
        if not fixes:
            print("  No specific fixes suggested.")
        else:
            for i, fix in enumerate(fixes, 1):
                print(f"\n  {i}. {fix['issue']}")
                print(f"     Problem : {fix['description']}")
                print(f"     Fix     : {fix['fix']}")

        print("\n" + "=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)
