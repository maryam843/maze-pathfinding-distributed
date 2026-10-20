"""Tests for scripts/: the personal-data scan, the README claims check, reproducibility."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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
figures = load_script("make_figures")


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
        ("id_60" + "1234567 here", "id-like-number"),
        ("other hash aaaaaaaa1234" + "5678", "id-like-number"),
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
        "path hash 1c7c4bb464616284",
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


def regenerated_elsewhere():
    """The committed results as another machine would produce them: new timings, no MPI."""
    data = fake_results()
    for r in data["static_maze"]:
        r["time_mean_s"] *= 1.7
    for r in data["backends"]:
        r["wall_mean_s"] *= 2.3
    data["backends"] = [r for r in data["backends"] if r["backend"] != "mpi"]
    data["backend_moves"] = [r for r in data["backend_moves"] if r["backend"] != "mpi"]
    data["backends_not_run"] = [{"backend": "mpi", "maze": "static", "reason": "no mpiexec"}]
    return data


@pytest.mark.skipif(not (ROOT / "results" / "summary.json").exists(), reason="no results yet")
def test_readme_claims_relaxed_check_reports_timings_as_info():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    data = regenerated_elsewhere()
    assert claims.check(readme, data)  # the exact check fails on these results
    problems, notes = claims.compare(readme, data, exact=False)
    assert problems == []
    assert any(n.startswith("[static] A*:") for n in notes)
    assert any(n.startswith("[backends]") for n in notes)
    assert any("mpi: not run" in n for n in notes)


@pytest.mark.skipif(not (ROOT / "results" / "summary.json").exists(), reason="no results yet")
def test_readme_claims_relaxed_check_still_fails_on_counts():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    data = regenerated_elsewhere()
    data["static_maze"][3]["nodes_expanded"] += 1  # A* nodes
    data["backend_moves"][0]["moves"] += 1
    data["random_summary"][0]["moves_mean"] += 1
    problems, _ = claims.compare(readme, data, exact=False)
    assert any(p.startswith("[static]") for p in problems)
    assert any(p.startswith("[backend_moves]") for p in problems)
    assert any(p.startswith("[random]") for p in problems)


@pytest.mark.skipif(not (ROOT / "results" / "summary.json").exists(), reason="no results yet")
def test_readme_claims_cli_exact_for_committed_relaxed_elsewhere(tmp_path, capsys):
    assert claims.main([]) == 0
    assert "0 mismatches" in capsys.readouterr().out
    folder = tmp_path / "results"
    folder.mkdir()
    (folder / "summary.json").write_text(json.dumps(regenerated_elsewhere()), encoding="utf-8")
    assert claims.main(["--results", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "info: [static]" in out and "0 mismatches in moves and nodes" in out
    assert claims.main(["--results", str(folder / "summary.json")]) == 0  # a file works too


def test_make_figures_says_what_to_run_when_results_are_missing(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        figures.main(["--out-dir", str(tmp_path)])
    assert exc.value.code == 2
    assert "run scripts/run_benchmarks.py first" in capsys.readouterr().err


def test_benchmark_is_reproducible(tmp_path):
    """T8 in small: same seeds -> identical moves, nodes and paths (timings may differ)."""
    args = ["--repeats", "2", "--sizes", "10", "20", "--seeds", "3",
            "--backends", "sequential", "multiprocessing", "--backend-mazes", "static"]  # fmt: skip
    keep = ("strategy", "moves", "nodes_expanded", "path_sha", "size", "seed")
    runs = []
    for i in range(2):
        out = tmp_path / str(i)
        assert bench.main([*args, "--out-dir", str(out)]) == 0
        data = json.loads((out / "results" / "summary.json").read_text())
        sweep = (out / "results" / "random_mazes.csv").read_text()
        static = [{k: r[k] for k in keep if k in r} for r in data["static_maze"]]
        runs.append((static, sweep, data["backend_moves"]))
    assert runs[0] == runs[1]


def test_benchmark_records_backends_it_cannot_run(tmp_path, monkeypatch):
    monkeypatch.setenv("MPIEXEC", "definitely-not-installed-mpiexec")
    out = tmp_path / "r"
    assert bench.main(["--repeats", "1", "--sizes", "10", "--seeds", "1", "--backends", "mpi",
                       "--backend-mazes", "static", "--out-dir", str(out)]) == 0  # fmt: skip
    data = json.loads((out / "results" / "summary.json").read_text())
    assert data["backends_not_run"][0]["reason"] == "mpiexec not found on PATH"


def test_benchmark_stops_a_hung_mpiexec(monkeypatch):
    def hang(cmd, **kwargs):
        assert kwargs["timeout"] == bench.MPI_TIMEOUT_S
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(bench.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="did not finish"):
        bench.run_mpi_once(4, ["--maze", "static"])


def _git(repo, *args):
    ident = ["-c", "user.name=Maryam Mahaboob",
             "-c", "user.email=185722545+maryam843@users.noreply.github.com"]  # fmt: skip
    subprocess.run(["git", *ident, *args], cwd=repo, check=True, capture_output=True)


def test_pii_scan_checks_its_own_file_in_history_and_at_head(tmp_path):
    """The scanner used to skip scripts/pii_scan.py, so an ID left in its history went unseen."""
    planted = "60" + "1234567"  # split so this test file itself stays clean
    repo = tmp_path / "repo"
    own = repo / "scripts" / "pii_scan.py"
    own.parent.mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(repo))
    own.write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    own.write_text(f"x = 1  # e.g. id_{planted}\n")
    _git(repo, "commit", "-q", "-am", "add comment")
    own.write_text("x = 1\n")
    _git(repo, "commit", "-q", "-am", "remove comment")

    hits, n_files, n_commits = pii.scan([], root=repo)
    assert n_files == 1 and n_commits == 3
    assert any(" diff:" in h and "id-like-number" in h for h in hits), hits  # found in history
    assert not any(h.startswith("scripts/pii_scan.py:") for h in hits)  # clean at HEAD

    own.write_text(f"x = 1  # e.g. id_{planted}\n")
    hits, _, _ = pii.scan([], root=repo)
    assert any(h.startswith("scripts/pii_scan.py:1: id-like-number") for h in hits), hits
