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
