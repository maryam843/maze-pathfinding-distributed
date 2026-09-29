"""Check that every results table in README.md matches results/summary.json exactly.

Tables sit between markers such as <!-- claims:static --> and <!-- /claims -->. For each one
this script rebuilds the table from the results file and compares the text row by row, so
any number that drifts from the saved results fails the check.

    python scripts/check_readme_claims.py            # check (exit 1 on any mismatch)
    python scripts/check_readme_claims.py --print    # print the expected tables
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


def check(readme: str, data: dict) -> list[str]:
    expected = expected_tables(data)
    problems, seen = [], set()
    for kind, body in BLOCK.findall(readme):
        seen.add(kind)
        if kind not in expected:
            problems.append(f"unknown claims block {kind!r}")
            continue
        got = [line.strip() for line in body.strip().splitlines()]
        want = expected[kind]
        if got != want:
            for i in range(max(len(got), len(want))):
                g = got[i] if i < len(got) else "<missing>"
                w = want[i] if i < len(want) else "<extra line>"
                if g != w:
                    problems.append(f"[{kind}] line {i + 1}: README has {g!r}, results say {w!r}")
    for kind in expected:
        if kind not in seen:
            problems.append(f"README has no <!-- claims:{kind} --> table")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check README numbers against results/.")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--results", type=Path, default=ROOT / "results" / "summary.json")
    parser.add_argument("--print", action="store_true", help="print the expected tables")
    args = parser.parse_args(argv)
    data = json.loads(args.results.read_text(encoding="utf-8"))
    if args.print:
        for kind, lines in expected_tables(data).items():
            print(f"<!-- claims:{kind} -->\n" + "\n".join(lines) + "\n<!-- /claims -->\n")
        return 0
    problems = check(args.readme.read_text(encoding="utf-8"), data)
    for p in problems:
        print(p, file=sys.stderr)
    n = len(BLOCK.findall(args.readme.read_text(encoding="utf-8")))
    print(f"{n} README tables checked, {len(problems)} mismatches")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
