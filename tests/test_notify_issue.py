#!/usr/bin/env python3
"""The ops alert that needs no secret: scripts/notify_issue.py.

A failed run used to reach a human only through DISCORD_WEBHOOK_URL. Without
the secret the alert step printed a line and that was the whole alert. These
hold the two properties the fallback exists for: it is delivered with nothing
but the run's own token, and it can never be the step that fails a run.

Fully offline: the GitHub API is a fake.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import notify_issue as ni  # noqa: E402

WORKFLOWS = ("daily", "deploy", "grapevine", "guide", "sunday-read", "weekly")
STEPS = json.dumps({"build": {"outcome": "success", "conclusion": "success"},
                    "tests": {"outcome": "failure", "conclusion": "failure"},
                    "alpr_fresh": {"outcome": "failure", "conclusion": "failure"},
                    "send": {"outcome": "skipped", "conclusion": "skipped"}})


@pytest.fixture
def api(monkeypatch):
    """A fake GitHub: records every call, serves a configurable issue list."""
    calls: list[tuple[str, str, dict | None]] = []
    state = {"issues": [{"number": 7, "title": ni.ISSUE_TITLE}], "fail": None}

    def fake(method, path, token, payload=None):
        calls.append((method, path, payload))
        if state["fail"]:
            raise state["fail"]
        if method == "GET":
            return state["issues"]
        if path.endswith("/issues"):
            return {"number": 12}
        return {"id": 1}

    monkeypatch.setattr(ni, "_api", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("STEPS_JSON", STEPS)
    monkeypatch.setenv("RUN_URL", "https://github.com/o/r/actions/runs/1")
    return calls, state


def test_comments_on_the_ops_issue_with_the_failed_steps(api, tmp_path):
    calls, _ = api
    log = tmp_path / "bb_alpr.txt"
    log.write_text("\n".join(f"line {n}" for n in range(40)), encoding="utf-8")
    assert ni.main(["--header", "daily run #5 failed", "--file", str(log),
                    "--file", str(tmp_path / "not_written.txt")]) == 0
    method, path, payload = calls[-1]
    assert (method, path) == ("POST", "/repos/o/r/issues/7/comments")
    body = payload["body"]
    assert body.startswith("**daily run #5 failed**")
    assert "`tests`" in body and "`alpr_fresh`" in body
    assert "`build`" not in body and "`send`" not in body
    assert "line 39" in body and "line 27" not in body      # the tail, not the file
    assert "not_written" not in body                        # a missing file is skipped
    assert "https://github.com/o/r/actions/runs/1" in body


def test_opens_the_issue_when_it_is_missing(api):
    """A closed or deleted issue must not silence the alert. A pull request
    with the same title is not the issue."""
    calls, state = api
    state["issues"] = [{"number": 3, "title": "Something else"},
                       {"number": 4, "title": ni.ISSUE_TITLE, "pull_request": {}}]
    assert ni.main(["--header", "h"]) == 0
    assert ("POST", "/repos/o/r/issues") == calls[1][:2]
    assert calls[1][2]["title"] == ni.ISSUE_TITLE
    assert calls[-1][1] == "/repos/o/r/issues/12/comments"


@pytest.mark.parametrize("breakage", ["no_token", "api_down", "bad_steps"])
def test_the_alert_never_fails_the_run_it_reports(api, monkeypatch, capsys, breakage):
    calls, state = api
    if breakage == "no_token":
        monkeypatch.delenv("GITHUB_TOKEN")
    elif breakage == "api_down":
        state["fail"] = OSError("403 Resource not accessible by integration")
    else:
        monkeypatch.setenv("STEPS_JSON", "{not json")
    assert ni.main(["--header", "h"]) == 0
    out = capsys.readouterr()
    if breakage == "bad_steps":
        assert calls[-1][1].endswith("/comments")       # still delivered
    else:
        assert "::error" in out.out and "NOT delivered" in out.err


@pytest.mark.parametrize("name", WORKFLOWS)
def test_every_workflow_has_the_alert_and_cannot_be_failed_by_it(name):
    """The step runs only on a run that has already failed, has the permission
    it needs, uses no secret, and cannot exit non-zero: the script returns 0
    and a script that cannot start falls through to an annotation. Not
    continue-on-error, which test_alpr_freshness bans from these files: this
    step is loud when it fails, it just is not red."""
    text = (ROOT / ".github" / "workflows" / f"{name}.yml").read_text(encoding="utf-8")
    perms = re.search(r"^permissions:\n((?:  .+\n)+)", text, re.M).group(1)
    assert "issues: write" in perms
    step = re.search(r"      - name: Comment on the ops issue on failure\n"
                     r"((?:        .+\n)+)", text)
    assert step, f"{name}.yml has no ops issue step"
    block = step.group(1)
    assert "        if: failure()\n" in block
    assert "continue-on-error" not in block
    assert "GITHUB_TOKEN: ${{ github.token }}" in block
    assert "STEPS_JSON: ${{ toJSON(steps) }}" in block
    assert "python scripts/notify_issue.py" in block
    assert block.rstrip().splitlines()[-1].lstrip().startswith('|| echo "::error ')
    assert "secrets." not in block                      # the point: no secret
