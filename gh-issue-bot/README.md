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
