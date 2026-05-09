# Goal: resolve auto-fix-labelled GitHub Issues

This sub-project's purpose is one specific autonomous loop: watch the configured
GitHub repo for issues with the `auto-fix` label, spawn an isolated Claude Code
session per issue inside a per-issue git worktree, and open a pull request with
`Closes #N` when the session reports success.

The sub-PM here serves only this loop. Tasks are not authored ahead of time;
they arrive dynamically as `add_task` events from `bin/tm-issue-watcher`.
