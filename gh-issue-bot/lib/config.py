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
    "TM_ISSUE_MAX_PARALLEL": "1",
    "TM_ISSUE_POLL_INTERVAL": "600",
    "TM_ISSUE_DAILY_CAP": "10",
    "TM_ISSUE_MAX_DIFF_LINES": "2000",
    # Single shared branch (no per-issue suffix). Despite the field name,
    # this is the literal branch name. All issue fixes accumulate here,
    # one shared PR.
    "TM_ISSUE_BRANCH_PREFIX": "auto-fix",
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
    import os
    bot_root = Path(bot_root)
    raw = _parse_env_file(bot_root / ".gh-issue-bot.env")
    # os.environ overrides file values (useful for testing and systemd units).
    env_overrides = {k: v for k, v in os.environ.items()
                     if k in _DEFAULTS or k in ("TM_GH_REPO",)}
    merged = {**_DEFAULTS, **raw, **env_overrides}

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
