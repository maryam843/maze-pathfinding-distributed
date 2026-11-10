# Design decisions

Each entry: the choice, the alternatives, why this one, and what it costs.

maze.py, explorer.py and constants.py were supplied with the original exercise; BFS, A*, the
left-hand explorer, the parallel runners, tests and benchmarks are the project's own code. "The
earlier version" below means this project before the fixes described here.

## 1. One coordinate convention, converted in one place

The provided `Maze` stores positions as `(x, y)` = `(col, row)`, while grids are indexed
`grid[row][col]`. All the search code uses `(row, col)`, and the only conversion is
`to_row_col()`, called from `MazeProblem.from_maze()`. The alternative was to keep `(x, y)`
everywhere to match the provided code, but the original BFS and A* were already written in
`(row, col)`, and mixing the two is how you end up solving the wrong cell. The earlier version
avoided the problem by pasting its own copy of the grid with its own start and goal, which is
worse: BFS and A* then solved a different maze. The cost is one extra helper and a boundary to remember when handing positions back to
the provided explorer (`to_x_y()` in `_wall_follower`).

## 2. Validate every returned path

`solve()` checks that each path starts at the entrance, ends at the exit, uses only open
cells and moves one 4-neighbour step at a time. The alternative is to trust the algorithm.
This check is what caught a real bug: hypothesis generated a maze where the start cell had
no open neighbour, and the provided explorer's "turn around" step walked through a wall.
The cost is an O(path length) pass per solve, which is included in the backend wall times
(not in the per-strategy search times).

## 3. Left-hand rule by swapping the explorer's two turns

`LeftHandExplorer` subclasses the provided `Explorer` and swaps `turn_right` and
`turn_left`. The loop "try right, else forward, else left, else back" becomes "try left,
else forward, else right, else back". The alternative was copying the 50-line loop with the
turns changed, which would leave two copies of the same logic to keep in sync. The cost is
that the trick is not obvious, so the class docstring explains it and a test checks it on a
maze that is its own mirror image.

## 4. Keep the provided explorer's behaviour, add guards around it

The rebuild did not rewrite the explorer. It only added: lazy `import pygame`, optional printing, a
`max_moves` guard of `4 * width * height`, and a check before the turn-around step. The
explorer's state is (cell, facing), so it has at most 4 x width x height distinct states,
and more moves than that means it is going round a cycle. This bound comes from that
argument, not from tuning. The alternative was a smarter explorer, but then "right-hand
explorer: 1,279 moves" would no longer describe the supplied code. The cost is that its
backtracking stays dead code: `is_stuck()` compares the last three *positions*, and a move
always changes position, so it can never fire. A test shows this, and the README reports 0
backtracks, not the 30 the earlier version reported.

## 5. A* stays as in the earlier version, plus one fix

Heap entries are still `(f, g, cell)`, so ties on `f` go to the smaller `g`. The one change:
a cell already expanded is skipped when an older heap entry for it comes out. Without this,
a cell can be expanded twice and "nodes expanded" overstates the work. Tie-breaking towards
larger `g` (deeper nodes first), which usually expands fewer nodes, was considered and left out
so the comparison is about the original algorithm, not a tuned one. The cost is
probably a few more expansions than necessary.

## 6. What "nodes expanded" means for each strategy

For BFS and A* it is the number of cells taken off the queue or heap. The wall followers
have no queue, so for them it is the number of distinct cells they stood on. The two are
not the same quantity. The alternative was to leave the wall followers blank, but the
distinct-cell count is still a useful "how much of the maze did it see" number. The cost is
possible confusion, so `SearchResult`'s docstring and the README say which is which, and the
nodes-vs-size figure plots only BFS and A*.

## 7. Same maze, different strategy, for every worker

Each parallel job is (maze, strategy): the same maze for all workers and one strategy each.
Every worker returns the fingerprint (SHA-256 prefix) of the maze it solved, and
`check_results()` asserts that all fingerprints match and every strategy appears once. In
the earlier version MPI and multiprocessing ran the same explorer on the same maze (identical results, so
"best explorer" was timing noise), and Celery built a new random maze per task (results not
comparable). The alternative was the same strategy on different seeded mazes, which
measures throughput but gives nothing to compare between workers. The cost: with only four
jobs, the longest one (the right-hand explorer on a big maze) sets the parallel time.

## 8. MPI: rank 0 builds the maze and broadcasts it

Rank 0 loads the maze and `bcast`s it. Ranks take strategies round-robin (`rank::size`),
and rank 0 `gather`s the results. The alternative, every rank building the maze itself,
works for the static maze but relies on every rank using the same seed for a random one.
Broadcasting makes "same maze" true by construction. The cost is one small broadcast (the
300x300 maze is about 90 kB as JSON).

## 9. Celery: the maze travels with the task, JSON only

`solve_task(problem_dict, strategy)` gets the maze as a JSON dict. JSON is the only accepted
serializer (no pickle from the broker). Tasks have `expires` (default 60 s), so tasks queued
while no worker is running are dropped instead of running later for a client that already
gave up. The client pings first and prints a "start the worker first" message instead
of hanging. The alternatives were sending a seed (smaller, but only correct if every worker
builds mazes the same way) or pickle (would allow sending the dataclass directly, but
unpickling broker data is unsafe). The cost is a bigger message.

## 10. Celery: `ResultSet.join()` instead of `.get()` on each result

The first client of the rebuild called `.get()` on each result in turn, like the earlier version. With the
`rpc://` backend some rounds stalled for exactly 1 or 2 s, while the worker log showed all
four tasks finished within about 10 ms. Collecting the results with
`ResultSet(...).join(timeout=...)` removed the stalls: ten rounds in a row took 10-40 ms
each. The exact cause inside kombu was not investigated, so this is a measured workaround,
not an explanation. The cost is that a timeout reports how many results arrived, not which
ones.

## 11. `forkserver` instead of `fork` for the multiprocessing pool

When the process had already talked to Celery, a `fork`-based pool broke the parent's broker
connection ("connection reset by peer" on the next Celery call). It reproduced with fork and
not with forkserver or spawn. The likely mechanism (not proven) is that forked children inherit
the open AMQP socket and Celery's after-fork cleanup closes it from inside the child. So the pool now
uses `forkserver` where it exists (Linux, macOS; Python 3.14's default on Linux) and `spawn`
otherwise (Windows); `MAZE_MP_START_METHOD` overrides. The benchmark also runs the Celery
client in its own process, as a real client would. The cost: pool start-up is slower than
fork (the static-maze multiprocessing total went from about 14 ms with fork in a trial run
to about 69 ms in the saved results), which makes the "parallel is slower for tiny tasks"
result even clearer.

## 12. Timers stop before any display, and results are rewritten, never appended

`timed_solve()` stops `perf_counter` before calling any display callback. The benchmark
never opens a window. Every results file is written fresh. This fixes three bugs of the earlier version: the BFS
time included a 3-second pygame window, every run appended rows to the results file, and a
43 s "time" came from a visualised run. The alternative, timing the whole script,
measures the display. The cost is that the CLI's `--visualize` window is not reflected in
any number, which is the point.

## 13. Timing method: mean ± sample sd of 5 repeats, raw values kept

Five repeats per measurement, reported as mean ± sample standard deviation, with every
backend repeat's raw wall time saved in `results/backends.csv` (`wall_runs_ms`). The
alternatives were a single run (what the earlier version did) or a median of many runs. Five is enough to
show the spread without making the benchmark slow, and keeping the raw values lets anyone
check an outlier. In one full run before the saved one, MPI on the static maze had a mean of
892 ms with sd 740 ms; the saved run's five values are all between 530 and 570 ms. The cost
is that five samples give a rough sd.

## 14. Backend timing: total wall time and, where possible, the work phase

"Total" is what a user waits for: for multiprocessing, pool start + work + shutdown; for MPI,
`mpiexec` launch to exit, measured by the parent; for Celery, submit to last result, with
workers already running. "Work phase" is the part after start-up: `pool.map` for
multiprocessing, and barrier to gather inside the MPI job. The alternative was to report
only one number, which either hides the start-up cost (unfair to sequential) or hides that
the work itself is tiny (unfair to MPI). The cost is two columns to explain.

## 15. The Docker image leaves out mpi4py

The image serves the Celery worker and client only. mpi4py has Linux wheels since 4.1.0, but
using it would also need an MPI library and mpiexec in the image. MPI is tested
directly on the host and in CI instead. The alternative, a multi-stage build with Open MPI,
would make the image several hundred MB larger for a backend that is never used inside it.
The cost is that the containers cannot run the MPI backend.

## 16. Broker login inside docker compose

RabbitMQ only allows the default `guest` user from localhost. Compose mounts a one-line
config (`loopback_users = none`) so the worker and client containers can use
`guest:guest`, and the broker port is not published to the host. The alternative was a
custom user and password in `.env`, which is more secure but adds a secret to manage for a
local demo. The cost: this setup is for a private local network only and must not be exposed
as is.

## 17. Headless by default

matplotlib uses the Agg backend and pygame is imported only inside the functions that open a
window, so tests and CI need no display. The alternative, `SDL_VIDEODRIVER=dummy`
everywhere, would still make pygame a hard import. The cost: `--visualize` fails with a
clear ImportError if pygame is missing, instead of at startup.
