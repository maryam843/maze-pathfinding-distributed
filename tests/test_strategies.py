"""Unit tests for strategies.py on small hand-made mazes with known answers."""

from __future__ import annotations

import pytest

from maze_runner.explorer import Explorer
from maze_runner.maze import create_maze
from maze_runner.strategies import (
    STRATEGY_NAMES,
    InvalidPathError,
    LeftHandExplorer,
    MazeProblem,
    astar,
    bfs,
    left_hand,
    load_problem,
    manhattan,
    neighbours,
    right_hand,
    solve,
    to_row_col,
    to_x_y,
    validate_path,
)

CORRIDOR = MazeProblem.from_rows(["101", "101", "101"], (0, 1), (2, 1), "corridor")

# Two dead ends (left branch, right branch); one route: 8 moves.
DEAD_ENDS = MazeProblem.from_rows(
    ["1011111", "1000001", "1010111", "1010001", "1111101"], (0, 1), (4, 5), "dead-ends"
)
DEAD_ENDS_PATH = [(0, 1), (1, 1), (1, 2), (1, 3), (2, 3), (3, 3), (3, 4), (3, 5), (4, 5)]

# A loop around a wall block; exit straight below the start: 4 moves.
LOOP = MazeProblem.from_rows(
    ["1011111", "1000001", "1011101", "1000001", "1011111"], (0, 1), (4, 1), "loop"
)

# The goal is sealed off; 6 cells reachable from the start.
NO_PATH = MazeProblem.from_rows(
    ["1011111", "1000001", "1111111", "1110111", "1111111"], (0, 1), (3, 3), "no-path"
)


def test_coordinate_helper_round_trip():
    assert to_row_col((11, 0)) == (0, 11)
    assert to_x_y((0, 11)) == (11, 0)
    assert to_x_y(to_row_col((3, 7))) == (3, 7)


def test_from_maze_uses_the_game_entrance_and_exit():
    maze = create_maze(0, 0, "static")
    problem = MazeProblem.from_maze(maze, "static")
    # StaticMaze stores (x, y) = (11, 0) and (13, 47); in (row, col) they swap.
    assert maze.start_pos == (11, 0) and maze.end_pos == (13, 47)
    assert problem.start == (0, 11) and problem.goal == (47, 13)
    assert (problem.height, problem.width) == (48, 62)


@pytest.mark.parametrize("strategy", STRATEGY_NAMES)
def test_corridor_every_strategy_two_moves(strategy):
    result = solve(CORRIDOR, strategy)
    assert result.path == [(0, 1), (1, 1), (2, 1)]
    assert result.moves == 2


@pytest.mark.parametrize("func", [bfs, astar])
def test_dead_ends_shortest_path(func):
    result = func(DEAD_ENDS)
    assert result.path == DEAD_ENDS_PATH
    assert result.moves == 8
    assert result.backtracks is None


@pytest.mark.parametrize("func", [right_hand, left_hand])
def test_dead_ends_wall_followers_reach_exit_with_detours(func):
    result = func(DEAD_ENDS)
    validate_path(DEAD_ENDS, result.path)
    assert result.moves >= 8
    assert result.backtracks == 0


def test_astar_expands_fewer_nodes_than_bfs_on_dead_ends():
    assert astar(DEAD_ENDS).nodes_expanded <= bfs(DEAD_ENDS).nodes_expanded


@pytest.mark.parametrize("strategy", STRATEGY_NAMES)
def test_loop_maze(strategy):
    result = solve(LOOP, strategy)
    validate_path(LOOP, result.path)
    if strategy in ("bfs", "astar"):
        assert result.moves == 4
    else:
        assert result.moves >= 4


@pytest.mark.parametrize("func", [bfs, astar])
def test_no_path_searches_whole_reachable_area(func):
    result = func(NO_PATH)
    assert not result.found and result.path is None and result.moves is None
    assert result.nodes_expanded == 6


@pytest.mark.parametrize("func", [right_hand, left_hand])
def test_no_path_wall_follower_stops_instead_of_looping_forever(func):
    result = func(NO_PATH)
    assert not result.found
    assert result.nodes_expanded == 6  # it walked every reachable cell before giving up


def test_start_equals_goal():
    p = MazeProblem.from_rows(["000"], (0, 1), (0, 1))
    for s in STRATEGY_NAMES:
        assert solve(p, s).moves == 0


def test_static_maze_known_values():
    """Known values on the static maze: right-hand 1279 moves, BFS and A* 127."""
    p = load_problem("static")
    moves = {s: solve(p, s).moves for s in STRATEGY_NAMES}
    assert moves["right_hand"] == 1279
    assert moves["bfs"] == moves["astar"] == 127


def test_left_hand_is_the_mirror_of_right_hand():
    assert LeftHandExplorer.turn_right is Explorer.turn_left
    assert LeftHandExplorer.turn_left is Explorer.turn_right
    # On a maze that is its own mirror image, the two wall followers use the same number of moves.
    sym = MazeProblem.from_rows(["11011", "10001", "10101", "10001", "11011"], (0, 2), (4, 2))
    assert right_hand(sym).moves == left_hand(sym).moves


def test_validate_path_rejects_bad_paths():
    good = [(0, 1), (1, 1), (2, 1)]
    validate_path(CORRIDOR, good)
    bad = {
        "empty": [],
        "wrong start": [(1, 1), (2, 1)],
        "wrong end": [(0, 1), (1, 1)],
        "wall": [(0, 1), (0, 0), (1, 1), (2, 1)],
        "jump": [(0, 1), (2, 1)],
    }
    for path in bad.values():
        with pytest.raises(InvalidPathError):
            validate_path(CORRIDOR, path)


def test_problem_validation():
    with pytest.raises(ValueError):
        MazeProblem.from_rows(["101", "10"], (0, 1), (1, 1))
    with pytest.raises(ValueError):
        MazeProblem.from_rows(["101"], (0, 0), (0, 1))  # start in a wall
    with pytest.raises(ValueError):
        MazeProblem.from_rows(["101"], (0, 1), (5, 1))  # goal outside


def test_fingerprint_and_dict_round_trip():
    p = load_problem("random", 15, 3)
    q = MazeProblem.from_dict(p.to_dict())
    assert q == p and q.fingerprint() == p.fingerprint()
    assert load_problem("random", 15, 4).fingerprint() != p.fingerprint()


def test_neighbours_order_and_bounds():
    assert list(neighbours(CORRIDOR, (1, 1))) == [(2, 1), (0, 1)]
    assert list(neighbours(CORRIDOR, (0, 1))) == [(1, 1)]


def test_manhattan():
    assert manhattan((0, 0), (3, 4)) == 7


def test_bad_arguments():
    with pytest.raises(ValueError):
        load_problem("hexagonal")
    with pytest.raises(ValueError):
        solve(CORRIDOR, "dfs")


def test_result_to_dict():
    d = solve(DEAD_ENDS, "bfs").to_dict()
    assert d == {
        "strategy": "bfs",
        "found": True,
        "moves": 8,
        "nodes_expanded": d["nodes_expanded"],
        "backtracks": None,
    }
