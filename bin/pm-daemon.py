#!/usr/bin/env python3
"""PM daemon. The non-Claude project manager.

Owns:
  - state.json   single source of truth for the project plan and worker registry
  - events/      append-only inbox for events from worker sessions
  - tasks/       per-worker assignment files (one .task per worker)
  - nags/        per-worker nag files written when a task lingers too long

Worker sessions communicate by:
  - dropping JSON events into events/   (input to PM)
  - reading their own tasks/<sid>.task  (output from PM)
  - reading their own nags/<sid>.nag    (output from PM)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT             = Path(os.environ["TM_ROOT"]).resolve() if os.environ.get("TM_ROOT") else Path(__file__).resolve().parent.parent
EVENTS_DIR       = ROOT / "events"
EVENTS_PROCESSED = ROOT / "events" / ".processed"
TASKS_DIR        = ROOT / "tasks"
NAGS_DIR         = ROOT / "nags"
ESCALATIONS_DIR  = ROOT / "escalations"
STATE_FILE       = ROOT / "pm-state.json"
PLAN_FILE        = ROOT / "plan.md"
LOG_FILE         = ROOT / "pm.log"

POLL_SEC         = 0.25   # how often the daemon ticks
NAG_AFTER_SEC    = 40     # nag a worker that has been busy this long
NAG_INTERVAL_SEC = 40     # then re-nag every this often
STALE_AFTER_SEC  = 120    # consider a worker dead if no events for this long
                          # (was 300; lowered so crashed Claude windows free
                          # their task in ~2 min instead of 5. Two nag cycles
                          # at 40s+80s give a slow-but-alive worker a chance
                          # to respond before reclaim.)

STRICT           = os.environ.get("PM_STRICT", "0") == "1"  # if set, run tm-review on each done event
MAX_REVIEW       = 3      # strict mode: give up on a task after this many review FAILs
MAX_SIGNAL       = 5      # give up on a task after this many signal_cmd FAILs
REVIEW_BIN       = Path(__file__).resolve().parent / "tm-review"

# ── Iterate mode: agent-self-iterator-style outer loop ──
ITERATE          = os.environ.get("PM_ITERATE", "0") == "1"
ASSESS           = os.environ.get("PM_ASSESS",  "0") == "1"   # assessor-driven instead of full re-plan
GOAL_REVIEW      = os.environ.get("PM_GOAL_REVIEW", "0") == "1"   # goal-level exit gate via tm-goal-review
FOREVER          = os.environ.get("PM_FOREVER", "0") == "1"   # never exit on all_done; idle waiting for add_task / shutdown
QUIET_STREAK     = int(os.environ.get("PM_QUIET_STREAK", "2"))    # consecutive exhausted rounds → exit
MAX_OUTER_ITERS  = int(os.environ.get("PM_MAX_OUTER_ITERS", "8")) # hard cap on outer rounds
MAX_ASSESSMENTS  = int(os.environ.get("PM_MAX_ASSESSMENTS", "30")) # hard cap on assessor invocations
MAX_RELOAD_FAILS = 3                                              # consecutive profile/plan errors → exit
PROFILE_BIN      = Path(__file__).resolve().parent / "tm-profile"
PLAN_BIN         = Path(__file__).resolve().parent / "tm-plan"
ASSESS_BIN       = Path(__file__).resolve().parent / "tm-assess"
GOAL_REVIEW_BIN  = Path(__file__).resolve().parent / "tm-goal-review"

# ────────── helpers ──────────

def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def parse_iso(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.rstrip("Z"))

def log(msg: str) -> None:
    # The launcher redirects stdout/stderr to pm.log, so a single print is enough.
    print(f"[{now_iso()}] {msg}", flush=True)


def emit_escalation(task: dict, kind: str, reason: str) -> None:
    """Surface a permanent-fail task as an escalation file. Replaces the silent
    `failed` outcome with a visible breadcrumb a human (or a wrapping loop) can
    pick up. kind ∈ {"review","signal"}. Idempotent — safe to call once per
    permanent fail."""
    ESCALATIONS_DIR.mkdir(parents=True, exist_ok=True)
    task["escalation_kind"] = kind
    task["escalation_ts"]   = now_iso()
    task["escalation_reason"] = reason
    out = ESCALATIONS_DIR / f"task-{task['id']:04d}.md"
    lines = [
        f"# Escalated task #{task['id']}",
        "",
        f"- **kind:** {kind} ({'review' if kind=='review' else 'signal_cmd'} kept failing)",
        f"- **escalated_at:** {task['escalation_ts']}",
        f"- **last_reason:** {reason}",
        f"- **title:** {task['title']}",
    ]
    if task.get("signal_cmd"):
        lines += ["", f"**signal_cmd:** `{task['signal_cmd']}`"]
    if task.get("summary"):
        lines += ["", f"**worker's last summary:**", "", f"> {task['summary']}"]
    if task.get("review_history"):
        lines += ["", "## review history"]
        for r in task["review_history"]:
            lines.append(f"- [{r.get('ts','?')}] {r.get('verdict','?')} — {r.get('reason','')}")
    if task.get("signal_history"):
        lines += ["", "## signal history"]
        for s in task["signal_history"]:
            lines.append(f"- [{s.get('ts','?')}] exit={s.get('exit_code','?')}")
            tail = (s.get("output_tail") or "").strip()
            if tail:
                lines.append("  ```")
                for ln in tail.splitlines()[-10:]:
                    lines.append(f"  {ln}")
                lines.append("  ```")
    out.write_text("\n".join(lines) + "\n")
    log(f"🚨 ESCALATED task #{task['id']} ({kind}): {reason} → {out.relative_to(ROOT)}")

# ────────── plan & state ──────────

NUM_LINE    = re.compile(r"^\s*(\d+)\.\s+(.+)$")
BUL_LINE    = re.compile(r"^\s*[-*]\s+(.+)$")
SIGNAL_LINE = re.compile(r"^\s+signal(?:_cmd)?\s*:\s*(.+)$")
DEP_LINE    = re.compile(r"^\s+depends?_on\s*:\s*(.+)$", re.IGNORECASE)
INDENT_LINE = re.compile(r"^\s+\S")  # any indented continuation

def parse_plan(text: str) -> list[dict]:
    """Plan.md grammar:

        1. <task title>
           signal_cmd: <shell command, optional>
           <continuation lines optional, indented>

        2. <next task>
        ...

    Bullet lines `- ...` also work but can't carry signal_cmd.
    """
    tasks: list[dict] = []
    current: dict | None = None

    def flush():
        nonlocal current
        if current:
            tasks.append(current)
            current = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            # blank line ends the current task block
            flush()
            continue

        m_num = NUM_LINE.match(line)
        m_bul = BUL_LINE.match(line) if not m_num else None
        if m_num or m_bul:
            flush()
            title = (m_num or m_bul).group(2 if m_num else 1).strip()
            current = {
                "id": len(tasks) + 1,
                "title": title,
                "signal_cmd": None,
                "depends_on": [],       # list[int]: parent task ids; all must be done before this can start
                "status": "todo",
                "assigned_to": None,
                "started_ts": None,
                "completed_ts": None,
                "last_nag_ts": None,
                "summary": None,
                "review_attempts": 0,
                "review_history": [],
                "signal_attempts": 0,
                "signal_history": [],   # list of {exit_code, ts, output_tail}
            }
            continue

        if current and SIGNAL_LINE.match(line):
            current["signal_cmd"] = SIGNAL_LINE.match(line).group(1).strip()
            continue

        if current and DEP_LINE.match(line):
            raw = DEP_LINE.match(line).group(1).strip().strip("[]")
            current["depends_on"] = [
                int(x) for x in re.split(r"[,\s]+", raw) if x.strip().isdigit()
            ]
            continue

        if current and INDENT_LINE.match(line):
            # extension to title
            current["title"] = (current["title"] + " " + line.strip()).strip()
            continue

        # non-matching top-level line — close any open task
        flush()

    flush()
    return tasks

def load_state() -> dict:
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
        # Migrate older state files that predate depends_on.
        for t in s.get("tasks", []):
            t.setdefault("depends_on", [])
        return s
    if not PLAN_FILE.exists():
        log(f"WARN: no plan.md at {PLAN_FILE}; starting with empty plan")
        tasks = []
    else:
        tasks = parse_plan(PLAN_FILE.read_text())
        log(f"loaded {len(tasks)} tasks from plan.md")
    return {"tasks": tasks, "workers": {}}

def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)

# ────────── review (strict mode) ──────────

def run_review(task: dict) -> tuple[str, str]:
    """Synchronously call tm-review for one task. Returns (verdict, reason)."""
    log(f"  reviewing task #{task['id']}…")
    try:
        proc = subprocess.run(
            [str(REVIEW_BIN), str(task["id"]), task["title"], task.get("summary") or ""],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return ("FAIL", "review timed out after 180s")
    except Exception as e:
        return ("FAIL", f"review subprocess error: {e}")
    out = proc.stdout.strip().splitlines()
    if not out:
        return ("FAIL", "review produced no output")
    try:
        d = json.loads(out[-1])
        return (d.get("verdict", "FAIL"), d.get("reason", "(no reason)"))
    except Exception:
        return ("FAIL", "could not parse review output: " + (out[-1] if out else ""))


# ────────── event processing ──────────

def process_events(state: dict) -> None:
    EVENTS_PROCESSED.mkdir(parents=True, exist_ok=True)
    # Skip *.tmp files — those are atomic-rename staging files mid-write.
    files = sorted(
        p for p in EVENTS_DIR.glob("*.json")
        if p.is_file() and not p.name.endswith(".tmp")
    )
    for f in files:
        try:
            ev = json.loads(f.read_text())
        except Exception as e:
            log(f"BAD EVENT {f.name}: {e}")
            f.unlink(missing_ok=True)
            continue

        sid  = ev.get("session_id", "unknown")
        typ  = ev.get("type", "?")
        ts   = ev.get("ts", now_iso())
        data = ev.get("data") or {}
        log(f"event {typ} sid={sid[:8]} data={data}")

        # last_seen_ts must reflect when the daemon CONFIRMED the worker is
        # alive (= now, when we're processing the event), not when the worker
        # emitted the event. Otherwise events backed up while the daemon was
        # down get a stale-on-arrival timestamp and expire_stale_workers
        # reaps the worker the moment we read its join event.
        seen_now = now_iso()
        w = state["workers"].setdefault(sid, {
            "status": "idle", "current_task_id": None,
            "role": "executor",
            "joined_ts": seen_now, "last_seen_ts": seen_now,
        })
        w["last_seen_ts"] = seen_now

        if typ == "join":
            # A re-join after going stale resurrects the worker.
            w["status"] = "idle"
            w["current_task_id"] = None
            # Role declared at SessionStart: "executor" (default) or "planner".
            # Planners don't take exec tasks; they emit add_task/assess_clean.
            if data.get("role"):
                w["role"] = data["role"]
            log(f"  worker {sid[:12]} (re)joined as idle role={w.get('role','executor')}")
        elif typ == "done":
            tid = w.get("current_task_id")
            if tid is not None:
                task = next((t for t in state["tasks"] if t["id"] == tid), None)
                if task is not None:
                    task["summary"] = data.get("summary")
                    if STRICT:
                        verdict, reason = run_review(task)
                        task["review_attempts"] += 1
                        task["review_history"].append(
                            {"verdict": verdict, "reason": reason, "ts": now_iso()}
                        )
                        if verdict == "PASS":
                            task["status"] = "done"
                            task["completed_ts"] = now_iso()
                            log(f"  ✓ task #{task['id']} reviewed PASS: {reason}")
                        elif task["review_attempts"] >= MAX_REVIEW:
                            task["status"] = "failed"
                            task["completed_ts"] = now_iso()
                            emit_escalation(task, "review", reason)
                        else:
                            # back to todo, will be re-assigned with feedback
                            task["status"] = "todo"
                            task["assigned_to"] = None
                            task["started_ts"] = None
                            log(f"  ↻ task #{task['id']} review FAIL ({task['review_attempts']}/{MAX_REVIEW}): {reason}")
                    else:
                        task["status"] = "done"
                        task["completed_ts"] = ts
            w["status"] = "idle"
            w["current_task_id"] = None
        elif typ == "add_task":
            # Assessor (or any privileged caller) is queueing a new task on the fly.
            title = (data.get("title") or "").strip()
            if not title:
                log("  ignored add_task with empty title")
            else:
                new_id = max((t["id"] for t in state["tasks"]), default=0) + 1
                deps = data.get("depends_on") or []
                if isinstance(deps, str):
                    deps = [int(x) for x in re.split(r"[,\s]+", deps) if x.strip().isdigit()]
                else:
                    deps = [int(d) for d in deps if str(d).isdigit()]
                new_task = {
                    "id": new_id,
                    "title": title,
                    "signal_cmd": (data.get("signal_cmd") or "").strip() or None,
                    "depends_on": deps,
                    "status": "todo",
                    "assigned_to": None,
                    "started_ts": None,
                    "completed_ts": None,
                    "last_nag_ts": None,
                    "summary": None,
                    "review_attempts": 0,
                    "review_history": [],
                    "signal_attempts": 0,
                    "signal_history": [],
                    "source": data.get("source", "assessor"),
                }
                state["tasks"].append(new_task)
                state["assess_clean_streak"] = 0
                log(f"  ＋ assessor queued task #{new_id}: {title[:80]}")
        elif typ == "assess_clean":
            state["assess_clean_streak"] = state.get("assess_clean_streak", 0) + 1
            log(f"  assessor: clean (streak {state['assess_clean_streak']}/{QUIET_STREAK}) — {data.get('reason','')}")
        elif typ == "signal_failed":
            tid = w.get("current_task_id")
            if tid is not None:
                task = next((t for t in state["tasks"] if t["id"] == tid), None)
                if task is not None:
                    task["signal_attempts"] += 1
                    task["signal_history"].append({
                        "exit_code": data.get("exit_code"),
                        "ts": now_iso(),
                        "output_tail": data.get("output_tail", "")[-1000:],
                    })
                    if task["signal_attempts"] >= MAX_SIGNAL:
                        task["status"] = "failed"
                        task["completed_ts"] = now_iso()
                        last_tail = (task["signal_history"][-1].get("output_tail") or "").strip()
                        emit_escalation(task, "signal",
                            f"signal_cmd failed {MAX_SIGNAL}x; last exit={data.get('exit_code')}; "
                            f"tail: {last_tail[-200:]}")
                    else:
                        # back to todo, will be re-assigned with feedback
                        task["status"] = "todo"
                        task["assigned_to"] = None
                        task["started_ts"] = None
                        log(f"  ↻ task #{task['id']} signal FAIL ({task['signal_attempts']}/{MAX_SIGNAL}) exit={data.get('exit_code')}")
            w["status"] = "idle"
            w["current_task_id"] = None
        elif typ == "progress":
            pass  # last_seen_ts update is enough
        elif typ == "shutdown":
            # Cooperative shutdown signal — usually from a supervisor agent
            # deciding the project has truly converged and tokens shouldn't
            # be burned idling.
            reason = data.get("reason", "(no reason)")
            log(f"🛑 shutdown event from {sid[:8]}: {reason}")
            state["_shutdown_requested"] = {"sid": sid, "reason": reason, "ts": now_iso()}

        elif typ == "leave":
            tid = w.get("current_task_id")
            if tid is not None:
                task = next((t for t in state["tasks"] if t["id"] == tid), None)
                if task is not None:
                    task["status"] = "todo"
                    task["assigned_to"] = None
                    task["started_ts"] = None
            w["status"] = "left"
            w["current_task_id"] = None
        else:
            log(f"WARN: unknown event type {typ!r}")

        f.rename(EVENTS_PROCESSED / f.name)

# ────────── assignment & nagging ──────────

def assign_tasks(state: dict) -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    # DAG gate: a task is only ready when every parent in depends_on is done.
    # Tasks with no depends_on are always ready (preserves single-track behavior).
    done_ids = {t["id"] for t in state["tasks"] if t["status"] == "done"}
    todo = [
        t for t in state["tasks"]
        if t["status"] == "todo"
        and all(d in done_ids for d in (t.get("depends_on") or []))
    ]
    if not todo:
        return
    # Only EXECUTORs take dispatched work. PLANNERs and SUPERVISORs are
    # creative roles that emit events of their own (add_task, shutdown).
    NON_EXEC_ROLES = ("planner", "supervisor")
    idle = [
        (sid, w) for sid, w in state["workers"].items()
        if w["status"] == "idle" and w.get("role", "executor") not in NON_EXEC_ROLES
    ]
    for (sid, w), task in zip(idle, todo):
        task["status"] = "in-progress"
        task["assigned_to"] = sid
        task["started_ts"] = now_iso()
        task["last_nag_ts"] = None
        w["status"] = "busy"
        w["current_task_id"] = task["id"]
        body = f"task #{task['id']}: {task['title']}\n"
        if task.get("signal_cmd"):
            body += f"\nsignal_cmd: {task['signal_cmd']}\n"
            body += "(tm-done will run signal_cmd; it must exit 0 or the task is re-queued)\n"
        # Prepend review feedback if this is a re-attempt.
        if task.get("review_history"):
            last = task["review_history"][-1]
            body += (
                f"\n⚠️ this task previously failed review "
                f"({task['review_attempts']}/{MAX_REVIEW}).\n"
                f"reviewer's feedback: {last['reason']}\n"
                f"address that before reporting done.\n"
            )
        if task.get("signal_history"):
            last = task["signal_history"][-1]
            body += (
                f"\n⚠️ signal_cmd previously exited {last['exit_code']} "
                f"({task['signal_attempts']}/{MAX_SIGNAL}).\n"
                f"last output tail:\n{last['output_tail']}\n"
            )
        (TASKS_DIR / f"{sid}.task").write_text(body)
        # Sidecar with just the signal command for tm-done to read.
        sig_path = TASKS_DIR / f"{sid}.signal"
        if task.get("signal_cmd"):
            sig_path.write_text(task["signal_cmd"] + "\n")
        elif sig_path.exists():
            sig_path.unlink()
        retag = []
        if task.get("review_attempts"): retag.append(f"review-retry {task['review_attempts']}")
        if task.get("signal_attempts"): retag.append(f"signal-retry {task['signal_attempts']}")
        retag_s = f" ({', '.join(retag)})" if retag else ""
        log(f"assigned task #{task['id']} to {sid[:8]}{retag_s}: {task['title']}")

def nag_workers(state: dict) -> None:
    NAGS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.utcnow()
    for sid, w in state["workers"].items():
        if w["status"] != "busy":
            continue
        tid = w.get("current_task_id")
        task = next((t for t in state["tasks"] if t["id"] == tid), None)
        if not task or not task.get("started_ts"):
            continue
        elapsed = (now - parse_iso(task["started_ts"])).total_seconds()
        if elapsed < NAG_AFTER_SEC:
            continue
        last = task.get("last_nag_ts")
        if last and (now - parse_iso(last)).total_seconds() < NAG_INTERVAL_SEC:
            continue
        nag_path = NAGS_DIR / f"{sid}.nag"
        nag_path.write_text(
            f"⏰ PM nag: task #{task['id']} ({task['title']}) has been "
            f"in-progress for {int(elapsed)}s. Status update? Push harder. "
            f"If blocked, run `tm-done \"blocked: <why>\"` to surface it.\n"
        )
        task["last_nag_ts"] = now_iso()
        log(f"nagged {sid[:8]} on task #{task['id']} (elapsed {int(elapsed)}s)")

def expire_stale_workers(state: dict) -> None:
    """A worker that hasn't sent an event in STALE_AFTER_SEC is gone.
    Reclaim its task, drop sidecar files, remove it from the registry.
    Keeping ghost entries here is what made the worker count silently grow
    (e.g. after each /resume or terminal restart, which gets a fresh sid)."""
    now = datetime.datetime.utcnow()
    for sid in list(state["workers"].keys()):
        w = state["workers"][sid]
        if w["status"] == "left":
            del state["workers"][sid]
            continue
        last = w.get("last_seen_ts")
        if not last:
            continue
        if (now - parse_iso(last)).total_seconds() > STALE_AFTER_SEC:
            tid = w.get("current_task_id")
            if tid is not None:
                task = next((t for t in state["tasks"] if t["id"] == tid), None)
                if task is not None and task["status"] == "in-progress":
                    task["status"] = "todo"
                    task["assigned_to"] = None
                    task["started_ts"] = None
                    log(f"reclaimed task #{tid} from stale worker {sid[:8]}")
            for sidecar in (TASKS_DIR / f"{sid}.task",
                            TASKS_DIR / f"{sid}.signal",
                            NAGS_DIR  / f"{sid}.nag"):
                if sidecar.exists():
                    sidecar.unlink()
            del state["workers"][sid]
            log(f"GC stale worker {sid[:8]}")

def all_done(state: dict) -> bool:
    """Plan is finished if every task is either done or permanently failed."""
    return bool(state["tasks"]) and all(
        t["status"] in ("done", "failed") for t in state["tasks"]
    )


# ────────── assessor (incremental, drip-feed) ──────────

def run_goal_review() -> tuple[str, str]:
    """Synchronously run tm-goal-review. Returns (verdict, reason).
    verdict ∈ {"DONE","CONTINUE"} — DONE means goal.md is fully satisfied."""
    log("GOAL_REVIEW: judging workspace vs goal.md…")
    try:
        proc = subprocess.run(
            [str(GOAL_REVIEW_BIN)],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return ("CONTINUE", "goal-review timed out after 300s")
    except Exception as e:
        return ("CONTINUE", f"goal-review subprocess error: {e}")
    out = proc.stdout.strip().splitlines()
    if not out:
        return ("CONTINUE", "goal-review produced no output")
    try:
        d = json.loads(out[-1])
        return (d.get("verdict", "CONTINUE"), d.get("reason", "(no reason)"))
    except Exception:
        return ("CONTINUE", "could not parse goal-review output: " + out[-1])


def run_assessor() -> bool:
    """Synchronously spawn the assessor; it writes an event we'll process next tick.
    Returns True iff the assessor ran cleanly (regardless of verdict)."""
    log("ASSESS: assessor running…")
    try:
        proc = subprocess.run(
            [str(ASSESS_BIN)],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        log(f"  assessor error: {e}")
        return False
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-400:]
        log(f"  assessor exit={proc.returncode} stderr: {tail}")
        return False
    return True


# ────────── outer iteration loop (agent-self-iterator style) ──────────

def reload_plan(state: dict) -> tuple[int, bool]:
    """Re-profile workspace, re-plan, swap in the new tasks. Workers stay registered.
    Returns (n_new_tasks, exhausted). exhausted=True if manifest says nothing left to do
    OR profile/plan failed (caller decides whether to retry or give up)."""
    log("ITERATE: re-profiling workspace…")
    try:
        proc = subprocess.run(
            [str(PROFILE_BIN), "--force"],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        log(f"  profile error: {e}")
        return (0, True)
    if proc.returncode != 0:
        log(f"  profile exit={proc.returncode}; stderr tail: {(proc.stderr or '')[-400:]}")
        return (0, True)

    manifest_path = ROOT / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as e:
        log(f"  manifest unreadable: {e}")
        return (0, True)

    dims = manifest.get("dimensions", []) or []
    unsat = [d for d in dims if not d.get("satisfied")]
    log(f"  manifest: {len(unsat)}/{len(dims)} dimensions unsatisfied")
    if not unsat:
        return (0, True)  # exhausted: nothing left to fix

    log("ITERATE: re-planning…")
    try:
        proc = subprocess.run(
            [str(PLAN_BIN), "--optimize", "--force"],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as e:
        log(f"  plan error: {e}")
        return (0, True)
    if proc.returncode != 0:
        log(f"  plan exit={proc.returncode}; stderr tail: {(proc.stderr or '')[-400:]}")
        return (0, True)

    new_tasks = parse_plan(PLAN_FILE.read_text())
    if not new_tasks:
        log("  new plan parsed to zero tasks")
        return (0, True)

    # Append history of completed/failed tasks so we can audit the run.
    state.setdefault("history", []).append({
        "ended_ts": now_iso(),
        "tasks": [
            {"id": t["id"], "title": t["title"], "status": t["status"], "summary": t.get("summary")}
            for t in state["tasks"]
        ],
    })

    # Renumber new tasks so IDs don't collide with history.
    max_id = max((t["id"] for t in state["tasks"]), default=0)
    if not state.get("history"):
        max_id = 0
    for i, t in enumerate(new_tasks, start=1):
        t["id"] = max_id + i

    state["tasks"] = new_tasks
    # Idle-out any worker that was busy on a now-replaced task.
    for sid, w in state["workers"].items():
        w["current_task_id"] = None
        if w.get("status") == "busy":
            w["status"] = "idle"

    log(f"  loaded {len(new_tasks)} new tasks (renumbered to start at #{max_id+1})")
    return (len(new_tasks), False)

# ────────── main ──────────

def main() -> int:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    NAGS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    state.setdefault("assess_clean_streak", 0)
    save_state(state)
    mode_bits = []
    mode_bits.append("STRICT" if STRICT else "trust")
    if FOREVER:
        mode_bits.append("FOREVER (idle on all_done; exit only on shutdown event)")
    elif ASSESS:
        mode_bits.append(f"ASSESS (quiet_streak={QUIET_STREAK}, max_assessments={MAX_ASSESSMENTS})")
    elif GOAL_REVIEW:
        mode_bits.append(f"GOAL_REVIEW (quiet_streak={QUIET_STREAK}, max_outer={MAX_OUTER_ITERS})")
    elif ITERATE:
        mode_bits.append(f"ITERATE (quiet_streak={QUIET_STREAK}, max_outer={MAX_OUTER_ITERS})")
    log(f"PM daemon started. tasks: {len(state['tasks'])}. mode: {', '.join(mode_bits)}")

    exhausted_streak = 0
    reload_fails = 0
    outer_iter = 0
    assessments = 0

    try:
        first_idle_logged = False
        while True:
            process_events(state)
            expire_stale_workers(state)

            # Cooperative shutdown — supervisor agent (or any caller) writes a
            # shutdown event; we honor it AFTER processing remaining events so
            # in-flight work isn't dropped.
            if state.get("_shutdown_requested"):
                req = state["_shutdown_requested"]
                log(f"🛑 honoring shutdown from {str(req.get('sid'))[:8]}: {req.get('reason')}")
                save_state(state)
                return 0

            if not all_done(state):
                first_idle_logged = False  # so the next time we hit idle, we log again
                assign_tasks(state)
                nag_workers(state)
            save_state(state)

            if all_done(state):
                if ASSESS:
                    # Assessor mode: ask the judge if there's anything more to do.
                    if state.get("assess_clean_streak", 0) >= QUIET_STREAK:
                        log(f"🎉 assessor declared clean for {QUIET_STREAK} consecutive rounds; exiting")
                        return 0
                    if assessments >= MAX_ASSESSMENTS:
                        log(f"hit MAX_ASSESSMENTS={MAX_ASSESSMENTS}; exiting")
                        return 0
                    # Need at least one connected (non-stale) worker, otherwise no point
                    # producing tasks.
                    has_active_worker = any(
                        w.get("status") in ("idle","busy") for w in state["workers"].values()
                    )
                    if not has_active_worker:
                        time.sleep(POLL_SEC)
                        continue
                    assessments += 1
                    log(f"── assessment #{assessments} (queue empty, asking assessor) ──")
                    run_assessor()
                    save_state(state)
                    time.sleep(POLL_SEC)
                    continue

                if GOAL_REVIEW:
                    # Goal-driven outer loop: judge against goal.md, re-plan
                    # while reviewer says CONTINUE. Independent of ITERATE
                    # (which uses manifest-based exhaustion instead).
                    outer_iter += 1
                    log(f"── outer iter {outer_iter} (current plan complete) ──")
                    if outer_iter > MAX_OUTER_ITERS:
                        log(f"hit MAX_OUTER_ITERS={MAX_OUTER_ITERS}; exiting")
                        return 0
                    verdict, reason = run_goal_review()
                    log(f"goal-review verdict={verdict}: {reason}")
                    if verdict == "DONE":
                        exhausted_streak += 1
                        log(f"  ✓ goal met (streak {exhausted_streak}/{QUIET_STREAK})")
                        if exhausted_streak >= QUIET_STREAK:
                            log(f"🎉 goal satisfied for {QUIET_STREAK} consecutive rounds; exiting")
                            return 0
                        time.sleep(2.0)
                        continue
                    exhausted_streak = 0
                    n_new, _ = reload_plan(state)
                    save_state(state)
                    if n_new == 0:
                        log("goal-review CONTINUE but re-plan produced 0 tasks; exiting")
                        return 0
                    time.sleep(2.0)
                    continue

                if FOREVER:
                    # Don't exit. Idle waiting for new add_task events
                    # (typically from a planner agent) or a shutdown event.
                    if not first_idle_logged:
                        log("✓ all current tasks complete; PM idling in FOREVER mode "
                            "(send shutdown event to exit, or new add_task to resume)")
                        first_idle_logged = True
                    time.sleep(POLL_SEC)
                    continue

                if not ITERATE:
                    log("🎉 plan complete; daemon exiting")
                    return 0

                outer_iter += 1
                log(f"── outer iter {outer_iter} (current plan complete) ──")
                if outer_iter > MAX_OUTER_ITERS:
                    log(f"hit MAX_OUTER_ITERS={MAX_OUTER_ITERS}; exiting")
                    return 0

                n_new, exhausted = reload_plan(state)
                save_state(state)
                if exhausted:
                    if n_new == 0:
                        # Either truly exhausted (manifest all green) or reload failed.
                        # Distinguish: check if manifest had any dims at all.
                        try:
                            mani = json.loads((ROOT / "manifest.json").read_text())
                            dims = mani.get("dimensions") or []
                            unsat = [d for d in dims if not d.get("satisfied")]
                            if dims and not unsat:
                                exhausted_streak += 1
                                reload_fails = 0
                                log(f"  ✓ truly exhausted (streak {exhausted_streak}/{QUIET_STREAK})")
                                if exhausted_streak >= QUIET_STREAK:
                                    log("🎉 manifest fully satisfied for "
                                        f"{QUIET_STREAK} consecutive rounds; exiting")
                                    return 0
                            else:
                                reload_fails += 1
                                log(f"  reload failed (count {reload_fails}/{MAX_RELOAD_FAILS})")
                                if reload_fails >= MAX_RELOAD_FAILS:
                                    log(f"too many reload failures; exiting")
                                    return 0
                        except Exception:
                            reload_fails += 1
                            if reload_fails >= MAX_RELOAD_FAILS:
                                log("manifest unreadable repeatedly; exiting")
                                return 0
                    # Wait a moment before continuing; loop will fall through to nothing-to-do.
                    time.sleep(2.0)
                else:
                    exhausted_streak = 0
                    reload_fails = 0

            time.sleep(POLL_SEC)
    except KeyboardInterrupt:
        log("PM daemon stopped (SIGINT)")
        return 0

if __name__ == "__main__":
    sys.exit(main())
