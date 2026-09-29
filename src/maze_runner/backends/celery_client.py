"""Send one task per strategy to the Celery workers and collect the results.

celery -A maze_runner.backends.celery_app worker -c 4 --loglevel=info   # first, terminal 1
python -m maze_runner.backends.celery_client --maze static              # then, terminal 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from celery.exceptions import TimeoutError as CeleryTimeoutError
from celery.result import ResultSet

from ..strategies import STRATEGY_NAMES, MazeProblem, load_problem
from .celery_app import TASK_EXPIRES_S, app
from .celery_tasks import solve_task
from .common import check_results, format_results, plan_jobs

START_WORKER_HINT = (
    "Start RabbitMQ and a worker first, then run this client again:\n"
    "  celery -A maze_runner.backends.celery_app worker -c 4 --loglevel=info\n"
    "(or use docker compose, see the README)."
)


class NoWorkerError(RuntimeError):
    """The broker is unreachable or no worker answered a ping."""


class ResultTimeoutError(RuntimeError):
    """Workers were up but did not return every result in time."""


def count_workers(timeout: float = 2.0) -> dict:
    """Ping the workers. Raises NoWorkerError with a clear message if there are none.

    Returns only counts: worker names contain host names, which are not stored anywhere.
    """
    try:
        replies = app.control.ping(timeout=timeout)
        stats = app.control.inspect(timeout=timeout).stats() or {} if replies else {}
    except Exception as exc:  # kombu raises several connection error types
        raise NoWorkerError(f"Cannot reach the broker ({exc}).\n{START_WORKER_HINT}") from exc
    if not replies:
        raise NoWorkerError(f"No Celery worker answered within {timeout} s.\n{START_WORKER_HINT}")
    processes = sum(s.get("pool", {}).get("max-concurrency", 0) for s in stats.values())
    return {"nodes": len(replies), "processes": processes}


def run_celery(
    problem: MazeProblem,
    strategies: Iterable[str] = STRATEGY_NAMES,
    timeout: float = 30.0,
    expires: int = TASK_EXPIRES_S,
    ping: bool = True,
) -> dict:
    """Submit one task per strategy (same maze) and wait for all of them."""
    strategies = list(strategies)
    jobs = plan_jobs(problem, strategies)
    workers = count_workers() if ping else None
    payload = problem.to_dict()
    t0 = time.perf_counter()
    pending = ResultSet(
        [solve_task.apply_async(args=(payload, s), expires=expires) for _, s in jobs]
    )
    try:
        # join() collects whichever result arrives first. Calling .get() on each result in turn
        # (as in 2025) made the rpc:// backend stall for 1-2 s in some rounds (see DECISIONS.md).
        results = pending.join(timeout=timeout)
    except CeleryTimeoutError as exc:
        done = pending.completed_count()
        pending.revoke()
        raise ResultTimeoutError(
            f"Got {done} of {len(pending)} results within {timeout} s; the rest were revoked "
            f"(and expire after {expires} s anyway).\n{START_WORKER_HINT}"
        ) from exc
    wall = time.perf_counter() - t0
    check_results(problem, results, strategies)
    return {"backend": "celery", "workers": workers, "results": results, "wall_total_s": wall}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve one maze with each strategy on Celery.")
    parser.add_argument("--maze", choices=["static", "random"], default="static")
    parser.add_argument("--size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--repeats", type=int, default=1, help="rounds to run and time")
    parser.add_argument("--out", type=Path, help="write the rounds to this JSON file")
    args = parser.parse_args(argv)
    problem = load_problem(args.maze, args.size, args.seed)
    try:
        runs = [
            run_celery(problem, timeout=args.timeout, ping=(i == 0)) for i in range(args.repeats)
        ]
    except (NoWorkerError, ResultTimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    workers = runs[0]["workers"]
    print(
        f"Celery: {workers['nodes']} worker node(s), {workers['processes']} worker processes, "
        f"maze {problem.name}"
    )
    print(format_results(runs[0]["results"]))
    walls = ", ".join(f"{r['wall_total_s']:.4f}" for r in runs)
    print(f"wall time (submit to last result), s: {walls}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": runs}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
