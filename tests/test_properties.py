"""Property-based tests (hypothesis): invariants on random solvable grids, loops included."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from maze_runner.strategies import MazeProblem, astar, bfs, solve, validate_path


@st.composite
def grids(draw):
    h = draw(st.integers(2, 12))
    w = draw(st.integers(2, 12))
    cells = draw(st.lists(st.booleans(), min_size=h * w, max_size=h * w))
    grid = [[0 if cells[r * w + c] else 1 for c in range(w)] for r in range(h)]
    opens = [(r, c) for r in range(h) for c in range(w) if grid[r][c] == 0]
    assume(len(opens) >= 1)
    start = draw(st.sampled_from(opens))
    goal = draw(st.sampled_from(opens))
    return MazeProblem(tuple(map(tuple, grid)), start, goal)


def shortest_by_flood(p: MazeProblem):
    """Independent oracle: plain distance flood, no parent tracking."""
    dist = {p.start: 0}
    frontier = [p.start]
    while frontier:
        nxt = []
        for r, c in frontier:
            for cell in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if p.is_open(cell) and cell not in dist:
                    dist[cell] = dist[(r, c)] + 1
                    nxt.append(cell)
        frontier = nxt
    return dist.get(p.goal)


@settings(max_examples=300, deadline=None)
@given(grids())
def test_astar_and_bfs_agree_with_an_independent_oracle(p):
    expected = shortest_by_flood(p)
    a, b = astar(p), bfs(p)
    assert a.moves == b.moves == expected
    if expected is not None:
        validate_path(p, a.path)
        validate_path(p, b.path)


@settings(max_examples=300, deadline=None)
@given(grids())
def test_astar_never_expands_more_than_bfs(p):
    assert astar(p).nodes_expanded <= bfs(p).nodes_expanded


@settings(max_examples=150, deadline=None)
@given(grids())
def test_wall_followers_return_valid_paths_or_give_up(p):
    for name in ("right_hand", "left_hand"):
        r = solve(p, name)  # solve() validates any path it returns
        if r.found:
            assert r.moves >= shortest_by_flood(p)


@settings(max_examples=40, deadline=None)
@given(st.integers(5, 40), st.integers(0, 10_000))
def test_generated_mazes_are_solvable_and_consistent(size, seed):
    from maze_runner.strategies import load_problem

    p = load_problem("random", size, seed)
    moves = {s: solve(p, s).moves for s in ("bfs", "astar", "right_hand", "left_hand")}
    assert moves["bfs"] == moves["astar"] is not None
    assert moves["right_hand"] >= moves["bfs"] and moves["left_hand"] >= moves["bfs"]
