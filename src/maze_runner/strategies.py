"""Four ways to get through a maze: two wall followers and two shortest-path searches.

Coordinate convention: every grid here is indexed grid[row][col], 0 = open, 1 = wall.
The provided Maze class stores positions as (x, y) = (col, row). All code in this module
works in (row, col), and the conversion happens in exactly one place: to_row_col(), used by
MazeProblem.from_maze(). (In 2025 my BFS and A* skipped this step and used their own
hard-coded grids and start/goal cells instead of the game's maze. That was bug B44.)
"""

from __future__ import annotations

import hashlib
import heapq
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace

from .explorer import Explorer, ExplorerCycleError
from .maze import create_maze

Cell = tuple[int, int]  # (row, col)


def to_row_col(pos_xy: tuple[int, int]) -> Cell:
    """Convert the provided Maze's (x, y) position into (row, col)."""
    x, y = pos_xy
    return (y, x)


def to_x_y(cell: Cell) -> tuple[int, int]:
    """Inverse of to_row_col, used only to hand positions back to the provided Explorer."""
    row, col = cell
    return (col, row)


@dataclass(frozen=True)
class MazeProblem:
    """A maze plus its start and goal, in (row, col). Immutable and cheap to send to workers."""

    grid: tuple[tuple[int, ...], ...]
    start: Cell
    goal: Cell
    name: str = "maze"

    def __post_init__(self) -> None:
        widths = {len(row) for row in self.grid}
        if not self.grid or len(widths) != 1:
            raise ValueError("grid must be a non-empty rectangle")
        for cell in (self.start, self.goal):
            if not self.in_bounds(cell) or not self.is_open(cell):
                raise ValueError(f"start/goal {cell} must be an open cell inside the grid")

    @classmethod
    def from_maze(cls, maze, name: str = "maze") -> MazeProblem:
        """Build a problem from the provided Maze/StaticMaze object (the only (x, y) boundary)."""
        grid = tuple(tuple(int(v) for v in row) for row in maze.grid)
        return cls(grid, to_row_col(maze.start_pos), to_row_col(maze.end_pos), name)

    @classmethod
    def from_rows(cls, rows: list[str], start: Cell, goal: Cell, name: str = "maze") -> MazeProblem:
        """Build a problem from strings such as "10001" (handy for small hand-made tests)."""
        return cls(tuple(tuple(int(c) for c in row) for row in rows), start, goal, name)

    @property
    def height(self) -> int:
        return len(self.grid)

    @property
    def width(self) -> int:
        return len(self.grid[0])

    def in_bounds(self, cell: Cell) -> bool:
        row, col = cell
        return 0 <= row < len(self.grid) and 0 <= col < len(self.grid[0])

    def is_open(self, cell: Cell) -> bool:
        return self.in_bounds(cell) and self.grid[cell[0]][cell[1]] == 0

    def rows(self) -> list[str]:
        return ["".join(str(v) for v in row) for row in self.grid]

    def fingerprint(self) -> str:
        """Short SHA-256 of grid + start + goal. Equal fingerprints mean the same maze."""
        text = "\n".join(self.rows()) + f"|{self.start}|{self.goal}"
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        """JSON-safe form (Celery uses the json serializer)."""
        return {
            "name": self.name,
            "rows": self.rows(),
            "start": list(self.start),
            "goal": list(self.goal),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MazeProblem:
        return cls.from_rows(data["rows"], tuple(data["start"]), tuple(data["goal"]), data["name"])


def load_problem(kind: str = "static", size: int = 30, seed: int | None = 0) -> MazeProblem:
    """The static maze from the assignment, or a seeded random maze of size x size."""
    if kind == "static":
        return MazeProblem.from_maze(create_maze(0, 0, "static"), name="static")
    if kind == "random":
        maze = create_maze(size, size, "random", seed=seed)
        return MazeProblem.from_maze(maze, name=f"random-{size}-seed{seed}")
    raise ValueError(f"unknown maze kind {kind!r} (use 'static' or 'random')")


@dataclass
class SearchResult:
    """What a strategy returns.

    path: cells from start to goal inclusive, or None if the goal was not reached.
    nodes_expanded: BFS/A*: cells taken off the queue/heap and expanded.
        Wall followers: distinct cells they stood on (they have no queue).
    backtracks: the provided explorer's backtrack counter. None for BFS/A*, which never
        backtrack (in 2025 BFS printed moves - 1 here, which was not a real count).
    """

    strategy: str
    path: list[Cell] | None
    nodes_expanded: int
    backtracks: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.path is not None

    @property
    def moves(self) -> int | None:
        return None if self.path is None else len(self.path) - 1

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "found": self.found,
            "moves": self.moves,
            "nodes_expanded": self.nodes_expanded,
            "backtracks": self.backtracks,
        }


class InvalidPathError(AssertionError):
    """A returned path broke one of the path rules."""


def validate_path(problem: MazeProblem, path: list[Cell]) -> None:
    """Check a path starts at the start, ends at the goal, uses open cells and 4-neighbour steps."""
    if not path:
        raise InvalidPathError("empty path")
    if path[0] != problem.start:
        raise InvalidPathError(f"path starts at {path[0]}, not at the start {problem.start}")
    if path[-1] != problem.goal:
        raise InvalidPathError(f"path ends at {path[-1]}, not at the goal {problem.goal}")
    for cell in path:
        if not problem.is_open(cell):
            raise InvalidPathError(f"path goes through a wall or outside the grid at {cell}")
    for a, b in zip(path, path[1:], strict=False):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            raise InvalidPathError(f"step {a} -> {b} is not a single 4-neighbour move")


def neighbours(problem: MazeProblem, cell: Cell) -> Iterator[Cell]:
    """Open 4-neighbours, in the same order my 2025 BFS/A* used: down, up, right, left."""
    row, col = cell
    for nxt in ((row + 1, col), (row - 1, col), (row, col + 1), (row, col - 1)):
        if problem.is_open(nxt):
            yield nxt


def _rebuild(came_from: dict[Cell, Cell | None], goal: Cell) -> list[Cell]:
    path = []
    node: Cell | None = goal
    while node is not None:
        path.append(node)
        node = came_from[node]
    return path[::-1]


def bfs(problem: MazeProblem) -> SearchResult:
    """Breadth-first search (from my 2025 bfs.py). Shortest path on an unweighted grid."""
    queue: deque[Cell] = deque([problem.start])
    came_from: dict[Cell, Cell | None] = {problem.start: None}
    expanded = 0
    while queue:
        current = queue.popleft()
        expanded += 1
        if current == problem.goal:
            return SearchResult("bfs", _rebuild(came_from, current), expanded)
        for nxt in neighbours(problem, current):
            if nxt not in came_from:
                came_from[nxt] = current
                queue.append(nxt)
    return SearchResult("bfs", None, expanded)


def manhattan(a: Cell, b: Cell) -> int:
    """Admissible and consistent for 4-neighbour moves of cost 1."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(problem: MazeProblem) -> SearchResult:
    """A* with the Manhattan heuristic (from my 2025 astar.py).

    Heap entries are (f, g, cell) as in 2025, so ties on f go to the smaller g.
    2026 change: a cell already expanded is skipped when an older heap entry for it is popped,
    so each cell is expanded at most once and nodes_expanded counts real work.
    """
    start, goal = problem.start, problem.goal
    heap: list[tuple[int, int, Cell]] = [(manhattan(start, goal), 0, start)]
    came_from: dict[Cell, Cell | None] = {start: None}
    g_score = {start: 0}
    closed: set[Cell] = set()
    while heap:
        _, g, current = heapq.heappop(heap)
        if current in closed:
            continue
        closed.add(current)
        if current == goal:
            return SearchResult("astar", _rebuild(came_from, current), len(closed))
        for nxt in neighbours(problem, current):
            if nxt in closed:
                continue
            tentative = g + 1
            if tentative < g_score.get(nxt, 1 << 62):
                g_score[nxt] = tentative
                came_from[nxt] = current
                heapq.heappush(heap, (tentative + manhattan(nxt, goal), tentative, nxt))
    return SearchResult("astar", None, len(closed))


class LeftHandExplorer(Explorer):
    """The provided right-hand explorer with its two turns swapped.

    Its loop is "turn right, else forward, else left, else back". Swapping turn_right and
    turn_left gives "turn left, else forward, else right, else back", which is the left-hand
    rule, without copying the loop.
    """

    turn_right = Explorer.turn_left
    turn_left = Explorer.turn_right


def _wall_follower(problem: MazeProblem, explorer_cls: type[Explorer], name: str) -> SearchResult:
    maze = SimpleNamespace(
        width=problem.width,
        height=problem.height,
        grid=[list(row) for row in problem.grid],
        start_pos=to_x_y(problem.start),
        end_pos=to_x_y(problem.goal),
    )
    explorer = explorer_cls(maze, visualize=False)
    try:
        _, moves = explorer.solve()
    except ExplorerCycleError:
        visited = {problem.start} | {to_row_col(m) for m in explorer.moves}
        return SearchResult(name, None, len(visited), explorer.backtrack_count)
    path = [problem.start] + [to_row_col(m) for m in moves]
    return SearchResult(name, path, len(set(path)), explorer.backtrack_count)


def right_hand(problem: MazeProblem) -> SearchResult:
    """The course's explorer, unchanged in behaviour (right-hand wall follower)."""
    return _wall_follower(problem, Explorer, "right_hand")


def left_hand(problem: MazeProblem) -> SearchResult:
    """Mirror image of the course's explorer (left-hand wall follower)."""
    return _wall_follower(problem, LeftHandExplorer, "left_hand")


STRATEGIES: dict[str, Callable[[MazeProblem], SearchResult]] = {
    "right_hand": right_hand,
    "left_hand": left_hand,
    "bfs": bfs,
    "astar": astar,
}
STRATEGY_NAMES: tuple[str, ...] = tuple(STRATEGIES)


def solve(problem: MazeProblem, strategy: str) -> SearchResult:
    """Run one strategy and check its path before returning it."""
    try:
        func = STRATEGIES[strategy]
    except KeyError:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {STRATEGY_NAMES}") from None
    result = func(problem)
    if result.path is not None:
        validate_path(problem, result.path)
    return result
