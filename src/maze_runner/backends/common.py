"""What every backend does per worker, and the checks that make the comparison fair.

Every job is the SAME maze with a DIFFERENT strategy, and each worker reports the fingerprint
of the maze it actually solved, so check_results() can prove that all workers solved one maze.
Without this, "best explorer" would only be timing noise.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable

from ..strategies import STRATEGY_NAMES, MazeProblem, solve


def plan_jobs(problem: MazeProblem, strategies: Iterable[str] = STRATEGY_NAMES) -> list[tuple]:
    """One job per strategy, all on the same maze. Duplicate strategies are rejected."""
    strategies = list(strategies)
    if len(set(strategies)) != len(strategies):
        raise ValueError("each worker must get a different strategy")
    return [(problem, s) for s in strategies]


def solve_job(problem: MazeProblem, strategy: str) -> dict:
    """Solve one job and describe it in a JSON-safe dict (the same shape on every backend)."""
    t0 = time.perf_counter()
    result = solve(problem, strategy)
    seconds = time.perf_counter() - t0
    out = result.to_dict()
    out.update(
        maze=problem.name,
        maze_fingerprint=problem.fingerprint(),
        solve_seconds=seconds,
        pid=os.getpid(),
    )
    return out


def check_results(problem: MazeProblem, results: list[dict], strategies: Iterable[str]) -> None:
    """Every worker solved this maze, and each strategy appears exactly once."""
    expected = problem.fingerprint()
    seen = [r["maze_fingerprint"] for r in results]
    if any(f != expected for f in seen):
        raise AssertionError(f"workers solved different mazes: {sorted(set(seen))}")
    got = sorted(r["strategy"] for r in results)
    if got != sorted(strategies):
        raise AssertionError(f"expected one result per strategy, got {got}")


def moves_by_strategy(results: list[dict]) -> dict[str, int | None]:
    return {r["strategy"]: r["moves"] for r in sorted(results, key=lambda r: r["strategy"])}


def format_results(results: list[dict]) -> str:
    """Plain-text table printed by every backend's command line."""
    lines = [f"{'strategy':<11} {'moves':>6} {'nodes':>6} {'backtracks':>10} {'solve s':>9}"]
    for r in results:
        backtracks = "-" if r["backtracks"] is None else str(r["backtracks"])
        moves = "no path" if r["moves"] is None else str(r["moves"])
        lines.append(
            f"{r['strategy']:<11} {moves:>6} {r['nodes_expanded']:>6} {backtracks:>10} "
            f"{r['solve_seconds']:>9.5f}"
        )
    return "\n".join(lines)


def run_sequential(problem: MazeProblem, strategies: Iterable[str] = STRATEGY_NAMES) -> dict:
    """Baseline: the same jobs one after another in this process."""
    strategies = list(strategies)
    t0 = time.perf_counter()
    results = [solve_job(p, s) for p, s in plan_jobs(problem, strategies)]
    wall = time.perf_counter() - t0
    check_results(problem, results, strategies)
    return {"backend": "sequential", "workers": 1, "results": results, "wall_total_s": wall}
