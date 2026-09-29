"""Run the strategies in parallel with a multiprocessing pool (one strategy per process).

Spawn-safe: the worker function is a top-level function, the job is a small picklable
dataclass, and nothing runs at import time. So it works with "spawn" (the only start method
on Windows) as well as "forkserver" (used by default on Linux/macOS) and "fork".
Set MAZE_MP_START_METHOD=spawn to force spawn anywhere.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import time
from collections.abc import Iterable

from ..strategies import STRATEGY_NAMES, MazeProblem, load_problem
from .common import check_results, format_results, plan_jobs, solve_job


def _worker(job: tuple[MazeProblem, str]) -> dict:
    problem, strategy = job
    return solve_job(problem, strategy)


def pick_start_method(requested: str | None = None) -> str:
    """Explicit argument, else MAZE_MP_START_METHOD, else forkserver where it exists, else spawn.

    Plain fork is avoided: it copies open sockets into the children, and Celery's after-fork
    hook then closes the parent's broker connection from inside the child (see DECISIONS.md).
    forkserver forks from a clean server process and is Python 3.14's default on Linux.
    """
    method = requested or os.environ.get("MAZE_MP_START_METHOD")
    if method:
        return method
    return "forkserver" if "forkserver" in mp.get_all_start_methods() else "spawn"


def run_multiprocessing(
    problem: MazeProblem,
    strategies: Iterable[str] = STRATEGY_NAMES,
    processes: int | None = None,
    start_method: str | None = None,
) -> dict:
    """Solve every strategy on the same maze in its own process.

    Returns the per-strategy results plus two timings: total (pool start-up + work +
    shut-down) and map-only (work sent to an already running pool).
    """
    strategies = list(strategies)
    jobs = plan_jobs(problem, strategies)
    ctx = mp.get_context(pick_start_method(start_method))
    t0 = time.perf_counter()
    with ctx.Pool(processes=processes or len(jobs)) as pool:
        t1 = time.perf_counter()
        results = pool.map(_worker, jobs)
        t2 = time.perf_counter()
    t3 = time.perf_counter()
    check_results(problem, results, strategies)
    return {
        "backend": "multiprocessing",
        "start_method": ctx.get_start_method(),
        "workers": processes or len(jobs),
        "results": results,
        "wall_total_s": t3 - t0,
        "wall_compute_s": t2 - t1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve one maze with each strategy in parallel.")
    parser.add_argument("--maze", choices=["static", "random"], default="static")
    parser.add_argument("--size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    problem = load_problem(args.maze, args.size, args.seed)
    run = run_multiprocessing(problem)
    print(f"multiprocessing ({run['start_method']}), maze {problem.name}")
    print(format_results(run["results"]))
    print(f"wall time: total {run['wall_total_s']:.4f} s, map only {run['wall_compute_s']:.4f} s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
