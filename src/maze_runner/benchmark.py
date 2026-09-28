"""Timing and result-writing helpers used by scripts/run_benchmarks.py.

Rules from the 2025 bugs: the timer covers the search only, never a display (B45); every run
writes fresh files instead of appending (B46); timings come from non-visual runs and are
repeated so a mean and standard deviation can be reported (B47).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable, Iterable
from importlib import metadata
from pathlib import Path

from .strategies import STRATEGY_NAMES, MazeProblem, SearchResult, load_problem, solve


def timed_solve(
    problem: MazeProblem,
    strategy: str,
    on_done: Callable[[SearchResult], None] | None = None,
) -> tuple[SearchResult, float]:
    """Solve once and return (result, seconds). The clock stops before on_done (e.g. a display)."""
    t0 = time.perf_counter()
    result = solve(problem, strategy)
    seconds = time.perf_counter() - t0
    if on_done is not None:
        on_done(result)
    return result, seconds


def mean_sd(values: Iterable[float]) -> tuple[float, float]:
    """Mean and sample standard deviation (0.0 when there is a single value)."""
    values = list(values)
    if not values:
        raise ValueError("no values")
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return statistics.fmean(values), sd


def path_sha(path) -> str | None:
    """Short hash of a path, used to check that two runs found exactly the same path."""
    if path is None:
        return None
    return hashlib.sha256(repr([tuple(c) for c in path]).encode()).hexdigest()[:16]


def time_strategy(problem: MazeProblem, strategy: str, repeats: int = 5) -> dict:
    """Run one strategy `repeats` times; results must be identical, timings are summarised."""
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    times, first = [], None
    for _ in range(repeats):
        result, seconds = timed_solve(problem, strategy)
        times.append(seconds)
        if first is None:
            first = result
        elif result.path != first.path:
            raise RuntimeError(f"{strategy} is not deterministic on {problem.name}")
    mean, sd = mean_sd(times)
    return {
        "maze": problem.name,
        "strategy": strategy,
        "moves": first.moves,
        "nodes_expanded": first.nodes_expanded,
        "backtracks": first.backtracks,
        "path_sha": path_sha(first.path),
        "repeats": repeats,
        "time_mean_s": mean,
        "time_sd_s": sd,
    }


def static_benchmark(repeats: int = 5, strategies: Iterable[str] = STRATEGY_NAMES) -> list[dict]:
    problem = load_problem("static")
    return [time_strategy(problem, s, repeats) for s in strategies]


def random_sweep(
    sizes: Iterable[int] = (10, 30, 50, 80),
    seeds: Iterable[int] = range(10),
    strategies: Iterable[str] = STRATEGY_NAMES,
) -> list[dict]:
    """One row per (size, seed, strategy). Seeds make every maze reproducible."""
    rows = []
    strategies = list(strategies)
    for size in sizes:
        for seed in seeds:
            problem = load_problem("random", size, seed)
            for strategy in strategies:
                result = solve(problem, strategy)
                rows.append(
                    {
                        "size": size,
                        "seed": seed,
                        "maze_fingerprint": problem.fingerprint(),
                        "strategy": strategy,
                        "found": result.found,
                        "moves": result.moves,
                        "nodes_expanded": result.nodes_expanded,
                        "path_sha": path_sha(result.path),
                    }
                )
    return rows


def summarise_sweep(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(per size+strategy mean/sd of moves and nodes, per size A*/BFS nodes ratio mean/sd)."""
    summary, ratios = [], []
    sizes = sorted({r["size"] for r in rows})
    strategies = list(dict.fromkeys(r["strategy"] for r in rows))
    for size in sizes:
        for strategy in strategies:
            sel = [r for r in rows if r["size"] == size and r["strategy"] == strategy]
            if not sel:
                continue
            m_mean, m_sd = mean_sd(r["moves"] for r in sel)
            n_mean, n_sd = mean_sd(r["nodes_expanded"] for r in sel)
            summary.append(
                {
                    "size": size,
                    "strategy": strategy,
                    "mazes": len(sel),
                    "moves_mean": m_mean,
                    "moves_sd": m_sd,
                    "nodes_mean": n_mean,
                    "nodes_sd": n_sd,
                }
            )
        by_seed: dict[int, dict[str, int]] = {}
        for r in rows:
            if r["size"] == size and r["strategy"] in ("astar", "bfs"):
                by_seed.setdefault(r["seed"], {})[r["strategy"]] = r["nodes_expanded"]
        per_maze = [v["astar"] / v["bfs"] for v in by_seed.values() if len(v) == 2]
        if per_maze:
            mean, sd = mean_sd(per_maze)
            ratios.append(
                {"size": size, "mazes": len(per_maze), "ratio_mean": mean, "ratio_sd": sd}
            )
    return summary, ratios


def _read_first(path: str, key: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith(key):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _ram_gb() -> float | None:
    if sys.platform.startswith("linux"):
        kb = _read_first("/proc/meminfo", "memtotal")
        return round(int(kb.split()[0]) / 1024**2, 1) if kb else None
    if sys.platform == "win32":  # pragma: no cover - exercised on the Windows CI runner only
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("avail", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong),
                ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_ext", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return round(status.total / 1024**3, 1)
    return None  # pragma: no cover


def machine_info() -> dict:
    """CPU, cores, RAM, OS, Python and library versions. No hostname or user name on purpose."""
    cpu = _read_first("/proc/cpuinfo", "model name") or platform.processor() or None
    versions = {}
    for dist in ("celery", "kombu", "mpi4py", "pygame", "matplotlib", "pillow"):
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = None
    return {
        "cpu_model": cpu,
        "logical_cores": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "libraries": versions,
    }


def utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def write_csv(path: Path | str, rows: list[dict]) -> Path:
    """Write rows to a new CSV, replacing any old file (never appends)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_json(path: Path | str, data) -> Path:
    """Write JSON to a new file, replacing any old file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
