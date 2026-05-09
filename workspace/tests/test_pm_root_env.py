"""TM_ROOT env var lets pm-daemon.py target a non-default project root."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_pm_daemon(root_override: str | None):
    """Re-import pm-daemon.py under a controlled TM_ROOT (or absence thereof)."""
    if "TM_ROOT" in os.environ:
        del os.environ["TM_ROOT"]
    if root_override is not None:
        os.environ["TM_ROOT"] = root_override
    src = Path(__file__).resolve().parents[2] / "bin" / "pm-daemon.py"
    spec = importlib.util.spec_from_file_location("pm_daemon_under_test", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pm_daemon_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_root_is_repo(tmp_path):
    mod = _load_pm_daemon(None)
    assert mod.ROOT.name == "ZeroProgramer" or mod.ROOT.is_dir()
    assert (mod.ROOT / "bin" / "pm-daemon.py").exists()


def test_tm_root_override(tmp_path):
    fake = tmp_path / "fake_root"
    fake.mkdir()
    mod = _load_pm_daemon(str(fake))
    assert mod.ROOT == fake
    assert mod.EVENTS_DIR == fake / "events"
    assert mod.STATE_FILE == fake / "pm-state.json"
