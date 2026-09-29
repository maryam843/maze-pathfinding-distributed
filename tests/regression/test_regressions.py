"""One regression test per fixed bug (IDs from the 2026 run-check register).

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
def test_b44_bfs_and_astar_solve_the_real_static_maze(target, strategy):
    assert target.static_moves(strategy) == STATIC_OPTIMUM


def test_b44_bfs_and_astar_agree(target):
    assert target.static_moves("bfs") == target.static_moves("astar")


def test_b45_timer_excludes_the_display(target):
    assert target.seconds_with_display("bfs", display_s=0.5) < 0.4


def test_b45_bfs_reports_no_fake_backtracks(target):
    moves, backtracks = target.reported_backtracks("bfs")
    assert backtracks is None or backtracks != moves - 1


def test_b46_results_file_is_replaced_not_appended(target, tmp_path):
    once = target.result_rows_after(1, tmp_path / "once")
    twice = target.result_rows_after(2, tmp_path / "twice")
    assert once == twice


def test_b48_celery_tasks_sent_the_same_way_solve_the_same_maze(target):
    moves = target.moves_for_identical_celery_tasks(4)
    assert len(set(moves)) == 1, moves


def test_b51_parallel_workers_get_different_strategies(target):
    assert target.distinct_parallel_jobs(4) == 4


def test_b49_celery_tasks_expire(target):
    sent = target.celery_send_options()
    assert sent and all(kw.get("expires") for kw in sent)


def test_b50_client_shows_the_real_backtrack_count(target):
    assert target.client_shows_backtracks(3) == 3


def test_b53_runs_headless_without_pygame(target):
    assert target.headless_import_ok()


def test_b52_requirements_list_and_pin_mpi4py_and_celery(target):
    lines = [ln.strip().lower() for ln in target.requirements().splitlines()]
    for pkg in ("mpi4py", "celery"):
        assert any(ln.startswith(pkg + "==") for ln in lines), pkg
