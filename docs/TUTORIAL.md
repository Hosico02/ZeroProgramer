# Tutorial: end-to-end ZeroProgramer walkthrough

This tutorial walks you from "I just cloned the repo" to "watching 4 agents
manage a project autonomously". ~20 minutes start to finish.

If you only want a quick demo, jump to [Step 5](#step-5-launch-the-team).

---

## Step 1 — install prerequisites

You need:

- **Claude Code CLI** (`claude`) authenticated — run `claude` in any
  terminal once and complete login if prompted.
- **`gh` CLI** (optional, only for `tm-github-sync`): `brew install gh`
  then `gh auth login`.
- **Python 3.8+** (already on most macOS / Linux).
- **bash 4+** (default on Linux; macOS ships bash 3.2 — you may want
  `brew install bash` for cleaner tracebacks, but the scripts are
  written to work on 3.2).

Quick check:

```bash
claude --version
python3 --version
bash --version | head -1
```

---

## Step 2 — clone or install

### Option A: try the bundled self-optimization demo

```bash
git clone https://github.com/Hosico02/ZeroProgramer
cd ZeroProgramer
./bin/setup-self-optimize        # copies the framework into workspace/
```

The demo's `goal.md` says "improve `workspace/`" — so the agent team
will optimize a copy of the framework itself. Good for seeing what each
agent does without writing your own `goal.md`.

### Option B: install on your own project

```bash
git clone https://github.com/Hosico02/ZeroProgramer ~/tools/zeroprogramer
~/tools/zeroprogramer/bin/tm-init ~/path/to/your/project
cd ~/path/to/your/project
```

`tm-init` creates `bin/`, `.claude/settings.json`, `goal.md`, `vision.md`,
`workspace/`, `.gitignore`. You then need to:

```bash
$EDITOR goal.md                  # describe what 'done' looks like
cp -r ~/source-code/* workspace/  # populate with code to be managed
rm workspace/.placeholder
```

---

## Step 3 — write a clear `goal.md`

This is the most important step. Bad goal → planner has nothing to anchor
to → wastes tokens. Good goal → planner finds gaps and fills them
automatically.

### Bad goal

```markdown
# Project goal

Make this project better.
```

### Good goal

```markdown
# Project goal: tighten test coverage and harden against bad input

## Axes

- **Tests pass**: `python3 -m pytest -q tests/` exits 0.
- **Shell injection-safe**: every bash variable that might contain user
  input is quoted; tests/test_shell_injection.py covers `$USER`, `$()`,
  backticks, single/double quotes.
- **Documented env vars**: every `os.environ.get(...)` site has a row
  in README.md's "Configuration" section with default + meaning.

## Constraints

- No external Python deps (stdlib only).
- All tests in tests/ run cleanly with no internet.
```

The pattern is: **each axis has a verifiable signal** — a shell command
that exits 0 if the axis is satisfied. Planner uses these to pick tasks.

---

## Step 4 — write a `vision.md` (optional but recommended)

`goal.md` is current-iteration commitment. `vision.md` is "where this could
go in 6-24 months". Anything in `vision.md` is candidate for supervisor
to graduate into `goal.md` when the project is ready.

```bash
./bin/tm-vision add "Add a web UI for the existing CLI"
./bin/tm-vision add "Support multi-user concurrent edits"
./bin/tm-vision propose 2     # have an LLM brainstorm 2 more
./bin/tm-vision list          # see everything
```

You can also just `$EDITOR vision.md` and write freely.

**Vision items don't enter the task queue directly** — supervisor decides
what to promote. This gating prevents LLM brainstorms from steering the
project into chaos.

---

## Step 5 — launch the team

```bash
./bin/tm-team-up 2
```

This:
1. Runs `tm-pm reset` (wipes any prior runtime state)
2. Starts `pm-daemon.py` in `--forever` mode (background)
3. Opens **4 new Terminal windows**:
   - 1 supervisor (TM_ROLE=supervisor)
   - 1 planner (TM_ROLE=planner)
   - 2 executors (default role)

Each Claude window auto-submits `go` and the agent enters its role-specific
loop. **No manual input needed.**

If `osascript` isn't available (e.g. SSH session, Linux), `tm-team-up`
prints the manual commands instead.

### What you'll see (approximately)

| Time | Event |
|---|---|
| 0s | 4 windows pop open, each Claude says "🎯/🔌/🧠 Connected to PM as ..." |
| ~5s | Supervisor reads `tm-pm status`, sees no work yet, writes first note |
| ~10s | Planner runs `tm-profile` (writes `manifest.json`), then proposes task #1 via `tm-plan-cycle add` |
| ~12s | PM dispatches task #1 to an idle executor |
| ~15s | Executor reads task, edits `workspace/`, runs `tm-done` |
| ~20s | Planner finds the next gap, proposes task #2 |
| ~5min | Supervisor wakes from its 600s polling loop, writes a status note |

---

## Step 6 — monitor

In a 5th terminal (any spare one):

```bash
./bin/tm-pm watch              # live dashboard, refresh 1Hz
# OR
./bin/tm-web                   # browser dashboard at http://localhost:7891
```

Each agent window's title bar also shows live state (no extra terminal
needed for at-a-glance):

```
● my-project · 5/8 · ▶2 · 3/4w · sup
```

`done/total · ▶in-progress · busy/total workers · role`

### Common terminal commands while it's running

```bash
./bin/tm-pm status              # one-shot snapshot (queue + workers)
./bin/tm-pm tail                # live PM event log
./bin/tm-context done           # done tasks with summaries
./bin/tm-pm escalations         # any permanent failures (ideally empty)
./bin/tm-decision list          # supervisor's audit trail
./bin/tm-status-report          # generate a markdown weekly report
./bin/tm-risk-list              # tasks at risk (multiple reclaims, etc.)
./bin/tm-vision list            # see vision + agent proposals
```

---

## Step 7 — inject ideas mid-flight

The system is running. You realize you want it to also think about
adding a CLI completion script. Just:

```bash
./bin/tm-vision add "Add bash completion for tm-* commands"
```

Within ~5 minutes the planner reads `vision.md`, considers the new item,
and either proposes a related task to PM or writes a tm-decision noting
why it's deferring. **Zero restart needed.**

Same pattern for changing direction:

```bash
./bin/tm-supervise revise-goal "Drop the daemon-resilience axis; we now
target a stateless rewrite that doesn't need the resilience guard."
```

This auto-snapshots `goal.md` before opening it for editing. Old version
preserved in `goal-history/` for rollback.

---

## Step 8 — stop the system

When you've seen enough, or when your token budget is running low:

### Graceful shutdown

```bash
./bin/tm-pm shutdown "user requested end of session"
```

PM processes any remaining events, then exits. Workers in `tm-done`/
`tm-plan-cycle`/`tm-supervise` polling notice the daemon is gone and
exit cleanly within a few seconds.

### Force-stop

```bash
./bin/tm-pm stop                # kill daemon
# Close the Claude windows manually
```

### Reset everything to start over

```bash
./bin/tm-pm reset
# (preserves goal.md, vision.md, CLAUDE.md, workspace/ — wipes runtime state)
```

---

## Step 9 — review the results

After a run, the project directory has audit trails:

```bash
ls status-reports/    # supervisor's weekly reports
ls decisions/         # ADR-style decision records
ls goal-history/      # snapshots of goal.md over time
ls escalations/       # tasks that permanently failed
cat workspace/...     # the actual code edits made
git log --oneline     # git history from setup-self-optimize, if used
```

A short post-run sanity check:

```bash
./bin/tm-status-report --stdout    # last weekly report on stdout
./bin/tm-decision list              # all supervisor decisions
./bin/tm-context done               # what got delivered
```

---

## Common pitfalls

### "Planner declared clean immediately"

Probably means `goal.md` has no actionable axes (no concrete signal_cmd).
Check: every axis should be verifiable as a shell command. See
[Step 3](#step-3--write-a-clear-goalmd).

### "Worker count keeps growing"

Each `/clear` or `/resume` in a Claude window creates a new session_id.
The old workers go stale and get GC'd within 2 min. If they're not getting
collected, run `./bin/tm-pm gc` manually.

### "Tasks reassigned multiple times"

Look at `./bin/tm-risk-list` — if a task has reclaim_count >= 3, it's
probably too big. Supervisor's prompt includes this trigger; expect
`tm-supervise revise-goal` to split it within a cycle or two.

### "Agent windows go quiet after 2 min"

Check `pm.log` — if you see `GC stale worker`, the Claude session stopped
emitting events (probably hit a permission prompt or the user closed the
window). Re-open with `./bin/tm-claude-executor`.

### "I want to use cheaper models for verification"

```bash
export TM_MODEL_VERIFIER=claude-haiku-4-5-20251001
./bin/tm-team-up 2
```

`tm-review` and `tm-goal-review` will use Haiku; everything else stays
default. Cuts ~30% of token spend.

---

## Next steps

- Read `README.md` for the full architecture diagram and design rationale.
- Read `CONTRIBUTING.md` if you want to send a PR.
- Read individual `bin/tm-*` scripts — most are <200 lines, well-commented,
  and the best documentation of how each piece actually works.
- Watch `bin/.promoted-bak/` accumulate — that's L5 in action, real fixes
  flowing from `workspace/` back into `bin/`.
