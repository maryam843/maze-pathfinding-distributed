"""T5: every command in the README "How to run" section runs and makes the files it promises.

The commands are read from README.md itself. If a command is added or changed there without
being covered here, test_every_readme_command_is_covered fails. Commands run in a temporary
copy of the repository, so the committed results/ and figures/ are not touched.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import broker_reachable, mpiexec_path

ROOT = Path(__file__).resolve().parents[1]

# command -> files it must create (relative to the repository root)
LOCAL = {
    "python -m maze_runner --maze static": [],
    "python -m maze_runner --maze random --size 50 --seed 3 --strategy astar "
    "--json out/astar_random50.json": ["out/astar_random50.json"],
    "python -m maze_runner.backends.multiproc --maze static": [],
    "python scripts/run_benchmarks.py": [
        "out/results/static_maze.csv", "out/results/random_mazes.csv",
        "out/results/random_summary.csv", "out/results/astar_vs_bfs.csv",
        "out/results/backends.csv", "out/results/backend_moves.csv", "out/results/summary.json",
    ],
    "python scripts/make_figures.py": [
        "out/figures/static_moves.png", "out/figures/nodes_vs_size.png",
        "out/figures/backends.png",
    ],
    "python scripts/make_gif.py": ["out/figures/astar_static.gif"],
}  # fmt: skip
MPI = {
    "mpiexec -n 4 python -m maze_runner.backends.mpi_run --maze static --out out/mpi_static.json": [
        "out/mpi_static.json"
    ],
}
CELERY_WORKER = "celery -A maze_runner.backends.celery_app worker -c 4 --loglevel=info"
CELERY_CLIENT = {
    "python -m maze_runner.backends.celery_client --maze static --out out/celery_static.json": [
        "out/celery_static.json"
    ],
}
# Covered elsewhere: environment setup is the fresh-clone check (T6), the claims check is run
# in CI and in test_scripts.py, pytest would call itself, Docker has its own CI job.
ELSEWHERE = {
    "python -m venv .venv",
    "pip install -r requirements.txt -r requirements-dev.txt",
    "python scripts/check_readme_claims.py",
    "python -m pytest",
    "docker compose -f docker/docker-compose.yml up --build --abort-on-container-exit "
    "--exit-code-from client",
}


def readme_commands() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## How to run", 1)[1].split("\n## ", 1)[0]
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", section, re.S):
        for line in block.splitlines():
            line = line.split("  #", 1)[0].strip()
            if line and not line.startswith(("source ", "#")):
                commands.append(line)
    return commands


def test_every_readme_command_is_covered():
    covered = set(LOCAL) | set(MPI) | set(CELERY_CLIENT) | {CELERY_WORKER} | ELSEWHERE
    assert set(readme_commands()) == covered


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    dest = tmp_path_factory.mktemp("repo")
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()  # fmt: skip
    for name in files:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    for sub in ("results", "figures", "out"):  # prove the commands create them
        shutil.rmtree(dest / sub, ignore_errors=True)
    return dest


def run(cmd: str, cwd: Path, timeout=600) -> subprocess.CompletedProcess:
    args = shlex.split(cmd)
    if args[0] == "python":
        args[0] = sys.executable
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


@pytest.mark.slow
@pytest.mark.parametrize("cmd", list(LOCAL))
def test_local_command(repo_copy, cmd):
    if "make_figures" in cmd:
        run("python scripts/run_benchmarks.py", repo_copy)  # needs results first
    proc = run(cmd, repo_copy)
    assert proc.returncode == 0, proc.stderr[-3000:]
    for name in LOCAL[cmd]:
        assert (repo_copy / name).stat().st_size > 0, name
    assert not (repo_copy / "results").exists() and not (repo_copy / "figures").exists()


@pytest.mark.mpi
@pytest.mark.parametrize("cmd", list(MPI))
def test_mpi_command(need_mpi, repo_copy, cmd):
    flags = os.environ.get("MPIEXEC_FLAGS", "")
    cmd = cmd.replace("mpiexec", f"{mpiexec_path()} {flags}".strip(), 1)
    cmd = cmd.replace(" python ", f" {sys.executable} ", 1)
    proc = run(cmd, repo_copy)
    assert proc.returncode == 0, proc.stderr[-3000:]
    for name in MPI[next(iter(MPI))]:
        assert (repo_copy / name).stat().st_size > 0


@pytest.mark.celery
@pytest.mark.parametrize("cmd", list(CELERY_CLIENT))
def test_celery_commands(need_broker, repo_copy, cmd):
    from maze_runner.backends.celery_client import NoWorkerError, count_workers

    worker = subprocess.Popen(
        [sys.executable, "-m", *shlex.split(CELERY_WORKER)],
        cwd=repo_copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        for _ in range(60):
            try:
                count_workers(timeout=1.0)
                break
            except NoWorkerError:
                time.sleep(0.5)
        proc = run(cmd, repo_copy)
        assert proc.returncode == 0, proc.stderr[-3000:]
        for name in CELERY_CLIENT[cmd]:
            assert (repo_copy / name).stat().st_size > 0
    finally:
        worker.terminate()
        worker.wait(timeout=30)


def test_broker_helper_is_boolean():
    assert broker_reachable() in (True, False)
