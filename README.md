# claude-team-demo

[中文](README.zh.md) | **English**

A **multi-agent self-managing project** framework. Install once, and a team of Claude agents takes over your project: planning, coding, reviewing, and adjusting course autonomously — until convergence or token exhaustion.

```
                 ┌──────────────────────────────────┐
                 │  SUPERVISOR (Claude, "the brain")│  L3-L6 meta-decisions
                 │  - patrol / write reports /       │
                 │    decide escalation paths        │
                 │  - edit goal.md / promote workspace│
                 │  - decide when to shutdown        │
                 └──────────────┬───────────────────┘
                                │ note / shutdown
                                ▼
   ┌────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
   │  PLANNER       │──▶│   pm-daemon.py        │──▶│  EXECUTOR × N      │
   │  Claude (ideas) │   │   Python (dispatcher) │   │  Claude (work)     │
   │  add_task      │   │   ✓ deterministic     │   │  edits workspace/  │
   │  ⨯ no code     │   │   ✓ zero-token        │   │  tm-done reports   │
   │                │   │   ✓ FOREVER mode      │   │                    │
   └────────────────┘   └──────────────────────┘   └────────────────────┘
                                ▲
                                │ events/*.json (file mailbox)
                                │
                         all four decoupled
```

**Core idea**: use LLMs where they earn their keep (creativity, judgment, code authoring); leave the dispatch plumbing to deterministic Python (assigning tasks, tracking state, nagging, recycling crashed workers).

---

## What you get

Built-in maturity ladder, all levels in place (L0–L6):

| Level | Capability | How it works |
|---|---|---|
| L0 | Single agent works on tasks | One Claude window |
| L1 | Multiple agents in parallel | PM dispatches to N executors via lock-free file mailbox |
| L2 | Planner generates new tasks continuously | `tm-profile` writes per-project `manifest.json`; planner drives off it; 5-min clean cooldown |
| L3 | Supervisor makes meta-decisions | `tm-claude-supervisor` + status reports + ADR decision logs |
| L4 | Agents harden their own source | Executor edits workspace/ |
| L5 | Workspace fixes auto-flow back to production | `tm-promote` with stale-snapshot detection |
| L6 | Goal evolves autonomously | `tm-supervise revise-goal` + version snapshots |
| Innovation channel | Human + LLM both inject vision | `vision.md` (you write) + `tm-vision propose` (LLM brainstorm) → supervisor promotes when ready |

> **Note on L7**: you might expect the ladder to continue to L7 (cross-project orchestration). **Intentionally omitted.** L7 is a different category of problem (multi-tenancy, cross-project state aggregation) requiring a base-layer rewrite. 99% of the "I want to manage multiple projects" use cases are solved by running `tm-init` + `tm-team-up` for each project independently — that's effectively a simplified L7 with zero extra code. A full L7 belongs in a separate multi-tenant project, not this framework's next version.

## On creativity (honest disclosure)

This system is **good at gap-filling, not invention**: the planner reads `manifest.json`, finds undone work, hardens code, fills coverage gaps. It **cannot** dream up "this should become a SaaS" / "this needs a web UI" / "this should run cross-project" — those are leaps outside the closed loop.

The fix: **humans are the source of innovation**. Two channels feed novel directions into the system:

| Channel | Source | Stored at | Read by |
|---|---|---|---|
| `vision.md` | **You (human)** write directly | repo root | planner each cycle, supervisor each cycle |
| `proposals/` | LLM brainstorm via `tm-vision propose` | `proposals/<iso>-<slug>.md` | supervisor decides promote / defer / reject |

Vision items do **not** enter the task queue directly. The supervisor is a gating layer — when something looks ripe, it's promoted into `goal.md` via `tm-supervise revise-goal`, after which the planner naturally generates tasks toward it. This gating prevents LLM-generated "ideas" from hijacking the project's direction.

Roles in detail:
- **PM (Python daemon)** — dispatches, tracks, GCs, escalates. Zero token cost.
- **SUPERVISOR (Claude)** — project manager: status reports, decisions, course corrections, shutdown.
- **PLANNER (Claude)** — keeps work flowing. Dimensions are **derived from the project itself**: `tm-profile` reads workspace/ and writes `manifest.json` with 3-7 dimensions tailored to THIS code (candidate pool covers correctness/robustness/perf/security/features/UI/docs/distribution/integrations/data_model, plus domain-specific axes like frame_pacing for games, audio_latency for audio apps, numerical_stability for physics sims). **Dimensions that don't apply to this project don't enter the manifest, saving tokens on irrelevant audits**. Planner only reads the manifest.
- **EXECUTOR × N (Claude)** — the hands. Edits code in workspace/. Multiple executors run in parallel.

---

## Quick start

### Option A: Run the self-optimization demo (workspace = framework copy)

The bundled demo points workspace/ at a copy of the framework itself, so the agent team optimizes the very code it's made of.

```bash
cd claude-team-demo
./bin/setup-self-optimize       # copies framework into workspace/
./bin/tm-team-up 2              # opens 4 Terminal windows: 1 supervisor + 1 planner + 2 executors
./bin/tm-pm watch               # in another terminal: real-time dashboard
```

Each new window auto-submits `go` and the agent enters its role-specific loop **without manual input**.

### Option B: Install on your own project (recommended)

```bash
# 1. clone the framework
git clone https://github.com/Hosico02/ZeroProgramer ~/tools/zeroprogramer

# 2. bootstrap into any target directory
~/tools/zeroprogramer/bin/tm-init ~/my-project

# 3. configure project goals
cd ~/my-project
$EDITOR goal.md                       # describe what 'done' looks like
cp -r ~/source/* workspace/           # populate workspace with code to be managed

# 4. launch
./bin/tm-team-up 2
```

`tm-init` creates:
- `bin/` — the toolkit
- `.claude/settings.json` — hooks + permissions + statusLine
- `CLAUDE.md` — executor instructions
- `goal.md` and `vision.md` templates
- `workspace/` — the only directory executors can edit
- `.gitignore` — runtime state stays out of git

---

## Usage

### Start / stop

```bash
./bin/tm-team-up [N]              # one-command launch (default: 1 executor; pass 2 or 3 for parallel)
./bin/tm-pm shutdown "<reason>"   # graceful (lets in-flight tasks finish)
./bin/tm-pm stop                  # force-stop daemon
./bin/tm-pm reset                 # wipe runtime state and start over
```

### Monitor (run in any spare terminal — zero token cost)

```bash
./bin/tm-pm watch                 # 1Hz terminal dashboard
./bin/tm-web                      # 1Hz browser dashboard at http://localhost:7891
./bin/tm-pm status                # one-shot snapshot
./bin/tm-pm tail                  # live PM event log
./bin/tm-status-report            # generate markdown report under status-reports/
./bin/tm-status-report --stdout   # print report to terminal
./bin/tm-risk-list                # tasks at risk (reclaimed often / failing / stuck)
./bin/tm-pm escalations           # permanent failures
./bin/tm-context list             # all task statuses
./bin/tm-context done             # done tasks with summaries
./bin/tm-decision list            # supervisor's decision log
```

**Each Claude window's title bar shows live project state** (workaround for Claude Code's statusLine refreshing only on agent turns):

```
● claude-team-demo · 8/13 · ▶3 · 3/4w · sup
```
project-name · `done/total` · `▶in_progress` · `busy/total workers` · role abbreviation

### Start individual roles (instead of `tm-team-up`)

```bash
./bin/tm-claude-supervisor        # the brain (meta-decisions)
./bin/tm-claude-planner           # ideas (continuous task generation)
./bin/tm-claude-executor          # work (edits workspace/)
```

Each wrapper auto-submits `go`, spawns a background title-keeper, cleans up on exit.

### Supervisor's PM toolkit (it uses these; you can too)

```bash
./bin/tm-decision new "<title>" "<context>" "<decision>" "<consequences>"
./bin/tm-decision list
./bin/tm-supervise revise-goal "<rationale>"      # L6: snapshot goal.md before editing
./bin/tm-promote                                   # L5: see workspace diff
./bin/tm-promote --apply pm-daemon.py              # explicitly promote a single file
./bin/tm-goal-snapshot list                        # past goal.md snapshots
./bin/tm-goal-snapshot diff 1                      # current vs latest snapshot
```

### Inject your own innovation (any time, from a terminal)

You can drop ambitious directions into the system at any moment:

```bash
# Append a one-liner to vision.md
./bin/tm-vision add "Web UI dashboard with real-time agent activity stream"

# Or open vision.md in your editor
./bin/tm-vision edit

# See current vision.md + any LLM-generated proposals
./bin/tm-vision list

# Have an LLM brainstorm 2 ambitious directions
./bin/tm-vision propose 2

# Inspect proposal #1
./bin/tm-vision show 1

# Wipe LLM proposals (vision.md untouched)
./bin/tm-vision clear-proposals
```

**No restart needed**. The next planner/supervisor cycle reads them. The supervisor's workflow includes "review vision/proposals → decide promote / defer".

`vision.md` is **user-authored** (like goal.md, not wiped by reset). `proposals/` is **agent-generated** and is wiped by reset.

---

## What the project produces (auditable)

Every run leaves these artifacts:

```
project/
├── goal.md                  # current "done" criteria (you write)
├── vision.md                # long-term ambitions (you write — innovation source)
├── status-reports/          # supervisor's periodic markdown reports
│   └── 2026-05-08T10-30Z.md
├── decisions/               # ADR-style decision log
│   └── 001-skip-promoting-tm-statusline.md
├── proposals/               # LLM-brainstormed ambitious directions awaiting supervisor review
│   └── 2026-05-08T11-15Z-web-dashboard.md
├── goal-history/            # snapshot of goal.md before each L6 revision
├── escalations/             # tasks that permanently failed (ideally empty)
├── workspace/               # the code executors actually edit
├── pm.log                   # PM event stream
├── supervisor.log           # supervisor decisions
└── bin/.promoted-bak/       # backups from each L5 promotion
```

Anyone can later read `status-reports` for progress, `decisions` for "why did it do this", `goal-history` for direction evolution, `escalations` for what went wrong.

---

## Token economics

| Process | Job | Token cost |
|---|---|---|
| `pm-daemon.py` | State machine dispatching | **0** |
| `tm-title-keeper` (×N) | Window title refresh | **0** |
| `tm-pm watch` / `tail` / `status-report` etc. | Read-only monitoring | **0** |
| supervisor (Claude) | Patrol + decisions | ~5% |
| planner (Claude) | Cross-dimension search | ~25% |
| executor × N (Claude) | Actually editing code | ~70% |

**~99% of LLM budget goes to executors writing code** — by design.

When tokens run out: planner / executor calls fail → escalations → supervisor sees the pattern → calls `tm-supervise shutdown` → PM exits gracefully. **The system decides for itself when to stop.**

---

## Configuration (env vars)

| Env | Default | Controls |
|---|---|---|
| `PM_FOREVER` | 0 | 1 = idle on empty queue, exit only on shutdown event |
| `PM_STRICT` | 0 | 1 = run tm-review on every done event |
| `PM_GOAL_REVIEW` | 0 | 1 = run tm-goal-review before exit-on-all-done |
| `STALE_AFTER_SEC` (constant) | 120 | Seconds without events before a worker is GC'd |
| `NAG_AFTER_SEC` | 40 | Seconds of work before PM nags a worker |
| `TM_PLAN_CLEAN_COOLDOWN` | 300 | After "clean" verdict, planner waits this long before re-evaluating |
| `SUPERVISE_INTERVAL` | 600 | Seconds between supervisor patrol cycles |
| `TM_PROJECT_NAME` | (dir basename) | Override the project name shown in statusLine + window title (otherwise uses the directory name) |
| `TM_TITLE_INTERVAL` | 2 | Title bar refresh frequency (s) |
| `PLANNER_INTERVAL` | 60 | Pace for the bash-based `tm-planner` daemon |
| `TM_MODEL_VERIFIER` | (claude default) | Model for deterministic checks (`tm-review`, `tm-goal-review`). Recommend a cheap fast model: `claude-haiku-4-5-20251001` |
| `TM_MODEL_CREATIVE` | (claude default) | Model for creative work (`tm-profile`, `tm-assess`, `tm-vision`, `tm-plan`, `tm-auto-loop`). Use the strong default unless you want to test a specific version. |

### Multi-LLM cost optimization

Verifier calls (PASS/FAIL grading, DONE/CONTINUE judgment) are deterministic checks that don't need a top-tier model. Routing them to a cheap fast model can halve total token spend without quality loss:

```bash
# Cheap model for verification, default for creative work
export TM_MODEL_VERIFIER=claude-haiku-4-5-20251001
./bin/tm-team-up 2
```

---

## Why these architectural choices

**Why PM is Python, not Claude**: PM's job (scan events, pair workers, update fields) is pure state machine — no LLM judgment needed. Running an LLM 4 times per second to do this would burn budget for no semantic value and introduce hallucination risk. LLMs earn their keep on creativity / judgment / context understanding — leave those to supervisor / planner / executor.

**Why file mailbox, not socket / RPC**: full decoupling. PM dies → workers can keep posting events for the next daemon. Worker crashes → PM auto-GCs and reclaims tasks. File IO is 10× simpler than network IPC and you can debug by `ls events/`.

**Why role via `TM_ROLE` env var**: each `tm-claude-*` wrapper sets `TM_ROLE` before spawning Claude. The SessionStart hook reads it from stdin JSON, includes it in the join event. PM stores per-worker role and only routes exec tasks to executors (skips supervisor/planner).

---

## Troubleshooting

| Symptom | Action |
|---|---|
| One worker isn't doing anything | `./bin/tm-pm status` — check role; if mis-registered, GC and re-open the window |
| Task stuck in-progress | `./bin/tm-context show <id>` — check signal_history; likely a flaky `signal_cmd` |
| Worker count climbs unbounded | User opened too many windows / used `/clear` repeatedly; `./bin/tm-pm gc` purges stale ones |
| PM crashed | Check tail of `pm.log` for traceback; `./bin/tm-pm start` to restart |
| Want to start over | `./bin/tm-pm reset && ./bin/tm-team-up 2` |

---

## Directory at a glance

```
bin/
├── pm-daemon.py              # background PM
├── tm-pm                     # PM control (start/stop/status/watch/...)
├── tm-team-up                # one-shot full-team launch
├── tm-init                   # install framework into target dir
├── tm-claude-supervisor      # spawn supervisor window
├── tm-claude-planner         # spawn planner window
├── tm-claude-executor        # spawn executor window
├── tm-launch-helpers         # spawn planner + N executors (no supervisor)
├── tm-status-report          # markdown weekly report
├── tm-decision               # ADR decision log
├── tm-risk-list              # risk register
├── tm-promote                # L5 workspace → bin sync
├── tm-goal-snapshot          # L6 goal.md history
├── tm-supervise              # supervisor CLI (note/shutdown/revise-goal)
├── tm-plan-cycle             # planner CLI (add/clean)
├── tm-done                   # executor CLI
├── tm-context                # task / history queries
├── tm-vision                 # innovation channel: add / propose / list / show / edit
├── tm-github-sync            # mirror escalations to GitHub Issues
├── tm-web                    # browser dashboard (single-page, polls /api/state)
├── tm-title-keeper           # live window-title refresher
├── tm-status-title           # title bar text generator
├── tm-statusline             # Claude Code statusLine command
├── tm-{session,prompt,stop,tool}-hook    # Claude Code hooks
└── tm-{plan,review,assess,goal-review,profile}    # one-shot claude -p tools
```

---

## Documentation

- **[Tutorial](docs/TUTORIAL.md)** — end-to-end walkthrough from clone to first run (~20 min)
- **[Design Journey](docs/DESIGN_JOURNEY.md)** — why the architecture is what it is (decisions, lessons, deliberate non-features)
- **[Contributing](CONTRIBUTING.md)** — PR guidelines + architecture invariants
- **[README.zh.md](README.zh.md)** — Chinese version

## Acknowledgments

Built on [Claude Code](https://claude.com/claude-code). Design inspired by `agent-self-iteration` (the previous-generation single-agent self-iterator from the same family).

License: [MIT](LICENSE)
