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
