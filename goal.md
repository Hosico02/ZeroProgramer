# Project goal: optimize claude-team-demo

The codebase under `workspace/` IS a fresh copy of THIS project (claude-team-demo, a multi-agent CLI org built on Claude Code). Improve it on these axes — without breaking existing scripts or changing externally visible behavior:

- **Shell-injection robustness**: scripts under `bin/` must handle task titles, signal output, and worker summaries that contain backticks, single/double quotes, and dollar signs without writing malformed event JSON.
- **Atomic event writes**: every script that produces an `events/*.json` file must write to `*.json.tmp` and rename atomically; the daemon must skip `.tmp` files (already true). Verify this property with a focused test.
- **Daemon resilience**: `bin/pm-daemon.py` should never crash on bad input. Bad event files are logged and skipped (already true). Add coverage so a regression would fail a test.
- **Unit tests**: introduce a `tests/` directory in workspace/ with pytest-runnable unit tests for: `parse_plan()` (numbered, bulleted, signal_cmd lines, continuation lines, blank-line separators), and the event-file atomicity property.
- **`tm-pm status` exit code**: it should exit 0 when the daemon completed naturally (`pm-state.json` exists with all tasks done) even if the process is no longer running. Today it returns 1 in that case.
- **Documentation accuracy**: `README.md` must describe the strict-mode review loop and the `signal_cmd` flow correctly. The `--auto` flag in `start-demo.sh` is documented; verify the exact behavior matches.

Constraints:
- Don't introduce external Python or shell dependencies.
- Don't modify `goal.md`, `plan.md`, or `manifest.json` — those are PM inputs, not target code.
- Each `bin/*` script must still pass `bash -n` after edits.
- The pytest suite (the new one in `tests/`) must run cleanly with `python3 -m pytest -q tests/`.
