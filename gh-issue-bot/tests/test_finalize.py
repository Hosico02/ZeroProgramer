"""tm-issue-finalize: validates worktree, branch, diff, then push + PR + comment."""
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


def _stub_gh_in_path(tmp_path: Path, behavior: str = "ok") -> Path:
    """Drop a `gh` shim into a fresh dir and return that dir for $PATH prepend.
    behavior: 'ok' | 'pr-exists' | 'fail-create'.
    """
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    if behavior == "ok":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            cmd="$1 $2"
            case "$cmd" in
              "pr list") echo "[]" ;;
              "pr create") echo "https://github.com/o/r/pull/77" ;;
              "issue comment") echo "https://github.com/o/r/issues/1#c-1" ;;
              *) exit 0 ;;
            esac
        """)
    elif behavior == "pr-exists":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            cmd="$1 $2"
            case "$cmd" in
              "pr list") echo '[{"number":55}]' ;;
              "issue comment") echo "https://github.com/o/r/issues/1#c-1" ;;
              *) exit 0 ;;
            esac
        """)
    else:
        body = "#!/usr/bin/env bash\nexit 1\n"
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_finalize_happy_path(tmp_git_repo, tmp_bot_root, monkeypatch, tmp_path):
    issue = 1
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)

    # Repurpose the source repo as the "remote" so push works.
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)

    stubs = _stub_gh_in_path(tmp_path, "ok")
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
    issue = 4
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)
    stubs = _stub_gh_in_path(tmp_path, "pr-exists")
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "55" in (proc.stdout + proc.stderr)  # reused PR number


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
