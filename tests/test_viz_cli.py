"""Tests for figures, the GIF, the pygame viewer (headless) and the command line."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from PIL import Image

from maze_runner import cli, viz
from maze_runner.benchmark import random_sweep, static_benchmark, summarise_sweep
from maze_runner.strategies import load_problem, solve


def test_figures(tmp_path):
    static = static_benchmark(repeats=1)
    summary, _ = summarise_sweep(random_sweep((10, 20), range(2)))
    backends = [
        {"maze": m, "label": b, "wall_mean_s": t, "wall_sd_s": t / 10}
        for m in ("static", "random-300-seed0")
        for b, t in (("sequential", 0.007), ("MPI (-n 4)", 0.5))
    ]
    for path in (
        viz.plot_static_moves(static, tmp_path / "a.png"),
        viz.plot_nodes_vs_size(summary, tmp_path / "b.png"),
        viz.plot_backends(backends, tmp_path / "c.png"),
    ):
        with Image.open(path) as img:
            assert img.size[0] > 500
            assert round(img.info["dpi"][0]) == viz.DPI


def test_maze_image_colours():
    p = load_problem("static")
    path = solve(p, "astar").path
    img = viz.maze_image(p, path, scale=1)
    assert img.size == (p.width, p.height)
    assert img.getpixel((p.start[1], p.start[0])) == (42, 120, 214)
    assert img.getpixel((p.goal[1], p.goal[0])) == (235, 104, 52)
    assert img.getpixel((0, 0)) == (40, 40, 40)


def test_make_gif(tmp_path):
    p = load_problem("static")
    out = viz.make_gif(p, solve(p, "astar").path, tmp_path / "a.gif", step=16, hold_frames=2)
    with Image.open(out) as gif:
        # 8 drawing frames; Pillow merges the identical hold frames into one longer last frame
        assert gif.n_frames == len(range(1, 128 + 1, 16)) + 1
        gif.seek(gif.n_frames - 1)
        assert gif.info["duration"] >= 2 * 60


def test_show_pygame_headless():
    pytest.importorskip("pygame")
    p = load_problem("random", 10, 0)
    viz.show_pygame(p, solve(p, "bfs").path, seconds=0)


def test_cli_in_process(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert cli.main(["--maze", "static", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "1279" in text and "127" in text
    data = json.loads(out.read_text())
    assert [r["moves"] for r in data["results"]] == [1279, 1201, 127, 127]


def test_cli_random_single_strategy(capsys):
    assert cli.main(["--maze", "random", "--size", "20", "--seed", "3", "--strategy", "bfs"]) == 0
    assert "random-20-seed3" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--maze", "random", "--size", "3"])


@pytest.mark.parametrize(
    "args, expect",
    [
        (["--help"], "--strategy"),
        (["--strategy", "astar"], "astar"),
        (["--maze", "random", "--size", "15", "--seed", "2"], "random-15-seed2"),
    ],
)
def test_cli_as_module(args, expect):
    proc = subprocess.run(
        [sys.executable, "-m", "maze_runner", *args], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert expect in proc.stdout
