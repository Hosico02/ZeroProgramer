# gh-issue-bot — design spec

> Auto-resolve labelled GitHub Issues via PM-coordinated Claude sessions.
> A standalone PM-managed sub-project living under `gh-issue-bot/` of the
> ZeroProgramer repo.

- **Date:** 2026-05-09
- **Author:** Hosico (via brainstorming with Claude)
- **Status:** approved (pending user spec review) → next: writing-plans

---

## 1. Goal

Watch a single GitHub repo for newly opened Issues that carry the `auto-fix`
label. For each, spawn a fresh Claude Code session in an isolated git worktree
to fix the issue, push the fix to a dedicated branch, open a PR with
`Closes #N`, and post a comment on the issue linking the PR. **Never**
auto-merge.

The only step that consumes Claude tokens is the session that actually edits
the code. Polling, spawning, comment-posting, branch-pushing, PR-opening, and
all bookkeeping are done by plain shell/Python scripts driven by the OS
scheduler (`launchd` on macOS, `systemd` / `cron` on Linux, `schtasks` on
Windows).

## 2. Constraints (hard requirements from the user)

1. Watch repo: `Hosico02/ZeroProgramer` (this same repo).
2. Per-issue isolation: each issue gets its own git worktree.
3. Push strategy: branch + PR + `Closes #N`. **No auto-merge.**
4. Filter: only issues with the `auto-fix` label (any author).
5. Concurrency: at most 3 issue-fixer sessions in flight simultaneously.
6. Scheduler: launchd on macOS, with cross-platform abstraction so
   Linux/Windows work too.
7. Failure: if a fix attempt fails (3 retries), comment the failure reason on
   the issue and add the `auto-fix-failed` label. Never silently spin.
8. Folder layout: a self-contained `gh-issue-bot/` sub-project at the repo
   root. Independent PM, independent state. Existing main-repo PM unaffected.
9. Session lifecycle: each issue-fixer session terminates and closes its
   terminal window after `tm-done`.
10. Token budget: only the in-session fix consumes tokens; everything else
    must be implementable as plain shell/Python.

## 3. Architecture

```
   launchd (10min tick, 0 token)
        │
        ▼
   bin/tm-issue-watcher  ←── gh issue list (label=auto-fix)
        │   ├─ new issue: create worktree + branch + write add_task event
        │   └─ in-flight issue: check PM state, finalize or fail
        ▼
   gh-issue-bot/events/*.json           (PM inbox; existing mechanism)
        │
        ▼
   gh-issue-bot/pm-daemon.py            (sub-PM, FOREVER mode)
        │
        ├─ assign_tasks: dispatch issue task to idle worker
        │
        ▼
   _tm-spawn.sh opens new terminal
        │
        ▼
   bin/tm-claude-issue-fixer            (Claude session — only token-burning role)
        │   cd worktrees/issue-N/, edit code, tm-done
        ▼
   tm-done runs signal_cmd:
        │
        ▼
   bin/tm-issue-finalize <N>            (push branch + open PR + comment + close window)
        │
        ▼
   GitHub: PR opened, "Resolved by PR #X" comment on issue
```

### 3.1 Why a sub-project (not bolt onto main PM)

The main repo currently runs a self-optimize PM driving `workspace/`. A
single PM is a single state machine; mixing the two flows would couple them.
A standalone `gh-issue-bot/` directory hosts an independent PM whose
`pm-state.json`, `events/`, `tasks/`, etc. never overlap with the main
project's. The two systems live in the same git repo only because the
target-of-fixes happens to be that repo.

### 3.2 The one piece of main-repo code we touch

`bin/pm-daemon.py`, `bin/tm-pm`, `bin/tm-done` need a `TM_ROOT`
environment-variable override so the same scripts can drive a different
project root. Patch shape (one line in `pm-daemon.py`):

```python
ROOT = Path(os.environ.get("TM_ROOT") or Path(__file__).resolve().parent.parent)
```

Backwards-compatible: when `TM_ROOT` is unset, behavior is unchanged.
Verified by `workspace/tests/test_pm_root_env.py`.

## 4. Components

| Component | Responsibility | Token? |
|---|---|---|
| `gh-issue-bot/bin/tm-issue-watcher`     | The 10-min poller. Diff GitHub vs local state, drop add_task events, spawn fixer windows, reap finished tasks. | ✗ |
| `gh-issue-bot/bin/tm-claude-issue-fixer`| Wrapper script that opens a Claude Code session in `gh-issue-bot/worktrees/issue-N/` and registers it as a PM worker. | **✓ (only)** |
| `gh-issue-bot/bin/tm-issue-finalize`    | Called by tm-done as `signal_cmd`. Validates diff, pushes branch, opens PR, posts comment, signals window-close. | ✗ |
| `gh-issue-bot/bin/tm-issue-fail`        | Posts failure comment + adds `auto-fix-failed` label. Called by watcher when escalation file appears. | ✗ |
| `gh-issue-bot/bin/tm-issue-bot`         | Top-level CLI: install / uninstall / start / stop / status / tick / logs. | ✗ |
| `gh-issue-bot/bin/tm-issue-bot-pm-start`| Launches the sub-PM (`TM_ROOT=$(pwd)/gh-issue-bot python3 ../bin/pm-daemon.py`) plus a watchdog. | ✗ |

The sub-PM does **not** copy `pm-daemon.py` / `tm-done` / `_tm-spawn.sh`. It
references the main repo's `bin/` via absolute path so the sub-project picks
up future PM improvements automatically.

## 5. Folder layout

```
ZeroProgramer/
├── bin/
│   ├── pm-daemon.py            ← TM_ROOT env override (one-line patch)
│   ├── tm-pm                   ← passes TM_ROOT through
│   └── tm-done                 ← passes TM_ROOT through
└── gh-issue-bot/               ← new sub-project
    ├── README.md               ← install / uninstall / log paths
    ├── goal.md                 ← "resolve auto-fix-labelled issues"
    ├── plan.md                 ← empty (tasks come dynamically via add_task)
    ├── pm-state.json           ← sub-PM's own state
    ├── pm.log
    ├── pm.pid
    ├── events/                 ← sub-PM inbox
    │   └── .processed/
    ├── tasks/
    ├── nags/
    ├── escalations/
    ├── worktrees/              ← issue sandboxes
    │   └── issue-42/
    ├── bin/                    ← issue-bot-only scripts
    │   ├── tm-issue-watcher
    │   ├── tm-issue-finalize
    │   ├── tm-issue-fail
    │   ├── tm-claude-issue-fixer
    │   ├── tm-issue-bot
    │   └── tm-issue-bot-pm-start
    ├── state.json              ← issue-level ledger (separate from pm-state.json)
    ├── .gh-issue-bot.env       ← config (gitignored)
    ├── watcher.log             ← launchd stdout
    └── tests/
        └── test_*.py           ← pytest
```

### 5.1 `state.json` schema (issue-level ledger maintained by watcher)

```json
{
  "version": 1,
  "last_poll_ts": "2026-05-09T10:35:00Z",
  "daily_spawn_count": 0,
  "daily_spawn_date": "2026-05-09",
  "issues": {
    "42": {
      "status": "assigned",
      "title": "fix typo in README",
      "labels": ["auto-fix", "bug"],
      "updated_at": "2026-05-09T10:30:00Z",
      "worktree": "/abs/path/gh-issue-bot/worktrees/issue-42",
      "branch": "auto-fix/issue-42",
      "task_id": 7,
      "pr_number": null,
      "session_id": "ab12cd34",
      "first_seen_ts": "2026-05-09T10:25:00Z",
      "attempts": 1
    }
  }
}
```

Status values: `seen | assigned | resolved | failed | cancelled`.

Legal transitions:

```
            (filter pass)
   gh issue ──────────────► seen
                              │ (worktree + add_task ok)
                              ▼
                          assigned
                          │      │
            (finalize ok) │      │ (escalation seen)
                          ▼      ▼
                       resolved  failed
                          │
            (issue closed/unlabelled by user)
                          ▼
                       cancelled
```

### 5.2 `.gh-issue-bot.env` schema

```
TM_GH_REPO=Hosico02/ZeroProgramer
TM_ISSUE_LABEL=auto-fix
TM_ISSUE_FAIL_LABEL=auto-fix-failed
TM_ISSUE_MAX_PARALLEL=3
TM_ISSUE_POLL_INTERVAL=600
TM_ISSUE_DAILY_CAP=10
TM_ISSUE_MAX_DIFF_LINES=2000
TM_ISSUE_BRANCH_PREFIX=auto-fix/issue-
```

## 6. Data flow

### 6.1 Happy path (one issue, end to end)

| # | Actor | Action | Token? |
|---|---|---|---|
| 1 | launchd | Triggers `tm-issue-watcher tick` every 10 min. | ✗ |
| 2 | watcher | `gh issue list -l auto-fix --state open --json number,title,body,labels,updatedAt` | ✗ |
| 3 | watcher | Diff vs `state.json`, identify unseen issue #N. | ✗ |
| 4 | watcher | `git worktree add gh-issue-bot/worktrees/issue-N -b auto-fix/issue-N main`. | ✗ |
| 5 | watcher | Write `gh-issue-bot/events/<ts>_add_task_issue-N.json` with task title (issue title + body + WORKTREE path + ISSUE number) and `signal_cmd: bin/tm-issue-finalize N`. | ✗ |
| 6 | watcher | Mark issue N `assigned` in `state.json`; spawn fixer window via `tm-claude-issue-fixer N`. | ✗ |
| 7 | new Claude session | SessionStart hook registers it as PM worker → sub-PM dispatches the new task. | ✗ |
| 8 | session | Reads task prompt with WORKTREE & ISSUE → cd into worktree → edits code → runs `tm-done`. | **✓** |
| 9 | tm-done | Runs the signal_cmd: `bin/tm-issue-finalize N`. | ✗ |
| 10 | tm-issue-finalize | `cd worktrees/issue-N` → assert non-empty `git diff main` → `git add -A && git commit` → `git push -u origin auto-fix/issue-N` → `gh pr create --body "Closes #N"` → `gh issue comment N --body "Resolved by PR #X"`. | ✗ |
| 11 | tm-issue-finalize | Returns 0; tm-done emits the `done` event; the wrapper `tm-claude-issue-fixer` exits Claude on `done` and runs `exit` to terminate the shell. | ✗ |
| 12 | watcher (next tick) | Sees PM marked task `done` → `state.json` issue N becomes `resolved`; worktree retained. | ✗ |

> Note on step 11: whether the terminal window itself closes after the shell exits is OS- and terminal-preference-dependent (e.g., macOS Terminal.app: Profile > Shell > "When the shell exits"). The bot guarantees Claude exits and the shell exits; users wanting the window to vanish set their terminal to close-on-exit. The bot's safety/concurrency model does not depend on the window actually closing — `tm-claude-issue-fixer` updates `state.json` to release the parallel slot regardless.

### 6.2 Failure paths

| Scenario | Bottom-half handler | Action |
|---|---|---|
| `signal_cmd` (finalize) exits non-zero | Sub-PM's existing retry uses `MAX_SIGNAL=5` (the PM default; we do not patch it). The same fixer worker stays idle-then-busy through retries — the worker only closes its window after a `done` outcome, not after `signal_failed`. After 5 failures PM writes an escalation file. | Watcher next tick spots escalation → calls `tm-issue-fail N "<reason>"` → `gh issue comment` + `gh issue edit --add-label auto-fix-failed` → cleanup worktree + (unpushed) branch. |
| Claude session crashes / blocks | Sub-PM's `STALE_AFTER_SEC` reclaims the task; the watcher detects the dangling assignment on next tick and respawns a fresh fixer window. `state.json.attempts` counts respawns; capped at 3 — after 3 respawn cycles the watcher gives up and follows the failure path above. |
| Issue already has `auto-fix-failed` label | Watcher filter rejects it. No retry. |
| User manually closes issue or removes label | Watcher detects on next tick → `state.json` flips to `cancelled` → if no PR pushed, delete worktree + branch; if PR exists, leave PR alone. |
| Empty diff (session changed 0 lines) | finalize exits non-zero → fail path → comment "auto-fix produced no diff". |
| Diff too large (> `TM_ISSUE_MAX_DIFF_LINES`) | finalize exits non-zero with reason → fail path → comment "diff exceeds threshold; needs human review". |

### 6.3 Idempotency invariants

- `tm-issue-watcher tick` is fully idempotent: every tick rebuilds the
  picture from `gh issue list` + `state.json` and converges. Crashes
  mid-tick are safe.
- `tm-issue-finalize N` is idempotent: checks `gh pr list --head <branch>`
  before opening a PR; checks last comment on issue before posting again.
- `state.json` writes are atomic (`tmp + os.replace`).

## 7. Cross-platform scheduler

`tm-issue-bot install` detects the platform and installs the appropriate
backend; `tm-issue-bot uninstall` removes it.

| Platform | Detection | Backend | Path |
|---|---|---|---|
| macOS | `uname -s = Darwin` | launchd LaunchAgent | `~/Library/LaunchAgents/com.zeroprogramer.gh-issue-bot.plist` |
| Linux + systemd | `command -v systemctl` | systemd user `.service` + `.timer` | `~/.config/systemd/user/gh-issue-bot.{service,timer}` |
| Linux without systemd | fallback | crontab line bracketed by markers | injected via `crontab -e` |
| Windows (Git Bash / native) | `uname` matches `MSYS*`/`MINGW*`/`CYGWIN*` or `wt.exe` available | `schtasks.exe` | `\Microsoft\ZeroProgramer\GhIssueBot` |
| WSL | reports Linux but `wt.exe` available | follows the Linux branch (systemd or cron) | — |

All backends fulfil three invariants:

1. Trigger every `TM_ISSUE_POLL_INTERVAL` seconds (default 600).
2. Run `<repo>/gh-issue-bot/bin/tm-issue-watcher tick` with stdout/stderr appended to `gh-issue-bot/watcher.log`.
3. Auto-start at boot/login.

### 7.1 macOS plist template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>com.zeroprogramer.gh-issue-bot</string>
  <key>ProgramArguments</key>
    <array>
      <string>{REPO}/gh-issue-bot/bin/tm-issue-watcher</string>
      <string>tick</string>
    </array>
  <key>StartInterval</key><integer>{INTERVAL}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{REPO}/gh-issue-bot/watcher.log</string>
  <key>StandardErrorPath</key><string>{REPO}/gh-issue-bot/watcher.log</string>
  <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string></dict>
</dict></plist>
```

`{REPO}` and `{INTERVAL}` are substituted at install time.

### 7.2 `tm-issue-bot` CLI surface

```
tm-issue-bot install      # detect platform, install scheduler, start sub-PM + watchdog, run one tick to validate
tm-issue-bot uninstall    # remove scheduler, stop sub-PM + watchdog, prompt about worktrees/state.json
tm-issue-bot status       # scheduler state, sub-PM state, in-flight issues, today's spawn count, recent errors
tm-issue-bot tick         # run one tick now (manual debug)
tm-issue-bot start        # start sub-PM only (dev mode, no scheduler)
tm-issue-bot stop         # stop sub-PM
tm-issue-bot logs [N]     # tail watcher.log + pm.log, last N lines
```

### 7.3 Install validation step

After installing the scheduler, `install` runs one immediate `tick` (in dry-run
mode if there's an issue ready to fix — the dry-run flag means we exercise the
full tick code path without spawning a real fixer session). Failure aborts the
install and rolls back the scheduler entry, so a misconfigured environment
(missing `gh`, wrong remote, plist syntax error) surfaces immediately rather
than silently no-op'ing every 10 minutes.

## 8. Safety rails

| Rail | Implementation |
|---|---|
| Daily token cap | `TM_ISSUE_DAILY_CAP=10`. `state.json.daily_spawn_count` resets at UTC midnight. Watcher refuses to spawn the 11th of a day; logs and continues. |
| Concurrency cap | `TM_ISSUE_MAX_PARALLEL=3`. Excess issues are queued (kept `seen`, not promoted to `assigned`) until a slot frees. |
| Retry cap | Two-layer: PM retries `signal_cmd` up to its default `MAX_SIGNAL=5` within one fixer window (handles transient finalize failures); watcher then respawns a fresh window up to 3 times (handles session crashes / stale workers). `state.json.attempts` counts watcher-level respawns. After 3 respawns OR PM escalation: force `auto-fix-failed` label + permanent skip. |
| Required labels | Skip issues missing `auto-fix`. Skip issues with `auto-fix-failed` or `wontfix`. |
| Worktree path lock | `tm-issue-finalize` asserts `cwd` resolves to inside `gh-issue-bot/worktrees/issue-N/` before any commit/push. |
| Branch prefix lock | finalize requires `HEAD` branch starts with `auto-fix/issue-`. Refuses to push otherwise. |
| No auto-merge | `gh pr merge` is **never** called from any issue-bot script. Static-checked in tests. |
| Diff size threshold | `TM_ISSUE_MAX_DIFF_LINES=2000`. Larger diffs route to fail path. |
| Kill switch | Presence of `gh-issue-bot/.disabled` makes watcher exit immediately on every tick. Scheduler stays installed; just no-ops. |
| Dry-run mode | `tm-issue-watcher tick --dry-run` walks the full tick logic, logs side effects, executes none. |

## 9. Testing

All tests in `gh-issue-bot/tests/`, runnable via `python3 -m pytest -q tests/`.
GitHub access is mocked; git operations target a tmpdir-scoped repo.

| Test | Verifies |
|---|---|
| `test_state_machine.py` | Legal transitions; illegal jumps rejected; `tick` is idempotent. |
| `test_filter.py` | `auto-fix` required; `auto-fix-failed` and `wontfix` skip; closed issues skip. |
| `test_concurrency.py` | With `TM_ISSUE_MAX_PARALLEL=3`, the 4th eligible issue queues, doesn't spawn. |
| `test_finalize_idempotent.py` | Running finalize twice doesn't reopen PR or duplicate comment. |
| `test_finalize_no_diff.py` | Empty diff → finalize exits non-zero → fail path engaged. |
| `test_finalize_diff_too_large.py` | `TM_ISSUE_MAX_DIFF_LINES` enforcement. |
| `test_install_macos.py` | `darwin` mock → correct plist generated; uninstall removes it. |
| `test_install_linux.py` | systemd / cron branches each pick correctly. |
| `test_pm_root_override.py` | Sub-PM with `TM_ROOT=...` writes to that path; without it, default behavior. |
| `test_event_format.py` | watcher-emitted add_task events parse cleanly via existing PM logic. |
| `test_watcher_e2e.py` | End-to-end with mock gh + tmp git repo: 1 new issue → state file → add_task → mock finalize → state `resolved`. |
| `test_safety_rails.py` | Daily cap, branch prefix lock, worktree path lock, kill switch all enforced. |
| `test_no_auto_merge.py` | grep -r '`gh pr merge`' over `gh-issue-bot/bin/` returns zero matches. |

A regression test at `workspace/tests/test_pm_root_env.py` verifies the
main-repo PM still defaults correctly when `TM_ROOT` is unset.

## 10. Out of scope (explicitly not doing)

- Webhooks (we poll, by user choice).
- Auto-merge of PRs.
- GitHub-Comment → task (only Issues, not comment-driven re-runs).
- Multi-repo support (one configured target repo per install).
- Editing issues other than commenting/labelling.
- Any LLM call outside of the issue-fixer Claude session itself.
- Rebasing the issue branch when `main` moves (PR will be reviewed by user;
  conflict resolution is a human task).

## 11. Decision log (the choices we locked in during brainstorming)

| Decision | Choice | Reason |
|---|---|---|
| Target repo | `Hosico02/ZeroProgramer` | User picked. |
| Workspace | git worktree per issue | Isolation from dirty main worktree. |
| Push strategy | branch + PR + `Closes #N`, no auto-merge | Safety. |
| Filter | label `auto-fix` only, any author | Simplest credible gate. |
| Concurrency | max 3 parallel | User picked. |
| Scheduler | launchd (macOS) + cross-platform abstraction | macOS-native; abstraction matches existing `_tm-spawn.sh` pattern. |
| Failure handling | `auto-fix-failed` label + comment | Visible, terminal, no infinite retry. |
| Folder layout | `gh-issue-bot/` independent sub-project | Clean isolation; no main-PM patches beyond TM_ROOT. |
| Session lifecycle | spawn-and-die per issue | No zombie windows; max 3 enforced via spawn count. |
| Install validation | yes — run a tick during install | Surface config errors immediately. |
| Sub-PM watchdog | yes | Symmetry with main-PM watchdog. |
| Daily token cap | 10 spawns/day | Sane default; user can raise. |
| Diff size threshold | enabled by default | Cheap safety; opt out via env. |
| Kill switch | `.disabled` file | Cheapest possible "pause without uninstall". |

---

## Next step

This spec is the input to **`writing-plans`**, which will produce a stepwise
implementation plan with discrete commits/tests per step.
