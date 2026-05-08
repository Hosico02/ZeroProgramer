# Contributing to ZeroProgramer

Thanks for considering a contribution. This is a small project run by one
maintainer ([@Hosico02](https://github.com/Hosico02)) — keep PRs focused and
expect honest feedback.

## What kind of contributions are welcome

| Welcome | Less welcome |
|---|---|
| Bug fixes with a regression test | Adding a 12th env var that nobody asked for |
| Cross-platform fixes (Linux / WSL when something is mac-specific) | Rewriting in a different language |
| New tools that fit existing role boundaries (executor / planner / supervisor) | New tools that violate the file-mailbox protocol |
| Better error messages, clearer logs | Pure cosmetic refactoring |
| Documentation fixes (any language) | Adding "best practice" abstractions for hypothetical scaling |
| Tutorial / example projects | Renaming things to "improve consistency" |

When in doubt: open an issue first to check fit before writing code.

## Before opening a PR

1. **Run syntax checks** on every script you touched:
   ```bash
   bash -n bin/<your-shell-script>
   python3 -c "import ast; ast.parse(open('bin/<your-py-script>').read())"
   ```

2. **Run the existing tests** if your change touches `workspace/bin/`:
   ```bash
   cd workspace && python3 -m pytest -q tests/
   ```

3. **Smoke test the full loop** if you changed PM, hooks, or wrappers:
   ```bash
   ./bin/tm-pm reset
   ./bin/tm-pm start --forever
   ./bin/tm-pm status              # should show 0 workers, 3 todo
   ./bin/tm-pm shutdown "smoke test"
   ```

4. **Check the watch dashboard** still renders cleanly:
   ```bash
   ./bin/tm-pm watch 0.5
   # press Ctrl+C after one screen
   ```

5. **`git status` is clean** of any runtime files (`pm-state.json`, `pm.log`,
   `events/*`, etc — they're gitignored, but verify with
   `git status --ignored`).

## Style

- **Bash**: 2-space indent, `set -euo pipefail` at top of every script. Quote
  variable expansions (`"$var"`, not `$var`). Prefer arrays (`args=("$@")`)
  over space-separated strings.
- **Python**: stdlib only (no Flask, no requests, no fancy deps). Type hints
  encouraged but not required. `from __future__ import annotations` if you
  use modern syntax.
- **Docstrings**: every script starts with a one-paragraph header explaining
  what it does and when to use it. Look at any existing tool for the pattern.
- **Commit messages**: present-tense imperative. First line ≤ 72 chars
  describing what changed; body explains why if non-obvious. Use
  `Co-Authored-By:` line if AI helped (be honest).

## Architecture invariants — please don't break

These are foundational; PRs that violate them will be asked to reconsider:

1. **PM is Python, not Claude.** Don't replace `pm-daemon.py` with an
   LLM-driven dispatcher; the deterministic state machine is the
   reliability backbone.

2. **Workers communicate only via `events/*.json` files.** No sockets,
   no pipes, no shared mutable state, no databases. The file mailbox is
   the wire protocol; respect it.

3. **Roles are decided by `TM_ROLE` env var at session start, not by
   command-line flags after the fact.** Anything that requires renegotiating
   a worker's role mid-session is anti-pattern.

4. **Executors only edit `workspace/`.** Supervisor edits `goal.md` (via
   `tm-supervise revise-goal`) and may run `tm-promote`. Planner edits
   nothing. The boundary keeps blast radius bounded.

5. **No new long-running daemons.** `pm-daemon.py` is the only
   continuously-running process. Things that need to "run periodically"
   should be CLIs called from supervisor's cycle loop, not new background
   services.

## Areas where help is most useful

(Loosely prioritized by maintainer interest)

- **Cross-platform**: Linux/WSL fixes for things that are macOS-only
  today (e.g. `osascript` in `tm-launch-helpers`, BSD vs GNU `find`/`sed`
  flag differences).
- **English documentation**: `README.md` is now English; example projects,
  tutorials, and FAQs in English are welcome.
- **Plugin system for custom roles**: today there are exactly 3 hardcoded
  roles. A clean way to register `TM_ROLE=qa-reviewer` with its own
  prompt + tool whitelist would unlock a lot.
- **Test coverage of `bin/` scripts** (not just `workspace/bin/`). The
  framework code itself has thinner test coverage than the workspace.
- **Performance profiling of `pm-daemon.py`** at scale (500+ tasks, 10+
  workers). Identify any O(n²) hot spots.

## Areas explicitly NOT wanted right now

- **Cross-project orchestration (L7)**: see README's "Note on L7". Not in
  scope; will be politely declined.
- **Replacing the file-mailbox protocol** with HTTP / WebSocket / Redis.
  The simplicity is a feature.
- **Forcing a specific LLM**: today both env vars (`TM_MODEL_VERIFIER`,
  `TM_MODEL_CREATIVE`) are optional. Don't hardwire model names into
  scripts.
- **GUI installers / wizards**. CLI is the surface. `tm-init` is the
  installer.

## Questions

Open an issue with `[question]` in the title. The maintainer reads them.
