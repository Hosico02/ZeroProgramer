"""Linux backends: systemd timer or cron line."""
from lib.scheduler import (
    render_systemd_service, render_systemd_timer,
    render_cron_line, CRON_BEGIN, CRON_END,
    inject_cron_block, remove_cron_block,
)


def test_render_systemd_service():
    out = render_systemd_service(watcher="/x/bin/tm-issue-watcher")
    assert "ExecStart=/x/bin/tm-issue-watcher tick" in out


def test_render_systemd_timer():
    out = render_systemd_timer(interval=600)
    assert "OnUnitActiveSec=600s" in out
    assert "Persistent=true" in out


def test_render_cron_line():
    out = render_cron_line(watcher="/x/bin/tm-issue-watcher",
                           log="/x/watcher.log", interval=600)
    # 600s == every 10 minutes
    assert "*/10 * * * *" in out
    assert "/x/bin/tm-issue-watcher tick" in out
    assert ">> /x/watcher.log" in out


def test_inject_cron_block_idempotent():
    existing = "0 5 * * * something\n"
    new = "*/10 * * * * /x/bin/tm-issue-watcher tick"
    out1 = inject_cron_block(existing, new)
    assert CRON_BEGIN in out1
    assert CRON_END in out1
    assert new in out1
    out2 = inject_cron_block(out1, new)
    assert out1 == out2  # second injection is a no-op


def test_remove_cron_block():
    base = "0 5 * * * x\n"
    new = "*/10 * * * * /a"
    with_block = inject_cron_block(base, new)
    cleaned = remove_cron_block(with_block)
    assert CRON_BEGIN not in cleaned
    assert CRON_END not in cleaned
    assert "0 5 * * * x" in cleaned
