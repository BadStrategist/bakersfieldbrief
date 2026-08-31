#!/usr/bin/env python3
"""Send the rendered daily brief email to MailerLite subscribers.

Reads email/latest/brief.html + brief.txt (rendered by the daily build),
creates a MailerLite regular campaign for the configured group, sets the
content, and sends it immediately.

VERIFIED API SHAPE (tested 2026-08-22):
  POST /campaigns            -> {"name", "type": "regular", "groups": [gid],
                                 "emails": [{"subject", "from", "from_name",
                                 "content" (HTML), "plain_text"}]}
                                 NOTE: "emails" is a FLAT array of objects;
                                 content is REQUIRED for the campaign to be
                                 valid (missing_data must be []).
  POST /campaigns/{id}/schedule -> {"delivery": "instant"}
  GET  /campaigns/{id}       -> status: draft -> ready -> sent

Usage: python scripts/send_newsletter_ml.py
Env:
  MAILERLITE_API_TOKEN   (required)
  MAILERLITE_GROUP_ID    (required — the group to send to)
  MAILERLITE_FROM_EMAIL  (default brief@bakersfieldbrief.com — must be
                          verified in MailerLite)
  MAILERLITE_FROM_NAME   (default "Bakersfield Brief")
Exit 0 on success; 1 on failure.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build import common  # noqa: E402

HTML = ROOT / "email" / "latest" / "brief.html"
TXT = ROOT / "email" / "latest" / "brief.txt"
SUBJECT = ROOT / "email" / "latest" / "subject.txt"
API = "https://connect.mailerlite.com/api"


def _token() -> str:
    tok = os.environ.get("MAILERLITE_API_TOKEN", "").strip()
    if not tok:
        raise SystemExit("MAILERLITE_API_TOKEN not set")
    return tok


def _group() -> str:
    gid = os.environ.get("MAILERLITE_GROUP_ID", "").strip()
    if not gid:
        raise SystemExit("MAILERLITE_GROUP_ID not set")
    return gid


def _req(method: str, path: str, payload: dict | None = None, token: str = "") -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API}{path}", data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise SystemExit(f"MailerLite {method} {path} -> {e.code}: {detail}")


def _campaign_name(d) -> str:
    """The canonical campaign name for a date — shared by the idempotency
    check and the sender so the two can never drift apart."""
    return f"Daily Brief {d.isoformat()}"


def _today_campaign_exists(token: str) -> str | None:
    """Return today's campaign id if a 'Daily Brief <today>' already exists
    (created today), else None. Makes the send idempotent so a delayed CI
    run or the Hermes watchdog never double-sends.

    Uses Pacific time (common.today_pacific) — NOT datetime.now(), which on
    a GitHub Actions runner is UTC. Between 4pm PT and midnight PT the UTC
    date is already "tomorrow", so comparing against UTC made the check miss
    today's campaign and re-send (three emails on 2026-08-28)."""
    d = common.today_pacific()
    name = _campaign_name(d)
    page = 1
    while page <= 3:  # guard: at most 3 pages of recent campaigns
        data = _req("GET", f"/campaigns?limit=100&sort=-created_at&page={page}", token=token)
        rows = data.get("data") or []
        if not rows:
            break
        for c in rows:
            if c.get("name") == name:
                return c.get("id")
        page += 1
    return None


def main() -> int:
    token = _token()
    group = _group()
    if not HTML.exists():
        print(f"no rendered brief at {HTML} — run the build first")
        return 1

    existing = _today_campaign_exists(token)
    if existing:
        print(f"already sent: campaign {existing} for today — skipping")
        return 0

    txt = TXT.read_text(encoding="utf-8") if TXT.exists() else ""
    html = HTML.read_text(encoding="utf-8")
    d = common.today_pacific()
    # Subject comes from the rendered subject.txt (single source of truth:
    # the emailer already leads with the day's top story). Fall back to the
    # plain date if the file is missing (e.g. older rendered email).
    subject = (SUBJECT.read_text(encoding="utf-8").strip()
               if SUBJECT.exists() and SUBJECT.read_text(encoding="utf-8").strip()
               else f"The Bakersfield Daily Brief — {d.strftime('%A, %B')} {d.day}, {d.year}")
    from_addr = os.environ.get("MAILERLITE_FROM_EMAIL", "brief@bakersfieldbrief.com")
    from_name = os.environ.get("MAILERLITE_FROM_NAME", "Bakersfield Brief")

    # Create the campaign with content inline (verified: flat emails array;
    # content required for missing_data to be empty; DO NOT send plain_text
    # alongside content — the API 422s with "emails.0 must be an array").
    payload = {
        "name": _campaign_name(d),
        "type": "regular",
        "groups": [group],
        "emails": [{
            "subject": subject,
            "from": from_addr,
            "from_name": from_name,
            "content": html,
        }],
    }
    camp = _req("POST", "/campaigns", payload, token)
    camp_id = (camp.get("data") or {}).get("id")
    if not camp_id:
        raise SystemExit(f"no campaign id: {camp}")
    missing = (camp.get("data") or {}).get("missing_data")
    if missing:
        raise SystemExit(f"campaign {camp_id} has missing_data: {missing}")

    # Send immediately
    _req("POST", f"/campaigns/{camp_id}/schedule", {"delivery": "instant"}, token)
    print(f"sent: campaign {camp_id} | {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
