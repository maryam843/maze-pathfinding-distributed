"""One regression test per bug fixed in the 2026 rebuild, each named after its bug.

Default: runs against the fixed package and must pass.
MAZE_REGRESSION_TARGET=legacy: runs the same tests against the 2025 files in original_2025/,
where every test is expected to FAIL (that is the proof each test catches its bug):

    MAZE_REGRESSION_TARGET=legacy python -m pytest tests/regression -p no:cacheprovider
"""

from __future__ import annotations

import os

import pytest

from .targets import LegacyTarget, NewTarget

STATIC_OPTIMUM = 127  # shortest path on the static maze, entrance (0, 11) -> exit (47, 13)


@pytest.fixture
def target(tmp_path):
    if os.environ.get("MAZE_REGRESSION_TARGET") == "legacy":
        return LegacyTarget(tmp_path)
    return NewTarget()


@pytest.mark.parametrize("strategy", ["bfs", "astar"])
def test_bfs_and_astar_solve_the_real_static_maze(target, strategy):
    """Bug: BFS and A* solved the wrong maze copy."""
    assert target.static_moves(strategy) == STATIC_OPTIMUM


def test_bfs_and_astar_agree(target):
    """Bug: BFS and A* solved the wrong maze copy, so their lengths differed."""
    assert target.static_moves("bfs") == target.static_moves("astar")


def test_timer_excludes_the_display(target):
    """Bug: the BFS timer included the 3-second display window."""
    assert target.seconds_with_display("bfs", display_s=0.5) < 0.4


def test_bfs_reports_no_fake_backtracks(target):
    """Bug: BFS reported moves - 1 as its backtrack count."""
    moves, backtracks = target.reported_backtracks("bfs")
    assert backtracks is None or backtracks != moves - 1


def test_results_file_is_replaced_not_appended(target, tmp_path):
    """Bug: every run appended rows to the results file."""
    once = target.result_rows_after(1, tmp_path / "once")
    twice = target.result_rows_after(2, tmp_path / "twice")
    assert once == twice


def test_celery_tasks_sent_the_same_way_solve_the_same_maze(target):
    """Bug: each Celery task built its own random maze."""
    moves = target.moves_for_identical_celery_tasks(4)
    assert len(set(moves)) == 1, moves


def test_parallel_workers_get_different_strategies(target):
    """Bug: every parallel worker ran the same explorer on the same maze."""
    assert target.distinct_parallel_jobs(4) == 4


def test_celery_tasks_expire(target):
    """Bug: Celery tasks never expired, so a stopped client left work queued."""
    sent = target.celery_send_options()
    assert sent and all(kw.get("expires") for kw in sent)


def test_client_shows_the_real_backtrack_count(target):
    """Bug: the Celery client printed a hard-coded 0 backtracks."""
    assert target.client_shows_backtracks(3) == 3


def test_runs_headless_without_pygame(target):
    """Bug: importing the code needed pygame and a display."""
    assert target.headless_import_ok()


def test_requirements_list_and_pin_mpi4py_and_celery(target):
    """Bug: requirements.txt did not list mpi4py or celery."""
    lines = [ln.strip().lower() for ln in target.requirements().splitlines()]
    for pkg in ("mpi4py", "celery"):
        assert any(ln.startswith(pkg + "==") for ln in lines), pkg
