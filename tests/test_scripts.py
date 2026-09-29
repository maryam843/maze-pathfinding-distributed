"""Tests for scripts/: the personal-data scan, the README claims check, reproducibility."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pii = load_script("pii_scan")
claims = load_script("check_readme_claims")
bench = load_script("run_benchmarks")


@pytest.mark.parametrize(
    "text, kind",
    [
        ("key = AKIA" + "ABCDEFGHIJKLMNOP", "aws-key"),
        ("t = 'ghp_" + "a" * 36 + "'", "github-token"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "private-key"),
        ("contact someone" + "@example.org", "email"),
        ("host 10.1.2." + "3", "ipv4"),
        ("C:\\Users\\" + "someone\\Desktop", "user-path"),
        ("/home/" + "someone/project", "user-path"),
        ("student 60" + "1234567", "id-like-number"),
        ("password = '" + "hunter22'", "password-assignment"),
        ("amqp://user:pw" + "@" + "rabbit.example/", "url-credentials"),
    ],
)
def test_pii_patterns_catch_planted_examples(text, kind):
    hits = pii.findings_in_text(text, "x", [])
    assert any(f": {kind}:" in h for h in hits), hits


@pytest.mark.parametrize(
    "text",
    [
        "185722545+maryam843@users.noreply.github.com",
        "pyamqp://guest@localhost//",
        "127.0.0.1 and 0.0.0.0",
        "time 0.001234567 s",
        "11111111111011111111111111111111111111111111111111111111111111",
        "version 3.12.3",
    ],
)
def test_pii_allowed_text_is_quiet(text):
    assert pii.findings_in_text(text, "x", []) == []


def test_pii_denylist_hides_the_term():
    hits = pii.findings_in_text("hello SecretName", "f", ["secretname"])
    assert hits and "SecretName" not in hits[0]


def test_pii_scan_of_this_repository_is_clean():
    hits, n_files, n_commits = pii.scan([])
    assert hits == [] and n_files > 0 and n_commits > 0


def fake_results():
    return json.loads((ROOT / "results" / "summary.json").read_text())


@pytest.mark.skipif(not (ROOT / "results" / "summary.json").exists(), reason="no results yet")
def test_readme_claims_match_results():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert claims.check(readme, fake_results()) == []


@pytest.mark.skipif(not (ROOT / "results" / "summary.json").exists(), reason="no results yet")
def test_readme_claims_detect_a_changed_number():
    data = fake_results()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    data["static_maze"][2]["moves"] += 1  # pretend BFS found a different length
    problems = claims.check(readme, data)
    assert any("[static]" in p for p in problems)
    assert any("[headline]" in p for p in problems)


def test_readme_claims_missing_block():
    data = {"static_maze": [], "random_summary": [], "astar_vs_bfs": [], "backends": [],
            "backend_moves": [], "run_info": {"repeats": 1}}  # fmt: skip
    data["static_maze"] = [
        {"strategy": s, "moves": 1, "nodes_expanded": 1, "backtracks": None,
         "time_mean_s": 0.0, "time_sd_s": 0.0}
        for s in ("right_hand", "left_hand", "bfs", "astar")
    ]  # fmt: skip
    problems = claims.check("<!-- claims:bogus -->\n| x |\n<!-- /claims -->", data)
    assert any("unknown claims block" in p for p in problems)
    assert any("no <!-- claims:static -->" in p for p in problems)


def test_benchmark_is_reproducible(tmp_path):
    """T8 in small: same seeds -> identical moves, nodes and paths (timings may differ)."""
    args = ["--repeats", "2", "--sizes", "10", "20", "--seeds", "3",
            "--backends", "sequential", "multiprocessing", "--backend-mazes", "static"]  # fmt: skip
    keep = ("strategy", "moves", "nodes_expanded", "path_sha", "size", "seed")
    runs = []
    for i in range(2):
        out = tmp_path / str(i)
        assert bench.main([*args, "--out-dir", str(out)]) == 0
        data = json.loads((out / "summary.json").read_text())
        sweep = (out / "random_mazes.csv").read_text()
        static = [{k: r[k] for k in keep if k in r} for r in data["static_maze"]]
        runs.append((static, sweep, data["backend_moves"]))
    assert runs[0] == runs[1]


def test_benchmark_records_backends_it_cannot_run(tmp_path, monkeypatch):
    monkeypatch.setenv("MPIEXEC", "definitely-not-installed-mpiexec")
    out = tmp_path / "r"
    assert bench.main(["--repeats", "1", "--sizes", "10", "--seeds", "1", "--backends", "mpi",
                       "--backend-mazes", "static", "--out-dir", str(out)]) == 0  # fmt: skip
    data = json.loads((out / "summary.json").read_text())
    assert data["backends_not_run"][0]["reason"] == "mpiexec not found on PATH"
