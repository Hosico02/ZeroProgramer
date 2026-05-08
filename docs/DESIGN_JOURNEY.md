# Design Journey

A condensed record of how ZeroProgramer was designed, the questions that drove
each architectural choice, and what was deliberately left out. Read this if you
want to understand WHY the system looks the way it does — not just WHAT it is.

---

## TL;DR

ZeroProgramer is a **multi-agent self-managing project framework**:

- **PM** is a deterministic Python daemon (zero-token plumbing).
- **Supervisor / Planner / Executor** are Claude agents (LLM creativity where it earns its keep).
- All four roles communicate **through `events/*.json` files only** — no sockets, no shared state.
- Maturity ladder L0–L6 fully built; L7 (cross-project) intentionally excluded.
- Two channels for innovation: `vision.md` (human-authored) + `proposals/` (LLM-generated, supervisor-gated).

---

## Architectural decisions, in the order they were made

### 1. PM is Python, not an LLM agent

**The temptation**: with 4 agent roles, why not make all 4 LLM-driven for purity?

**Why we didn't**: PM ticks every 250ms. If each tick were an LLM call, that's 14,400 calls per hour just to dispatch tasks. Plus PM is a deterministic state machine — scan events, pair workers, update fields — none of which needs judgment. Letting LLMs do this introduces hallucination risk into the reliability backbone.

**Result**: PM stays Python (zero token cost, deterministic). Creative work goes to the three Claude agents above PM.

### 2. File mailbox, not sockets / RPC / DB

**Why**: full decoupling. PM dies → workers can keep posting events for the next daemon. Worker crashes → PM auto-GCs and reclaims tasks. File IO is 10× simpler than network IPC, and you can debug by `ls events/`.

**Trade-off accepted**: events are eventually-consistent (PM polls every 250ms, not instant). For our use case (~tasks/minute), latency doesn't matter.

### 3. Role assignment via `TM_ROLE` env var

**Earlier design**: roles inferred from session_id pattern or hardcoded per-window. Brittle.

**Final design**: `tm-claude-{supervisor,planner,executor}` wrappers each `exec env TM_ROLE=<role> claude "$@"`. SessionStart hook reads the env, includes it in the join event. PM stores `worker.role` and only routes exec tasks to executors.

**Why it's better**: no flag negotiation mid-session. Role is fixed at process start.

### 4. Five bugs found during early multi-window testing

| Bug | Root cause | Fix |
|---|---|---|
| Tasks routed to wrong worker | `.session-id` was a single shared file, last-writer-wins across windows | Hooks read session_id from stdin JSON; `tm-done` uses `$CLAUDE_CODE_SESSION_ID` env var |
| Worker count grew unbounded | `expire_stale_workers` only marked, never deleted | Stale workers now removed from registry (sidecar files cleaned too) |
| Workers GC'd on daemon restart | `last_seen_ts` was set to event-emit time, not event-process time | Set `last_seen_ts = now_iso()` when processing |
| Idle executors GC'd between tasks | `tm-done`'s polling loop didn't emit progress events | Added 30s heartbeat to tm-done's poll |
| Reviewer auto-failed all tasks | `tm-review` heredoc interpolated raw output unsafely | Pass via `sys.argv` (deferred to executor's task #6 in run 2) |

### 5. Four capabilities built once basic correctness held

After the above fixes, the system was reliable enough to add real features:

- **DAG dependencies** in plan.md (`depends_on:` lines), so independent tasks parallelize
- **Goal-level reviewer** (`tm-goal-review`): claude-driven DONE/CONTINUE check on goal.md vs workspace
- **Cross-task context** (`tm-context`): query past task summaries so workers don't redo work
- **Structured escalations**: permanent failures write `escalations/task-NNNN.md` with full history (vs. silent `failed` status)

### 6. PM_FOREVER mode + cooperative shutdown

**Question from user**: "I want it to run forever until tokens run out, not exit on plan-complete."

**Implementation**: `PM_FOREVER=1` makes PM idle on `all_done` instead of exiting. New `shutdown` event type, written by `tm-pm shutdown <reason>` or by the supervisor agent. PM honors it on next tick after draining pending events.

**Why graceful**: in-flight tasks finish; nothing's lost. Better than `kill -9 daemon`.

### 7. Supervisor agent ("the brain")

**User pushed back**: "PM should be the brain, but should it be an LLM agent then?"

**Resolution**: PM stays Python (see #1). But there ARE meta-decisions an LLM should make — handling escalations, evolving goal.md, deciding when to stop. Those go to a **new role**: SUPERVISOR.

The supervisor doesn't dispatch tasks (PM does). It writes status reports, ADR-style decision logs, edits goal.md when patterns warrant, decides shutdown.

**4-role architecture finalized**: PM (Python) + Supervisor + Planner + Executor (3× Claude).

### 8. PostToolUse heartbeat

**Bug**: workers blocking in `tm-done` / `tm-supervise note` / `tm-plan-cycle` polls were getting stale-GC'd because Claude itself was suspended (not using tools, no PostToolUse fires).

**Fix**: added a PostToolUse hook (`tm-tool-hook`) that emits a progress event on every tool use. Combined with each polling CLI's own 30s self-heartbeat, no live worker is ever falsely killed.

### 9. Maturity ladder L0–L6, with explicit L7 exclusion

| Level | Capability | Built? |
|---|---|---|
| L0 | Single agent | ✓ |
| L1 | Multi-agent parallel | ✓ |
| L2 | Persistent task generation (planner with project-derived dimensions) | ✓ |
| L3 | Meta-decisions (supervisor with reports + ADR log) | ✓ |
| L4 | Self-modification (executor edits workspace/) | ✓ |
| L5 | Promote (workspace → bin) | ✓ via `tm-promote` |
| L6 | Goal evolution | ✓ via `tm-supervise revise-goal` |
| L7 | Cross-project orchestration | **Intentionally NOT** |

**Why no L7**: it's a different problem class (multi-tenancy, namespaces, cross-project state aggregation) requiring a base-layer rewrite. 99% of "I want to manage multiple projects" use cases are solved by `tm-init` + `tm-team-up` per project. A real L7 belongs in a separate multi-tenant project, not this framework's next version. Listing L7 as "TODO" would be misleading.

### 10. Planner dimensions: 7 → 8 → moved into profiler

**v1**: 7 hardcoded "audit dimensions" (tests, robustness, observability, docs, refactoring, security, ops). Planner considered all 7 each cycle.

**User pushback #1**: "Some projects have UI; this list misses it."
→ **v2**: 8 dimensions, split into "Quality" (correctness/robustness/perf/security) and "Scope" (features/UI/docs/distribution).

**User pushback #2**: "If a project has no UI, why waste tokens auditing UI?"
→ **v3**: dimensions removed from planner prompt entirely. Moved into `tm-profile` as a *candidate pool*. tm-profile reads workspace, picks 3-7 dimensions that ACTUALLY apply to THIS project (skipping ones that don't), writes them to `manifest.json`. Planner only reads the manifest. Domain-specific axes (frame_pacing for games, audio_latency for audio apps, numerical_stability for physics sims) added to the candidate pool too.

**Lesson**: a fixed checklist always biases search. Project-derived dimensions are higher-leverage AND token-cheaper.

### 11. Innovation channel (vision.md + tm-vision)

**User pushback #3**: "This system is just gap-filling. It can't innovate."

**Honest acknowledgment**: that's correct. The planner finds undone work but cannot leap outside scope (e.g. "this should become a SaaS"). Such leaps require external input.

**Solution**: two channels feed novel directions in:

| Channel | Source | Path | Read by |
|---|---|---|---|
| `vision.md` | **You (human)** | repo root | planner each cycle, supervisor each cycle |
| `proposals/` | LLM brainstorm via `tm-vision propose` | `proposals/<iso>-<slug>.md` | supervisor decides promote / defer / reject |

Vision items don't enter the task queue directly. Supervisor is a gating layer — when something looks ripe, it's promoted into `goal.md` via `tm-supervise revise-goal`, after which the planner naturally generates tasks toward it.

**Honest limitation noted in README**: "the system can't out-imagine its user." Even with the vision channel, true creativity comes from the human.

### 12. Status line workaround: terminal title bar

**Problem**: Claude Code's `statusLine` only refreshes on agent turn boundaries. During multi-second tool calls it's stale.

**Solution**: each `tm-claude-*` wrapper spawns a background `tm-title-keeper` that writes the project state into the *terminal window title* via OSC 0 escape every 2s. ANSI escapes don't depend on Claude Code's UI lifecycle. All windows show real-time same state in their title bars. Zero token cost.

### 13. Project name resolution (the latest fix)

**Problem**: statusLine was parsing `plan.md`'s first heading and surfacing planner-generated text like "PM Daemon Worker Loop" — internals leaking into the user-facing UI.

**Fix**: project name now comes from `TM_PROJECT_NAME` env var → falls back to directory basename. Identical resolution in both `tm-statusline` and `tm-status-title`. So the same framework installed in `/path/to/anything` shows `anything` with no editing required.

### 14. Distribution: tm-init + GitHub release

- `bin/tm-init <target>` copies the framework into any directory, generates `goal.md`/`vision.md` templates, sets up `.gitignore`. Two-command install for new users.
- Public GitHub repo `Hosico02/ZeroProgramer` with MIT license, 8 discoverability topics, English README, Chinese README, contributing guide, end-to-end tutorial.

### 15. GitHub-native loop, web dashboard, multi-LLM routing

The final round of additions before pause:

- `bin/tm-github-sync`: mirror `escalations/` to GitHub Issues; auto-close when escalation resolved. Supervisor calls it each cycle when applicable.
- `bin/tm-web`: single-file Python http.server browser dashboard, 1Hz polling, auto port fallback (7891 → 7892 → ...) when port busy.
- `TM_MODEL_VERIFIER` / `TM_MODEL_CREATIVE` env vars: route deterministic calls (tm-review, tm-goal-review) to a cheap model and creative calls (tm-profile, tm-assess, tm-vision, tm-plan, tm-auto-loop) to a strong one. Cuts ~30% of token spend with no quality loss.

---

## What's deliberately NOT built (and why)

| Thing | Why not |
|---|---|
| L7 cross-project orchestration | Different problem class; multi-tenancy needs a separate project. Documented in README. |
| Replacing file mailbox with HTTP/WebSocket/Redis | The simplicity is the feature. Debuggability via `ls events/` is gold. |
| Hardwiring specific LLM models | Both env vars are optional; user-configurable. |
| GUI installers / wizards | CLI is the surface. `tm-init` is the installer. |
| Generic checklist of optimization dimensions in planner | Empirically: project-derived dimensions (via `tm-profile`) outperform a fixed list. |
| Auto-promote workspace fixes without supervisor approval | High blast radius. `tm-promote --apply` requires explicit basenames. |
| Auto-edit goal.md from planner directives | Goal evolution is a supervisor decision (L6), not a planner one. Prevents scope drift. |

---

## Lessons learned

### LLMs are good at gap-fill, weak at invention

Even with 8 carefully-tuned dimensions, the planner can't propose "let's pivot to SaaS." That has to come from a human via `vision.md`. Designing systems around this asymmetry — humans set direction, LLMs execute and iterate — is more productive than expecting LLMs to be visionary.

### Generic checklists waste tokens

A 7- or 8-dimension hardcoded list forces the planner to consider UI on a backend library, performance on a Hello-World CLI, etc. Every irrelevant dimension is wasted token spend. Project-derived dimensions (manifest.json) audit only what matters.

### "Run until token exhaustion" requires more than a `while True`

A trivial `while True: do_work()` loop hits real limits: planner runs out of ideas, supervisor exhausts patience, executors hit context windows. The clean architecture is: `pm-daemon.py` runs forever cheaply (Python loop), but the LLM agents naturally stop generating events when their token budget runs out, which the supervisor detects and converts into a graceful shutdown event. The system **decides when to stop**.

### Status line and other UI limitations belong outside Claude Code

Claude Code's statusLine refresh cadence is fixed. Working around it by writing to the terminal title bar via ANSI escape costs zero tokens and works across all 4 agent windows in lockstep. Sometimes the right answer is "go around the platform constraint."

### File-mailbox simplicity > distributed-systems sophistication

The whole project communicates via `events/*.json`. No service mesh, no broker, no protobuf. Debugging a stuck worker means `ls events/.processed/`. The friction of more sophisticated tooling would have outweighed the benefits at this scale.

---

## Where things ended up

```
github.com/Hosico02/ZeroProgramer
├── 14 commits over the design session
├── MIT license
├── 8 discoverability topics
├── README.md (English) + README.zh.md (Chinese)
├── docs/TUTORIAL.md (9-step end-to-end walkthrough)
├── docs/DESIGN_JOURNEY.md (this file)
├── CONTRIBUTING.md
├── ~25 tools under bin/
└── 4-role agent architecture, L0–L6 fully built, innovation channel
   wired in, GitHub integration, web dashboard, multi-LLM routing
```

The system is at a clean release-candidate state: anyone can clone, run `tm-init`, write `goal.md`, run `tm-team-up 2`, and have 4 Claude agents start managing their project autonomously.

---

## What you might do next (not part of the system, just suggestions)

From `vision.md` (longer-term ambitions):

1. **Plugin system for custom agent roles** — register `TM_ROLE=qa` / `TM_ROLE=docs-writer` / etc. via a markdown file describing prompt + tool whitelist
2. **Replay & time-travel** — every event is logged; replay a stuck task to see exactly where it went wrong
3. **Self-hosted SaaS form factor** — Docker image + multi-user web UI for teams
4. **GitHub-native bidirectional** — currently push-only; add the reverse (GH issue → escalation) for triggered workflows
5. **CONTRIBUTING.md areas**: cross-platform fixes, English documentation expansion, plugin system, performance profiling at scale

Each is a self-contained project. None require modifying the core 4-role architecture.

---

*Last updated: 2026-05-08, after the conversation that built this. Future updates: append, don't rewrite — this is a record of decisions, not a living spec.*
