"""tm-issue-fail posts comment + adds fail label."""
import os
import subprocess
import textwrap
from pathlib import Path


FAIL = Path(__file__).resolve().parents[1] / "bin" / "tm-issue-fail"


def _stub_gh(tmp_path: Path, log_path: Path) -> Path:
    bin_dir = tmp_path / "stubs"
    bin_dir.mkdir()
    body = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log_path}"
        exit 0
    """)
    (bin_dir / "gh").write_text(body)
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def test_fail_posts_comment_and_adds_label(tmp_path):
    log = tmp_path / "gh.log"
    stubs = _stub_gh(tmp_path, log)
    env = os.environ.copy()
    env["PATH"] = f"{stubs}:{env['PATH']}"
    env["TM_GH_REPO"] = "o/r"
    env["TM_ISSUE_FAIL_LABEL"] = "auto-fix-failed"

    proc = subprocess.run([str(FAIL), "42", "diff was empty"],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    log_text = log.read_text()
    assert "issue comment 42" in log_text
    assert "diff was empty" in log_text
    assert "issue edit 42" in log_text
    assert "--add-label auto-fix-failed" in log_text


def test_fail_requires_args(tmp_path):
    proc = subprocess.run([str(FAIL)], capture_output=True, text=True)
    assert proc.returncode == 64
