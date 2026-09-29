"""Draw the three result figures from results/summary.json into figures/ (dpi 150)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maze_runner.viz import plot_backends, plot_nodes_vs_size, plot_static_moves

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results" / "summary.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "figures")
    args = parser.parse_args(argv)
    data = json.loads(args.results.read_text(encoding="utf-8"))
    written = [
        plot_static_moves(data["static_maze"], args.out_dir / "static_moves.png"),
        plot_nodes_vs_size(data["random_summary"], args.out_dir / "nodes_vs_size.png"),
        plot_backends(data["backends"], args.out_dir / "backends.png"),
    ]
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
