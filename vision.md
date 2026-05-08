# Project vision — long-term ambitions

This file is for ambitions that DON'T have to be done right now but
should shape where the project goes. Different from `goal.md`:

- `goal.md` = "what 'done' looks like for the current iteration"
- `vision.md` = "what this project could become 6-24 months from now"

The agent team can't out-imagine you on what this project should
become — this is YOUR creativity channel. Drop bullet points here
freely. Planner reads this every cycle and may propose work towards
items here. Supervisor can promote items into goal.md when ready.

## User-authored vision

These are seed ideas for ZeroProgramer — replace / extend with your own.

- **L7 cross-project orchestration**: one supervisor managing N projects
  in parallel. Shared decision log + dashboard. Useful for monorepos and
  consultancies running many small projects.
- **Web UI dashboard**: live view of all 4 agents across all projects,
  real-time event stream, click-to-promote-proposal workflow. Today's
  `tm-pm watch` is terminal-only; bring it to the browser.
- **Plugin system for custom agent roles**: today there are 3 hardcoded
  roles (supervisor / planner / executor). Let users define a role via
  a single markdown file describing its prompt + allowed tools, register
  via `tm-role add <name>`. Could enable QA / security-auditor / docs-only
  / refactor-specialist roles.
- **Multi-LLM routing**: route deterministic-grade tasks (signal_cmd
  verification) to a cheap model, creative tasks (planner) to a strong
  one. Could halve token cost without quality loss.
- **GitHub-native loop**: open issues / PRs from PM events, link
  escalations to GitHub issues, close issues when signal_cmd passes.
  Make ZeroProgramer a bot you can invite to any repo.
- **Self-hosted SaaS form factor**: package as Docker image + web UI
  for teams that want a hosted ZeroProgramer instance to manage their
  internal projects.
- **Replay & time-travel**: every event is logged; let supervisor (or
  human) replay a stuck task to see exactly where it went wrong, fork
  state at any historical point.

## Agent-generated proposals

See `proposals/` directory; supervisor reviews and selects.

Add via: `./bin/tm-vision propose [N]`
