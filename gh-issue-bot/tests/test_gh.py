"""Thin wrappers over `gh` CLI calls."""
import json
import subprocess

import pytest

from lib import gh


def test_list_open_issues_with_label(fake_gh):
    payload = [
        {"number": 1, "title": "fix", "body": "", "labels": [{"name": "auto-fix"}],
         "updatedAt": "2026-05-09T10:00:00Z", "state": "OPEN"},
        {"number": 2, "title": "y", "body": "", "labels": [{"name": "wontfix"}],
         "updatedAt": "2026-05-09T11:00:00Z", "state": "OPEN"},
    ]
    fake_gh(("gh", "issue", "list", "--repo", "o/r", "--label", "auto-fix",
             "--state", "open", "--json", "number,title,body,labels,updatedAt,state",
             "--limit", "200"),
            stdout=json.dumps(payload))
    rows = gh.list_issues("o/r", label="auto-fix")
    assert rows[0]["number"] == 1
    assert rows[1]["number"] == 2


def test_view_issue_returns_full_body(fake_gh):
    payload = {"number": 7, "title": "T", "body": "Big body", "state": "OPEN",
               "labels": [{"name": "auto-fix"}], "updatedAt": "x"}
    fake_gh(("gh", "issue", "view", "7", "--repo", "o/r",
             "--json", "number,title,body,labels,updatedAt,state"),
            stdout=json.dumps(payload))
    issue = gh.view_issue("o/r", 7)
    assert issue["body"] == "Big body"


def test_comment_issue(fake_gh):
    fake_gh(("gh", "issue", "comment", "7", "--repo", "o/r", "--body", "hi"),
            stdout="https://github.com/o/r/issues/7#issuecomment-1\n")
    url = gh.comment_issue("o/r", 7, "hi")
    assert "issuecomment" in url


def test_add_label(fake_gh):
    fake_gh(("gh", "issue", "edit", "7", "--repo", "o/r", "--add-label", "auto-fix-failed"),
            stdout="ok")
    gh.add_label("o/r", 7, "auto-fix-failed")


def test_pr_exists_for_branch_true(fake_gh):
    fake_gh(("gh", "pr", "list", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--state", "open", "--json", "number"),
            stdout=json.dumps([{"number": 99}]))
    n = gh.pr_for_branch("o/r", "auto-fix/issue-42")
    assert n == 99


def test_pr_exists_for_branch_false(fake_gh):
    fake_gh(("gh", "pr", "list", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--state", "open", "--json", "number"),
            stdout="[]")
    assert gh.pr_for_branch("o/r", "auto-fix/issue-42") is None


def test_create_pr_returns_number(fake_gh):
    fake_gh(("gh", "pr", "create", "--repo", "o/r", "--head", "auto-fix/issue-42",
             "--base", "main", "--title", "Auto-fix #42: T", "--body", "Closes #42\n\n..."),
            stdout="https://github.com/o/r/pull/123\n")
    n = gh.create_pr("o/r", head="auto-fix/issue-42", base="main",
                     title="Auto-fix #42: T", body="Closes #42\n\n...")
    assert n == 123


def test_propagates_nonzero_exit(fake_gh):
    fake_gh(("gh", "issue", "view", "404", "--repo", "o/r",
             "--json", "number,title,body,labels,updatedAt,state"),
            stdout="", returncode=1, stderr="not found")
    with pytest.raises(gh.GhError, match="not found"):
        gh.view_issue("o/r", 404)
