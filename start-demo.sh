#!/usr/bin/env bash
# Reset state, optionally generate plan from goal.md, start the PM daemon.
# Usage:
#   ./start-demo.sh                      # normal mode
#   ./start-demo.sh --strict             # every done event is auto-reviewed by claude -p
#   ./start-demo.sh --plan-from-goal     # if no plan.md, generate one from goal.md
#   ./start-demo.sh --auto               # plan-from-goal + strict
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

strict=0
plan_from_goal=0
for arg in "$@"; do
  case "$arg" in
    --strict)         strict=1 ;;
    --plan-from-goal) plan_from_goal=1 ;;
    --auto)           strict=1; plan_from_goal=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

echo "▸ resetting demo state"
"$HERE/bin/tm-pm" reset >/dev/null

if [ "$plan_from_goal" -eq 1 ]; then
  if [ -f "$HERE/plan.md" ]; then
    echo "▸ plan.md already exists; keeping it (use 'tm-plan --force' to regenerate)"
  else
    echo "▸ generating plan.md from goal.md via 'claude -p'"
    "$HERE/bin/tm-plan"
  fi
fi

if [ ! -f "$HERE/plan.md" ]; then
  echo "✗ no plan.md and no --plan-from-goal flag. Either write plan.md or pass --auto." >&2
  exit 1
fi

echo "▸ starting PM daemon$([ "$strict" -eq 1 ] && echo ' (STRICT mode: review every done)')"
if [ "$strict" -eq 1 ]; then
  PM_STRICT=1 "$HERE/bin/tm-pm" start
else
  "$HERE/bin/tm-pm" start
fi

cat <<EOF

next:
  cd $HERE
  claude

  inside Claude, just type anything (e.g. "go") — the worker will read its
  task from PM and start working autonomously, looping until the plan is done.

  the bottom of the Claude UI shows live: project name, X/N tasks done,
  workers busy/idle, and the current task title.

side terminals (optional):
  $HERE/bin/tm-pm tail        # follow PM daemon log
  $HERE/bin/tm-pm status      # snapshot of plan + workers
EOF
