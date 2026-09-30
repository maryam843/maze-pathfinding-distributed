"""In-process tests of the backend code (the real multi-process runs are in integration/)."""

from __future__ import annotations

import json

import pytest
from celery.exceptions import TimeoutError as CeleryTimeoutError

from maze_runner.backends import celery_client, common, mpi_run
from maze_runner.backends.celery_app import app
from maze_runner.backends.celery_tasks import solve_task
from maze_runner.strategies import STRATEGY_NAMES, load_problem

STATIC = load_problem("static")


def test_plan_jobs_same_maze_different_strategies():
    jobs = common.plan_jobs(STATIC)
    assert len({p.fingerprint() for p, _ in jobs}) == 1
    assert [s for _, s in jobs] == list(STRATEGY_NAMES)
    with pytest.raises(ValueError):
        common.plan_jobs(STATIC, ["bfs", "bfs"])


def test_solve_job_shape():
    r = common.solve_job(STATIC, "bfs")
    assert r["moves"] == 127 and r["maze_fingerprint"] == STATIC.fingerprint()
    assert {"solve_seconds", "pid", "nodes_expanded", "backtracks"} <= set(r)


def test_check_results_catches_wrong_maze_and_missing_strategy():
    results = [common.solve_job(STATIC, s) for s in STRATEGY_NAMES]
    common.check_results(STATIC, results, STRATEGY_NAMES)
    other = load_problem("random", 12, 1)
    with pytest.raises(AssertionError, match="different mazes"):
        common.check_results(
            STATIC, results[:3] + [common.solve_job(other, "astar")], STRATEGY_NAMES
        )
    with pytest.raises(AssertionError, match="one result per strategy"):
        common.check_results(STATIC, results[:3], STRATEGY_NAMES)


def test_sequential_and_format():
    run = common.run_sequential(STATIC)
    assert common.moves_by_strategy(run["results"]) == {
        "astar": 127, "bfs": 127, "left_hand": 1201, "right_hand": 1279,
    }  # fmt: skip
    text = common.format_results(run["results"])
    assert "right_hand" in text and "1279" in text
    no_path = dict(run["results"][0], moves=None, backtracks=None)
    assert "no path" in common.format_results([no_path])


class FakeComm:
    """Single-rank stand-in for an mpi4py communicator."""

    def Get_rank(self):
        return 0

    def Get_size(self):
        return 1

    def bcast(self, obj, root=0):
        return json.loads(json.dumps(obj))  # what MPI would do: a serialised copy

    def Barrier(self):
        pass

    def gather(self, obj, root=0):
        return [obj]


def test_strategies_for_rank_round_robin():
    assert mpi_run.strategies_for_rank(0, 4) == ["right_hand"]
    assert mpi_run.strategies_for_rank(1, 2) == ["left_hand", "astar"]
    assert mpi_run.strategies_for_rank(0, 1) == list(STRATEGY_NAMES)


def test_mpi_run_with_fake_comm(tmp_path, capsys):
    out = tmp_path / "mpi.json"
    assert mpi_run.main(["--maze", "static", "--out", str(out)], comm=FakeComm()) == 0
    data = json.loads(out.read_text())
    assert data["workers"] == 1 and len(data["results"]) == 4
    assert "MPI with 1 ranks" in capsys.readouterr().out


def test_mpi_run_non_root_returns_none():
    class Rank1(FakeComm):
        def Get_rank(self):
            return 1

        def Get_size(self):
            return 2

        def bcast(self, obj, root=0):
            return STATIC.to_dict()

    assert mpi_run.run(Rank1(), None) is None


def test_celery_task_called_directly_uses_given_maze():
    r = solve_task(STATIC.to_dict(), "astar")
    assert r["moves"] == 127 and r["maze_fingerprint"] == STATIC.fingerprint()


@pytest.fixture
def eager(monkeypatch):
    monkeypatch.setattr(app.conf, "task_always_eager", True)
    yield


def test_run_celery_eager_sets_expiry(eager, monkeypatch):
    sent = []
    original = solve_task.apply_async

    def spy(*args, **kwargs):
        sent.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(solve_task, "apply_async", spy)
    run = celery_client.run_celery(STATIC, ping=False)
    assert common.moves_by_strategy(run["results"])["bfs"] == 127
    assert all(kw.get("expires") for kw in sent) and len(sent) == 4


def test_count_workers_no_worker(monkeypatch):
    monkeypatch.setattr(app.control, "ping", lambda timeout: [])
    with pytest.raises(celery_client.NoWorkerError, match="Start RabbitMQ and a worker first"):
        celery_client.count_workers()


def test_count_workers_broker_down(monkeypatch):
    def boom(timeout):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(app.control, "ping", boom)
    with pytest.raises(celery_client.NoWorkerError, match="Cannot reach the broker"):
        celery_client.count_workers()


def test_count_workers_counts_processes(monkeypatch):
    class Inspect:
        def stats(self):
            return {"w1": {"pool": {"max-concurrency": 4}}}

    monkeypatch.setattr(app.control, "ping", lambda timeout: [{"w1": {"ok": "pong"}}])
    monkeypatch.setattr(app.control, "inspect", lambda timeout: Inspect())
    assert celery_client.count_workers() == {"nodes": 1, "processes": 4}


def test_run_celery_timeout_revokes(eager, monkeypatch):
    revoked = []

    def slow_join(self, timeout=None, **kw):
        raise CeleryTimeoutError("slow")

    monkeypatch.setattr(celery_client.ResultSet, "join", slow_join)
    monkeypatch.setattr(celery_client.ResultSet, "revoke", lambda self, **kw: revoked.append(1))
    with pytest.raises(celery_client.ResultTimeoutError, match="revoked"):
        celery_client.run_celery(STATIC, ping=False, timeout=0.1)
    assert revoked


def test_celery_main_reports_clean_error(monkeypatch, capsys):
    def no_worker(*a, **k):
        raise celery_client.NoWorkerError("No Celery worker answered")

    monkeypatch.setattr(celery_client, "run_celery", no_worker)
    assert celery_client.main([]) == 2
    assert "No Celery worker answered" in capsys.readouterr().err


def test_celery_main_success(eager, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        celery_client, "count_workers", lambda timeout=2.0: {"nodes": 1, "processes": 4}
    )
    out = tmp_path / "c.json"
    assert celery_client.main(["--repeats", "2", "--out", str(out)]) == 0
    assert len(json.loads(out.read_text())["runs"]) == 2
    assert "4 worker processes" in capsys.readouterr().out


def test_pick_start_method(monkeypatch):
    from maze_runner.backends.multiproc import pick_start_method

    monkeypatch.delenv("MAZE_MP_START_METHOD", raising=False)
    assert pick_start_method("spawn") == "spawn"
    assert pick_start_method() in ("forkserver", "spawn")
    monkeypatch.setenv("MAZE_MP_START_METHOD", "spawn")
    assert pick_start_method() == "spawn"


def test_wait_for_workers_retries_then_gives_up(monkeypatch):
    calls = []

    def ping(timeout):
        calls.append(1)
        return [{"w": {"ok": "pong"}}] if len(calls) >= 3 else []

    class Inspect:
        def stats(self):
            return {}

    monkeypatch.setattr(app.control, "ping", ping)
    monkeypatch.setattr(app.control, "inspect", lambda timeout: Inspect())
    assert celery_client.wait_for_workers(5, poll=0.01)["nodes"] == 1
    monkeypatch.setattr(app.control, "ping", lambda timeout: [])
    with pytest.raises(celery_client.NoWorkerError):
        celery_client.wait_for_workers(0.05, poll=0.01)
