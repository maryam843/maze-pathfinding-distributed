"""Scan tracked files AND the whole git history for secrets and personal data.

Checks: API keys/tokens/private keys, e-mail addresses (other than the allowed noreply),
IPv4 addresses (other than loopback/0.0.0.0), user home paths, and 8-9 digit ID-like numbers.
Also checks every commit's author and committer e-mail.

    python scripts/pii_scan.py                     # tracked files + all commits
    python scripts/pii_scan.py --denylist FILE     # extra private terms, one per line (kept
                                                   # outside the repo, never committed)
Exit code 1 if anything is found.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAILS = {"185722545+maryam843@users.noreply.github.com"}
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0"}
# Reviewed 2026-09-30: 16-hex SHA-256 prefixes (path_sha / maze_fingerprint columns) in
# results/random_mazes.csv whose digit tails match the ID pattern. Exact values only.
ALLOWED_HASHES = {
    "17f176737038e3e1",  # results/random_mazes.csv:48-49 path_sha
    "1c7c4bb464616284",  # results/random_mazes.csv:76-77 path_sha
    "928115846fe91b51",  # results/random_mazes.csv:124-125 path_sha
    "927f771c32255021",  # results/random_mazes.csv:130-133 maze_fingerprint
}

PATTERNS = {
    "aws-key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "openai-style-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "slack-token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password-assignment": re.compile(
        r"(?i)\b(password|passwd|secret|api_key|token)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"
    ),
    # RabbitMQ's documented default guest:guest login is allowed; anything else is flagged.
    "url-credentials": re.compile(r"[a-z]+://(?!guest:guest@)[^/\s:@]+:[^/\s@]+@(?!localhost)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ipv4": re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    "user-path": re.compile(
        r"(?i)([A-Z]:\\Users\\[^\\\s]+|/home/(?!runner\b)[a-z0-9_-]+|/Users/[A-Za-z0-9_-]+)"
    ),
    "id-like-number": re.compile(r"(?<![\d.])\d{8,9}(?![\d.])"),
}


def findings_in_text(text: str, where: str, deny: list[str]) -> list[str]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for allowed in ALLOWED_EMAILS:  # its digits are a GitHub user id, not personal data
            line = line.replace(allowed, "<allowed-noreply>")
        for allowed in ALLOWED_HASHES:
            line = line.replace(allowed, "<allowed-hash>")
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(line):
                value = m.group(0)
                if name == "email" and value in ALLOWED_EMAILS:
                    continue
                if name == "ipv4" and (
                    value in ALLOWED_IPS or any(int(p) > 255 for p in value.split("."))
                ):
                    continue
                if name == "id-like-number" and ("pid" in line.lower() or "seed" in line.lower()):
                    continue
                hits.append(f"{where}:{lineno}: {name}: {value}")
        lowered = line.lower()
        for term in deny:
            if term in lowered:
                hits.append(f"{where}:{lineno}: denylist term (not shown)")
    return hits


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, errors="replace"
    ).stdout


def scan(deny: list[str], root: Path = ROOT) -> tuple[list[str], int, int]:
    """Scan every tracked file and every commit under `root`, this scanner's own file included.

    (It used to skip itself, and that gap let a real identifier sit in its history unnoticed.)
    """
    hits = []
    files = git("ls-files", root=root).splitlines()
    for name in files:
        data = (root / name).read_bytes()
        if b"\0" in data[:8000]:
            continue  # binary (PNG/GIF): checked through history metadata only
        hits += findings_in_text(data.decode("utf-8", "replace"), name, deny)
    commits = git("rev-list", "--all", root=root).split()
    for sha in commits:
        meta = git("show", "-s", "--format=%an%n%ae%n%cn%n%ce%n%B", sha, root=root)
        _, author_email, _, committer_email, *_ = meta.splitlines() + [""] * 5
        for email in (author_email, committer_email):
            if email not in ALLOWED_EMAILS:
                hits.append(f"commit {sha[:8]}: identity e-mail not allowed: {email}")
        hits += findings_in_text(meta, f"commit {sha[:8]} message", deny)
        patch = git("show", "--format=", "--no-color", "--text", sha, root=root)
        added = "\n".join(
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        hits += findings_in_text(added, f"commit {sha[:8]} diff", deny)
    return sorted(set(hits)), len(files), len(commits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Secret and personal-data scan.")
    parser.add_argument("--denylist", type=Path, help="file with extra private terms")
    args = parser.parse_args(argv)
    deny = []
    if args.denylist:
        deny = [t.strip().lower() for t in args.denylist.read_text().splitlines() if t.strip()]
    hits, n_files, n_commits = scan(deny)
    for h in hits:
        print(h)
    print(f"scanned {n_files} tracked files and {n_commits} commits "
          f"({len(deny)} denylist terms): {len(hits)} hits")  # fmt: skip
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
