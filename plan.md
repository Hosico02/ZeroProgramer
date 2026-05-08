# Project: PM Daemon Worker Loop

Three manifest dimensions are unsatisfied: missing tests, a wrong exit code on natural completion, and an incomplete README. Each task below ends with a `signal_cmd` that exits 0 only once that specific gap is closed.

1. Create `tests/test_parse_plan.py` and `tests/test_event_atomicity.py` under workspace/: import `parse_plan` from `bin/pm-daemon.py` and assert it handles numbered items, bulleted items, `signal_cmd:` lines, continuation lines, and blank-line separators; in the atomicity test, write a `*.tmp` file into a temp `events/` dir and assert `pm-daemon`'s event scanner skips it, then rename it to `*.json` and assert it is picked up.
   signal_cmd: python3 -m pytest -q tests/
2. Add `tests/test_tm_pm_status.py` that seeds a `pm-state.json` with all tasks in `done`/`failed` and no running pid, runs `bin/tm-pm status`, and asserts exit code 0; then patch `bin/tm-pm`'s `status` subcommand so that when `pm-state.json` exists and every task is in a terminal state, it prints status and exits 0 even if the pid file is missing or the process is gone.
   signal_cmd: python3 -m pytest -q tests/test_tm_pm_status.py
3. Edit README.md to add a "Task grammar" section that documents the `signal_cmd:` field (parsed by pm-daemon, executed by tm-done, retried up to MAX_SIGNAL times) and expand the strict-mode section to describe the review loop with retries up to 3 attempts before a task is marked failed.
   signal_cmd: grep -q signal_cmd README.md && grep -qi strict README.md
