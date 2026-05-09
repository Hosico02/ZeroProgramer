"""Thin wrappers over the `gh` CLI.

Each function does one shell-out and returns a parsed result. Errors raise
GhError with the trimmed stderr. Tests inject a fake `subprocess.run` via the
`fake_gh` fixture, so no network access ever occurs in CI.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

ISSUE_FIELDS = "number,title,body,labels,updatedAt,state"


class GhError(RuntimeError):
    pass


def _run(*argv: str) -> str:
    proc = subprocess.run(list(argv), capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout or "gh failed").strip())
    return proc.stdout


def list_issues(repo: str, *, label: str | None = None,
                state: str = "open", limit: int = 200) -> list[dict]:
    argv = ["gh", "issue", "list", "--repo", repo]
    if label:
        argv += ["--label", label]
    argv += ["--state", state, "--json", ISSUE_FIELDS, "--limit", str(limit)]
    out = _run(*argv)
    return json.loads(out)


def view_issue(repo: str, number: int) -> dict:
    out = _run("gh", "issue", "view", str(number), "--repo", repo,
               "--json", ISSUE_FIELDS)
    return json.loads(out)


def comment_issue(repo: str, number: int, body: str) -> str:
    out = _run("gh", "issue", "comment", str(number), "--repo", repo,
               "--body", body)
    return out.strip()


def add_label(repo: str, number: int, label: str) -> None:
    _run("gh", "issue", "edit", str(number), "--repo", repo,
         "--add-label", label)


def remove_label(repo: str, number: int, label: str) -> None:
    _run("gh", "issue", "edit", str(number), "--repo", repo,
         "--remove-label", label)


def pr_for_branch(repo: str, head: str) -> int | None:
    out = _run("gh", "pr", "list", "--repo", repo, "--head", head,
               "--state", "open", "--json", "number")
    rows = json.loads(out)
    return rows[0]["number"] if rows else None


def create_pr(repo: str, *, head: str, base: str, title: str, body: str) -> int:
    out = _run("gh", "pr", "create", "--repo", repo,
               "--head", head, "--base", base,
               "--title", title, "--body", body)
    m = re.search(r"/pull/(\d+)", out)
    if not m:
        raise GhError(f"could not parse PR number from: {out.strip()}")
    return int(m.group(1))
