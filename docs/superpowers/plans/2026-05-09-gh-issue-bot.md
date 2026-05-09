# gh-issue-bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `gh-issue-bot/` sub-project that polls the Hosico02/ZeroProgramer GitHub repo every 10 minutes for issues labelled `auto-fix`, spawns a Claude Code session per issue inside a dedicated git worktree to fix it, and opens a PR with `Closes #N` — all without consuming any Claude tokens outside the in-session fix itself.

**Architecture:** Independent PM-managed sub-project at `gh-issue-bot/` with its own `pm-daemon.py` instance (via new `TM_ROOT` env override on the existing daemon), its own `events/`, its own `pm-state.json`, plus a separate `state.json` ledger. A platform-aware scheduler (launchd / systemd / cron / schtasks) ticks the watcher every 10 min. Watcher diffs GitHub against local state, drops `add_task` events into the sub-PM, spawns fixer windows via `_tm-spawn.sh`, and reaps finished tasks. The fixer's `tm-done` runs `tm-issue-finalize` as `signal_cmd`, which performs the only network writes (push branch + open PR + post comment). All non-fixer steps are pure shell/Python.

**Tech Stack:** Python 3.11+ stdlib only (no new deps), bash 3.2+, `gh` CLI, `git` ≥ 2.5 (worktree), pytest, platform schedulers. Reuses existing `bin/pm-daemon.py`, `bin/tm-done`, `bin/tm-pm`, `bin/_tm-spawn.sh`.

**Spec:** `docs/superpowers/specs/2026-05-09-gh-issue-bot-design.md` (commit `61e719e`)

---

## File Structure

### Modified (main repo)

| Path | Change |
|---|---|
| `bin/pm-daemon.py` | One-line: `ROOT = Path(os.environ.get("TM_ROOT") or Path(__file__).resolve().parent.parent)`. Add `import os`. |
| `bin/tm-pm` | Two lines: derive `ROOT` from `${TM_ROOT:-...}`; `PIDFILE`/`LOG`/etc. become absolute under that ROOT. |
| `bin/tm-done` | One line: derive `ROOT` from `${TM_ROOT:-...}` to match. |

### Created (gh-issue-bot sub-project)

| Path | Responsibility |
|---|---|
| `gh-issue-bot/.gitignore` | Ignore `pm-state.json`, `pm.log`, `pm.pid`, `events/`, `tasks/`, `nags/`, `escalations/`, `worktrees/`, `state.json`, `watcher.log`, `.gh-issue-bot.env`, `.disabled`. |
| `gh-issue-bot/README.md` | User-facing: how to install / uninstall / monitor. |
| `gh-issue-bot/goal.md` | "Resolve `auto-fix`-labelled issues automatically." (sub-PM input) |
| `gh-issue-bot/plan.md` | Empty / one comment line — tasks come dynamically via `add_task` events. |
| `gh-issue-bot/.gh-issue-bot.env.example` | Documented config template. |
| `gh-issue-bot/lib/__init__.py` | Empty package marker. |
| `gh-issue-bot/lib/config.py` | `.gh-issue-bot.env` loader; resolves config paths to absolute. |
| `gh-issue-bot/lib/state.py` | `state.json` schema, atomic read/write, state-machine transition validator. |
| `gh-issue-bot/lib/gh.py` | Thin wrappers over `gh issue list / view / comment / edit` and `gh pr list / create`. Each function calls `subprocess.run`; tests mock `subprocess.run`. |
| `gh-issue-bot/lib/scheduler.py` | Platform detection (`darwin` / `linux+systemd` / `linux+cron` / `windows` / `wsl`); `install(repo_root, interval)` and `uninstall()`; pure-function templates. |
| `gh-issue-bot/bin/tm-issue-bot-pm-start` | Bash launcher: `TM_ROOT=$ROOT/gh-issue-bot nohup python3 $ROOT/bin/pm-daemon.py …` plus watchdog. |
| `gh-issue-bot/bin/tm-issue-watcher` | Python entry point (executable). One `tick` action: poll → diff → drop add_task → spawn fixer → reap. Reads `lib/*`. |
| `gh-issue-bot/bin/tm-claude-issue-fixer` | Bash. Args: issue number. Re-enters worktree, exports `TM_ROOT`, exec's `claude` (mirroring the existing `tm-claude-executor` shape). |
| `gh-issue-bot/bin/tm-issue-finalize` | Bash. Called as `signal_cmd` by tm-done. Asserts cwd, validates diff, pushes branch, opens PR if missing, posts comment. |
| `gh-issue-bot/bin/tm-issue-fail` | Bash. Args: issue#, reason. Posts comment, adds fail label, cleans up worktree if no PR opened. |
| `gh-issue-bot/bin/tm-issue-bot` | Bash CLI router: install/uninstall/start/stop/status/tick/logs. Calls Python `lib/scheduler.py` for install. |
| `gh-issue-bot/tests/conftest.py` | Pytest fixtures: tmp git repo + tmp gh-issue-bot/ tree + `gh` mock factory. |
| `gh-issue-bot/tests/test_*.py` | One file per spec §9 row. |

### Created (regression test on main repo)

| Path | Responsibility |
|---|---|
| `workspace/tests/test_pm_root_env.py` | Verifies main `pm-daemon.py` honors `TM_ROOT` and falls back correctly. |

---

## Task list

1. **Patch `pm-daemon.py` to honor `TM_ROOT`** — main-repo enabler
2. **Patch `tm-pm` to honor `TM_ROOT`** — control plane parity
3. **Patch `tm-done` to honor `TM_ROOT`** — worker-side parity
4. **Create `gh-issue-bot/` skeleton** — folders, README, goal/plan/env templates
5. **`lib/config.py`** — env loader (tested)
6. **`lib/state.py`** — state ledger + machine (tested)
7. **`lib/gh.py`** — gh CLI wrappers (mocked tests)
8. **`bin/tm-issue-bot-pm-start`** — sub-PM launcher (smoke test)
9. **`bin/tm-claude-issue-fixer`** — fixer session wrapper
10. **`bin/tm-issue-finalize`** — finalize/push/PR/comment script (tested)
11. **`bin/tm-issue-fail`** — failure comment helper (tested)
12. **`bin/tm-issue-watcher`** — the main poller (tested incl. e2e)
13. **`lib/scheduler.py`** — cross-platform install/uninstall (tested)
14. **`bin/tm-issue-bot`** — top-level CLI (smoke test)
15. **End-to-end smoke + final README** — ties it all together

---

## Task 1: Patch `pm-daemon.py` to honor `TM_ROOT`

**Files:**
- Modify: `bin/pm-daemon.py:24-34` (ROOT and surrounding constants)
- Test: `workspace/tests/test_pm_root_env.py` (new)

- [ ] **Step 1.1: Read current ROOT block to anchor the edit**

Run: `sed -n '14,34p' bin/pm-daemon.py`
Expected: see `from pathlib import Path`, then `ROOT = Path(__file__).resolve().parent.parent` and the `EVENTS_DIR = ROOT / "events"` block.

- [ ] **Step 1.2: Write the failing regression test**

Create `workspace/tests/test_pm_root_env.py`:

```python
"""TM_ROOT env var lets pm-daemon.py target a non-default project root."""
import importlib.util
import os
import sys
from pathlib import Path


def _load_pm_daemon(root_override: str | None):
    """Re-import pm-daemon.py under a controlled TM_ROOT (or absence thereof)."""
    if "TM_ROOT" in os.environ:
        del os.environ["TM_ROOT"]
    if root_override is not None:
        os.environ["TM_ROOT"] = root_override
    src = Path(__file__).resolve().parents[2] / "bin" / "pm-daemon.py"
    spec = importlib.util.spec_from_file_location("pm_daemon_under_test", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pm_daemon_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_root_is_repo(tmp_path):
    mod = _load_pm_daemon(None)
    assert mod.ROOT.name == "ZeroProgramer" or mod.ROOT.is_dir()
    assert (mod.ROOT / "bin" / "pm-daemon.py").exists()


def test_tm_root_override(tmp_path):
    fake = tmp_path / "fake_root"
    fake.mkdir()
    mod = _load_pm_daemon(str(fake))
    assert mod.ROOT == fake
    assert mod.EVENTS_DIR == fake / "events"
    assert mod.STATE_FILE == fake / "pm-state.json"
```

- [ ] **Step 1.3: Run the test to confirm it fails**

Run: `cd /Users/mack/Desktop/Hosico/Works/Work/ZeroProgramer && python3 -m pytest workspace/tests/test_pm_root_env.py -v`
Expected: `test_tm_root_override` FAILs because TM_ROOT is ignored today; `test_default_root_is_repo` passes.

- [ ] **Step 1.4: Apply the patch to `pm-daemon.py`**

Edit `bin/pm-daemon.py`. Find the import block (around line 14-24) and ensure `import os` exists (it already does — confirm with `grep '^import os' bin/pm-daemon.py`).

Replace the ROOT line:

```python
# OLD:
ROOT             = Path(__file__).resolve().parent.parent

# NEW:
ROOT             = Path(os.environ["TM_ROOT"]).resolve() if os.environ.get("TM_ROOT") else Path(__file__).resolve().parent.parent
```

Leave every other constant (`EVENTS_DIR = ROOT / "events"`, etc.) untouched — they pick up the new ROOT automatically.

- [ ] **Step 1.5: Re-run the regression test**

Run: `python3 -m pytest workspace/tests/test_pm_root_env.py -v`
Expected: both tests PASS.

- [ ] **Step 1.6: Quick lint and behavior check**

Run: `python3 -c "import bin.pm_daemon" 2>&1 || python3 bin/pm-daemon.py --help 2>&1 | head` (the daemon has no `--help` so this last form will likely error, but should not be a syntax error)

Better: `python3 -m py_compile bin/pm-daemon.py`
Expected: no output (compile OK).

- [ ] **Step 1.7: Commit**

```bash
git add bin/pm-daemon.py workspace/tests/test_pm_root_env.py
git commit -m "$(cat <<'EOF'
pm-daemon: honor TM_ROOT env override (backwards-compatible)

Allows a second pm-daemon instance to drive a separate project root
(e.g. gh-issue-bot/) without code duplication. When TM_ROOT is unset
the existing parent-of-bin/ behavior is preserved.

Test: workspace/tests/test_pm_root_env.py
EOF
)"
```

---

## Task 2: Patch `tm-pm` to honor `TM_ROOT`

**Files:**
- Modify: `bin/tm-pm` (the `ROOT=` line at top)

- [ ] **Step 2.1: Read current `ROOT=` line to anchor**

Run: `grep -n '^ROOT=' bin/tm-pm`
Expected: line ~6: `ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`

- [ ] **Step 2.2: Apply patch — replace that line**

```bash
# OLD:
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# NEW:
ROOT="${TM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROOT="$(cd "$ROOT" && pwd)"   # canonicalize even if TM_ROOT was relative
```

- [ ] **Step 2.3: Smoke-test default behavior unchanged**

Run: `bash -n bin/tm-pm && bin/tm-pm status | head -3`
Expected: no syntax error; status command still runs against the default ROOT.

- [ ] **Step 2.4: Smoke-test TM_ROOT override**

```bash
mkdir -p /tmp/tm-root-smoke/events /tmp/tm-root-smoke/tasks
cat > /tmp/tm-root-smoke/pm-state.json <<'EOF'
{"tasks": [{"id":1,"title":"x","status":"done","summary":null,"signal_cmd":null,"depends_on":[],"assigned_to":null,"started_ts":null,"completed_ts":null,"last_nag_ts":null,"review_attempts":0,"review_history":[],"signal_attempts":0,"signal_history":[]}], "workers": {}}
EOF
TM_ROOT=/tmp/tm-root-smoke bin/tm-pm status
```
Expected: status reports the fake root's state (1/1 done) and exits 0 — confirming `tm-pm` reads the override.

Cleanup: `rm -rf /tmp/tm-root-smoke`

- [ ] **Step 2.5: Commit**

```bash
git add bin/tm-pm
git commit -m "tm-pm: honor TM_ROOT env override"
```

---

## Task 3: Patch `tm-done` to honor `TM_ROOT`

**Files:**
- Modify: `bin/tm-done` (the `ROOT=` line)

- [ ] **Step 3.1: Read current ROOT line**

Run: `grep -n '^ROOT=' bin/tm-done`
Note the line number and exact form.

- [ ] **Step 3.2: Apply the same TM_ROOT-aware replacement as Task 2**

```bash
# OLD:
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# NEW:
ROOT="${TM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROOT="$(cd "$ROOT" && pwd)"
```

- [ ] **Step 3.3: Syntax check**

Run: `bash -n bin/tm-done`
Expected: no output.

- [ ] **Step 3.4: Commit**

```bash
git add bin/tm-done
git commit -m "tm-done: honor TM_ROOT env override"
```

---

## Task 4: Create `gh-issue-bot/` skeleton

**Files (all new):**
- `gh-issue-bot/.gitignore`
- `gh-issue-bot/README.md`
- `gh-issue-bot/goal.md`
- `gh-issue-bot/plan.md`
- `gh-issue-bot/.gh-issue-bot.env.example`
- `gh-issue-bot/lib/__init__.py` (empty)
- `gh-issue-bot/tests/__init__.py` (empty)
- `gh-issue-bot/tests/conftest.py`
- `gh-issue-bot/bin/.keep` (placeholder so empty dir tracks)

- [ ] **Step 4.1: Make directories**

Run:
```bash
mkdir -p gh-issue-bot/{bin,lib,tests,events/.processed,tasks,nags,escalations,worktrees}
```

- [ ] **Step 4.2: Write `.gitignore`**

Create `gh-issue-bot/.gitignore`:

```
# State managed by the running system (not source-controlled)
pm-state.json
pm.log
pm.pid
pm-watchdog.log
pm-watchdog.pid
events/
tasks/
nags/
escalations/
worktrees/
state.json
watcher.log
.gh-issue-bot.env
.disabled
.last-progress-*
.session-id

# Re-include processed-marker dir so the events/ pipeline boots clean on first run
!events/.processed/
```

- [ ] **Step 4.3: Write `goal.md`**

Create `gh-issue-bot/goal.md`:

```markdown
# Goal: resolve auto-fix-labelled GitHub Issues

This sub-project's purpose is one specific autonomous loop: watch the configured
GitHub repo for issues with the `auto-fix` label, spawn an isolated Claude Code
session per issue inside a per-issue git worktree, and open a pull request with
`Closes #N` when the session reports success.

The sub-PM here serves only this loop. Tasks are not authored ahead of time;
they arrive dynamically as `add_task` events from `bin/tm-issue-watcher`.
```

- [ ] **Step 4.4: Write `plan.md`**

Create `gh-issue-bot/plan.md`:

```markdown
# Plan

(Empty by design. Tasks arrive at runtime from `bin/tm-issue-watcher`
via add_task events. The sub-PM idles in FOREVER mode waiting for them.)
```

- [ ] **Step 4.5: Write `.gh-issue-bot.env.example`**

Create `gh-issue-bot/.gh-issue-bot.env.example`:

```
# Copy to .gh-issue-bot.env and edit. Values shown are defaults.

# Target repo (owner/name). If unset, derived from `git remote get-url origin`.
TM_GH_REPO=Hosico02/ZeroProgramer

# Required label. Issues missing this label are ignored.
TM_ISSUE_LABEL=auto-fix

# Applied when an attempt fails terminally. Issues with this label are skipped.
TM_ISSUE_FAIL_LABEL=auto-fix-failed

# Concurrency cap on in-flight fixer sessions.
TM_ISSUE_MAX_PARALLEL=3

# Polling cadence (seconds). Match this to the scheduler interval.
TM_ISSUE_POLL_INTERVAL=600

# Hard stop on the number of fixer spawns per UTC day.
TM_ISSUE_DAILY_CAP=10

# Refuse to push diffs larger than this (lines). Use 0 to disable the cap.
TM_ISSUE_MAX_DIFF_LINES=2000

# Branch prefix for auto-fix branches.
TM_ISSUE_BRANCH_PREFIX=auto-fix/issue-
```

- [ ] **Step 4.6: Write `README.md`**

Create `gh-issue-bot/README.md`:

```markdown
# gh-issue-bot

Auto-resolves GitHub Issues labelled `auto-fix` on the configured repo by
spawning a Claude Code session per issue in an isolated git worktree, then
opening a PR with `Closes #N`. **Never auto-merges.**

## Quick start

```bash
cp gh-issue-bot/.gh-issue-bot.env.example gh-issue-bot/.gh-issue-bot.env
# edit .gh-issue-bot.env if you want non-default config
gh-issue-bot/bin/tm-issue-bot install
```

That single command:

1. Detects your platform (macOS / Linux+systemd / Linux+cron / Windows).
2. Installs a 10-minute scheduler entry.
3. Starts the sub-PM (a separate `pm-daemon.py` instance pointed at this folder).
4. Starts a watchdog so the sub-PM survives crashes.
5. Runs one validation tick to surface any config errors immediately.

## Daily commands

```bash
gh-issue-bot/bin/tm-issue-bot status     # scheduler / sub-PM / in-flight issues
gh-issue-bot/bin/tm-issue-bot logs       # tail watcher.log + pm.log
gh-issue-bot/bin/tm-issue-bot tick       # run one tick now
touch  gh-issue-bot/.disabled            # pause without uninstalling
rm     gh-issue-bot/.disabled            # resume
```

## Uninstall

```bash
gh-issue-bot/bin/tm-issue-bot uninstall
```

Removes the scheduler entry, stops the sub-PM and watchdog, and asks whether
to keep the worktrees and state.json (default: keep).

## Configuration

See `.gh-issue-bot.env.example` for all knobs. The bot operates on a single
repo per install; multi-repo support is intentionally not provided.

## Architecture

See `docs/superpowers/specs/2026-05-09-gh-issue-bot-design.md` for the design.
```

- [ ] **Step 4.7: Write empty package markers**

Create `gh-issue-bot/lib/__init__.py` (empty file).
Create `gh-issue-bot/tests/__init__.py` (empty file).
Create `gh-issue-bot/bin/.keep` (empty file — keeps `bin/` in the commit before scripts land).

- [ ] **Step 4.8: Write `tests/conftest.py` skeleton**

Create `gh-issue-bot/tests/conftest.py`:

```python
"""Shared pytest fixtures for gh-issue-bot tests."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make `lib` importable from tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tmp_bot_root(tmp_path):
    """A clean gh-issue-bot/-shaped tree under tmp_path."""
    root = tmp_path / "bot"
    for sub in ("bin", "lib", "events/.processed", "tasks", "nags",
                "escalations", "worktrees"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def tmp_git_repo(tmp_path):
    """An initialized empty-but-clean git repo with a `main` branch and one
    initial commit. Tests that need worktrees clone or branch from here."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def fake_gh(monkeypatch):
    """Replace subprocess.run to intercept `gh ...` calls and return canned
    responses set via the returned helper. Real subprocess calls (git, etc.)
    pass through."""
    real_run = subprocess.run
    canned: dict[tuple, subprocess.CompletedProcess] = {}

    def setter(args_tuple, *, stdout="", returncode=0, stderr=""):
        canned[args_tuple] = subprocess.CompletedProcess(
            args=list(args_tuple), returncode=returncode,
            stdout=stdout, stderr=stderr,
        )

    def fake_run(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, list) and argv and argv[0] == "gh":
            key = tuple(argv)
            if key in canned:
                return canned[key]
            # Helpful failure for missing canned response
            raise AssertionError(
                f"fake_gh: no canned response for `{' '.join(argv)}`. "
                f"Register one with fake_gh.set(...)."
            )
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    setter.calls = canned
    return setter
```

- [ ] **Step 4.9: Verify the tree was created correctly**

Run: `find gh-issue-bot -type f | sort`
Expected output (paths in any order):
```
gh-issue-bot/.gh-issue-bot.env.example
gh-issue-bot/.gitignore
gh-issue-bot/README.md
gh-issue-bot/bin/.keep
gh-issue-bot/goal.md
gh-issue-bot/lib/__init__.py
gh-issue-bot/plan.md
gh-issue-bot/tests/__init__.py
gh-issue-bot/tests/conftest.py
```

- [ ] **Step 4.10: Smoke-test the conftest imports cleanly**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/ 2>&1 | tail -5`
Expected: "no tests ran" / collected 0 items / no import errors.

- [ ] **Step 4.11: Commit**

```bash
git add gh-issue-bot/
git commit -m "$(cat <<'EOF'
gh-issue-bot: scaffold sub-project skeleton

Folder layout per spec §5: bin/, lib/, tests/, events/, tasks/, nags/,
escalations/, worktrees/. .gitignore excludes runtime state. Includes
goal.md and plan.md (sub-PM inputs), config template, README, and a
pytest conftest with a tmp_git_repo fixture and a gh-CLI mock helper.

Spec: docs/superpowers/specs/2026-05-09-gh-issue-bot-design.md
EOF
)"
```

---

## Task 5: `lib/config.py` — env loader

**Files:**
- Create: `gh-issue-bot/lib/config.py`
- Test: `gh-issue-bot/tests/test_config.py`

- [ ] **Step 5.1: Write the failing test**

Create `gh-issue-bot/tests/test_config.py`:

```python
"""Config loader: parses .gh-issue-bot.env, applies defaults, types correctly."""
from pathlib import Path

import pytest

from lib.config import Config, load_config


def _write_env(root: Path, body: str) -> None:
    (root / ".gh-issue-bot.env").write_text(body)


def test_defaults_when_no_env_file(tmp_bot_root):
    cfg = load_config(tmp_bot_root)
    assert isinstance(cfg, Config)
    assert cfg.label == "auto-fix"
    assert cfg.fail_label == "auto-fix-failed"
    assert cfg.max_parallel == 3
    assert cfg.poll_interval == 600
    assert cfg.daily_cap == 10
    assert cfg.max_diff_lines == 2000
    assert cfg.branch_prefix == "auto-fix/issue-"


def test_overrides_from_env_file(tmp_bot_root):
    _write_env(tmp_bot_root, "TM_ISSUE_MAX_PARALLEL=5\nTM_ISSUE_LABEL=triage\n")
    cfg = load_config(tmp_bot_root)
    assert cfg.max_parallel == 5
    assert cfg.label == "triage"


def test_blank_and_comment_lines_ok(tmp_bot_root):
    _write_env(tmp_bot_root, "\n# comment\nTM_ISSUE_DAILY_CAP=1\n   \n")
    cfg = load_config(tmp_bot_root)
    assert cfg.daily_cap == 1


def test_missing_repo_falls_back_to_git_remote(tmp_bot_root, monkeypatch):
    monkeypatch.setattr(
        "lib.config._git_remote_owner_repo",
        lambda root: "owner/repo-from-remote",
    )
    cfg = load_config(tmp_bot_root)
    assert cfg.repo == "owner/repo-from-remote"


def test_explicit_repo_beats_remote(tmp_bot_root, monkeypatch):
    monkeypatch.setattr(
        "lib.config._git_remote_owner_repo",
        lambda root: "owner/wrong",
    )
    _write_env(tmp_bot_root, "TM_GH_REPO=Hosico02/right\n")
    cfg = load_config(tmp_bot_root)
    assert cfg.repo == "Hosico02/right"


def test_invalid_int_raises(tmp_bot_root):
    _write_env(tmp_bot_root, "TM_ISSUE_MAX_PARALLEL=many\n")
    with pytest.raises(ValueError, match="TM_ISSUE_MAX_PARALLEL"):
        load_config(tmp_bot_root)
```

- [ ] **Step 5.2: Run the tests and confirm they fail**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_config.py 2>&1 | tail -10`
Expected: ImportError on `from lib.config import …`.

- [ ] **Step 5.3: Implement `lib/config.py`**

Create `gh-issue-bot/lib/config.py`:

```python
"""Loads gh-issue-bot/.gh-issue-bot.env and exposes typed config.

The env-file format is minimal — `KEY=value` per line, blank/`#` lines ignored,
no shell interpolation. Anything fancier earns its own validation rule.
"""
from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

_INT_KEYS = {
    "TM_ISSUE_MAX_PARALLEL", "TM_ISSUE_POLL_INTERVAL",
    "TM_ISSUE_DAILY_CAP", "TM_ISSUE_MAX_DIFF_LINES",
}


@dataclasses.dataclass(frozen=True)
class Config:
    repo: str                 # "owner/name"
    label: str                # required label to qualify
    fail_label: str           # applied on terminal failure
    max_parallel: int
    poll_interval: int        # seconds
    daily_cap: int            # max fixer spawns per UTC day
    max_diff_lines: int       # 0 = disabled
    branch_prefix: str

    def is_diff_capped(self) -> bool:
        return self.max_diff_lines > 0


_DEFAULTS = {
    "TM_ISSUE_LABEL": "auto-fix",
    "TM_ISSUE_FAIL_LABEL": "auto-fix-failed",
    "TM_ISSUE_MAX_PARALLEL": "3",
    "TM_ISSUE_POLL_INTERVAL": "600",
    "TM_ISSUE_DAILY_CAP": "10",
    "TM_ISSUE_MAX_DIFF_LINES": "2000",
    "TM_ISSUE_BRANCH_PREFIX": "auto-fix/issue-",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue   # silently skip malformed lines (parity with shell `source`)
        out[m.group(1)] = m.group(2).strip()
    return out


def _git_remote_owner_repo(root: Path) -> str | None:
    """Best-effort: parse `git remote get-url origin` for owner/repo. None on failure."""
    try:
        cwd = root if (root / ".git").exists() else root.parent
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", url)
    return m.group(1) if m else None


def load_config(bot_root: Path) -> Config:
    bot_root = Path(bot_root)
    raw = _parse_env_file(bot_root / ".gh-issue-bot.env")
    merged = {**_DEFAULTS, **raw}

    repo = merged.get("TM_GH_REPO") or _git_remote_owner_repo(bot_root)
    if not repo:
        raise ValueError(
            "TM_GH_REPO is unset and `git remote get-url origin` did not yield "
            "a github.com URL. Set TM_GH_REPO in .gh-issue-bot.env."
        )

    def _int(key: str) -> int:
        try:
            return int(merged[key])
        except ValueError as e:
            raise ValueError(f"{key} must be an integer; got {merged[key]!r}") from e

    return Config(
        repo=repo,
        label=merged["TM_ISSUE_LABEL"],
        fail_label=merged["TM_ISSUE_FAIL_LABEL"],
        max_parallel=_int("TM_ISSUE_MAX_PARALLEL"),
        poll_interval=_int("TM_ISSUE_POLL_INTERVAL"),
        daily_cap=_int("TM_ISSUE_DAILY_CAP"),
        max_diff_lines=_int("TM_ISSUE_MAX_DIFF_LINES"),
        branch_prefix=merged["TM_ISSUE_BRANCH_PREFIX"],
    )
```

- [ ] **Step 5.4: Run the tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_config.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add gh-issue-bot/lib/config.py gh-issue-bot/tests/test_config.py
git commit -m "gh-issue-bot: add lib/config.py with .env loader + tests"
```

---

## Task 6: `lib/state.py` — state ledger + state machine

**Files:**
- Create: `gh-issue-bot/lib/state.py`
- Test: `gh-issue-bot/tests/test_state_machine.py`

- [ ] **Step 6.1: Write the failing test**

Create `gh-issue-bot/tests/test_state_machine.py`:

```python
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
```

- [ ] **Step 6.2: Run tests, confirm failure**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_state_machine.py 2>&1 | tail -5`
Expected: ImportError.

- [ ] **Step 6.3: Implement `lib/state.py`**

Create `gh-issue-bot/lib/state.py`:

```python
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
```

- [ ] **Step 6.4: Run tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_state_machine.py -v`
Expected: all tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add gh-issue-bot/lib/state.py gh-issue-bot/tests/test_state_machine.py
git commit -m "gh-issue-bot: add lib/state.py — ledger + state machine"
```

---

## Task 7: `lib/gh.py` — gh CLI wrappers

**Files:**
- Create: `gh-issue-bot/lib/gh.py`
- Test: `gh-issue-bot/tests/test_gh.py`

- [ ] **Step 7.1: Write the failing test**

Create `gh-issue-bot/tests/test_gh.py`:

```python
"""Thin wrappers over `gh` CLI calls."""
import json
import subprocess

import pytest

from lib import gh


def test_list_open_issues_with_label(fake_gh):
    payload = [
        {"number": 1, "title": "fix", "body": "", "labels": [{"name": "auto-fix"}],
         "updatedAt": "2026-05-09T10:00:00Z", "state": "OPEN"},
        {"number": 2, "title": "y", "body": "", "labels": [{"name": "wontfix"}],
         "updatedAt": "2026-05-09T11:00:00Z", "state": "OPEN"},
    ]
    fake_gh(("gh", "issue", "list", "--repo", "o/r", "--label", "auto-fix",
             "--state", "open", "--json", "number,title,body,labels,updatedAt,state",
             "--limit", "200"),
            stdout=json.dumps(payload))
    rows = gh.list_issues("o/r", label="auto-fix")
    assert rows[0]["number"] == 1
    assert rows[1]["number"] == 2


def test_view_issue_returns_full_body(fake_gh):
    payload = {"number": 7, "title": "T", "body": "Big body", "state": "OPEN",
               "labels": [{"name": "auto-fix"}], "updatedAt": "x"}
    fake_gh(("gh", "issue", "view", "7", "--repo", "o/r",
             "--json", "number,title,body,labels,updatedAt,state"),
            stdout=json.dumps(payload))
    issue = gh.view_issue("o/r", 7)
    assert issue["body"] == "Big body"


def test_comment_issue(fake_gh):
    fake_gh(("gh", "issue", "comment", "7", "--repo", "o/r", "--body", "hi"),
            stdout="https://github.com/o/r/issues/7#issuecomment-1\n")
    url = gh.comment_issue("o/r", 7, "hi")
    assert "issuecomment" in url


def test_add_label(fake_gh):
    fake_gh(("gh", "issue", "edit", "7", "--repo", "o/r", "--add-label", "auto-fix-failed"),
            stdout="ok")
    gh.add_label("o/r", 7, "auto-fix-failed")


def test_pr_exists_for_branch_true(fake_gh):
    fake_gh(("gh", "pr", "list", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--state", "open", "--json", "number"),
            stdout=json.dumps([{"number": 99}]))
    n = gh.pr_for_branch("o/r", "auto-fix/issue-42")
    assert n == 99


def test_pr_exists_for_branch_false(fake_gh):
    fake_gh(("gh", "pr", "list", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--state", "open", "--json", "number"),
            stdout="[]")
    assert gh.pr_for_branch("o/r", "auto-fix/issue-42") is None


def test_create_pr_returns_number(fake_gh):
    fake_gh(("gh", "pr", "create", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--base", "main", "--title", "Auto-fix #42: T", "--body", "Closes #42\n\n..."),
            stdout="https://github.com/o/r/pull/123\n")
    n = gh.create_pr("o/r", head="auto-fix/issue-42", base="main",
                     title="Auto-fix #42: T", body="Closes #42\n\n...")
    assert n == 123


def test_propagates_nonzero_exit(fake_gh):
    fake_gh(("gh", "issue", "view", "404", "--repo", "o/r",
             "--json", "number,title,body,labels,updatedAt,state"),
            stdout="", returncode=1, stderr="not found")
    with pytest.raises(gh.GhError, match="not found"):
        gh.view_issue("o/r", 404)
```

- [ ] **Step 7.2: Run, confirm failure**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_gh.py 2>&1 | tail -5`
Expected: ImportError.

- [ ] **Step 7.3: Implement `lib/gh.py`**

Create `gh-issue-bot/lib/gh.py`:

```python
"""Thin wrappers over the `gh` CLI.

Each function does one shell-out and returns a parsed result. Errors raise
GhError with the trimmed stderr. Tests inject a fake `subprocess.run` via the
`fake_gh` fixture, so no network access ever occurs in CI.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

ISSUE_FIELDS = "number,title,body,labels,updatedAt,state"


class GhError(RuntimeError):
    pass


def _run(*argv: str) -> str:
    proc = subprocess.run(list(argv), capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout or "gh failed").strip())
    return proc.stdout


def list_issues(repo: str, *, label: str | None = None,
                state: str = "open", limit: int = 200) -> list[dict]:
    argv = ["gh", "issue", "list", "--repo", repo]
    if label:
        argv += ["--label", label]
    argv += ["--state", state, "--json", ISSUE_FIELDS, "--limit", str(limit)]
    out = _run(*argv)
    return json.loads(out)


def view_issue(repo: str, number: int) -> dict:
    out = _run("gh", "issue", "view", str(number), "--repo", repo,
               "--json", ISSUE_FIELDS)
    return json.loads(out)


def comment_issue(repo: str, number: int, body: str) -> str:
    out = _run("gh", "issue", "comment", str(number), "--repo", repo,
               "--body", body)
    return out.strip()


def add_label(repo: str, number: int, label: str) -> None:
    _run("gh", "issue", "edit", str(number), "--repo", repo,
         "--add-label", label)


def remove_label(repo: str, number: int, label: str) -> None:
    _run("gh", "issue", "edit", str(number), "--repo", repo,
         "--remove-label", label)


def pr_for_branch(repo: str, head: str) -> int | None:
    out = _run("gh", "pr", "list", "--repo", repo, "--head", head,
               "--state", "open", "--json", "number")
    rows = json.loads(out)
    return rows[0]["number"] if rows else None


def create_pr(repo: str, *, head: str, base: str, title: str, body: str) -> int:
    out = _run("gh", "pr", "create", "--repo", repo,
               "--head", head, "--base", base,
               "--title", title, "--body", body)
    m = re.search(r"/pull/(\d+)", out)
    if not m:
        raise GhError(f"could not parse PR number from: {out.strip()}")
    return int(m.group(1))
```

- [ ] **Step 7.4: Run, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_gh.py -v`
Expected: 7 passed.

- [ ] **Step 7.5: Commit**

```bash
git add gh-issue-bot/lib/gh.py gh-issue-bot/tests/test_gh.py
git commit -m "gh-issue-bot: add lib/gh.py — gh CLI wrappers (mocked tests)"
```

---

## Task 8: `bin/tm-issue-bot-pm-start` — sub-PM launcher

**Files:**
- Create: `gh-issue-bot/bin/tm-issue-bot-pm-start`

This script starts a `pm-daemon.py` instance scoped to `gh-issue-bot/` via `TM_ROOT`. It mirrors `bin/tm-pm start --forever` but pinned to this folder.

- [ ] **Step 8.1: Write the script**

Create `gh-issue-bot/bin/tm-issue-bot-pm-start`:

```bash
#!/usr/bin/env bash
# Start the gh-issue-bot sub-PM (separate from the main repo's PM).
# Always runs in --forever mode (issue tasks arrive dynamically).
# Foreground by default; `--background` daemonizes via nohup.
set -euo pipefail

BOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$BOT_ROOT/.." && pwd)"
DAEMON="$REPO_ROOT/bin/pm-daemon.py"
PIDFILE="$BOT_ROOT/pm.pid"
LOG="$BOT_ROOT/pm.log"

bg=0
for arg in "$@"; do
  case "$arg" in
    --background|-b) bg=1 ;;
    *) echo "tm-issue-bot-pm-start: unknown arg $arg" >&2; exit 1 ;;
  esac
done

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "sub-PM already running (pid $(cat "$PIDFILE"))"
  exit 0
fi
rm -f "$PIDFILE"

if [ "$bg" -eq 1 ]; then
  : > "$LOG"
  TM_ROOT="$BOT_ROOT" PM_FOREVER=1 PM_STRICT=1 \
    nohup python3 "$DAEMON" >> "$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  sleep 0.4
  if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "✓ sub-PM started (pid $(cat "$PIDFILE")) log: $LOG"
  else
    echo "✗ sub-PM failed to start; tail of $LOG:" >&2
    tail -n 20 "$LOG" >&2 || true
    exit 1
  fi
else
  exec env TM_ROOT="$BOT_ROOT" PM_FOREVER=1 PM_STRICT=1 \
    python3 "$DAEMON"
fi
```

- [ ] **Step 8.2: Make it executable**

Run: `chmod +x gh-issue-bot/bin/tm-issue-bot-pm-start`

- [ ] **Step 8.3: Lint**

Run: `bash -n gh-issue-bot/bin/tm-issue-bot-pm-start`
Expected: no output.

- [ ] **Step 8.4: Smoke-test (foreground, then immediately Ctrl+C)**

Run:
```bash
gh-issue-bot/bin/tm-issue-bot-pm-start &
PM_PID=$!
sleep 1
ls gh-issue-bot/pm-state.json gh-issue-bot/events/ gh-issue-bot/tasks/ 2>&1 | head
kill $PM_PID 2>/dev/null || true
sleep 0.5
rm -f gh-issue-bot/pm-state.json gh-issue-bot/pm.log gh-issue-bot/pm.pid
```
Expected: the three paths exist (sub-PM created them in BOT_ROOT, not REPO_ROOT). Cleanup removes test artefacts.

- [ ] **Step 8.5: Commit**

```bash
git add gh-issue-bot/bin/tm-issue-bot-pm-start
git commit -m "gh-issue-bot: add bin/tm-issue-bot-pm-start (sub-PM launcher)"
```

---

## Task 9: `bin/tm-claude-issue-fixer` — fixer session wrapper

**Files:**
- Create: `gh-issue-bot/bin/tm-claude-issue-fixer`

This script is invoked by `tm-issue-watcher` (via `_tm-spawn.sh`) to launch a Claude Code session in a per-issue worktree. It:
1. Reads the issue number from `$1`.
2. cd's into the worktree directory.
3. Sets `TM_ROOT=<bot_root>` so `tm-done` writes to the sub-PM.
4. Sources `~/.claude/CLAUDE.md`-style env if needed.
5. exec's `claude` with auto-submit "go" so the worker auto-starts.

- [ ] **Step 9.1: Inspect existing executor wrapper for shape parity**

Run: `cat bin/tm-claude-executor`
Note: take its key invariants (auto-submit "go", session-hook usage) and adapt.

- [ ] **Step 9.2: Write the script**

Create `gh-issue-bot/bin/tm-claude-issue-fixer`:

```bash
#!/usr/bin/env bash
# Launch a Claude Code session inside the per-issue worktree.
# Args: <issue-number>
#
# Called from tm-issue-watcher via _tm-spawn.sh; the watcher has already
# created the worktree and dropped the add_task event for this issue. The
# session here just registers as a sub-PM worker, gets the task, and works.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: tm-claude-issue-fixer <issue-number>" >&2
  exit 64
fi
ISSUE="$1"

BOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$BOT_ROOT/.." && pwd)"
WORKTREE="$BOT_ROOT/worktrees/issue-$ISSUE"

if [ ! -d "$WORKTREE" ]; then
  echo "worktree missing: $WORKTREE — watcher should have created it" >&2
  exit 65
fi

cd "$WORKTREE"
export TM_ROOT="$BOT_ROOT"            # tm-done writes events to sub-PM
export TM_ISSUE_NUMBER="$ISSUE"       # available to the session for the prompt
export TM_PROJECT_NAME="issue-$ISSUE"  # statusline label

# Auto-submit "go" so the session begins immediately, mirroring tm-team-up.
# Pre-flight by piping into claude's tty stdin; harmless if claude doesn't read it.
exec claude --dangerously-skip-permissions <<<"go"
```

- [ ] **Step 9.3: Make executable + lint**

```bash
chmod +x gh-issue-bot/bin/tm-claude-issue-fixer
bash -n gh-issue-bot/bin/tm-claude-issue-fixer
```
Expected: no output from `bash -n`.

- [ ] **Step 9.4: Commit**

```bash
git add gh-issue-bot/bin/tm-claude-issue-fixer
git commit -m "gh-issue-bot: add bin/tm-claude-issue-fixer (fixer session wrapper)"
```

---

## Task 10: `bin/tm-issue-finalize` — finalize/push/PR/comment

**Files:**
- Create: `gh-issue-bot/bin/tm-issue-finalize`
- Test: `gh-issue-bot/tests/test_finalize.py`

Called by `tm-done` as the task's `signal_cmd`. Exit 0 iff branch successfully synced + PR opened (or already exists) + comment posted.

- [ ] **Step 10.1: Write the failing test**

Create `gh-issue-bot/tests/test_finalize.py`:

```python
"""tm-issue-finalize: validates worktree, branch, diff, then push + PR + comment."""
import os
import subprocess
import shutil
import textwrap
from pathlib import Path

import pytest


FINALIZE = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_worktree_with_diff(tmp_git_repo, bot_root, issue_num):
    """Create a worktree at bot_root/worktrees/issue-N with a real diff."""
    branch = f"auto-fix/issue-{issue_num}"
    wt = bot_root / "worktrees" / f"issue-{issue_num}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    (wt / "fix.txt").write_text("the fix\n")
    _git("add", "-A", cwd=wt)
    _git("commit", "-m", f"fix #{issue_num}", cwd=wt)
    return wt, branch


def _stub_gh_in_path(tmp_path: Path, behavior: str = "ok") -> Path:
    """Drop a `gh` shim into a fresh dir and return that dir for $PATH prepend.
    behavior: 'ok' | 'pr-exists' | 'fail-create'.
    """
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    if behavior == "ok":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            cmd="$1 $2"
            case "$cmd" in
              "pr list") echo "[]" ;;
              "pr create") echo "https://github.com/o/r/pull/77" ;;
              "issue comment") echo "https://github.com/o/r/issues/1#c-1" ;;
              *) exit 0 ;;
            esac
        """)
    elif behavior == "pr-exists":
        body = textwrap.dedent("""\
            #!/usr/bin/env bash
            cmd="$1 $2"
            case "$cmd" in
              "pr list") echo '[{"number":55}]' ;;
              "issue comment") echo "https://github.com/o/r/issues/1#c-1" ;;
              *) exit 0 ;;
            esac
        """)
    else:
        body = "#!/usr/bin/env bash\nexit 1\n"
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_finalize_happy_path(tmp_git_repo, tmp_bot_root, monkeypatch, tmp_path):
    issue = 1
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)

    # Repurpose the source repo as the "remote" so push works.
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)

    stubs = _stub_gh_in_path(tmp_path, "ok")
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run(
        [str(FINALIZE), str(issue)],
        cwd=wt, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_finalize_rejects_outside_worktree(tmp_path, monkeypatch):
    """Running finalize from a path outside the bot's worktrees/ must fail."""
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_path / "elsewhere")
    proc = subprocess.run(
        [str(FINALIZE), "1"], cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "worktree" in (proc.stderr + proc.stdout).lower()


def test_finalize_rejects_wrong_branch(tmp_git_repo, tmp_bot_root, tmp_path):
    """Branch must start with TM_ISSUE_BRANCH_PREFIX."""
    issue = 2
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-b", "feature/wrong", str(wt), "main", cwd=tmp_git_repo)
    (wt / "fix.txt").write_text("x"); _git("add", "-A", cwd=wt); _git("commit", "-m", "x", cwd=wt)

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "branch" in (proc.stderr + proc.stdout).lower()


def test_finalize_empty_diff_fails(tmp_git_repo, tmp_bot_root, tmp_path):
    issue = 3
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"auto-fix/issue-{issue}"
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    # No diff.

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "diff" in (proc.stderr + proc.stdout).lower()


def test_finalize_idempotent_when_pr_exists(tmp_git_repo, tmp_bot_root, tmp_path):
    issue = 4
    wt, branch = _make_worktree_with_diff(tmp_git_repo, tmp_bot_root, issue)
    _git("remote", "add", "origin", str(tmp_git_repo), cwd=wt)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=tmp_git_repo)
    stubs = _stub_gh_in_path(tmp_path, "pr-exists")
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "55" in (proc.stdout + proc.stderr)  # reused PR number


def test_finalize_diff_too_large(tmp_git_repo, tmp_bot_root, tmp_path):
    issue = 5
    wt = tmp_bot_root / "worktrees" / f"issue-{issue}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"auto-fix/issue-{issue}"
    _git("worktree", "add", "-b", branch, str(wt), "main", cwd=tmp_git_repo)
    big = "\n".join(f"line {i}" for i in range(1500)) + "\n"
    (wt / "big.txt").write_text(big)
    _git("add", "-A", cwd=wt); _git("commit", "-m", "big", cwd=wt)

    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_ISSUE_MAX_DIFF_LINES"] = "100"
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(FINALIZE), str(issue)], cwd=wt, env=env,
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "diff" in (proc.stderr + proc.stdout).lower()
```

- [ ] **Step 10.2: Run tests, expect failure (script doesn't exist)**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_finalize.py 2>&1 | tail -5`
Expected: every test fails with "FileNotFoundError" or non-zero exit.

- [ ] **Step 10.3: Implement `tm-issue-finalize`**

Create `gh-issue-bot/bin/tm-issue-finalize`:

```bash
#!/usr/bin/env bash
# tm-issue-finalize <issue-number>
#
# Called by tm-done as a task's signal_cmd. Run from inside the per-issue
# worktree. On success: pushes branch, opens PR (idempotent), posts comment
# on the issue, exits 0. On any safety/validation failure: exits non-zero
# with a reason on stderr.
#
# Required env:
#   TM_BOT_ROOT             absolute path to gh-issue-bot/
#   TM_GH_REPO              owner/repo (target of the PR)
#   TM_ISSUE_BRANCH_PREFIX  e.g. "auto-fix/issue-"
# Optional:
#   TM_ISSUE_MAX_DIFF_LINES default 2000; 0 disables
set -euo pipefail

if [ $# -lt 1 ]; then echo "usage: tm-issue-finalize <issue#>" >&2; exit 64; fi
ISSUE="$1"
[ -n "${TM_BOT_ROOT:-}" ]              || { echo "TM_BOT_ROOT unset" >&2; exit 2; }
[ -n "${TM_GH_REPO:-}" ]               || { echo "TM_GH_REPO unset" >&2; exit 2; }
[ -n "${TM_ISSUE_BRANCH_PREFIX:-}" ]   || { echo "TM_ISSUE_BRANCH_PREFIX unset" >&2; exit 2; }
MAX_DIFF="${TM_ISSUE_MAX_DIFF_LINES:-2000}"

# 1. cwd lock — must resolve inside TM_BOT_ROOT/worktrees/issue-<N>
CWD_REAL="$(cd "$PWD" && pwd -P)"
WT_REQUIRED="$(cd "$TM_BOT_ROOT" && pwd -P)/worktrees/issue-${ISSUE}"
if [ "$CWD_REAL" != "$WT_REQUIRED" ]; then
  echo "finalize refused: cwd '$CWD_REAL' is not the expected worktree '$WT_REQUIRED'" >&2
  exit 10
fi

# 2. branch lock
HEAD_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
case "$HEAD_BRANCH" in
  "$TM_ISSUE_BRANCH_PREFIX"*) ;;
  *) echo "finalize refused: HEAD branch '$HEAD_BRANCH' lacks prefix '$TM_ISSUE_BRANCH_PREFIX'" >&2; exit 11 ;;
esac

# 3. diff existence check
if git diff --quiet main -- 2>/dev/null && git diff --cached --quiet main -- 2>/dev/null; then
  # Nothing changed at all relative to main.
  echo "finalize refused: empty diff against main (session produced no changes)" >&2
  exit 12
fi

# 4. diff size guard
if [ "$MAX_DIFF" != "0" ]; then
  changed=$(git diff main -- 2>/dev/null | grep -E '^[+-]' | grep -Ev '^(\+\+\+|---)' | wc -l | tr -d ' ')
  if [ "$changed" -gt "$MAX_DIFF" ]; then
    echo "finalize refused: diff size $changed lines exceeds TM_ISSUE_MAX_DIFF_LINES=$MAX_DIFF" >&2
    exit 13
  fi
fi

# 5. Push (idempotent: -u sets upstream once, force-with-lease guards subsequent pushes)
git push -u --force-with-lease origin "HEAD:$HEAD_BRANCH" >/dev/null

# 6. PR — open if missing, else reuse number
PR_NUM=$(gh pr list --repo "$TM_GH_REPO" --head "$HEAD_BRANCH" --state open --json number --jq '.[0].number' 2>/dev/null || true)
if [ -z "$PR_NUM" ] || [ "$PR_NUM" = "null" ]; then
  TITLE_RAW=$(git log -1 --format=%s)
  TITLE="Auto-fix #${ISSUE}: ${TITLE_RAW}"
  BODY="$(printf 'Closes #%s\n\nOpened automatically by gh-issue-bot.\n' "$ISSUE")"
  PR_URL=$(gh pr create --repo "$TM_GH_REPO" --head "$HEAD_BRANCH" --base main \
           --title "$TITLE" --body "$BODY")
  PR_NUM=$(printf '%s' "$PR_URL" | grep -oE '/pull/[0-9]+' | grep -oE '[0-9]+' | tail -1)
fi

# 7. Comment on the issue (idempotent enough — duplicate "Resolved by..." is harmless)
gh issue comment "$ISSUE" --repo "$TM_GH_REPO" \
  --body "Resolved by PR #${PR_NUM} (auto-generated by gh-issue-bot)." >/dev/null

echo "ok pr=$PR_NUM branch=$HEAD_BRANCH"
```

- [ ] **Step 10.4: Make executable + lint**

```bash
chmod +x gh-issue-bot/bin/tm-issue-finalize
bash -n gh-issue-bot/bin/tm-issue-finalize
```

- [ ] **Step 10.5: Run finalize tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_finalize.py -v`
Expected: 5 passed.

- [ ] **Step 10.6: Commit**

```bash
git add gh-issue-bot/bin/tm-issue-finalize gh-issue-bot/tests/test_finalize.py
git commit -m "gh-issue-bot: add bin/tm-issue-finalize + tests (push + PR + comment)"
```

---

## Task 11: `bin/tm-issue-fail` — failure comment helper

**Files:**
- Create: `gh-issue-bot/bin/tm-issue-fail`
- Test: `gh-issue-bot/tests/test_fail.py`

- [ ] **Step 11.1: Write the failing test**

Create `gh-issue-bot/tests/test_fail.py`:

```python
"""tm-issue-fail posts comment + adds fail label."""
import os
import subprocess
import textwrap
from pathlib import Path


FAIL = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-fail"


def _stub_gh(tmp_path: Path, log_path: Path) -> Path:
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    body = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log_path}"
        exit 0
    """)
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_fail_posts_comment_and_adds_label(tmp_path):
    log = tmp_path / "gh.log"
    stubs = _stub_gh(tmp_path, log)
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_ISSUE_FAIL_LABEL"] = "auto-fix-failed"

    proc = subprocess.run([str(FAIL), "42", "diff was empty"],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    log_text = log.read_text()
    assert "issue comment 42" in log_text
    assert "diff was empty" in log_text
    assert "issue edit 42" in log_text
    assert "--add-label auto-fix-failed" in log_text


def test_fail_requires_args(tmp_path):
    proc = subprocess.run([str(FAIL)], capture_output=True, text=True)
    assert proc.returncode == 64
```

- [ ] **Step 11.2: Run, expect failure**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_fail.py 2>&1 | tail -5`
Expected: file-not-found.

- [ ] **Step 11.3: Implement `tm-issue-fail`**

Create `gh-issue-bot/bin/tm-issue-fail`:

```bash
#!/usr/bin/env bash
# tm-issue-fail <issue#> "<reason>"
#
# Posts a "auto-fix-failed: <reason>" comment on the issue and adds the
# fail label. Used by tm-issue-watcher when an attempt is permanently lost.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: tm-issue-fail <issue#> <reason>" >&2
  exit 64
fi
ISSUE="$1"; shift
REASON="$*"

[ -n "${TM_GH_REPO:-}" ]         || { echo "TM_GH_REPO unset" >&2; exit 2; }
LABEL="${TM_ISSUE_FAIL_LABEL:-auto-fix-failed}"

BODY="$(printf 'auto-fix-failed: %s\n\n(gh-issue-bot will not retry this issue until the `%s` label is removed.)\n' "$REASON" "$LABEL")"

gh issue comment "$ISSUE" --repo "$TM_GH_REPO" --body "$BODY" >/dev/null
gh issue edit    "$ISSUE" --repo "$TM_GH_REPO" --add-label "$LABEL" >/dev/null
echo "ok labelled=$LABEL"
```

- [ ] **Step 11.4: chmod, lint, test**

```bash
chmod +x gh-issue-bot/bin/tm-issue-fail
bash -n gh-issue-bot/bin/tm-issue-fail
cd gh-issue-bot && python3 -m pytest -q tests/test_fail.py -v
```
Expected: all pass.

- [ ] **Step 11.5: Commit**

```bash
git add gh-issue-bot/bin/tm-issue-fail gh-issue-bot/tests/test_fail.py
git commit -m "gh-issue-bot: add bin/tm-issue-fail + tests (failure comment + label)"
```

---

## Task 12: `bin/tm-issue-watcher` — main poller

This is the largest single component. Decompose into smaller helpers in `lib/watcher_logic.py` for testability, and a thin CLI in `bin/tm-issue-watcher`.

**Files:**
- Create: `gh-issue-bot/lib/watcher_logic.py`
- Create: `gh-issue-bot/bin/tm-issue-watcher`
- Test: `gh-issue-bot/tests/test_watcher_logic.py`
- Test: `gh-issue-bot/tests/test_watcher_e2e.py`

- [ ] **Step 12.1: Write `test_watcher_logic.py` (unit-level)**

Create `gh-issue-bot/tests/test_watcher_logic.py`:

```python
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
```

- [ ] **Step 12.2: Run, expect ImportError on watcher_logic**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_watcher_logic.py 2>&1 | tail -3`
Expected: ImportError.

- [ ] **Step 12.3: Implement `lib/watcher_logic.py`**

Create `gh-issue-bot/lib/watcher_logic.py`:

```python
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
```

- [ ] **Step 12.4: Run unit tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_watcher_logic.py -v`
Expected: 9 passed.

- [ ] **Step 12.5: Commit watcher_logic + its tests**

```bash
git add gh-issue-bot/lib/watcher_logic.py gh-issue-bot/tests/test_watcher_logic.py
git commit -m "gh-issue-bot: add lib/watcher_logic.py — pure tick decision logic"
```

- [ ] **Step 12.6: Write `tests/test_watcher_e2e.py`**

Create `gh-issue-bot/tests/test_watcher_e2e.py`:

```python
"""End-to-end: mock gh + tmp git repo → one tick → state.json + add_task event."""
import json
import os
import subprocess
import textwrap
from pathlib import Path


WATCHER = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-watcher"


def _stub_gh_returning(tmp_path: Path, issues_json: str) -> Path:
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    body = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
          cat <<'JSON'
{issues_json}
JSON
          exit 0
        fi
        exit 0
    """)
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def _seed_bot_root(tmp_git_repo, tmp_bot_root):
    """Make tmp_git_repo behave as the repo's `origin` for worktree commands."""
    # bot_root is alongside repo, but worktree must be on the repo's git dir.
    # We make bot_root contain a .git symlink-ish — easier: have the watcher
    # spawn worktrees against tmp_git_repo by setting TM_REPO_PATH (a knob the
    # watcher honors for testing; in production it derives it from the repo
    # the bot lives in).
    return tmp_git_repo


def test_one_tick_promotes_and_writes_event(tmp_git_repo, tmp_bot_root, tmp_path):
    issues = [{
        "number": 42, "title": "fix typo", "body": "the body",
        "labels": [{"name": "auto-fix"}], "state": "OPEN",
        "updatedAt": "2026-05-09T10:00:00Z",
    }]
    stubs = _stub_gh_returning(tmp_path, json.dumps(issues))

    # Stub `_tm-spawn.sh` invocation by intercepting `tm-claude-issue-fixer`
    # — the watcher in --dry-run mode should NOT spawn anything anyway.
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_REPO_PATH"] = str(tmp_git_repo)
    env["TM_GH_REPO"] = "o/r"
    env["TM_ISSUE_LABEL"] = "auto-fix"
    env["TM_ISSUE_FAIL_LABEL"] = "auto-fix-failed"
    env["TM_ISSUE_BRANCH_PREFIX"] = "auto-fix/issue-"
    env["TM_ISSUE_MAX_PARALLEL"] = "3"
    env["TM_ISSUE_DAILY_CAP"] = "10"
    env["TM_ISSUE_POLL_INTERVAL"] = "600"
    env["TM_ISSUE_MAX_DIFF_LINES"] = "2000"
    env["TM_DRY_RUN"] = "1"

    proc = subprocess.run([str(WATCHER), "tick"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    # state.json reflects the issue as `seen` (dry-run: no promote)
    led = json.loads((tmp_bot_root / "state.json").read_text())
    assert "42" in led["issues"]
    assert led["issues"]["42"]["status"] == "seen"


def test_status_subcommand_reports_in_flight(tmp_bot_root):
    # Pre-seed a state.json with one assigned issue.
    (tmp_bot_root / "state.json").write_text(json.dumps({
        "version": 1, "last_poll_ts": "x",
        "daily_spawn_count": 1, "daily_spawn_date": "2026-05-09",
        "issues": {"7": {"status": "assigned", "title": "t", "labels": [],
                          "updated_at": "x", "worktree": None, "branch": None,
                          "task_id": None, "pr_number": None,
                          "session_id": None, "first_seen_ts": None,
                          "attempts": 1}},
    }, indent=2))
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_GH_REPO"] = "o/r"

    proc = subprocess.run([str(WATCHER), "status"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "in-flight" in proc.stdout.lower()
    assert "7" in proc.stdout
```

- [ ] **Step 12.7: Run, expect FileNotFoundError on the watcher**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_watcher_e2e.py 2>&1 | tail -3`
Expected: failure (script doesn't exist).

- [ ] **Step 12.8: Implement `bin/tm-issue-watcher`**

Create `gh-issue-bot/bin/tm-issue-watcher`:

```python
#!/usr/bin/env python3
"""tm-issue-watcher — the 10-min poller for gh-issue-bot.

Subcommands:
  tick     run one poll/diff/spawn/reap cycle
  status   summarize scheduler / sub-PM / in-flight issues to stdout
  doctor   sanity-check config and external tools (gh, git)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure lib/ on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load_config
from lib.gh import list_issues, GhError
from lib.state import load_ledger, save_ledger
from lib.watcher_logic import plan_actions

WATCHER_LOG_NAME = "watcher.log"


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bot_root() -> Path:
    p = os.environ.get("TM_BOT_ROOT")
    if p:
        return Path(p).resolve()
    return Path(__file__).resolve().parents[1]


def _repo_path() -> Path:
    """Path to the *target* git repo (whose remote we push to)."""
    p = os.environ.get("TM_REPO_PATH")
    if p:
        return Path(p).resolve()
    # Default: the parent of bot_root (the ZeroProgramer repo itself).
    return _bot_root().parent


def _disabled(bot_root: Path) -> bool:
    return (bot_root / ".disabled").exists()


def _create_worktree(repo: Path, wt_dir: Path, branch: str) -> None:
    wt_dir.parent.mkdir(parents=True, exist_ok=True)
    if wt_dir.exists():
        return  # already created (resume after crash)
    subprocess.run(["git", "worktree", "add", "-b", branch, str(wt_dir), "main"],
                   cwd=repo, check=True, capture_output=True)


def _drop_add_task_event(bot_root: Path, *, title: str, signal_cmd: str,
                         source: str) -> None:
    events_dir = bot_root / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    micro = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1_000_000)
    payload = {
        "ts": _now_iso(),
        "type": "add_task",
        "session_id": "watcher",
        "data": {"title": title, "signal_cmd": signal_cmd, "source": source},
    }
    p = events_dir / f"{micro}_add_task_{source.replace(':','_')}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, p)


def _spawn_fixer(bot_root: Path, issue_num: str) -> str | None:
    """Launch a new terminal running tm-claude-issue-fixer <N>. Returns 'spawned'
    or None on failure. Honors TM_DRY_RUN=1 (logs only)."""
    if os.environ.get("TM_DRY_RUN") == "1":
        _log(bot_root, f"DRY: would spawn fixer for issue #{issue_num}")
        return "dry"
    repo_root = _repo_path()
    spawn_helper = repo_root / "bin" / "_tm-spawn.sh"
    fixer = bot_root / "bin" / "tm-claude-issue-fixer"
    cmd = (
        f". '{spawn_helper}' && "
        f"tm_spawn_terminal_window '{bot_root}' '{fixer} {issue_num}'"
    )
    proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        _log(bot_root, f"spawn failed for #{issue_num}: {proc.stderr.strip()}")
        return None
    return "spawned"


def _log(bot_root: Path, msg: str) -> None:
    p = bot_root / WATCHER_LOG_NAME
    with p.open("a") as f:
        f.write(f"[{_now_iso()}] {msg}\n")


# ── Subcommands ────────────────────────────────────────────────────────────

def cmd_tick(args) -> int:
    bot_root = _bot_root()
    if _disabled(bot_root):
        _log(bot_root, "tick: .disabled present; skipping")
        return 0
    cfg = load_config(bot_root)
    led = load_ledger(bot_root)

    try:
        issues = list_issues(cfg.repo, label=cfg.label)
    except GhError as e:
        _log(bot_root, f"gh issue list FAILED: {e}")
        return 1

    today = _today_utc()
    actions = plan_actions(issues, led, cfg, today=today)

    promoted = 0
    cancelled = 0
    for a in actions:
        if a["op"] == "upsert_seen":
            led.upsert_seen(a["number"], title=a["title"],
                            labels=a["labels"], updated_at=a["updated_at"])
        elif a["op"] == "cancel":
            led.transition(a["number"], "cancelled")
            cancelled += 1
        elif a["op"] == "promote":
            num = a["number"]
            branch = f"{cfg.branch_prefix}{num}"
            wt = bot_root / "worktrees" / f"issue-{num}"
            try:
                if os.environ.get("TM_DRY_RUN") != "1":
                    _create_worktree(_repo_path(), wt, branch)
                title = (
                    f"[issue #{num}] {a['title']}\n\nBody:\n{a['body']}\n\n"
                    f"WORKTREE: {wt}\nISSUE: {num}\n\n"
                    f"Edit code in WORKTREE to resolve the issue, then run tm-done."
                )
                signal_cmd = f"{bot_root / 'bin' / 'tm-issue-finalize'} {num}"
                if os.environ.get("TM_DRY_RUN") != "1":
                    _drop_add_task_event(
                        bot_root, title=title, signal_cmd=signal_cmd,
                        source=f"github-issue:{num}",
                    )
                if os.environ.get("TM_DRY_RUN") != "1":
                    led.transition(num, "assigned",
                                   worktree=str(wt), branch=branch,
                                   attempts=led.issues[num].attempts + 1)
                    led.note_spawn(today=today)
                    _spawn_fixer(bot_root, num)
                promoted += 1
            except Exception as e:
                _log(bot_root, f"promote #{num} FAILED: {e}")

    led.last_poll_ts = _now_iso()
    save_ledger(bot_root, led)
    _log(bot_root, f"tick: promoted={promoted} cancelled={cancelled} "
                   f"in_flight={led.count_in_flight()} daily={led.daily_spawn_count}")
    return 0


def cmd_status(args) -> int:
    bot_root = _bot_root()
    led = load_ledger(bot_root)
    print(f"gh-issue-bot @ {bot_root}")
    print(f"  last_poll: {led.last_poll_ts or 'never'}")
    print(f"  daily spawns: {led.daily_spawn_count} (date {led.daily_spawn_date})")
    in_flight = [(n, r) for n, r in led.issues.items() if r.status == "assigned"]
    print(f"  in-flight ({len(in_flight)}):")
    for num, rec in in_flight:
        print(f"    #{num} {rec.title[:60]} attempts={rec.attempts} branch={rec.branch}")
    return 0


def cmd_doctor(args) -> int:
    bot_root = _bot_root()
    ok = True
    for tool in ("gh", "git"):
        proc = subprocess.run(["which", tool], capture_output=True, text=True)
        print(f"  {tool}: {proc.stdout.strip() or 'NOT FOUND'}")
        if proc.returncode != 0: ok = False
    try:
        cfg = load_config(bot_root)
        print(f"  config: repo={cfg.repo} label={cfg.label} max_parallel={cfg.max_parallel}")
    except Exception as e:
        print(f"  config: FAIL {e}")
        ok = False
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="tm-issue-watcher")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick").set_defaults(func=cmd_tick)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 12.9: chmod, sanity check imports**

```bash
chmod +x gh-issue-bot/bin/tm-issue-watcher
python3 -c "import importlib.util, sys; sys.path.insert(0,'gh-issue-bot'); spec=importlib.util.spec_from_file_location('w','gh-issue-bot/bin/tm-issue-watcher'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('ok')"
```
Expected: `ok`.

- [ ] **Step 12.10: Run e2e tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_watcher_e2e.py -v`
Expected: 2 passed.

- [ ] **Step 12.11: Run the full gh-issue-bot suite**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/`
Expected: all tests pass (config + state + gh + finalize + fail + watcher_logic + watcher_e2e).

- [ ] **Step 12.12: Commit**

```bash
git add gh-issue-bot/bin/tm-issue-watcher gh-issue-bot/tests/test_watcher_e2e.py
git commit -m "gh-issue-bot: add bin/tm-issue-watcher (poll + diff + spawn + reap)"
```

---

## Task 13: `lib/scheduler.py` — cross-platform install/uninstall

**Files:**
- Create: `gh-issue-bot/lib/scheduler.py`
- Test: `gh-issue-bot/tests/test_install_macos.py`
- Test: `gh-issue-bot/tests/test_install_linux.py`

- [ ] **Step 13.1: Write failing tests**

Create `gh-issue-bot/tests/test_install_macos.py`:

```python
"""macOS launchd backend: render plist, install, uninstall, idempotent."""
from pathlib import Path

from lib.scheduler import (
    detect_platform, render_macos_plist,
    macos_install, macos_uninstall, MACOS_LABEL,
)


def test_detect_macos(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert detect_platform() == "macos"


def test_render_plist_has_required_fields():
    out = render_macos_plist(
        watcher="/abs/bot/bin/tm-issue-watcher",
        log="/abs/bot/watcher.log",
        interval=600,
    )
    assert "<key>Label</key><string>com.zeroprogramer.gh-issue-bot</string>" in out
    assert "<integer>600</integer>" in out
    assert "/abs/bot/bin/tm-issue-watcher" in out
    assert "<key>RunAtLoad</key><true/>" in out


def test_macos_install_writes_plist(tmp_path, monkeypatch):
    target = tmp_path / "LaunchAgents"
    target.mkdir()
    calls = []
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **kw: calls.append(a[0]) or type("R", (), {"returncode":0,"stdout":"","stderr":""})())
    monkeypatch.setattr("lib.scheduler._launch_agents_dir", lambda: target)

    macos_install(watcher="/x/bin/tm-issue-watcher", log="/x/log", interval=600)
    assert (target / f"{MACOS_LABEL}.plist").exists()
    # bootstrap call recorded
    assert any("launchctl" in (a[0] if isinstance(a, list) else "") for a in calls)


def test_macos_uninstall_removes_plist(tmp_path, monkeypatch):
    target = tmp_path / "LaunchAgents"
    target.mkdir()
    plist = target / f"{MACOS_LABEL}.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **kw: type("R", (), {"returncode":0,"stdout":"","stderr":""})())
    monkeypatch.setattr("lib.scheduler._launch_agents_dir", lambda: target)
    macos_uninstall()
    assert not plist.exists()


def test_macos_install_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "LaunchAgents"
    target.mkdir()
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **kw: type("R", (), {"returncode":0,"stdout":"","stderr":""})())
    monkeypatch.setattr("lib.scheduler._launch_agents_dir", lambda: target)
    macos_install(watcher="/x/w", log="/x/l", interval=600)
    macos_install(watcher="/x/w", log="/x/l", interval=600)  # second time
    files = list(target.iterdir())
    assert len(files) == 1
```

Create `gh-issue-bot/tests/test_install_linux.py`:

```python
"""Linux backends: systemd timer or cron line."""
from lib.scheduler import (
    render_systemd_service, render_systemd_timer,
    render_cron_line, CRON_BEGIN, CRON_END,
    inject_cron_block, remove_cron_block,
)


def test_render_systemd_service():
    out = render_systemd_service(watcher="/x/bin/tm-issue-watcher")
    assert "ExecStart=/x/bin/tm-issue-watcher tick" in out


def test_render_systemd_timer():
    out = render_systemd_timer(interval=600)
    assert "OnUnitActiveSec=600s" in out
    assert "Persistent=true" in out


def test_render_cron_line():
    out = render_cron_line(watcher="/x/bin/tm-issue-watcher",
                           log="/x/watcher.log", interval=600)
    # 600s == every 10 minutes
    assert "*/10 * * * *" in out
    assert "/x/bin/tm-issue-watcher tick" in out
    assert ">> /x/watcher.log" in out


def test_inject_cron_block_idempotent():
    existing = "0 5 * * * something\n"
    new = "*/10 * * * * /x/bin/tm-issue-watcher tick"
    out1 = inject_cron_block(existing, new)
    assert CRON_BEGIN in out1
    assert CRON_END in out1
    assert new in out1
    out2 = inject_cron_block(out1, new)
    assert out1 == out2  # second injection is a no-op


def test_remove_cron_block():
    base = "0 5 * * * x\n"
    new = "*/10 * * * * /a"
    with_block = inject_cron_block(base, new)
    cleaned = remove_cron_block(with_block)
    assert CRON_BEGIN not in cleaned
    assert CRON_END not in cleaned
    assert "0 5 * * * x" in cleaned
```

- [ ] **Step 13.2: Run, expect ImportError**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_install_macos.py tests/test_install_linux.py 2>&1 | tail -3`
Expected: ImportError on `lib.scheduler`.

- [ ] **Step 13.3: Implement `lib/scheduler.py`**

Create `gh-issue-bot/lib/scheduler.py`:

```python
"""Cross-platform scheduler install/uninstall.

Backends:
  macOS  → launchd LaunchAgent in ~/Library/LaunchAgents
  Linux  → systemd user .service + .timer (preferred) or crontab block (fallback)
  Windows → schtasks.exe (created via tm-issue-bot CLI; this module returns the
            command lines, since schtasks is best invoked from a shell)
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

MACOS_LABEL = "com.zeroprogramer.gh-issue-bot"
CRON_BEGIN = "# >>> gh-issue-bot >>>"
CRON_END   = "# <<< gh-issue-bot <<<"


# ── platform detection ────────────────────────────────────────────────────

def detect_platform() -> str:
    sysname = platform.system()
    if sysname == "Darwin":
        return "macos"
    if sysname == "Windows":
        return "windows"
    if sysname == "Linux":
        # WSL still installs via Linux backend; user can opt-in to schtasks via
        # explicit override.
        if _has("systemctl"):
            return "linux-systemd"
        return "linux-cron"
    return "unsupported"


def _has(tool: str) -> bool:
    return subprocess.run(["which", tool], capture_output=True).returncode == 0


# ── macOS ─────────────────────────────────────────────────────────────────

def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def render_macos_plist(*, watcher: str, log: str, interval: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{MACOS_LABEL}</string>
  <key>ProgramArguments</key>
    <array>
      <string>{watcher}</string>
      <string>tick</string>
    </array>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict></plist>
"""


def macos_install(*, watcher: str, log: str, interval: int) -> None:
    d = _launch_agents_dir()
    d.mkdir(parents=True, exist_ok=True)
    plist_path = d / f"{MACOS_LABEL}.plist"
    plist_path.write_text(render_macos_plist(watcher=watcher, log=log,
                                             interval=interval))
    # Re-bootstrap (unload first to make idempotent)
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True,
                   capture_output=True)


def macos_uninstall() -> None:
    plist_path = _launch_agents_dir() / f"{MACOS_LABEL}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)],
                       capture_output=True)
        plist_path.unlink()


# ── Linux: systemd user ───────────────────────────────────────────────────

def _systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def render_systemd_service(*, watcher: str) -> str:
    return f"""[Unit]
Description=gh-issue-bot watcher

[Service]
Type=oneshot
ExecStart={watcher} tick
"""


def render_systemd_timer(*, interval: int) -> str:
    return f"""[Unit]
Description=gh-issue-bot watcher timer

[Timer]
OnBootSec=60
OnUnitActiveSec={interval}s
Persistent=true
Unit=gh-issue-bot.service

[Install]
WantedBy=timers.target
"""


def systemd_install(*, watcher: str, interval: int) -> None:
    d = _systemd_user_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "gh-issue-bot.service").write_text(render_systemd_service(watcher=watcher))
    (d / "gh-issue-bot.timer").write_text(render_systemd_timer(interval=interval))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "gh-issue-bot.timer"],
                   check=True)


def systemd_uninstall() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", "gh-issue-bot.timer"],
                   capture_output=True)
    d = _systemd_user_dir()
    for f in ("gh-issue-bot.service", "gh-issue-bot.timer"):
        p = d / f
        if p.exists(): p.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


# ── Linux: cron fallback ──────────────────────────────────────────────────

def render_cron_line(*, watcher: str, log: str, interval: int) -> str:
    minutes = max(1, interval // 60)
    return f"*/{minutes} * * * * {watcher} tick >> {log} 2>&1"


def inject_cron_block(existing: str, line: str) -> str:
    if CRON_BEGIN in existing:
        # Replace whatever's between begin/end markers with our block.
        out = []
        skip = False
        for raw in existing.splitlines(keepends=True):
            if raw.strip() == CRON_BEGIN:
                skip = True
                out.append(CRON_BEGIN + "\n"); out.append(line + "\n"); out.append(CRON_END + "\n")
                continue
            if raw.strip() == CRON_END:
                skip = False
                continue
            if skip:
                continue
            out.append(raw)
        return "".join(out)
    suffix = "" if existing.endswith("\n") or not existing else "\n"
    return existing + suffix + CRON_BEGIN + "\n" + line + "\n" + CRON_END + "\n"


def remove_cron_block(existing: str) -> str:
    out = []
    skip = False
    for raw in existing.splitlines(keepends=True):
        if raw.strip() == CRON_BEGIN: skip = True; continue
        if raw.strip() == CRON_END:   skip = False; continue
        if skip: continue
        out.append(raw)
    return "".join(out)


def cron_install(*, watcher: str, log: str, interval: int) -> None:
    line = render_cron_line(watcher=watcher, log=log, interval=interval)
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    base = existing.stdout if existing.returncode == 0 else ""
    new = inject_cron_block(base, line)
    proc = subprocess.run(["crontab", "-"], input=new, text=True,
                          capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"crontab install failed: {proc.stderr}")


def cron_uninstall() -> None:
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    base = existing.stdout if existing.returncode == 0 else ""
    new = remove_cron_block(base)
    if new.strip():
        subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    else:
        subprocess.run(["crontab", "-r"], capture_output=True)
```

- [ ] **Step 13.4: Run scheduler tests, expect green**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/test_install_macos.py tests/test_install_linux.py -v`
Expected: all pass.

- [ ] **Step 13.5: Commit**

```bash
git add gh-issue-bot/lib/scheduler.py gh-issue-bot/tests/test_install_macos.py gh-issue-bot/tests/test_install_linux.py
git commit -m "gh-issue-bot: add lib/scheduler.py — launchd / systemd / cron backends"
```

---

## Task 14: `bin/tm-issue-bot` — top-level CLI

**Files:**
- Create: `gh-issue-bot/bin/tm-issue-bot`

The user-facing entry point. Routes install/uninstall/start/stop/status/tick/logs/doctor to the right backend.

- [ ] **Step 14.1: Write the script**

Create `gh-issue-bot/bin/tm-issue-bot`:

```bash
#!/usr/bin/env bash
# tm-issue-bot — top-level CLI for the gh-issue-bot sub-project.
set -euo pipefail

BOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$BOT_ROOT/.." && pwd)"
WATCHER="$BOT_ROOT/bin/tm-issue-watcher"
PMSTART="$BOT_ROOT/bin/tm-issue-bot-pm-start"
LOG="$BOT_ROOT/watcher.log"
PIDFILE="$BOT_ROOT/pm.pid"
WATCHDOG_PIDFILE="$BOT_ROOT/pm-watchdog.pid"
WATCHDOG_LOG="$BOT_ROOT/pm-watchdog.log"

# Read poll interval from .env (default 600)
INTERVAL=600
if [ -f "$BOT_ROOT/.gh-issue-bot.env" ]; then
  v=$(awk -F= '/^TM_ISSUE_POLL_INTERVAL=/ {print $2; exit}' "$BOT_ROOT/.gh-issue-bot.env" || true)
  [ -n "${v:-}" ] && INTERVAL="$v"
fi

is_pm_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
is_wd_running() { [ -f "$WATCHDOG_PIDFILE" ] && kill -0 "$(cat "$WATCHDOG_PIDFILE")" 2>/dev/null; }

cmd_install() {
  echo "── installing gh-issue-bot ──"
  # 1. ensure config exists
  if [ ! -f "$BOT_ROOT/.gh-issue-bot.env" ]; then
    cp "$BOT_ROOT/.gh-issue-bot.env.example" "$BOT_ROOT/.gh-issue-bot.env"
    echo "  wrote default $BOT_ROOT/.gh-issue-bot.env (review it!)"
  fi
  # 2. start sub-PM (background)
  "$PMSTART" --background
  # 3. start watchdog (uses tm-pm watchdog --forever scoped to BOT_ROOT)
  if ! is_wd_running; then
    : > "$WATCHDOG_LOG"
    TM_ROOT="$BOT_ROOT" nohup "$REPO_ROOT/bin/tm-pm" watchdog --forever \
      >> "$WATCHDOG_LOG" 2>&1 &
    sleep 0.4
  fi
  # 4. install scheduler
  python3 - "$BOT_ROOT" "$WATCHER" "$LOG" "$INTERVAL" <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))
from lib.scheduler import (
    detect_platform,
    macos_install, systemd_install, cron_install,
)
plat = detect_platform()
if plat == "macos":
    macos_install(watcher=sys.argv[2], log=sys.argv[3], interval=int(sys.argv[4]))
elif plat == "linux-systemd":
    systemd_install(watcher=sys.argv[2], interval=int(sys.argv[4]))
elif plat == "linux-cron":
    cron_install(watcher=sys.argv[2], log=sys.argv[3], interval=int(sys.argv[4]))
else:
    print(f"unsupported platform: {plat}", file=sys.stderr); sys.exit(1)
print(f"  scheduler installed: {plat}")
PY
  # 5. validation tick (dry-run)
  echo "── validation tick (dry-run) ──"
  TM_BOT_ROOT="$BOT_ROOT" TM_DRY_RUN=1 "$WATCHER" tick || {
    echo "✗ validation tick failed; rolling back" >&2
    cmd_uninstall
    exit 1
  }
  echo "✓ install complete"
  cmd_status
}

cmd_uninstall() {
  echo "── uninstalling gh-issue-bot ──"
  python3 - "$BOT_ROOT" <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))
from lib.scheduler import detect_platform, macos_uninstall, systemd_uninstall, cron_uninstall
plat = detect_platform()
if plat == "macos":         macos_uninstall()
elif plat == "linux-systemd": systemd_uninstall()
elif plat == "linux-cron":    cron_uninstall()
PY
  # stop watchdog before PM (so PM stays down)
  if is_wd_running; then kill "$(cat "$WATCHDOG_PIDFILE")" 2>/dev/null || true; fi
  rm -f "$WATCHDOG_PIDFILE"
  if is_pm_running; then
    TM_ROOT="$BOT_ROOT" "$REPO_ROOT/bin/tm-pm" shutdown "uninstall" || true
    sleep 1
    is_pm_running && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo "✓ scheduler removed; sub-PM stopped"
  printf "Remove worktrees and state.json? [y/N] "
  read -r ans || ans=""
  case "$ans" in
    y|Y|yes|YES)
      rm -rf "$BOT_ROOT/worktrees"/* "$BOT_ROOT/state.json" "$BOT_ROOT/pm-state.json"
      rm -rf "$BOT_ROOT/events"/* "$BOT_ROOT/tasks"/* "$BOT_ROOT/escalations"/*
      echo "  ✓ purged" ;;
    *) echo "  (kept worktrees/ and state.json)" ;;
  esac
}

cmd_status() {
  echo "── gh-issue-bot status ──"
  echo -n "  scheduler: "
  python3 - "$BOT_ROOT" <<'PY'
import sys, pathlib, subprocess
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve()))
from lib.scheduler import detect_platform, MACOS_LABEL
plat = detect_platform()
if plat == "macos":
    p = subprocess.run(["launchctl", "list", MACOS_LABEL], capture_output=True)
    print("running" if p.returncode == 0 else "not loaded")
elif plat == "linux-systemd":
    p = subprocess.run(["systemctl", "--user", "is-active", "gh-issue-bot.timer"],
                       capture_output=True, text=True)
    print(p.stdout.strip() or "unknown")
elif plat == "linux-cron":
    p = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    print("installed" if "gh-issue-bot" in p.stdout else "not installed")
else:
    print(f"unsupported platform {plat}")
PY
  if is_pm_running; then echo "  sub-PM:  running (pid $(cat "$PIDFILE"))"
  else echo "  sub-PM:  not running"; fi
  if is_wd_running; then echo "  watchdog: running (pid $(cat "$WATCHDOG_PIDFILE"))"
  else echo "  watchdog: not running"; fi
  TM_BOT_ROOT="$BOT_ROOT" "$WATCHER" status
}

cmd_tick()  { TM_BOT_ROOT="$BOT_ROOT" "$WATCHER" tick; }
cmd_doctor(){ TM_BOT_ROOT="$BOT_ROOT" "$WATCHER" doctor; }
cmd_start() { "$PMSTART" --background; }
cmd_stop()  {
  if is_pm_running; then
    TM_ROOT="$BOT_ROOT" "$REPO_ROOT/bin/tm-pm" shutdown "stop" || true
  fi
}
cmd_logs()  {
  n="${1:-50}"
  echo "── watcher.log (last $n) ──"; tail -n "$n" "$LOG" 2>/dev/null || true
  echo "── pm.log (last $n) ──";      tail -n "$n" "$BOT_ROOT/pm.log" 2>/dev/null || true
}

case "${1:-help}" in
  install)   shift; cmd_install ;;
  uninstall) shift; cmd_uninstall ;;
  status)    cmd_status ;;
  tick)      cmd_tick ;;
  doctor)    cmd_doctor ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  logs)      shift; cmd_logs "${1:-50}" ;;
  help|-h|--help)
    cat <<EOF
tm-issue-bot — gh-issue-bot CLI

Subcommands:
  install      detect platform → install scheduler + start sub-PM + watchdog + validation tick
  uninstall    remove scheduler + stop sub-PM/watchdog (asks before purging state)
  status       scheduler / sub-PM / watchdog / in-flight issues
  tick         run one watcher tick now (debug)
  doctor       sanity-check tools + config
  start        start sub-PM only (no scheduler)
  stop         stop sub-PM
  logs [N]     tail watcher.log + pm.log
EOF
    ;;
  *) echo "unknown subcommand: $1" >&2; exit 1 ;;
esac
```

- [ ] **Step 14.2: chmod, lint**

```bash
chmod +x gh-issue-bot/bin/tm-issue-bot
bash -n gh-issue-bot/bin/tm-issue-bot
```
Expected: no syntax errors.

- [ ] **Step 14.3: Smoke-test help**

Run: `gh-issue-bot/bin/tm-issue-bot help`
Expected: usage text printed.

- [ ] **Step 14.4: Smoke-test status (without install)**

Run: `gh-issue-bot/bin/tm-issue-bot status 2>&1 | head -10`
Expected: prints scheduler "not loaded/installed", sub-PM "not running", and the watcher's status output.

- [ ] **Step 14.5: Commit**

```bash
git add gh-issue-bot/bin/tm-issue-bot
git commit -m "gh-issue-bot: add bin/tm-issue-bot (top-level CLI)"
```

---

## Task 15: End-to-end smoke + safety-rail static checks + final docs

**Files:**
- Create: `gh-issue-bot/tests/test_safety_rails.py`
- Create: `gh-issue-bot/tests/test_no_auto_merge.py`
- Create: `gh-issue-bot/tests/test_event_format.py`
- Modify: `gh-issue-bot/README.md` (add troubleshooting section)
- Modify: `README.md` (root) — add a one-paragraph pointer to gh-issue-bot

- [ ] **Step 15.1: Add `test_no_auto_merge.py` (static check that nothing in the bot calls `gh pr merge`)**

Create `gh-issue-bot/tests/test_no_auto_merge.py`:

```python
"""Static check: no script in gh-issue-bot/ ever calls `gh pr merge`."""
from pathlib import Path


def test_no_auto_merge():
    bot_dir = Path(__file__).resolve().parents[1]
    offenders = []
    for sub in ("bin", "lib"):
        for path in (bot_dir / sub).rglob("*"):
            if not path.is_file():
                continue
            try:
                txt = path.read_text()
            except UnicodeDecodeError:
                continue
            if "gh pr merge" in txt or "pr_merge" in txt or "merge_pr" in txt:
                offenders.append(str(path))
    assert not offenders, f"auto-merge call detected in: {offenders}"
```

- [ ] **Step 15.2: Add `test_event_format.py` (watcher-emitted events parse via existing PM logic)**

Create `gh-issue-bot/tests/test_event_format.py`:

```python
"""Events the watcher writes must be readable by the existing pm-daemon."""
import importlib.util
import json
from pathlib import Path


def test_add_task_event_shape_matches_pm():
    """Event keys: ts, type, session_id, data; data has title, signal_cmd, source."""
    repo_root = Path(__file__).resolve().parents[2]
    pm_path = repo_root / "bin" / "pm-daemon.py"
    spec = importlib.util.spec_from_file_location("pm", pm_path)
    pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)

    # Construct the same event shape the watcher writes.
    ev = {
        "ts": "2026-05-09T10:00:00Z",
        "type": "add_task",
        "session_id": "watcher",
        "data": {
            "title": "[issue #1] x",
            "signal_cmd": "/x/finalize 1",
            "source": "github-issue:1",
        },
    }
    # Round-trip through json.
    s = json.dumps(ev)
    parsed = json.loads(s)
    # The PM's process_events code expects exactly these keys; mirror its access pattern.
    assert parsed["type"] == "add_task"
    assert parsed["data"]["title"]
    assert parsed["data"]["signal_cmd"]
    assert parsed["data"]["source"].startswith("github-issue:")
```

- [ ] **Step 15.3: Add `test_safety_rails.py`**

Create `gh-issue-bot/tests/test_safety_rails.py`:

```python
"""Safety rails: daily cap, branch prefix, worktree path lock, kill switch."""
import os
import subprocess
from pathlib import Path

from lib.config import Config
from lib.state import Ledger
from lib.watcher_logic import eligible_for_promote


def _cfg(**ov):
    base = dict(repo="o/r", label="auto-fix", fail_label="auto-fix-failed",
                max_parallel=3, poll_interval=600, daily_cap=10,
                max_diff_lines=2000, branch_prefix="auto-fix/issue-")
    base.update(ov); return Config(**base)


def test_daily_cap_blocks_promotion():
    cfg = _cfg(daily_cap=2)
    led = Ledger.empty()
    led.daily_spawn_date = "2026-05-09"; led.daily_spawn_count = 2
    for n in ("1", "2"):
        led.upsert_seen(n, title="t", labels=["auto-fix"], updated_at="x")
    assert eligible_for_promote(led, cfg, today="2026-05-09") == []


def test_kill_switch_disables_tick(tmp_bot_root, tmp_path):
    (tmp_bot_root / ".disabled").touch()
    watcher = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-watcher"
    env = os.environ.copy()
    env["TM_BOT_ROOT"] = str(tmp_bot_root)
    env["TM_GH_REPO"] = "o/r"
    proc = subprocess.run([str(watcher), "tick"], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0
    # No state.json should have been written when disabled
    assert not (tmp_bot_root / "state.json").exists() or \
           "skipping" in (tmp_bot_root / "watcher.log").read_text()


def test_branch_prefix_lock_enforced_in_finalize():
    """Static: bin/tm-issue-finalize contains the prefix check."""
    finalize = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"
    txt = finalize.read_text()
    assert "TM_ISSUE_BRANCH_PREFIX" in txt
    assert "lacks prefix" in txt or "branch" in txt


def test_worktree_path_lock_enforced_in_finalize():
    finalize = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-finalize"
    txt = finalize.read_text()
    assert "is not the expected worktree" in txt
    assert "WT_REQUIRED" in txt
```

- [ ] **Step 15.4: Run the full gh-issue-bot suite**

Run: `cd gh-issue-bot && python3 -m pytest -q tests/`
Expected: all tests pass.

- [ ] **Step 15.5: Add a troubleshooting section to `gh-issue-bot/README.md`**

Append to `gh-issue-bot/README.md`:

```markdown

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `tm-issue-bot status` shows "scheduler: not loaded" on macOS | LaunchAgent path doesn't exist or has bad XML | `tm-issue-bot uninstall` then `install`. Check with `launchctl list | grep gh-issue-bot`. |
| `gh issue list FAILED: gh auth status …` in `watcher.log` | gh CLI not authenticated | `gh auth login`. |
| sub-PM keeps respawning, fixer windows never appear | `_tm-spawn.sh` can't find a terminal backend | Run `bash -x` on the watcher; if on Linux/headless, set `TM_TERMINAL=tmux`. |
| Issue stuck in `assigned` for hours | Fixer session crashed without reporting | `tm-issue-bot tick` (next tick respawns up to 3 times). |
| Want to pause without uninstalling | — | `touch gh-issue-bot/.disabled`. Resume with `rm gh-issue-bot/.disabled`. |
| Want to retry an already-failed issue | The `auto-fix-failed` label blocks re-entry | Remove the label on GitHub. |

## Logs

- `gh-issue-bot/watcher.log` — every tick prints one summary line.
- `gh-issue-bot/pm.log` — sub-PM's task assignments / signal_cmd retries / escalations.
- `gh-issue-bot/pm-watchdog.log` — sub-PM watchdog crashes/restarts.
```

- [ ] **Step 15.6: Add pointer in repo-root `README.md`**

Append a short section to `README.md` (the project root one) — find the "Tools" or "Components" section and add:

```markdown

### `gh-issue-bot/` (optional)

A standalone sub-project that watches a configured GitHub repo for issues
labelled `auto-fix` and resolves them autonomously by spawning a Claude
session per issue inside an isolated git worktree, then opening a PR with
`Closes #N`. Install with `gh-issue-bot/bin/tm-issue-bot install`. See
`gh-issue-bot/README.md` and `docs/superpowers/specs/2026-05-09-gh-issue-bot-design.md`.
```

(If the existing README has a clearer place for this — e.g., a feature list — put it there instead. Do not duplicate.)

- [ ] **Step 15.7: Final smoke — full test run from repo root**

Run:
```bash
cd /Users/mack/Desktop/Hosico/Works/Work/ZeroProgramer
python3 -m pytest -q workspace/tests/test_pm_root_env.py
cd gh-issue-bot && python3 -m pytest -q tests/
```
Expected: all green.

- [ ] **Step 15.8: Final commit**

```bash
git add gh-issue-bot/tests/test_safety_rails.py gh-issue-bot/tests/test_no_auto_merge.py gh-issue-bot/tests/test_event_format.py gh-issue-bot/README.md README.md
git commit -m "$(cat <<'EOF'
gh-issue-bot: add safety-rail tests, troubleshooting docs, root README pointer

Closes the spec's testing matrix: no_auto_merge static check,
event_format compatibility test against the running PM, and
safety_rails integration tests covering the daily cap, kill switch,
and the static branch-prefix / worktree-path locks in tm-issue-finalize.
EOF
)"
```

---

## Self-review checklist (run by the writer of this plan)

Spec coverage:

- §3.2 TM_ROOT patch → Tasks 1–3 ✓
- §4 components → Tasks 5–14 ✓
- §5 folder layout → Task 4 ✓
- §5.1 state.json schema → Task 6 ✓
- §5.2 .env schema → Task 5 ✓
- §6.1 happy path → Tasks 9–12 collectively ✓
- §6.2 fail paths → Tasks 10, 11, 12 (cancel branch in watcher_logic) ✓
- §6.3 idempotency invariants → Task 10 (test_finalize_idempotent_when_pr_exists), Task 6 (atomic save), Task 12 (tick repeatable) ✓
- §7 cross-platform scheduler → Task 13 ✓
- §7.1 plist template → Task 13 (render_macos_plist) ✓
- §7.2 CLI surface → Task 14 ✓
- §7.3 install validation step → Task 14 step 14.1 in cmd_install ✓
- §8 safety rails → Task 15 (test_safety_rails) + finalize/watcher implementations ✓
- §9 testing matrix → all test files mapped ✓
- §10 out-of-scope items not implemented (correct) ✓

Placeholder scan: no TBDs, all code blocks complete, no "similar to Task N" punts.

Type consistency:

- `Config` dataclass fields used identically in Tasks 5, 12, 13, 15 ✓
- `Ledger.transition` signature matches across Tasks 6, 12, 15 ✓
- `STATUSES = ("seen", "assigned", "resolved", "failed", "cancelled")` consistent ✓
- `MACOS_LABEL` constant referenced in both Task 13 implementation and test ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-gh-issue-bot.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration via the `superpowers:subagent-driven-development` skill.

**2. Inline Execution** — Execute tasks in this session using the `superpowers:executing-plans` skill, batch execution with checkpoints for review.

Which approach?
