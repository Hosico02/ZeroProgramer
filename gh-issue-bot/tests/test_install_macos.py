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
