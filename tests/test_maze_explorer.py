"""Tests for the provided maze and explorer modules and my 2026 changes to them."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from maze_runner.explorer import Explorer, ExplorerCycleError, ExplorerStuckError
from maze_runner.maze import Maze, create_maze


def grid_maze(rows, start_xy, end_xy):
    grid = [[int(c) for c in r] for r in rows]
    return SimpleNamespace(
        width=len(grid[0]), height=len(grid), grid=grid, start_pos=start_xy, end_pos=end_xy
    )


def test_seeded_random_maze_is_reproducible():
    a, b = create_maze(21, 21, seed=7), create_maze(21, 21, seed=7)
    assert a.grid == b.grid and a.start_pos == b.start_pos and a.end_pos == b.end_pos
    assert create_maze(21, 21, seed=8).grid != a.grid


def test_unseeded_mazes_still_vary():
    grids = {tuple(map(tuple, Maze(15, 15).grid)) for _ in range(5)}
    assert len(grids) > 1


@pytest.mark.parametrize("size", [10, 30, 50, 80])
def test_random_maze_start_and_exit_are_open(size):
    m = create_maze(size, size, seed=0)
    assert not m.is_wall(m.start_pos) and not m.is_wall(m.end_pos)


def test_static_maze_ignores_width_and_height():
    m = create_maze(5, 5, "static")
    assert (m.width, m.height) == (62, 48)
    assert m.start_pos == (11, 0) and m.end_pos == (13, 47)


def test_explorer_static_maze_1279_moves_and_no_backtracks():
    t, moves = Explorer(create_maze(0, 0, "static")).solve()
    assert len(moves) == 1279 and t >= 0


def test_backtracking_never_triggers(monkeypatch):
    """is_stuck() compares the last 3 positions, but every move changes position, so they can
    never all be equal. The backtracking branch is unreachable and backtrack_count stays 0."""

    def fail(self):
        raise AssertionError("backtrack() was called")

    monkeypatch.setattr(Explorer, "backtrack", fail)
    Explorer(create_maze(0, 0, "static")).solve()
    for seed in range(20):
        e = Explorer(create_maze(30, 30, seed=seed))
        e.solve()
        assert e.backtrack_count == 0


def test_verbose_prints_statistics(capsys):
    Explorer(grid_maze(["101", "101"], (1, 0), (1, 1)), verbose=True).solve()
    out = capsys.readouterr().out
    assert "Total moves made: 1" in out


def test_print_statistics_zero_time(capsys):
    e = Explorer(grid_maze(["101", "101"], (1, 0), (1, 1)))
    e.print_statistics(0)
    assert "Cannot calculate" in capsys.readouterr().out


def test_cycle_guard_raises():
    sealed = grid_maze(["10111", "10001", "11111", "11011"], (1, 0), (2, 3))
    with pytest.raises(ExplorerCycleError):
        Explorer(sealed).solve()


def test_default_guard_is_four_states_per_cell():
    m = grid_maze(["101", "101"], (1, 0), (1, 1))
    assert Explorer(m).max_moves == 4 * 3 * 2


def test_explorer_imports_without_pygame(monkeypatch):
    monkeypatch.setitem(sys.modules, "pygame", None)  # any "import pygame" now fails
    t, moves = Explorer(grid_maze(["101", "101", "101"], (1, 0), (1, 2))).solve()
    assert len(moves) == 2


def test_explorer_visualize_headless(monkeypatch):
    pygame = pytest.importorskip("pygame")
    monkeypatch.setattr(pygame.time, "wait", lambda ms: None)
    e = Explorer(grid_maze(["101", "101", "101"], (1, 0), (1, 2)), visualize=True)
    e.clock = SimpleNamespace(tick=lambda fps: 0)
    _, moves = e.solve()
    assert len(moves) == 2


def test_turns_are_inverse():
    e = Explorer(grid_maze(["101"], (1, 0), (1, 0)))
    start = e.direction
    e.turn_right()
    e.turn_left()
    assert e.direction == start


def test_find_backtrack_path_and_backtrack_directly():
    """backtrack() is unreachable from solve(), but the method itself still works."""
    m = grid_maze(["10111", "10001", "10111"], (1, 0), (1, 2))
    e = Explorer(m)
    e.moves = [(1, 1), (2, 1), (3, 1)]
    e.x, e.y = 3, 1
    # walking back from (3, 1), the first cell with 2+ open neighbours is (2, 1)
    assert e.find_backtrack_path() == [(2, 1), (3, 1)]
    assert e.backtrack() and e.backtrack_count == 1
    e.backtrack_path, e.moves = [], []
    assert not e.backtrack()


def test_boxed_in_start_raises_instead_of_walking_through_walls():
    boxed = grid_maze(["1110", "1101"], (3, 0), (2, 1))  # start (x=3, y=0) has no open neighbour
    with pytest.raises(ExplorerStuckError):
        Explorer(boxed).solve()
