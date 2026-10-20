"""The Celery task: solve the maze it is given with the strategy it is given.

The maze travels with the task, so every worker solves the same maze. The result carries the
real counters (moves, nodes, backtracks), and errors reach the client as task failures.
"""

from __future__ import annotations

from ..strategies import MazeProblem
from .celery_app import app
from .common import solve_job


@app.task(name="maze_runner.solve")
def solve_task(problem: dict, strategy: str) -> dict:
    return solve_job(MazeProblem.from_dict(problem), strategy)
