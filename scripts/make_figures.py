"""Draw the three result figures (dpi 150) from OUT_DIR/results into OUT_DIR/figures.

OUT_DIR defaults to out/, the folder run_benchmarks.py writes to. `--out-dir .` reads
results/summary.json and replaces the committed figures/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maze_runner.viz import plot_backends, plot_nodes_vs_size, plot_static_moves

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "out", help="figures go to OUT_DIR/figures"
    )
    parser.add_argument(
        "--results", type=Path, help="summary.json to draw (default OUT_DIR/results/summary.json)"
    )
    args = parser.parse_args(argv)
    results = args.results or args.out_dir / "results" / "summary.json"
    if not results.exists():
        parser.error(f"{results} not found: run scripts/run_benchmarks.py first or pass --results")
    data = json.loads(results.read_text(encoding="utf-8"))
    figures = args.out_dir / "figures"
    written = [
        plot_static_moves(data["static_maze"], figures / "static_moves.png"),
        plot_nodes_vs_size(data["random_summary"], figures / "nodes_vs_size.png"),
        plot_backends(data["backends"], figures / "backends.png"),
    ]
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
