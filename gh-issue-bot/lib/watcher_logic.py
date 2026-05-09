"""Pure decision logic for tm-issue-watcher.

Separated from the CLI/IO entry point so it's unit-testable without git or gh.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

from lib.config import Config
from lib.state import Ledger

ENV_DAY_KEY = "_today"  # exposed only so tests can pin "today"


def _label_names(issue: dict) -> set[str]:
    return {l.get("name") for l in (issue.get("labels") or []) if l.get("name")}


def classify_issue(issue: dict, cfg: Config) -> str:
    """Return one of: 'eligible', 'skip:missing-label', 'skip:fail-label',
    'skip:wontfix', 'skip:closed'."""
    if issue.get("state", "OPEN") != "OPEN":
        return "skip:closed"
    names = _label_names(issue)
    if cfg.fail_label in names:
        return "skip:fail-label"
    if "wontfix" in names:
        return "skip:wontfix"
    if cfg.label not in names:
        return "skip:missing-label"
    return "eligible"


def eligible_for_promote(led: Ledger, cfg: Config, today: str) -> list[str]:
    """Return issue numbers (as strings) currently in `seen` that should be
    promoted to `assigned` this tick, oldest first, capped by max_parallel and
    daily_cap."""
    in_flight = led.count_in_flight()
    cap_remaining = max(0, cfg.max_parallel - in_flight)
    if cap_remaining == 0:
        return []
    if led.daily_spawn_date == today and led.daily_spawn_count >= cfg.daily_cap:
        return []
    daily_remaining = (cfg.daily_cap - led.daily_spawn_count) if led.daily_spawn_date == today else cfg.daily_cap
    slots = min(cap_remaining, daily_remaining)
    if slots <= 0:
        return []
    seen = [(num, rec) for num, rec in led.issues.items() if rec.status == "seen"]
    seen.sort(key=lambda kv: kv[1].updated_at or "")
    return [num for num, _ in seen[:slots]]


def plan_actions(issues: list[dict], led: Ledger, cfg: Config,
                 today: str) -> list[dict]:
    """Return an ordered list of action dicts the caller should execute.
    Each action: {'op': str, 'number': str, ...payload}."""
    actions: list[dict] = []

    issues_by_num = {str(i["number"]): i for i in issues}

    # 1. Upsert eligible issues into the ledger as `seen`.
    for num, issue in issues_by_num.items():
        verdict = classify_issue(issue, cfg)
        if verdict != "eligible":
            continue
        rec = led.issues.get(num)
        if rec is None or rec.status not in ("seen", "assigned"):
            actions.append({
                "op": "upsert_seen", "number": num,
                "title": issue.get("title", ""),
                "labels": list(_label_names(issue)),
                "updated_at": issue.get("updatedAt", ""),
            })

    # 2. Cancel issues we're tracking that no longer satisfy the filter
    #    (label removed, closed, or fail label added) — only if not terminal.
    for num, rec in led.issues.items():
        if rec.status not in ("seen", "assigned"):
            continue
        live_issue = issues_by_num.get(num)
        if live_issue is None:
            actions.append({"op": "cancel", "number": num,
                            "reason": "issue no longer matches filter"})
            continue
        if classify_issue(live_issue, cfg) != "eligible":
            actions.append({"op": "cancel", "number": num,
                            "reason": "filter no longer satisfied"})

    # 3. Promote up to N from `seen` to `assigned` (subject to caps).
    # NB: this requires the ledger to have just been updated with step-1 upserts
    # by the caller before invoking eligible_for_promote. plan_actions is pure;
    # it returns an "upsert_then_promote" plan that the caller applies in order.
    promo_after_upsert = led_with_upserts_applied(led, actions)
    promotes = eligible_for_promote(promo_after_upsert, cfg, today=today)
    for num in promotes:
        issue = issues_by_num[num]
        actions.append({
            "op": "promote", "number": num,
            "title": issue.get("title", ""),
            "body":  issue.get("body", ""),
        })

    return actions


def led_with_upserts_applied(led: Ledger, actions: list[dict]) -> Ledger:
    """Return a shallow-copied ledger with `upsert_seen` actions virtually
    applied (so eligible_for_promote sees them too). Caller still applies the
    real mutations in order from the action list."""
    import copy
    proj = copy.deepcopy(led)
    for a in actions:
        if a["op"] == "upsert_seen":
            proj.upsert_seen(a["number"], title=a["title"],
                             labels=a["labels"], updated_at=a["updated_at"])
    return proj
