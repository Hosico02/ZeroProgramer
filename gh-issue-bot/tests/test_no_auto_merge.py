"""Static check: no script in gh-issue-bot/ ever calls `gh pr merge`."""
from pathlib import Path


def test_no_auto_merge():
    bot_dir = Path(__file__).resolve().parents[1]
    offenders = []
    for sub in ("bin", "lib"):
        for path in (bot_dir / sub).rglob("*"):
            if not path.is_file():
                continue
            try:
                txt = path.read_text()
            except UnicodeDecodeError:
                continue
            if "gh pr merge" in txt or "pr_merge" in txt or "merge_pr" in txt:
                offenders.append(str(path))
    assert not offenders, f"auto-merge call detected in: {offenders}"
