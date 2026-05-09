"""tm-issue-finalize: validates worktree/branch/diff, pushes branch, posts a
structured solution-summary comment. Does NOT open a PR (by design)."""
from __future__ import annotations
import os
import subprocess
import shutil
import textwrap
from pathlib import Path

import pytest


FINALIZE = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_worktree_with_diff(tmp_git_repo, bot_root, issue_num):
    """Create a worktree at bot_root/worktrees/issue-N with a real diff."""
    branch = f"auto-fix/issue-{issue_num}"
    wt = bot_root / "worktrees" / f"issue-{issue_num}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    (wt / "fix.txt").write_text("the fix\n")
    _git("add", "-A", cwd=wt)
    _git("commit", "-m", f"fix #{issue_num}", cwd=wt)
    return wt, branch


def _stub_gh_in_path(tmp_path: Path, log_path: Path | None = None,
                     pr_exists: bool = False) -> Path:
    """Drop a `gh` shim. If pr_exists, `pr list` returns one PR (idempotency
    check); otherwise empty and `pr create` returns a new PR URL."""
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    pr_list_out = '[{"number":99}]' if pr_exists else "[]"
    log_block = "" if log_path is None else f'echo "ARGS: $@" >> "{log_path}"\nfor ((i=1; i<=$#; i++)); do\n  if [ "${{!i}}" = "--body" ]; then\n    j=$((i+1)); echo "BODY_BEGIN" >> "{log_path}"; echo "${{!j}}" >> "{log_path}"; echo "BODY_END" >> "{log_path}"\n  fi\ndone'
    body = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        {log_block}
        case "$1 $2" in
          "pr list")        echo '{pr_list_out}' ;;
          "pr create")      echo "https://github.com/o/r/pull/77" ;;
          "issue comment")  echo "https://github.com/o/r/issues/1#issuecomment-1" ;;
          *) ;;
        esac
        exit 0
    """)
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_finalize_happy_path_pushes_pr_and_comments(tmp_git_repo, tmp_bot_root, tmp_path):
    """Branch pushed, PR created, short pointer comment on issue."""
    issue = 1
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)

    gh_log = tmp_path / "gh.log"
    stubs = _stub_gh_in_path(tmp_path, gh_log)
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    log_text = gh_log.read_text()
    assert "pr list" in log_text
    assert "pr create" in log_text
    assert f"issue comment {issue}" in log_text


def test_finalize_pr_body_includes_closes_diffstat_commit(
    tmp_git_repo, tmp_bot_root, tmp_path,
):
    """The PR body carries the 整体方案 — Closes #N + diff stat + commit msg."""
    issue = 7
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)

    gh_log = tmp_path / "gh.log"
    stubs = _stub_gh_in_path(tmp_path, gh_log)
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "owner/repo"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    # Find the PR-create body (3rd BODY block: list, create, comment).
    log_text = gh_log.read_text()
    bodies = [seg.split("BODY_END", 1)[0] for seg in log_text.split("BODY_BEGIN")[1:]]
    assert any(f"Closes #{issue}" in b for b in bodies)
    assert any("fix.txt" in b for b in bodies)  # diff stat file


def test_finalize_rejects_outside_worktree(tmp_path, monkeypatch):
    """Running finalize from a path outside the bot's worktrees/ must fail."""
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_path / "elsewhere")
    proc = subprocess.run(
        [str(FINALIZE), "1"], cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "worktree" in (proc.stderr + proc.stdout).lower()


def test_finalize_rejects_wrong_branch(tmp_git_repo, tmp_bot_root, tmp_path):
    """Branch must start with TM_ISSUE_BRANCH_PREFIX."""
    issue = 2
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", "feature/wrong", str(wt), "main", cwd=tmp_git_repo)
    (wt / "fix.txt").write_text("x"); _git("add", "-A", cwd=wt); _git("commit", "-m", "x", cwd=wt)

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "branch" in (proc.stderr + proc.stdout).lower()


def test_finalize_empty_diff_fails(tmp_git_repo, tmp_bot_root, tmp_path):
    issue = 3
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"auto-fix/issue-{issue}"
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    # No diff.

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "diff" in (proc.stderr + proc.stdout).lower()


def test_finalize_idempotent_when_pr_exists(tmp_git_repo, tmp_bot_root, tmp_path):
    """Re-running finalize when a PR already exists for this branch: skip
    `pr create`, reuse PR number 99 from the stub's pr-list output."""
    issue = 4
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)
    gh_log = tmp_path / "gh.log"
    stubs = _stub_gh_in_path(tmp_path, gh_log, pr_exists=True)
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    log_text = gh_log.read_text()
    assert "pr list" in log_text
    assert "pr create" not in log_text   # didn't re-create
    assert "99" in (proc.stdout + proc.stderr)  # reused PR number


def test_finalize_diff_too_large(tmp_git_repo, tmp_bot_root, tmp_path):
    issue = 5
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"auto-fix/issue-{issue}"
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    big = "\n".join(f"line {i}" for i in range(1500)) + "\n"
    (wt / "big.txt").write_text(big)
    _git("add", "-A", cwd=wt); _git("commit", "-m", "big", cwd=wt)

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_ISSUE_MAX_DIFF_LINES"] = "100"
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "diff" in (proc.stderr + proc.stdout).lower()
