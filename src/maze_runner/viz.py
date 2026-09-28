"""Figures and the path animation, all drawn from data (no screen recordings).

matplotlib runs on the non-interactive Agg backend, and pygame is imported only inside
show_pygame(), so everything else works on a headless machine or CI runner (2025 bug B53).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

from .strategies import Cell, MazeProblem  # noqa: E402

DPI = 150
# Fixed order, one colour per strategy everywhere (checked for colour-blind separation).
COLOURS = {
    "right_hand": "#2a78d6",
    "left_hand": "#eb6834",
    "bfs": "#1baf7a",
    "astar": "#eda100",
}
LABELS = {"right_hand": "right-hand", "left_hand": "left-hand", "bfs": "BFS", "astar": "A*"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(MUTED)
    ax.tick_params(colors=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig, out: Path | str) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return out


def plot_static_moves(rows: Sequence[dict], out: Path | str) -> Path:
    """Bar chart of moves per strategy on the static maze, log scale, values labelled."""
    names = [r["strategy"] for r in rows]
    moves = [r["moves"] for r in rows]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    bars = ax.bar([LABELS[n] for n in names], moves, color=[COLOURS[n] for n in names], width=0.6)
    ax.set_yscale("log")
    ax.set_ylabel("moves to reach the exit (log scale)", color=INK)
    ax.set_title("Static maze: moves per strategy", color=INK, loc="left")
    for bar, value in zip(bars, moves, strict=True):
        ax.annotate(
            f"{value:,}",
            (bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            color=INK,
        )
    ax.set_ylim(top=max(moves) * 3)
    _style(ax)
    return _save(fig, out)


def plot_nodes_vs_size(summary: Sequence[dict], out: Path | str) -> Path:
    """Mean nodes expanded (with +/- 1 sd bars) against maze size, one line per strategy."""
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    strategies = list(dict.fromkeys(r["strategy"] for r in summary))
    for s in strategies:
        sel = sorted((r for r in summary if r["strategy"] == s), key=lambda r: r["size"])
        xs = [r["size"] for r in sel]
        ax.errorbar(
            xs,
            [r["nodes_mean"] for r in sel],
            yerr=[r["nodes_sd"] for r in sel],
            color=COLOURS[s],
            linewidth=2,
            marker="o",
            markersize=6,
            capsize=3,
            label=LABELS[s],
        )
    ax.set_xlabel("maze size (cells per side)", color=INK)
    ax.set_ylabel("nodes expanded (mean of 10 seeds)", color=INK)
    ax.set_title("Random mazes: search effort grows with size", color=INK, loc="left")
    ax.set_xticks(sorted({r["size"] for r in summary}))
    ax.legend(frameon=False)
    _style(ax)
    return _save(fig, out)


def plot_backends(rows: Sequence[dict], out: Path | str) -> Path:
    """Horizontal bars: mean wall time per backend (+/- 1 sd), one panel per maze."""
    mazes = list(dict.fromkeys(r["maze"] for r in rows))
    fig, axes = plt.subplots(1, len(mazes), figsize=(6.8, 0.9 + 0.55 * 5), squeeze=False)
    for ax, maze in zip(axes[0], mazes, strict=True):
        sel = [r for r in rows if r["maze"] == maze]
        labels = [r["label"] for r in sel]
        means = [r["wall_mean_s"] * 1000 for r in sel]
        sds = [r["wall_sd_s"] * 1000 for r in sel]
        ys = range(len(sel))
        ax.barh(ys, means, xerr=sds, color="#2a78d6", height=0.6, capsize=3)
        ax.set_yticks(list(ys), labels)
        ax.invert_yaxis()
        ax.set_xscale("log")
        ax.set_xlabel("wall time, ms (log scale)", color=INK)
        ax.set_title(maze, color=INK, loc="left")
        for y, m in zip(ys, means, strict=True):
            ax.annotate(f"{m:.1f}", (m, y), xytext=(4, -9), textcoords="offset points", color=INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=MUTED)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    fig.suptitle("Running the 4 strategies: sequential vs parallel", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)


def maze_image(problem: MazeProblem, path: Sequence[Cell] = (), scale: int = 8) -> Image.Image:
    """Walls dark, open cells white, path cells yellow, start blue, goal orange."""
    img = Image.new("RGB", (problem.width, problem.height), (255, 255, 255))
    px = img.load()
    for r, row in enumerate(problem.grid):
        for c, v in enumerate(row):
            if v:
                px[c, r] = (40, 40, 40)
    for r, c in path:
        px[c, r] = (237, 161, 0)
    px[problem.start[1], problem.start[0]] = (42, 120, 214)
    px[problem.goal[1], problem.goal[0]] = (235, 104, 52)
    return img.resize((problem.width * scale, problem.height * scale), Image.NEAREST)


def make_gif(
    problem: MazeProblem,
    path: Sequence[Cell],
    out: Path | str,
    step: int = 2,
    frame_ms: int = 60,
    hold_frames: int = 20,
) -> Path:
    """Animate the path being drawn, `step` cells per frame, then hold the last frame."""
    frames = [maze_image(problem, path[:i]) for i in range(1, len(path) + 1, step)]
    frames += [maze_image(problem, path)] * hold_frames
    frames = [f.convert("P", palette=Image.ADAPTIVE, colors=8) for f in frames]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out, save_all=True, append_images=frames[1:], duration=frame_ms, loop=0, optimize=True
    )
    return out


def show_pygame(problem: MazeProblem, path: Sequence[Cell], seconds: float = 3.0) -> None:
    """Open a window with the maze and the path. Called only after timing has stopped (B45)."""
    import pygame  # lazy: only needed when a window is asked for

    img = maze_image(problem, path, scale=12)
    pygame.init()
    try:
        screen = pygame.display.set_mode(img.size)
        pygame.display.set_caption(f"{problem.name}: {len(path) - 1} moves")
        surface = pygame.image.fromstring(img.tobytes(), img.size, "RGB")
        screen.blit(surface, (0, 0))
        pygame.display.flip()
        pygame.time.wait(int(seconds * 1000))
    finally:
        pygame.quit()
