"""Tests for benchmark.py (timing rules, summaries, fresh result files)."""

from __future__ import annotations

import csv
import json
import time

import pytest

from maze_runner import benchmark as bm
from maze_runner.strategies import load_problem


def test_timer_stops_before_display():
    p = load_problem("static")
    shown = []
    result, seconds = bm.timed_solve(p, "bfs", on_done=lambda r: (time.sleep(0.3), shown.append(r)))
    assert shown and shown[0] is result
    assert seconds < 0.25


def test_mean_sd():
    assert bm.mean_sd([2.0]) == (2.0, 0.0)
    mean, sd = bm.mean_sd([1.0, 2.0, 3.0])
    assert mean == 2.0 and sd == pytest.approx(1.0)
    with pytest.raises(ValueError):
        bm.mean_sd([])


def test_time_strategy_repeats_and_is_deterministic():
    row = bm.time_strategy(load_problem("static"), "astar", repeats=3)
    assert row["moves"] == 127 and row["repeats"] == 3 and row["backtracks"] is None
    assert row["time_mean_s"] > 0 and row["time_sd_s"] >= 0
    with pytest.raises(ValueError):
        bm.time_strategy(load_problem("static"), "astar", repeats=0)


def test_time_strategy_detects_nondeterminism(monkeypatch):
    calls = iter(range(10))

    def flaky(problem, strategy):
        from maze_runner.strategies import SearchResult

        n = next(calls)
        return SearchResult(strategy, [problem.start] * (n + 1), 1)

    monkeypatch.setattr(bm, "solve", flaky)
    with pytest.raises(RuntimeError):
        bm.time_strategy(load_problem("static"), "bfs", repeats=2)


def test_static_benchmark_rows():
    rows = bm.static_benchmark(repeats=2)
    assert [r["strategy"] for r in rows] == ["right_hand", "left_hand", "bfs", "astar"]
    assert {r["strategy"]: r["moves"] for r in rows}["right_hand"] == 1279


def test_random_sweep_and_summary():
    rows = bm.random_sweep(sizes=(10, 20), seeds=range(3))
    assert len(rows) == 2 * 3 * 4
    summary, ratios = bm.summarise_sweep(rows)
    assert len(summary) == 2 * 4
    assert [r["size"] for r in ratios] == [10, 20]
    assert all(0 < r["ratio_mean"] <= 1 for r in ratios)  # A* never expands more than BFS
    assert bm.random_sweep((12,), [5]) == bm.random_sweep((12,), [5])  # seeded


def test_path_sha():
    assert bm.path_sha(None) is None
    assert bm.path_sha([(0, 1), (1, 1)]) == bm.path_sha([[0, 1], [1, 1]])


def test_write_csv_replaces_instead_of_appending(tmp_path):
    out = tmp_path / "r.csv"
    for _ in range(3):
        bm.write_csv(out, [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    with out.open() as fh:
        assert len(list(csv.DictReader(fh))) == 2
    bm.write_csv(out, [])
    assert out.read_text() == ""


def test_write_json(tmp_path):
    out = bm.write_json(tmp_path / "sub" / "x.json", {"k": [1, 2]})
    assert json.loads(out.read_text()) == {"k": [1, 2]}


def test_machine_info_has_no_host_name():
    import platform

    info = bm.machine_info()
    assert info["logical_cores"] and info["python"]
    assert platform.node() not in json.dumps(info)
    assert "T" in bm.utc_timestamp()
