"""state.json schema, atomic IO, transition validator."""
import datetime as dt
import json

import pytest

from lib.state import (
    IssueRecord, Ledger, IllegalTransition, STATUSES, load_ledger, save_ledger,
)


def test_legal_transition_seen_to_assigned(tmp_bot_root):
    led = Ledger.empty()
    led.upsert_seen("42", title="t", labels=["auto-fix"], updated_at="2026-05-09T00:00:00Z")
    assert led.issues["42"].status == "seen"
    led.transition("42", "assigned", task_id=7,
                   worktree="/abs/wt", branch="auto-fix/issue-42",
                   session_id="abcd1234")
    assert led.issues["42"].status == "assigned"
    assert led.issues["42"].task_id == 7


def test_illegal_jump_seen_to_resolved(tmp_bot_root):
    led = Ledger.empty()
    led.upsert_seen("42", title="t", labels=[], updated_at="x")
    with pytest.raises(IllegalTransition):
        led.transition("42", "resolved")


@pytest.mark.parametrize(
    "src,dst",
    [
        ("seen", "cancelled"),         # user closes/unlabels before fixer runs
        ("assigned", "resolved"),      # happy path
        ("assigned", "failed"),        # PM escalation
        ("assigned", "cancelled"),     # user cancels mid-flight
        ("seen", "assigned"),          # promotion
    ],
)
def test_legal_transitions_parametrized(src, dst):
    led = Ledger.empty()
    led.upsert_seen("1", title="x", labels=[], updated_at="x")
    if src != "seen":
        led.transition("1", src)
    led.transition("1", dst)
    assert led.issues["1"].status == dst


def test_terminal_states_reject_further_transitions():
    led = Ledger.empty()
    led.upsert_seen("1", title="x", labels=[], updated_at="x")
    led.transition("1", "assigned")
    led.transition("1", "resolved")
    with pytest.raises(IllegalTransition):
        led.transition("1", "assigned")


def test_atomic_save_load_roundtrip(tmp_bot_root):
    led = Ledger.empty()
    led.upsert_seen("9", title="t", labels=["auto-fix"], updated_at="2026-05-09T00:00:00Z")
    save_ledger(tmp_bot_root, led)
    led2 = load_ledger(tmp_bot_root)
    assert led2.issues["9"].title == "t"
    assert led2.issues["9"].labels == ["auto-fix"]


def test_save_is_crash_safe_atomic(tmp_bot_root):
    """A partially written .tmp shouldn't appear as the canonical file."""
    led = Ledger.empty()
    save_ledger(tmp_bot_root, led)
    state_file = tmp_bot_root / "state.json"
    assert state_file.exists()
    # No stray .tmp left over
    assert not (tmp_bot_root / "state.json.tmp").exists()


def test_daily_spawn_counter_resets_at_utc_midnight(tmp_bot_root):
    led = Ledger.empty()
    led.daily_spawn_count = 5
    led.daily_spawn_date = "2026-05-08"   # yesterday
    led.note_spawn(today="2026-05-09")
    assert led.daily_spawn_count == 1
    assert led.daily_spawn_date == "2026-05-09"


def test_daily_spawn_counter_increments_same_day(tmp_bot_root):
    led = Ledger.empty()
    led.daily_spawn_date = "2026-05-09"
    led.daily_spawn_count = 2
    led.note_spawn(today="2026-05-09")
    assert led.daily_spawn_count == 3


def test_count_assigned_for_concurrency(tmp_bot_root):
    led = Ledger.empty()
    for n in range(5):
        led.upsert_seen(str(n), title="t", labels=[], updated_at="x")
    led.transition("1", "assigned")
    led.transition("3", "assigned")
    assert led.count_in_flight() == 2


def test_statuses_constant_matches_spec():
    assert set(STATUSES) == {"seen", "assigned", "resolved", "failed", "cancelled"}
