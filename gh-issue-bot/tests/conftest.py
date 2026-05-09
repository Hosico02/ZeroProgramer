"""Shared pytest fixtures for gh-issue-bot tests."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make `lib` importable from tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tmp_bot_root(tmp_path):
    """A clean gh-issue-bot/-shaped tree under tmp_path."""
    root = tmp_path / "bot"
    for sub in ("bin", "lib", "events/.processed", "tasks", "nags",
                "escalations", "worktrees"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def tmp_git_repo(tmp_path):
    """An initialized empty-but-clean git repo with a `main` branch and one
    initial commit. Tests that need worktrees clone or branch from here."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def fake_gh(monkeypatch):
    """Replace subprocess.run to intercept `gh ...` calls and return canned
    responses set via the returned helper. Real subprocess calls (git, etc.)
    pass through."""
    real_run = subprocess.run
    canned: dict[tuple, subprocess.CompletedProcess] = {}

    def setter(args_tuple, *, stdout="", returncode=0, stderr=""):
        canned[args_tuple] = subprocess.CompletedProcess(
            args=list(args_tuple), returncode=returncode,
            stdout=stdout, stderr=stderr,
        )

    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, list) and argv and argv[0] == "gh":
            key = tuple(argv)
            if key in canned:
                return canned[key]
            # Helpful failure for missing canned response
            raise AssertionError(
                f"fake_gh: no canned response for `{' '.join(argv)}`. "
                f"Register one with fake_gh.set(...)."
            )
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    setter.calls = canned
    return setter
