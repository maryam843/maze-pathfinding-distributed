"""Run the strategies with MPI: rank 0 builds the maze, broadcasts it, ranks split the strategies.

    mpiexec -n 4 python -m maze_runner.backends.mpi_run --maze static --out results/mpi.json

With 4 ranks each rank solves one strategy; with 2 ranks each solves two. In 2025 every rank
built and solved the same maze with the same explorer (B51), so the ranks had nothing
different to compare. Broadcasting from rank 0 also guarantees they all see the same maze,
even for a random one.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..strategies import STRATEGY_NAMES, MazeProblem, load_problem
from .common import check_results, format_results, solve_job


def strategies_for_rank(rank: int, size: int, strategies=STRATEGY_NAMES) -> list[str]:
    """Round-robin split: rank r gets strategies r, r + size, r + 2*size, ..."""
    return list(strategies)[rank::size]


def run(comm, problem: MazeProblem | None, strategies=STRATEGY_NAMES) -> dict | None:
    """The MPI part. `comm` is an mpi4py communicator (or a stand-in with the same methods).

    Returns the combined result on rank 0 and None on the other ranks.
    """
    rank, size = comm.Get_rank(), comm.Get_size()
    data = comm.bcast(problem.to_dict() if rank == 0 else None, root=0)
    problem = MazeProblem.from_dict(data)
    comm.Barrier()
    t0 = time.perf_counter()
    local = []
    for strategy in strategies_for_rank(rank, size, strategies):
        result = solve_job(problem, strategy)
        result["rank"] = rank
        local.append(result)
    gathered = comm.gather(local, root=0)
    if rank != 0:
        return None
    wall = time.perf_counter() - t0
    results = [r for part in gathered for r in part]
    check_results(problem, results, strategies)
    return {"backend": "mpi", "workers": size, "results": results, "wall_compute_s": wall}


def main(argv: list[str] | None = None, comm=None) -> int:
    parser = argparse.ArgumentParser(description="Solve one maze with each strategy over MPI.")
    parser.add_argument("--maze", choices=["static", "random"], default="static")
    parser.add_argument("--size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="write rank 0's result to this JSON file")
    args = parser.parse_args(argv)
    if comm is None:  # pragma: no cover - the real communicator is used under mpiexec only
        from mpi4py import MPI  # imported here so the package imports without an MPI runtime

        comm = MPI.COMM_WORLD
    problem = load_problem(args.maze, args.size, args.seed) if comm.Get_rank() == 0 else None
    out = run(comm, problem)
    if out is not None:
        print(f"MPI with {out['workers']} ranks, maze {out['results'][0]['maze']}")
        print(format_results(out["results"]))
        print(f"wall time (after start-up): {out['wall_compute_s']:.4f} s")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
