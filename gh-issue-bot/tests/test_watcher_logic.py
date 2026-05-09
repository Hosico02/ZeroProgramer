"""Pure-function unit tests for the tick decision logic."""
import datetime as dt

from lib.state import Ledger
from lib.config import Config
from lib.watcher_logic import (
    classify_issue, plan_actions, eligible_for_promote, ENV_DAY_KEY,
)


def _cfg(**overrides):
    base = dict(repo="o/r", label="auto-fix", fail_label="auto-fix-failed",
                max_parallel=3, poll_interval=600, daily_cap=10,
                max_diff_lines=2000, branch_prefix="auto-fix/issue-")
    base.update(overrides)
    return Config(**base)


def test_classify_skip_if_missing_label():
    cfg = _cfg()
    issue = {"number": 1, "labels": [{"name": "bug"}], "state": "OPEN"}
    assert classify_issue(issue, cfg) == "skip:missing-label"


def test_classify_skip_if_fail_label():
    cfg = _cfg()
    issue = {"number": 1, "labels": [{"name": "auto-fix"}, {"name": "auto-fix-failed"}],
             "state": "OPEN"}
    assert classify_issue(issue, cfg) == "skip:fail-label"


def test_classify_skip_if_wontfix():
    cfg = _cfg()
    issue = {"number": 1, "labels": [{"name": "auto-fix"}, {"name": "wontfix"}],
             "state": "OPEN"}
    assert classify_issue(issue, cfg) == "skip:wontfix"


def test_classify_skip_if_closed():
    cfg = _cfg()
    issue = {"number": 1, "labels": [{"name": "auto-fix"}], "state": "CLOSED"}
    assert classify_issue(issue, cfg) == "skip:closed"


def test_classify_eligible():
    cfg = _cfg()
    issue = {"number": 1, "labels": [{"name": "auto-fix"}], "state": "OPEN"}
    assert classify_issue(issue, cfg) == "eligible"


def test_eligible_for_promote_respects_concurrency():
    cfg = _cfg(max_parallel=2)
    led = Ledger.empty()
    led.upsert_seen("1", title="t", labels=["auto-fix"], updated_at="x")
    led.upsert_seen("2", title="t", labels=["auto-fix"], updated_at="x")
    led.upsert_seen("3", title="t", labels=["auto-fix"], updated_at="x")
    led.transition("1", "assigned"); led.transition("2", "assigned")
    # Already at cap; #3 must wait.
    assert eligible_for_promote(led, cfg, today="2026-05-09") == []


def test_eligible_for_promote_respects_daily_cap():
    cfg = _cfg(daily_cap=2)
    led = Ledger.empty()
    led.daily_spawn_date = "2026-05-09"
    led.daily_spawn_count = 2
    led.upsert_seen("1", title="t", labels=["auto-fix"], updated_at="x")
    assert eligible_for_promote(led, cfg, today="2026-05-09") == []


def test_eligible_for_promote_picks_oldest_first():
    cfg = _cfg(max_parallel=3, daily_cap=10)
    led = Ledger.empty()
    led.upsert_seen("100", title="t", labels=["auto-fix"], updated_at="2026-05-09T03:00:00Z")
    led.upsert_seen("99",  title="t", labels=["auto-fix"], updated_at="2026-05-09T01:00:00Z")
    led.upsert_seen("101", title="t", labels=["auto-fix"], updated_at="2026-05-09T02:00:00Z")
    picks = eligible_for_promote(led, cfg, today="2026-05-09")
    assert picks == ["99", "101", "100"]


def test_plan_actions_promotes_unseen_then_caps():
    cfg = _cfg(max_parallel=2, daily_cap=10)
    led = Ledger.empty()
    issues = [
        {"number": 1, "title": "a", "body": "", "labels": [{"name":"auto-fix"}],
         "state": "OPEN", "updatedAt": "2026-05-09T01:00:00Z"},
        {"number": 2, "title": "b", "body": "", "labels": [{"name":"auto-fix"}],
         "state": "OPEN", "updatedAt": "2026-05-09T02:00:00Z"},
        {"number": 3, "title": "c", "body": "", "labels": [{"name":"auto-fix"}],
         "state": "OPEN", "updatedAt": "2026-05-09T03:00:00Z"},
    ]
    actions = plan_actions(issues, led, cfg, today="2026-05-09")
    promoted = [a for a in actions if a["op"] == "promote"]
    assert len(promoted) == 2
    assert {a["number"] for a in promoted} == {"1", "2"}


def test_plan_actions_cancels_when_label_removed():
    cfg = _cfg()
    led = Ledger.empty()
    led.upsert_seen("5", title="t", labels=["auto-fix"], updated_at="x")
    led.transition("5", "assigned")
    issues = [
        {"number": 5, "title": "t", "body": "", "labels": [{"name":"bug"}],
         "state": "OPEN", "updatedAt": "x"}
    ]
    actions = plan_actions(issues, led, cfg, today="2026-05-09")
    assert any(a["op"] == "cancel" and a["number"] == "5" for a in actions)
