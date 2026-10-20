"""Check that every results table in README.md matches a results folder.

Tables sit between markers such as <!-- claims:static --> and <!-- /claims -->. For each one
this script rebuilds the table from DIR/summary.json and compares it with the README.

Against the committed results/ (the default) every cell must match exactly. Against any other
folder, such as the out/results/ that run_benchmarks.py writes by default, move and node counts
must still match exactly, but timings depend on the machine: timing differences, and backends
that could not run there, are printed as info and do not fail the check.

    python scripts/check_readme_claims.py                      # committed results (exact)
    python scripts/check_readme_claims.py --results out/results
    python scripts/check_readme_claims.py --print              # print the expected tables
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"right_hand": "right-hand", "left_hand": "left-hand", "bfs": "BFS", "astar": "A*"}
BLOCK = re.compile(r"<!-- claims:(\w+) -->\n(.*?)<!-- /claims -->", re.S)


def _ms(mean: float, sd: float) -> str:
    return f"{mean * 1000:.2f} ± {sd * 1000:.2f}"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return lines + ["| " + " | ".join(r) + " |" for r in rows]


def expected_tables(data: dict) -> dict[str, list[str]]:
    static = {r["strategy"]: r for r in data["static_maze"]}
    right, best = static["right_hand"]["moves"], static["astar"]["moves"]
    out = {}
    out["headline"] = table(
        ["Static maze", "Moves"],
        [
            ["Right-hand explorer (provided)", f"{right:,}"],
            ["BFS (mine, fixed)", f"{static['bfs']['moves']:,}"],
            ["A* (mine, fixed)", f"{best:,}"],
            ["Reduction vs right-hand", f"{(right - best) / right:.1%}"],
        ],
    )
    reps = data["run_info"]["repeats"]
    out["static"] = table(
        ["Strategy", "Moves", "Nodes expanded", "Backtracks", f"Time ms (mean ± sd, {reps} runs)"],
        [
            [
                NAMES[r["strategy"]],
                f"{r['moves']:,}",
                f"{r['nodes_expanded']:,}",
                "-" if r["backtracks"] is None else str(r["backtracks"]),
                _ms(r["time_mean_s"], r["time_sd_s"]),
            ]
            for r in data["static_maze"]
        ],
    )
    out["random"] = table(
        ["Size", "Strategy", "Moves (mean ± sd)", "Nodes expanded (mean ± sd)"],
        [
            [
                str(r["size"]),
                NAMES[r["strategy"]],
                f"{r['moves_mean']:.1f} ± {r['moves_sd']:.1f}",
                f"{r['nodes_mean']:.1f} ± {r['nodes_sd']:.1f}",
            ]
            for r in data["random_summary"]
        ],
    )
    out["ratio"] = table(
        ["Size", "Mazes", "A* nodes / BFS nodes (mean ± sd)"],
        [
            [str(r["size"]), str(r["mazes"]), f"{r['ratio_mean']:.3f} ± {r['ratio_sd']:.3f}"]
            for r in data["astar_vs_bfs"]
        ],
    )
    rows = []
    for r in data["backends"]:
        compute = (
            "-" if r["compute_mean_s"] is None else _ms(r["compute_mean_s"], r["compute_sd_s"])
        )
        rows.append(
            [
                r["maze"],
                r["label"],
                _ms(r["wall_mean_s"], r["wall_sd_s"]),
                compute,
                str(r["repeats"]),
            ]  # fmt: skip
        )
    for r in data.get("backends_not_run", []):
        rows.append([r["maze"], r["backend"], "not run", "-", "0"])
    out["backends"] = table(
        ["Maze", "Backend", "Total wall ms (mean ± sd)", "Work phase only ms", "Repeats"], rows
    )
    moves = {}
    for r in data["backend_moves"]:
        moves.setdefault((r["maze"], r["strategy"]), {})[r["backend"]] = r["moves"]
    backends = list(dict.fromkeys(r["backend"] for r in data["backend_moves"]))
    out["backend_moves"] = table(
        ["Maze", "Strategy", *backends],
        [[maze, NAMES[s], *(f"{v[b]:,}" for b in backends)] for (maze, s), v in moves.items()],
    )
    return out


# Column index of the timing cell in tables that mix counts and timings.
TIMING_COLUMN = {"static": 4}
# Every cell of this table is a wall time, or a label or repeat count that depends on the machine.
TIMING_TABLES = {"backends"}


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def compare_lines(kind: str, got: list[str], want: list[str]) -> list[str]:
    problems = []
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else "<missing>"
        w = want[i] if i < len(want) else "<extra line>"
        if g != w:
            problems.append(f"[{kind}] line {i + 1}: README has {g!r}, results say {w!r}")
    return problems


def compare_timing_column(kind: str, got: list[str], want: list[str]) -> tuple[list, list]:
    """Exact on every cell except the timing column, whose differences are info."""
    if len(got) != len(want):
        return compare_lines(kind, got, want), []
    problems, notes, col = [], [], TIMING_COLUMN[kind]
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        gc, wc = cells(g), cells(w)
        if len(gc) != len(wc) or gc[:col] + gc[col + 1 :] != wc[:col] + wc[col + 1 :]:
            problems.append(f"[{kind}] line {i + 1}: README has {g!r}, results say {w!r}")
        elif gc[col] != wc[col]:
            notes.append(f"[{kind}] {gc[0]}: README {gc[col]!r}, these results {wc[col]!r}")
    return problems, notes


def compare_backend_moves(got: list[str], want: list[str]) -> tuple[list, list]:
    """Move counts must match for every backend that ran; a backend that did not run is info."""
    if len(got) < 2 or len(want) < 2:
        return compare_lines("backend_moves", got, want), []
    problems, notes = [], []
    got_head, want_head = cells(got[0]), cells(want[0])
    want_rows = {tuple(cells(w)[:2]): cells(w) for w in want[2:]}
    for name in got_head[2:]:
        if name not in want_head:
            notes.append(f"[backend_moves] {name}: not run in these results")
    for i, g in enumerate(got[2:], start=3):
        gc = cells(g)
        wc = want_rows.pop(tuple(gc[:2]), None)
        if wc is None:
            problems.append(f"[backend_moves] line {i}: README row {g!r} is not in the results")
            continue
        for name, value in zip(got_head[2:], gc[2:], strict=False):
            if name in want_head and wc[want_head.index(name)] != value:
                problems.append(
                    f"[backend_moves] line {i}: {name} README has {value!r}, "
                    f"results say {wc[want_head.index(name)]!r}"
                )
    for key in want_rows:
        problems.append(f"[backend_moves] results row {' | '.join(key)!r} is not in the README")
    return problems, notes


def compare(readme: str, data: dict, exact: bool = True) -> tuple[list[str], list[str]]:
    """Return (mismatches, info notes). exact=False lets timings differ (see module docstring)."""
    expected = expected_tables(data)
    problems, notes, seen = [], [], set()
    for kind, body in BLOCK.findall(readme):
        seen.add(kind)
        if kind not in expected:
            problems.append(f"unknown claims block {kind!r}")
            continue
        got = [line.strip() for line in body.strip().splitlines()]
        want = expected[kind]
        if got == want:
            continue
        if exact:
            problems += compare_lines(kind, got, want)
        elif kind in TIMING_TABLES:
            notes += compare_lines(kind, got, want)
        elif kind in TIMING_COLUMN:
            p, n = compare_timing_column(kind, got, want)
            problems, notes = problems + p, notes + n
        elif kind == "backend_moves":
            p, n = compare_backend_moves(got, want)
            problems, notes = problems + p, notes + n
        else:
            problems += compare_lines(kind, got, want)
    for kind in expected:
        if kind not in seen:
            problems.append(f"README has no <!-- claims:{kind} --> table")
    return problems, notes


def check(readme: str, data: dict) -> list[str]:
    """Exact check: every cell must match."""
    return compare(readme, data, exact=True)[0]


def results_file(path: Path) -> Path:
    return path / "summary.json" if path.is_dir() else path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check README numbers against a results folder.")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument(
        "--results",
        type=Path,
        default=ROOT / "results",
        help="results folder (or its summary.json); exact check only for the committed results/",
    )
    parser.add_argument("--print", action="store_true", help="print the expected tables")
    args = parser.parse_args(argv)
    path = results_file(args.results)
    data = json.loads(path.read_text(encoding="utf-8"))
    if args.print:
        for kind, lines in expected_tables(data).items():
            print(f"<!-- claims:{kind} -->\n" + "\n".join(lines) + "\n<!-- /claims -->\n")
        return 0
    exact = path.resolve() == (ROOT / "results" / "summary.json").resolve()
    readme = args.readme.read_text(encoding="utf-8")
    problems, notes = compare(readme, data, exact=exact)
    for note in notes:
        print(f"info: {note}")
    for p in problems:
        print(p, file=sys.stderr)
    n = len(BLOCK.findall(readme))
    if exact:
        print(f"{n} README tables checked, {len(problems)} mismatches")
    else:
        print(
            f"{n} README tables checked against {args.results}, {len(problems)} mismatches in "
            f"moves and nodes, {len(notes)} timing differences (info only)"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
