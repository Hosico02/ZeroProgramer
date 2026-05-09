"""Config loader: parses .gh-issue-bot.env, applies defaults, types correctly."""
from pathlib import Path

import pytest

from lib.config import Config, load_config


def _write_env(root: Path, body: str) -> None:
    (root / ".gh-issue-bot.env").write_text(body)


@pytest.fixture(autouse=True)
def _default_git_remote(monkeypatch):
    """Patch out the git-remote helper so tests that don't set TM_GH_REPO still
    get a valid repo string without needing a real git remote in tmp_path."""
    monkeypatch.setattr(
        "lib.config._git_remote_owner_repo",
        lambda root: "owner/default-repo",
    )


def test_defaults_when_no_env_file(tmp_bot_root):
    cfg = load_config(tmp_bot_root)
    assert isinstance(cfg, Config)
    assert cfg.label == "auto-fix"
    assert cfg.fail_label == "auto-fix-failed"
    assert cfg.max_parallel == 3
    assert cfg.poll_interval == 600
    assert cfg.daily_cap == 10
    assert cfg.max_diff_lines == 2000
    assert cfg.branch_prefix == "auto-fix/issue-"


def test_overrides_from_env_file(tmp_bot_root):
    _write_env(tmp_bot_root, "TM_ISSUE_MAX_PARALLEL=5\nTM_ISSUE_LABEL=triage\n")
    cfg = load_config(tmp_bot_root)
    assert cfg.max_parallel == 5
    assert cfg.label == "triage"


def test_blank_and_comment_lines_ok(tmp_bot_root):
    _write_env(tmp_bot_root, "\n# comment\nTM_ISSUE_DAILY_CAP=1\n   \n")
    cfg = load_config(tmp_bot_root)
    assert cfg.daily_cap == 1


def test_missing_repo_falls_back_to_git_remote(tmp_bot_root, monkeypatch):
    monkeypatch.setattr(
        "lib.config._git_remote_owner_repo",
        lambda root: "owner/repo-from-remote",
    )
    cfg = load_config(tmp_bot_root)
    assert cfg.repo == "owner/repo-from-remote"


def test_explicit_repo_beats_remote(tmp_bot_root, monkeypatch):
    monkeypatch.setattr(
        "lib.config._git_remote_owner_repo",
        lambda root: "owner/wrong",
    )
    _write_env(tmp_bot_root, "TM_GH_REPO=Hosico02/right\n")
    cfg = load_config(tmp_bot_root)
    assert cfg.repo == "Hosico02/right"


def test_invalid_int_raises(tmp_bot_root):
    _write_env(tmp_bot_root, "TM_ISSUE_MAX_PARALLEL=many\n")
    with pytest.raises(ValueError, match="TM_ISSUE_MAX_PARALLEL"):
        load_config(tmp_bot_root)
