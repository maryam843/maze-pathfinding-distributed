"""Regenerate every number in results/ from scratch (files are replaced, never appended).

    python scripts/run_benchmarks.py                      # everything that is available
    python scripts/run_benchmarks.py --backends sequential multiprocessing

Backends that need outside services are recorded as "not run" with the reason instead of
failing: MPI needs `mpiexec` on PATH, Celery needs a broker and a running worker.
Environment: MPIEXEC (default "mpiexec"), MPIEXEC_FLAGS (e.g. "--oversubscribe").
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from maze_runner.backends.common import moves_by_strategy, run_sequential
from maze_runner.backends.multiproc import run_multiprocessing
from maze_runner.benchmark import (
    machine_info,
    mean_sd,
    random_sweep,
    static_benchmark,
    summarise_sweep,
    utc_timestamp,
    write_csv,
    write_json,
)
from maze_runner.strategies import STRATEGY_NAMES, load_problem

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ("sequential", "multiprocessing", "mpi", "celery")


def parse_maze(spec: str):
    """'static' or 'random:SIZE:SEED'."""
    if spec == "static":
        return load_problem("static"), ["--maze", "static"]
    kind, size, seed = spec.split(":")
    if kind != "random":
        raise ValueError(spec)
    return load_problem("random", int(size), int(seed)), [
        "--maze", "random", "--size", size, "--seed", seed,
    ]  # fmt: skip


def mpi_command(np_: int, maze_args: list[str], out: Path) -> list[str]:
    exe = os.environ.get("MPIEXEC", "mpiexec")
    flags = shlex.split(os.environ.get("MPIEXEC_FLAGS", ""))
    return [exe, *flags, "-n", str(np_), sys.executable, "-m", "maze_runner.backends.mpi_run",
            *maze_args, "--out", str(out)]  # fmt: skip


def run_mpi_once(np_: int, maze_args: list[str]) -> dict:
    """Launch mpiexec; total = launch to exit (seen from here), compute = inside the MPI job."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "mpi.json"
        t0 = time.perf_counter()
        proc = subprocess.run(mpi_command(np_, maze_args, out), capture_output=True, text=True)
        total = time.perf_counter() - t0
        if proc.returncode != 0:
            raise RuntimeError(f"mpiexec failed ({proc.returncode}): {proc.stderr[-2000:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    data["wall_total_s"] = total
    return data


class NotAvailable(RuntimeError):
    """A backend that needs an outside service which is not running."""


def run_celery_rounds(repeats: int, maze_args: list[str]) -> list[dict]:
    """Run the Celery client in its own process.

    Keeping broker connections out of this process matters: a fork-based multiprocessing pool
    started later would inherit the open AMQP sockets, and when the children exit the broker
    resets the connection (see docs/DECISIONS.md).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "celery.json"
        cmd = [sys.executable, "-m", "maze_runner.backends.celery_client", *maze_args,
               "--repeats", str(repeats), "--out", str(out)]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 2:
            raise NotAvailable(proc.stderr.strip().removeprefix("error: ").splitlines()[0])
        if proc.returncode != 0:
            raise RuntimeError(f"celery client failed ({proc.returncode}): {proc.stderr[-2000:]}")
        return json.loads(out.read_text(encoding="utf-8"))["runs"]


def backend_rounds(name: str, problem, maze_args, repeats: int, mpi_np: int) -> list[dict]:
    runs = []
    for _ in range(repeats):
        if name == "sequential":
            runs.append(run_sequential(problem))
        elif name == "multiprocessing":
            runs.append(run_multiprocessing(problem))
        elif name == "mpi":
            runs.append(run_mpi_once(mpi_np, maze_args))
        elif name == "celery":
            return run_celery_rounds(repeats, maze_args)
        else:
            raise ValueError(name)
    return runs


def availability(name: str) -> str | None:
    """None if the backend can run here, otherwise the reason it cannot."""
    if name == "mpi" and shutil.which(os.environ.get("MPIEXEC", "mpiexec")) is None:
        return "mpiexec not found on PATH"
    return None


def backend_label(name: str, run: dict, mpi_np: int) -> str:
    if name == "sequential":
        return "sequential (1 process)"
    if name == "multiprocessing":
        return f"multiprocessing ({run['workers']} processes)"
    if name == "mpi":
        return f"MPI (-n {mpi_np})"
    return f"Celery ({(run['workers'] or {}).get('processes', '?')} worker processes)"


def run_backends(args, info: dict) -> tuple[list[dict], list[dict], list[dict]]:
    timing_rows, moves_rows, skipped = [], [], []
    for spec in args.backend_mazes:
        problem, maze_args = parse_maze(spec)
        reference = None
        for name in args.backends:
            reason = availability(name)
            if reason:
                skipped.append({"backend": name, "maze": problem.name, "reason": reason})
                print(f"  {name:<16} {problem.name:<22} NOT RUN: {reason}")
                continue
            try:
                runs = backend_rounds(name, problem, maze_args, args.repeats, args.mpi_np)
            except NotAvailable as exc:
                skipped.append({"backend": name, "maze": problem.name, "reason": str(exc)})
                print(f"  {name:<16} {problem.name:<22} NOT RUN: {exc}")
                continue
            moves = moves_by_strategy(runs[0]["results"])
            for run in runs[1:]:
                if moves_by_strategy(run["results"]) != moves:
                    raise AssertionError(f"{name}: move counts changed between repeats")
            if reference is None:
                reference = moves
            elif moves != reference:
                raise AssertionError(f"{name} disagrees with the first backend: {moves}")
            label = backend_label(name, runs[0], args.mpi_np)
            total_mean, total_sd = mean_sd(r["wall_total_s"] for r in runs)
            row = {
                "maze": problem.name,
                "backend": name,
                "label": label,
                "repeats": len(runs),
                "wall_mean_s": total_mean,
                "wall_sd_s": total_sd,
                "compute_mean_s": None,
                "compute_sd_s": None,
                "wall_runs_ms": " ".join(f"{r['wall_total_s'] * 1000:.1f}" for r in runs),
                "solve_sum_mean_s": mean_sd(
                    sum(x["solve_seconds"] for x in r["results"]) for r in runs
                )[0],
            }
            if "wall_compute_s" in runs[0]:
                row["compute_mean_s"], row["compute_sd_s"] = mean_sd(
                    r["wall_compute_s"] for r in runs
                )
            if name == "multiprocessing":
                info["multiprocessing_start_method"] = runs[0]["start_method"]
            timing_rows.append(row)
            for r in runs[0]["results"]:
                moves_rows.append(
                    {
                        "maze": problem.name,
                        "backend": name,
                        "strategy": r["strategy"],
                        "moves": r["moves"],
                        "nodes_expanded": r["nodes_expanded"],
                        "maze_fingerprint": r["maze_fingerprint"],
                    }
                )
            print(f"  {name:<16} {problem.name:<22} {total_mean * 1000:9.2f} ms (sd "
                  f"{total_sd * 1000:.2f})  moves {moves}")  # fmt: skip
    return timing_rows, moves_rows, skipped


def tool_version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0] if text else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 30, 50, 80])
    parser.add_argument("--seeds", type=int, default=10, help="seeds 0..N-1 per size")
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    parser.add_argument("--backend-mazes", nargs="+", default=["static", "random:300:0"])
    parser.add_argument("--mpi-np", type=int, default=4)
    args = parser.parse_args(argv)

    out = args.out_dir
    info = {
        "generated_utc": utc_timestamp(),
        "command": "python scripts/run_benchmarks.py " + " ".join(argv or sys.argv[1:]),
        "machine": machine_info(),
        "mpiexec": tool_version([os.environ.get("MPIEXEC", "mpiexec"), "--version"]),
        "repeats": args.repeats,
        "random_sizes": args.sizes,
        "random_seeds": list(range(args.seeds)),
        "backend_mazes": args.backend_mazes,
        "strategies": list(STRATEGY_NAMES),
        "timer": "time.perf_counter around the search only; no display during timing",
    }

    print("static maze ...")
    static_rows = static_benchmark(args.repeats)
    for r in static_rows:
        print(f"  {r['strategy']:<11} moves {r['moves']:>5}  nodes {r['nodes_expanded']:>5}  "
              f"{r['time_mean_s'] * 1000:.3f} ms")  # fmt: skip

    print("random mazes ...")
    sweep = random_sweep(args.sizes, range(args.seeds))
    summary, ratios = summarise_sweep(sweep)
    for r in ratios:
        print(f"  size {r['size']:>3}: A*/BFS nodes {r['ratio_mean']:.3f} +/- {r['ratio_sd']:.3f}")

    print("backends ...")
    timing_rows, moves_rows, skipped = run_backends(args, info)

    write_csv(out / "static_maze.csv", static_rows)
    write_csv(out / "random_mazes.csv", sweep)
    write_csv(out / "random_summary.csv", summary)
    write_csv(out / "astar_vs_bfs.csv", ratios)
    write_csv(out / "backends.csv", timing_rows)
    write_csv(out / "backend_moves.csv", moves_rows)
    write_json(
        out / "summary.json",
        {
            "run_info": info,
            "static_maze": static_rows,
            "random_summary": summary,
            "astar_vs_bfs": ratios,
            "backends": timing_rows,
            "backend_moves": moves_rows,
            "backends_not_run": skipped,
        },
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
