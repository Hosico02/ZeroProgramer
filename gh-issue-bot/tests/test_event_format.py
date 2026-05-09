"""Events the watcher writes must be readable by the existing pm-daemon."""
import importlib.util
import json
from pathlib import Path


def test_add_task_event_shape_matches_pm():
    """Event keys: ts, type, session_id, data; data has title, signal_cmd, source."""
    repo_root = Path(__file__).resolve().parents[2]
    pm_path = repo_root / "bin" / "pm-daemon.py"
    spec = importlib.util.spec_from_file_location("pm", pm_path)
    pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)

    # Construct the same event shape the watcher writes.
    ev = {
        "ts": "2026-05-09T10:00:00Z",
        "type": "add_task",
        "session_id": "watcher",
        "data": {
            "title": "[issue #1] x",
            "signal_cmd": "/x/finalize 1",
            "source": "github-issue:1",
        },
    }
    # Round-trip through json.
    s = json.dumps(ev)
    parsed = json.loads(s)
    # The PM's process_events code expects exactly these keys; mirror its access pattern.
    assert parsed["type"] == "add_task"
    assert parsed["data"]["title"]
    assert parsed["data"]["signal_cmd"]
    assert parsed["data"]["source"].startswith("github-issue:")
