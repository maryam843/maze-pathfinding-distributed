"""Command line: solve a maze with one strategy or all four.

python -m maze_runner --maze static --strategy all
python -m maze_runner --maze random --size 50 --seed 3 --strategy astar --json out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import timed_solve
from .strategies import STRATEGY_NAMES, load_problem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m maze_runner",
        description="Solve the static maze or a seeded random maze.",
    )
    parser.add_argument("--maze", choices=["static", "random"], default="static")
    parser.add_argument("--size", type=int, default=30, help="random maze width and height")
    parser.add_argument("--seed", type=int, default=0, help="random maze seed")
    parser.add_argument(
        "--strategy", choices=[*STRATEGY_NAMES, "all"], default="all", help="default: all"
    )
    parser.add_argument("--json", type=Path, help="also write the results to this JSON file")
    parser.add_argument(
        "--visualize", action="store_true", help="show the last path in a pygame window"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.maze == "random" and args.size < 5:
        raise SystemExit("error: --size must be at least 5")
    problem = load_problem(args.maze, args.size, args.seed)
    names = STRATEGY_NAMES if args.strategy == "all" else (args.strategy,)
    print(
        f"maze {problem.name}: {problem.height} rows x {problem.width} cols, "
        f"start {problem.start}, exit {problem.goal} (row, col)"
    )
    print(f"{'strategy':<11} {'moves':>6} {'nodes':>6} {'backtracks':>10} {'time ms':>8}")
    rows, last = [], None
    for name in names:
        result, seconds = timed_solve(problem, name)
        last = result
        row = result.to_dict() | {"time_s": seconds}
        rows.append(row)
        moves = "no path" if result.moves is None else result.moves
        backtracks = "-" if result.backtracks is None else result.backtracks
        print(
            f"{name:<11} {moves:>6} {result.nodes_expanded:>6} {backtracks:>10} "
            f"{seconds * 1000:>8.3f}"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"maze": problem.name, "fingerprint": problem.fingerprint(), "results": rows}
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.visualize and last is not None and last.path:  # pragma: no cover - opens a window
        from .viz import show_pygame

        show_pygame(problem, last.path)
    return 0
