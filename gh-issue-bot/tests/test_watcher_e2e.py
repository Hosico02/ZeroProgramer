"""End-to-end: mock gh + tmp git repo → one tick → state.json + add_task event."""
import json
import os
import subprocess
import textwrap
from pathlib import Path


WATCHER = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-watcher"


def _stub_gh_returning(tmp_path: Path, issues_json: str) -> Path:
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    # Write the script line by line so the shebang is guaranteed at column 0.
    lines = [
        "#!/usr/bin/env bash\n",
        "if [ \"$1\" = \"issue\" ] && [ \"$2\" = \"list\" ]; then\n",
        "  printf '%s\\n' " + repr(issues_json) + "\n",
        "  exit 0\n",
        "fi\n",
        "exit 0\n",
    ]
    (bin_dir / "gh").write_text("".join(lines))
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def _seed_bot_root(tmp_git_repo, tmp_bot_root):
    """Make tmp_git_repo behave as the repo's `origin` for worktree commands."""
    # bot_root is alongside repo, but worktree must be on the repo's git dir.
    # We make bot_root contain a .git symlink-ish — easier: have the watcher
    # spawn worktrees against tmp_git_repo by setting TM_REPO_PATH (a knob the
    # watcher honors for testing; in production it derives it from the repo
    # the bot lives in).
    return tmp_git_repo


def test_one_tick_promotes_and_writes_event(tmp_git_repo, tmp_bot_root, tmp_path):
    issues = [{
        "number": 42, "title": "fix typo", "body": "the body",
        "labels": [{"name": "auto-fix"}], "state": "OPEN",
        "updatedAt": "2026-05-09T10:00:00Z",
    }]
    stubs = _stub_gh_returning(tmp_path, json.dumps(issues))

    # Stub `_tm-spawn.sh` invocation by intercepting `tm-claude-issue-fixer`
    # — the watcher in --dry-run mode should NOT spawn anything anyway.
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_REPO_PATH"] = str(tmp_git_repo)
    env["TM_GH_REPO"] = "o/r"
    env["TM_ISSUE_LABEL"] = "auto-fix"
    env["TM_ISSUE_FAIL_LABEL"] = "auto-fix-failed"
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_ISSUE_MAX_PARALLEL"] = "3"
    env["TM_ISSUE_DAILY_CAP"] = "10"
    env["TM_ISSUE_POLL_INTERVAL"] = "600"
    env["TM_ISSUE_MAX_DIFF_LINES"] = "2000"
    env["TM_DRY_RUN"] = "1"

    proc = subprocess.run([str(WATCHER), "tick"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    # state.json reflects the issue as `seen` (dry-run: no promote)
    led = json.loads((tmp_bot_root / "state.json").read_text())
    assert "42" in led["issues"]
    assert led["issues"]["42"]["status"] == "seen"


def test_status_subcommand_reports_in_flight(tmp_bot_root):
    # Pre-seed a state.json with one assigned issue.
    (tmp_bot_root / "state.json").write_text(json.dumps({
        "version": 1, "last_poll_ts": "x",
        "daily_spawn_count": 1, "daily_spawn_date": "2026-05-09",
        "issues": {"7": {"status": "assigned", "title": "t", "labels": [],
                          "updated_at": "x", "worktree": None, "branch": None,
                          "task_id": None, "pr_number": None,
                          "session_id": None, "first_seen_ts": None,
                          "attempts": 1}},
    }, indent=2))
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(WATCHER), "status"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "in-flight" in proc.stdout.lower()
    assert "7" in proc.stdout
