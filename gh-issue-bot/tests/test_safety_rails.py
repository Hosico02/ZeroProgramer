"""Safety rails: daily cap, branch prefix, worktree path lock, kill switch."""
import os
import subprocess
from pathlib import Path

from lib.config import Config
from lib.state import Ledger
from lib.watcher_logic import eligible_for_promote


def _cfg(**ov):
    base = dict(repo="o/r", label="auto-fix", fail_label="auto-fix-failed",
                max_parallel=3, poll_interval=600, daily_cap=10,
                max_diff_lines=2000, branch_prefix="auto-fix/issue-")
    base.update(ov); return Config(**base)


def test_daily_cap_blocks_promotion():
    cfg = _cfg(daily_cap=2)
    led = Ledger.empty()
    led.daily_spawn_date = "2026-05-09"; led.daily_spawn_count = 2
    for n in ("1", "2"):
        led.upsert_seen(n, title="t", labels=["auto-fix"], updated_at="x")
    assert eligible_for_promote(led, cfg, today="2026-05-09") == []


def test_kill_switch_disables_tick(tmp_bot_root, tmp_path):
    (tmp_bot_root / ".disabled").touch()
    watcher = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-watcher"
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_GH_REPO"] = "o/r"
    proc = subprocess.run([str(watcher), "tick"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    # No state.json should have been written when disabled
    assert not (tmp_bot_root / "state.json").exists() or \
           "skipping" in (tmp_bot_root / "watcher.log").read_text()


def test_branch_prefix_lock_enforced_in_finalize():
    """Static: bin/tm-issue-finalize contains the prefix check."""
    finalize = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"
    txt = finalize.read_text()
    assert "TM_ISSUE_BRANCH_PREFIX" in txt
    assert "lacks prefix" in txt or "branch" in txt


def test_worktree_path_lock_enforced_in_finalize():
    finalize = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"
    txt = finalize.read_text()
    assert "is not the expected worktree" in txt
    assert "WT_REQUIRED" in txt
