"""The Celery task: solve the maze it is given with the strategy it is given.

In 2025 the task built its own random maze (so four workers solved four different mazes, B48),
reported no backtracks (the client printed a hard-coded 0, B50) and swallowed errors by
returning None. Now the maze travels with the task, the result carries the real counters,
and errors propagate to the client as task failures.
"""

from __future__ import annotations

from ..strategies import MazeProblem
from .celery_app import app
from .common import solve_job


@app.task(name="maze_runner.solve")
def solve_task(problem: dict, strategy: str) -> dict:
    return solve_job(MazeProblem.from_dict(problem), strategy)
