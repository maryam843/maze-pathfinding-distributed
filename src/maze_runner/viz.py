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
    """Mean nodes expanded (+/- 1 sd) against maze size for BFS and A*.

    The wall followers are left out: they keep no queue, so their "nodes" (distinct cells
    stood on) measure something different.
    """
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for s, shift in (("bfs", -0.8), ("astar", 0.8)):
        sel = sorted((r for r in summary if r["strategy"] == s), key=lambda r: r["size"])
        ax.errorbar(
            [r["size"] + shift for r in sel],
            [r["nodes_mean"] for r in sel],
            yerr=[r["nodes_sd"] for r in sel],
            color=COLOURS[s],
            linewidth=2,
            marker="o",
            markersize=6,
            capsize=3,
            label=LABELS[s],
        )
    ax.set_xlabel("maze size (cells per side, 10 seeded mazes each)", color=INK)
    ax.set_ylabel("nodes expanded (mean, +/- 1 sd)", color=INK)
    ax.set_title("Random mazes: nodes expanded by BFS and A*", color=INK, loc="left")
    ax.set_xticks(sorted({r["size"] for r in summary}))
    ax.legend(frameon=False)
    _style(ax)
    return _save(fig, out)


def plot_backends(rows: Sequence[dict], out: Path | str) -> Path:
    """Mean wall time per backend (+/- 1 sd), one bar per maze, log scale."""
    mazes = list(dict.fromkeys(r["maze"] for r in rows))
    backends = list(dict.fromkeys(r["label"] for r in rows))
    colours = ["#2a78d6", "#eb6834"]
    height = 0.8 / len(mazes)
    fig, ax = plt.subplots(figsize=(7.2, 1.2 + 0.8 * len(backends)))
    for i, maze in enumerate(mazes):
        sel = {r["label"]: r for r in rows if r["maze"] == maze}
        ys = [b + (i - (len(mazes) - 1) / 2) * height for b in range(len(backends))]
        present = [(y, sel[lab]) for y, lab in zip(ys, backends, strict=True) if lab in sel]
        means = [r["wall_mean_s"] * 1000 for _, r in present]
        ax.barh(
            [y for y, _ in present],
            means,
            xerr=[r["wall_sd_s"] * 1000 for _, r in present],
            height=height * 0.9,
            color=colours[i % 2],
            capsize=3,
            label=maze,
        )
        for (y, r), m in zip(present, means, strict=True):
            end = m + r["wall_sd_s"] * 1000  # label after the error bar, not on top of it
            ax.annotate(f"{m:.1f} ms", (end, y), xytext=(6, -4), textcoords="offset points",
                        color=INK, fontsize=8)  # fmt: skip
    ax.set_yticks(range(len(backends)), backends)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("wall time for all 4 strategies, ms (log scale, mean of repeats)", color=INK)
    ax.set_title("Sequential vs parallel backends", color=INK, loc="left")
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(right=ax.get_xlim()[1] * 3)
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
