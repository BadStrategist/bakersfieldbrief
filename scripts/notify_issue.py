#!/usr/bin/env python3
"""Comment on the ops issue when a CI run fails. Needs no secret.

The Discord alert depends on DISCORD_WEBHOOK_URL. When that secret is missing
or the webhook is dead, a failed run told nobody: the step printed a line into
the log of the run nobody was reading. This is the alert that cannot lose its
key. It uses the run's own GITHUB_TOKEN (`issues: write`) to comment on one
pinned issue, and GitHub mails the comment to whoever watches the issue. The
repository is private, so nothing in the comment is published.

The issue is found by its title (ISSUE_TITLE), open, and created when it is
missing, so a closed or deleted issue cannot silence the alert either.

The comment: --header, the steps whose outcome was `failure` (read from
STEPS_JSON, the workflow's `toJSON(steps)`), the last lines of every --file
that exists, and RUN_URL.

ALWAYS exits 0. This step reports a run that has already failed; it must never
be the reason a run is red, and never change which step a reader blames. What
went wrong is printed, with an ::error annotation, and that is all.
Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ISSUE_TITLE = "Ops alerts: failed CI runs"
ISSUE_BODY = (
    "Every failed workflow run comments here (`scripts/notify_issue.py`). "
    "This is the alert that needs no secret: it works when the ops Discord "
    "webhook does not.\n\nKeep this issue open and pinned. Watch it to get "
    "the comments by email. If it is closed, the next failed run opens a new one.")
TAIL_LINES = 12
TAIL_CHARS = 3000


def _api(method: str, path: str, token: str, payload: dict | None = None):
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    req = urllib.request.Request(
        f"{base}{path}", method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "bakersfieldbrief-ci"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def failed_steps(steps_json: str) -> list[str]:
    """Step ids whose outcome was failure, from the workflow's toJSON(steps)."""
    try:
        steps = json.loads(steps_json or "{}")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(steps, dict):
        return []
    return [name for name, s in steps.items()
            if isinstance(s, dict) and s.get("outcome") == "failure"]


def _tail(path: str) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(lines[-TAIL_LINES:])[-TAIL_CHARS:].strip()


def build_comment(header: str, steps_json: str, files: list[str], run_url: str) -> str:
    parts = [f"**{header}**" if header else "**A workflow run failed**"]
    failed = failed_steps(steps_json)
    if failed:
        parts.append("Failed steps: " + ", ".join(f"`{s}`" for s in failed))
    for f in files:
        text = _tail(f)
        if text:
            parts.append(f"`{Path(f).name}`\n```\n{text.replace('```', '` ` `')}\n```")
    if run_url:
        parts.append(f"Run: {run_url}")
    return "\n\n".join(parts)


def find_or_create_issue(repo: str, token: str) -> int:
    issues = _api("GET", f"/repos/{repo}/issues?state=open&per_page=100", token) or []
    for it in issues:
        if it.get("title") == ISSUE_TITLE and "pull_request" not in it:
            return int(it["number"])
    made = _api("POST", f"/repos/{repo}/issues", token,
                {"title": ISSUE_TITLE, "body": ISSUE_BODY})
    print(f"notify_issue: no open issue titled {ISSUE_TITLE!r}; opened #{made['number']}")
    return int(made["number"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--header", default="", help="Bold first line of the comment")
    ap.add_argument("--file", action="append", default=[],
                    help="A file whose last lines go in the comment; repeatable, "
                         "a missing file is skipped")
    args = ap.parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if not token or not repo:
            raise RuntimeError("GITHUB_TOKEN or GITHUB_REPOSITORY is not set")
        body = build_comment(args.header, os.environ.get("STEPS_JSON", ""),
                             args.file, os.environ.get("RUN_URL", ""))
        number = find_or_create_issue(repo, token)
        _api("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": body})
        print(f"notify_issue: commented on #{number}")
    except Exception as e:  # noqa: BLE001
        # Loud, and still exit 0: see the module docstring.
        print(f"::error title=ops issue alert not delivered::{type(e).__name__}: {e}")
        print(f"notify_issue: NOT delivered ({type(e).__name__}: {e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
