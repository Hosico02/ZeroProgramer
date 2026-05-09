"""state.json — issue-level ledger maintained by the watcher.

Distinct from pm-state.json (which the sub-PM owns). This file tracks the
business-level state machine of each GitHub issue we've seen.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

STATE_FILE = "state.json"

# Authoritative list (and order is meaningful for displays).
STATUSES = ("seen", "assigned", "resolved", "failed", "cancelled")
TERMINAL = ("resolved", "failed", "cancelled")

# Map of legal transitions. {} value means terminal (no exits).
_LEGAL: dict[str, set[str]] = {
    "seen":      {"assigned", "cancelled"},
    "assigned":  {"resolved", "failed", "cancelled"},
    "resolved":  set(),
    "failed":    set(),
    "cancelled": set(),
}


class IllegalTransition(Exception):
    """Raised when caller asks for a transition not in _LEGAL."""


@dataclasses.dataclass
class IssueRecord:
    status: str
    title: str
    labels: list[str]
    updated_at: str
    worktree: str | None = None
    branch: str | None = None
    task_id: int | None = None
    pr_number: int | None = None
    session_id: str | None = None
    first_seen_ts: str | None = None
    attempts: int = 0


@dataclasses.dataclass
class Ledger:
    version: int = 1
    last_poll_ts: str | None = None
    daily_spawn_count: int = 0
    daily_spawn_date: str | None = None
    issues: dict[str, IssueRecord] = dataclasses.field(default_factory=dict)

    @classmethod
    def empty(cls) -> "Ledger":
        return cls()

    def upsert_seen(self, num: str, *, title: str, labels: list[str],
                    updated_at: str) -> IssueRecord:
        rec = self.issues.get(num)
        if rec is None:
            rec = IssueRecord(
                status="seen", title=title, labels=labels,
                updated_at=updated_at, first_seen_ts=_now_iso(),
            )
            self.issues[num] = rec
            return rec
        # Refresh metadata; do not perturb status.
        rec.title = title
        rec.labels = labels
        rec.updated_at = updated_at
        return rec

    def transition(self, num: str, dst: str, **fields: Any) -> None:
        if dst not in STATUSES:
            raise IllegalTransition(f"unknown status: {dst!r}")
        rec = self.issues.get(num)
        if rec is None:
            raise IllegalTransition(f"unknown issue {num!r}")
        if dst not in _LEGAL[rec.status]:
            raise IllegalTransition(
                f"illegal transition: issue {num} {rec.status} → {dst}"
            )
        rec.status = dst
        for k, v in fields.items():
            if not hasattr(rec, k):
                raise AttributeError(f"IssueRecord has no field {k}")
            setattr(rec, k, v)

    def count_in_flight(self) -> int:
        return sum(1 for r in self.issues.values() if r.status == "assigned")

    def note_spawn(self, today: str) -> None:
        if self.daily_spawn_date != today:
            self.daily_spawn_date = today
            self.daily_spawn_count = 1
        else:
            self.daily_spawn_count += 1


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_dict(led: Ledger) -> dict:
    return {
        "version": led.version,
        "last_poll_ts": led.last_poll_ts,
        "daily_spawn_count": led.daily_spawn_count,
        "daily_spawn_date": led.daily_spawn_date,
        "issues": {k: dataclasses.asdict(v) for k, v in led.issues.items()},
    }


def _from_dict(d: dict) -> Ledger:
    issues = {k: IssueRecord(**v) for k, v in (d.get("issues") or {}).items()}
    return Ledger(
        version=d.get("version", 1),
        last_poll_ts=d.get("last_poll_ts"),
        daily_spawn_count=d.get("daily_spawn_count", 0),
        daily_spawn_date=d.get("daily_spawn_date"),
        issues=issues,
    )


def load_ledger(bot_root: Path) -> Ledger:
    p = Path(bot_root) / STATE_FILE
    if not p.exists():
        return Ledger.empty()
    return _from_dict(json.loads(p.read_text()))


def save_ledger(bot_root: Path, led: Ledger) -> None:
    p = Path(bot_root) / STATE_FILE
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_to_dict(led), indent=2, sort_keys=True))
    os.replace(tmp, p)
