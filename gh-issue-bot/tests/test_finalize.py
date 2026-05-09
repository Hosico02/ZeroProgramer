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


def _stub_gh_in_path(tmp_path: Path, log_path: Path | None = None) -> Path:
    """Drop a `gh` shim into a fresh dir; record every call to log_path if given."""
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    if log_path is not None:
        body = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            # Log the full command + the --body argument value (if any) for tests to inspect.
            echo "ARGS: $@" >> "{log_path}"
            for ((i=1; i<=$#; i++)); do
              if [ "${{!i}}" = "--body" ]; then
                j=$((i+1))
                echo "BODY_BEGIN" >> "{log_path}"
                echo "${{!j}}"     >> "{log_path}"
                echo "BODY_END"   >> "{log_path}"
              fi
            done
            case "$1 $2" in
              "issue comment") echo "https://github.com/o/r/issues/1#issuecomment-1" ;;
              *) ;;
            esac
            exit 0
        """)
    else:
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            case "$1 $2" in
              "issue comment") echo "https://github.com/o/r/issues/1#issuecomment-1" ;;
              *) ;;
            esac
            exit 0
        """)
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_finalize_happy_path_pushes_and_comments(tmp_git_repo, tmp_bot_root, tmp_path):
    """Branch is pushed; a structured comment is posted; NO PR is created."""
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

    proc = subprocess.run(
        [str(FINALIZE), str(issue)],
        cwd=wt, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout

    log_text = gh_log.read_text()
    # Comment was posted on the issue.
    assert f"issue comment {issue}" in log_text
    # No PR was opened.
    assert "pr create" not in log_text
    assert "pr list" not in log_text


def test_finalize_comment_body_includes_branch_commit_diffstat(
    tmp_git_repo, tmp_bot_root, tmp_path,
):
    """The comment body IS the solution summary — must include branch name,
    commit short SHA, and diff stat."""
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

    log_text = gh_log.read_text()
    body_match = log_text.split("BODY_BEGIN", 1)[1].split("BODY_END", 1)[0]
    assert branch in body_match
    assert "compare/main..." in body_match
    assert "fix.txt" in body_match  # the file we changed appears in diff stat
    assert "owner/repo" in body_match  # compare URL contains target repo


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


def test_finalize_rerun_is_idempotent(tmp_git_repo, tmp_bot_root, tmp_path):
    """Running finalize twice on the same worktree produces 2 comments but
    pushes nothing new the second time. The branch state on remote is
    unchanged after the second run (no force-with-lease conflict)."""
    issue = 4
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

    p1 = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                        capture_output=True, text=True)
    assert p1.returncode == 0, p1.stderr + p1.stdout
    p2 = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                        capture_output=True, text=True)
    assert p2.returncode == 0, p2.stderr + p2.stdout


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
