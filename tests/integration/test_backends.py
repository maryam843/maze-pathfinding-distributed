"""Integration: real processes, real MPI ranks, real Celery workers on a real broker.

The key assertion: every backend returns the SAME move count for each strategy, because every
worker solves the same maze (checked by fingerprint) with a different strategy.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import shlex
import subprocess
import sys
import time

import pytest
from conftest import mpiexec_path

from maze_runner.backends.common import moves_by_strategy, run_sequential
from maze_runner.backends.multiproc import pick_start_method, run_multiprocessing
from maze_runner.strategies import load_problem

MAZES = [("static", ["--maze", "static"]),
         ("random", ["--maze", "random", "--size", "25", "--seed", "4"])]  # fmt: skip


_BARRIER = None


def _set_barrier(barrier):
    global _BARRIER
    _BARRIER = barrier


def _meet_at_barrier(_):
    # Returns only when two jobs are inside the pool at the same moment. A worker that took one
    # job is blocked here, so the other job must be running in a second process.
    _BARRIER.wait(timeout=120)
    return os.getpid()


def assert_pool_runs_two_jobs_at_once(method):
    """Deterministic concurrency check for a pool made with this start method.

    Not timing-based: it passes only if two pool processes run at the same time, and fails
    (BrokenBarrierError) only if a second worker cannot start within 120 s.
    """
    ctx = mp.get_context(pick_start_method(method))
    barrier = ctx.Barrier(2)
    with ctx.Pool(2, initializer=_set_barrier, initargs=(barrier,)) as pool:
        pids = pool.map(_meet_at_barrier, range(2), chunksize=1)
    assert len(set(pids)) == 2 and os.getpid() not in pids


def problem_for(kind):
    return load_problem("static") if kind == "static" else load_problem("random", 25, 4)


def expected(kind):
    return moves_by_strategy(run_sequential(problem_for(kind))["results"])


@pytest.mark.parametrize("kind, _", MAZES)
@pytest.mark.parametrize("method", [*mp.get_all_start_methods(), None])
def test_multiprocessing_matches_sequential(kind, _, method):
    run = run_multiprocessing(problem_for(kind), start_method=method)
    assert moves_by_strategy(run["results"]) == expected(kind)
    # The work ran in pool processes, not in this one. (How the 4 jobs spread over the pool is
    # up to Pool: with spawn, one fast-starting child can take all of them, so that is not
    # asserted. Real concurrency is checked separately with a barrier.)
    assert all(r["pid"] != os.getpid() for r in run["results"])
    assert_pool_runs_two_jobs_at_once(method)
    assert run["wall_total_s"] >= run["wall_compute_s"] > 0


def test_multiprocessing_module_main(capsys):
    from maze_runner.backends import multiproc

    assert multiproc.main(["--maze", "random", "--size", "12", "--seed", "1"]) == 0
    assert "random-12-seed1" in capsys.readouterr().out


@pytest.mark.mpi
@pytest.mark.parametrize("kind, maze_args", MAZES)
@pytest.mark.parametrize("ranks", [2, 4])
def test_mpi_matches_sequential(need_mpi, tmp_path, kind, maze_args, ranks):
    out = tmp_path / "mpi.json"
    flags = shlex.split(os.environ.get("MPIEXEC_FLAGS", ""))
    cmd = [mpiexec_path(), *flags, "-n", str(ranks), sys.executable, "-m",
           "maze_runner.backends.mpi_run", *maze_args, "--out", str(out)]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    data = json.loads(out.read_text())
    assert data["workers"] == ranks
    assert sorted({r["rank"] for r in data["results"]}) == list(range(ranks))
    assert moves_by_strategy(data["results"]) == expected(kind)


@pytest.mark.celery
def test_celery_client_broker_up_but_no_worker(need_broker):
    """Runs before the module's worker starts: clear 'start the worker first' message, exit 2."""
    from maze_runner.backends.celery_client import NoWorkerError, count_workers

    try:
        count_workers(timeout=1.0)
        pytest.skip("another Celery worker is already running on this broker")
    except NoWorkerError:
        pass
    proc = subprocess.run(
        [sys.executable, "-m", "maze_runner.backends.celery_client"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 2
    assert "No Celery worker answered" in proc.stderr and "worker first" in proc.stderr


def test_celery_client_broker_unreachable():
    """Nothing listens on port 1: the client says so and exits with code 2, no traceback."""
    env = dict(os.environ, CELERY_BROKER_URL="pyamqp://guest@localhost:1//")
    proc = subprocess.run(
        [sys.executable, "-m", "maze_runner.backends.celery_client"],
        capture_output=True, text=True, timeout=120, env=env,
    )  # fmt: skip
    assert proc.returncode == 2
    assert "Cannot reach the broker" in proc.stderr and "Traceback" not in proc.stderr


@pytest.fixture(scope="module")
def celery_worker():
    """Start one worker node with 4 processes for this module, stop it afterwards."""
    from conftest import broker_reachable

    if sys.platform == "win32" or not broker_reachable():
        pytest.skip("needs a RabbitMQ broker (Linux CI service container or local)")
    cmd = [sys.executable, "-m", "celery", "-A", "maze_runner.backends.celery_app", "worker",
           "-c", "4", "--loglevel=warning", "--without-gossip", "--without-mingle"]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from maze_runner.backends.celery_client import NoWorkerError, count_workers

    try:
        for _ in range(60):
            try:
                count_workers(timeout=1.0)
                break
            except NoWorkerError:
                time.sleep(0.5)
        else:
            pytest.fail("Celery worker did not start")
        yield proc
    finally:
        proc.terminate()
        proc.wait(timeout=30)


@pytest.mark.celery
@pytest.mark.parametrize("kind, maze_args", MAZES)
def test_celery_matches_sequential(need_broker, celery_worker, tmp_path, kind, maze_args):
    # The client runs in its own process, as a user would run it.
    out = tmp_path / "celery.json"
    cmd = [sys.executable, "-m", "maze_runner.backends.celery_client", *maze_args,
           "--repeats", "2", "--out", str(out)]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-3000:]
    runs = json.loads(out.read_text())["runs"]
    assert runs[0]["workers"]["processes"] >= 1
    for run in runs:
        assert moves_by_strategy(run["results"]) == expected(kind)
        assert len({r["maze_fingerprint"] for r in run["results"]}) == 1


@pytest.mark.mpi
@pytest.mark.celery
def test_all_three_backends_identical_moves(need_mpi, need_broker, celery_worker, tmp_path):
    """The headline check: sequential, multiprocessing, MPI and Celery give identical moves."""
    from maze_runner.backends.celery_client import run_celery

    kind, maze_args = MAZES[0]
    ref = expected(kind)
    mp_moves = moves_by_strategy(run_multiprocessing(problem_for(kind))["results"])
    out = tmp_path / "mpi.json"
    flags = shlex.split(os.environ.get("MPIEXEC_FLAGS", ""))
    subprocess.run([mpiexec_path(), *flags, "-n", "4", sys.executable, "-m",
                    "maze_runner.backends.mpi_run", *maze_args, "--out", str(out)],
                   check=True, capture_output=True, timeout=120)  # fmt: skip
    mpi_moves = moves_by_strategy(json.loads(out.read_text())["results"])
    celery_moves = moves_by_strategy(run_celery(problem_for(kind))["results"])
    assert ref == mp_moves == mpi_moves == celery_moves
