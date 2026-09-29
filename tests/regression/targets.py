"""Two implementations of the same questions: the fixed 2026 package and the 2025 originals.

The regression tests ask a target things like "how many moves does BFS report on the static
maze?". NewTarget answers with maze_runner; LegacyTarget runs the untouched 2025 files in
original_2025/ and reads what they print or send. The legacy side only observes: display
windows are replaced (by a no-op or a fixed sleep) and Celery's network calls are replaced by
recorders, but no 2025 logic is changed.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import random
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / "original_2025"
LEGACY_MODULES = ("src", "celery_app", "celery_task", "celery_main", "multiprocessing_main")


def _number(pattern: str, text: str) -> float:
    m = re.search(pattern, text)
    if not m:
        raise AssertionError(f"pattern {pattern!r} not found in output:\n{text}")
    return float(m.group(1))


class NewTarget:
    name = "new"

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
        return len((workdir / "static_maze.csv").read_text().strip().splitlines()) - 1

    def moves_for_identical_celery_tasks(self, n: int) -> list[int]:
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


class LegacyTarget:
    """Runs the 2025 code from original_2025/ (in a temporary working directory)."""

    name = "legacy"

    def __init__(self, workdir: Path):
        self.workdir = workdir

    @contextlib.contextmanager
    def _legacy(self):
        saved_path, saved_cwd = list(sys.path), os.getcwd()
        for mod in [m for m in sys.modules if m.split(".")[0] in LEGACY_MODULES]:
            del sys.modules[mod]
        sys.path.insert(0, str(LEGACY))
        os.chdir(self.workdir)
        try:
            yield
        finally:
            os.chdir(saved_cwd)
            sys.path[:] = saved_path
            for mod in [m for m in sys.modules if m.split(".")[0] in LEGACY_MODULES]:
                del sys.modules[mod]

    def _run_solver_main(self, strategy: str, display=lambda *a, **k: None) -> str:
        module = {"bfs": "src.bfs", "astar": "src.astar"}[strategy]
        with self._legacy():
            mod = importlib.import_module(module)
            mod.visualize_maze_with_stats = display
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.main()
        return out.getvalue()

    def static_moves(self, strategy: str) -> int:
        return int(_number(r"Total moves made: (\d+)", self._run_solver_main(strategy)))

    def reported_backtracks(self, strategy: str) -> tuple[int, int | None]:
        text = self._run_solver_main(strategy)
        return (
            int(_number(r"Total moves made: (\d+)", text)),
            int(_number(r"Number of backtrack operations: (\d+)", text)),
        )

    def seconds_with_display(self, strategy: str, display_s: float) -> float:
        text = self._run_solver_main(strategy, lambda *a, **k: time.sleep(display_s))
        return _number(r"Total time taken: ([\d.]+)", text)

    def result_rows_after(self, runs: int, workdir: Path) -> int:
        workdir.mkdir(parents=True, exist_ok=True)
        self.workdir = workdir
        for _ in range(runs):
            self._run_solver_main("astar")
        return len((workdir / "results.csv").read_text().strip().splitlines()) - 1

    def moves_for_identical_celery_tasks(self, n: int) -> list[int]:
        with self._legacy():
            task = importlib.import_module("celery_task")
            random.seed(0)  # seeded once, so this test is deterministic
            with contextlib.redirect_stdout(io.StringIO()):
                return [task.solve_maze(10, 10)["moves"] for _ in range(n)]

    def distinct_parallel_jobs(self, n: int) -> int:
        with self._legacy():
            mp_main = importlib.import_module("multiprocessing_main")
            maze_mod = importlib.import_module("src.maze")
            recorded = []

            class RecordingPool:
                def __init__(self, processes):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def starmap(self, func, jobs):
                    jobs = list(jobs)
                    recorded.extend(jobs)
                    return [func(*job) for job in jobs]

            mp_main.multiprocessing = SimpleNamespace(Pool=RecordingPool)
            with contextlib.redirect_stdout(io.StringIO()):
                mp_main.parallel_exploration(maze_mod.create_maze(10, 10, "static"), n)
        # what differs between the jobs, apart from the (shared) maze object
        return len({tuple(a for a in job[1:]) for job in recorded})

    def _run_celery_main(self, result: dict) -> tuple[list[dict], str]:
        sent = []

        class FakeResult:
            def get(self, timeout=None):
                return result

        with self._legacy():
            task = importlib.import_module("celery_task")

            def record(*args, **kwargs):
                sent.append(kwargs)
                return FakeResult()

            task.solve_maze.apply_async = record  # .delay() calls apply_async
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    runpy.run_path(str(LEGACY / "celery_main.py"), run_name="__main__")
            finally:
                del task.solve_maze.apply_async
        return sent, out.getvalue()

    def celery_send_options(self) -> list[dict]:
        sent, _ = self._run_celery_main({"time_taken": 0.1, "moves": 5})
        return sent

    def client_shows_backtracks(self, true_value: int) -> int:
        _, text = self._run_celery_main({"time_taken": 0.1, "moves": 5, "backtracks": true_value})
        return int(_number(r"Number of backtrack operations: (\d+)", text))

    def headless_import_ok(self) -> bool:
        code = "import sys; sys.modules['pygame'] = None\nimport src.explorer\n"
        return (
            subprocess.run([sys.executable, "-c", code], cwd=LEGACY, capture_output=True).returncode
            == 0
        )

    def requirements(self) -> str:
        return (LEGACY / "requirements.txt").read_text()
