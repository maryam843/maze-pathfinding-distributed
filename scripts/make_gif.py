"""Animate the A* path on the static maze (frames drawn from code, not a screen recording).

The GIF goes to OUT_DIR/figures/astar_static.gif, by default out/figures/. `--out-dir .`
replaces the committed figures/astar_static.gif. `--out` names the file directly.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from maze_runner.strategies import load_problem, solve
from maze_runner.viz import make_gif

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "out", help="the GIF goes to OUT_DIR/figures"
    )
    parser.add_argument("--out", type=Path, help="GIF file (overrides --out-dir)")
    parser.add_argument("--strategy", default="astar")
    args = parser.parse_args(argv)
    problem = load_problem("static")
    result = solve(problem, args.strategy)
    out = make_gif(problem, result.path, args.out or args.out_dir / "figures" / "astar_static.gif")
    print(f"wrote {out} ({result.moves} moves, {out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
