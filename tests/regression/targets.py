"""The questions the regression tests ask, answered by the maze_runner package.

The regression tests ask things like "how many moves does BFS report on the static maze?".
Target answers them with the current code, so each test states one fixed bug as a property.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Target:
    def static_moves(self, strategy: str) -> int:
        from maze_runner.strategies import load_problem, solve

        return solve(load_problem("static"), strategy).moves

    def reported_backtracks(self, strategy: str) -> tuple[int, int | None]:
        from maze_runner.strategies import load_problem, solve

        r = solve(load_problem("static"), strategy)
        return r.moves, r.backtracks

    def seconds_with_display(self, strategy: str, display_s: float) -> float:
        from maze_runner.benchmark import timed_solve
        from maze_runner.strategies import load_problem

        _, seconds = timed_solve(load_problem("static"), strategy, lambda r: time.sleep(display_s))
        return seconds

    def result_rows_after(self, runs: int, workdir: Path) -> int:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import run_benchmarks
        finally:
            sys.path.pop(0)
        args = ["--out-dir", str(workdir), "--repeats", "1", "--sizes", "10", "--seeds", "1",
                "--backends", "sequential", "--backend-mazes", "static"]  # fmt: skip
        for _ in range(runs):
            with contextlib.redirect_stdout(io.StringIO()):
                run_benchmarks.main(args)
        return len((workdir / "results" / "static_maze.csv").read_text().strip().splitlines()) - 1

    def moves_for_identical_celery_tasks(self, n: int) -> list[int]:
        """Design check: the task receives the maze in its payload, so identical tasks solve the
        same maze by construction."""
        from maze_runner.backends.celery_tasks import solve_task
        from maze_runner.strategies import load_problem

        payload = load_problem("random", 10, 0).to_dict()
        return [solve_task(payload, "right_hand")["moves"] for _ in range(n)]

    def distinct_parallel_jobs(self, n: int) -> int:
        from maze_runner.backends.common import plan_jobs
        from maze_runner.strategies import STRATEGY_NAMES, load_problem

        jobs = plan_jobs(load_problem("static"), STRATEGY_NAMES[:n])
        return len({s for _, s in jobs})

    def celery_send_options(self) -> list[dict]:
        from maze_runner.backends import celery_client
        from maze_runner.backends.celery_app import app
        from maze_runner.backends.celery_tasks import solve_task
        from maze_runner.strategies import load_problem

        sent, original = [], solve_task.apply_async

        def spy(*args, **kwargs):
            sent.append(kwargs)
            return original(*args, **kwargs)

        old_eager = app.conf.task_always_eager
        app.conf.task_always_eager = True
        solve_task.apply_async = spy
        try:
            celery_client.run_celery(load_problem("static"), ping=False)
        finally:
            app.conf.task_always_eager = old_eager
            del solve_task.apply_async
        return sent

    def client_shows_backtracks(self, true_value: int) -> int:
        from maze_runner.backends.common import format_results

        row = {"strategy": "right_hand", "moves": 5, "nodes_expanded": 5,
               "backtracks": true_value, "solve_seconds": 0.1}  # fmt: skip
        return int(format_results([row]).splitlines()[1].split()[3])

    def headless_import_ok(self) -> bool:
        code = (
            "import sys; sys.modules['pygame'] = None\n"
            "from maze_runner.strategies import load_problem, solve\n"
            "from maze_runner import cli, benchmark, explorer\n"
            "assert solve(load_problem('static'), 'right_hand').moves == 1279\n"
        )
        return subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0

    def requirements(self) -> str:
        return (ROOT / "requirements.txt").read_text()
