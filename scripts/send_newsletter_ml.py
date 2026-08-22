#!/usr/bin/env python3
"""Send the rendered daily brief email to MailerLite subscribers.

Reads email/latest/brief.html + brief.txt (rendered by the daily build),
creates a MailerLite regular campaign for the configured group, sets the
content, and sends it immediately (POST /campaigns/{id}/schedule with
delivery=instant). Prints the campaign id on success.

Usage: python scripts/send_newsletter_ml.py
Env:
  MAILERLITE_API_TOKEN   (required)
  MAILERLITE_GROUP_ID    (required — the group to send to)
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


def main() -> int:
    token = _token()
    group = _group()
    if not HTML.exists():
        print(f"no rendered brief at {HTML} — run the build first")
        return 1

    txt = TXT.read_text(encoding="utf-8") if TXT.exists() else ""
    html = HTML.read_text(encoding="utf-8")
    d = common.today_pacific()
    subject = f"The Bakersfield Daily Brief — {d.strftime('%A, %B')} {d.day}, {d.year}"

    # Create the campaign with content inline. Custom HTML needs the Advanced
    # plan; on free/trial use plain_text (builder default). Try HTML first,
    # fall back to plain text if the API rejects it.
    # NOTE: the API expects emails as a FLAT array of email objects (docs),
    # and the from address must be VERIFIED in MailerLite (Settings ->
    # Sender emails). The default below uses the account Gmail (verified);
    # set MAILERLITE_FROM_EMAIL to brief@bakersfieldbrief.com once verified.
    from_addr = os.environ.get("MAILERLITE_FROM_EMAIL", "tscgroupiron@gmail.com")
    from_name = os.environ.get("MAILERLITE_FROM_NAME", "Bakersfield Brief")
    payload = {
        "name": f"Daily Brief {d.isoformat()}",
        "type": "regular",
        "groups": [group],
        "emails": [{
            "subject": subject,
            "from": from_addr,
            "from_name": from_name,
            "plain_text": txt or "See https://bakersfieldbrief.com/",
        }],
    }
    try:
        payload["emails"][0]["content"] = html
        camp = _req("POST", "/campaigns", payload, token)
    except SystemExit:
        # retry without the HTML content (free plan)
        del payload["emails"][0]["content"]
        camp = _req("POST", "/campaigns", payload, token)

    camp_id = (camp.get("data") or {}).get("id")
    if not camp_id:
        raise SystemExit(f"no campaign id: {camp}")

    # Send immediately
    _req("POST", f"/campaigns/{camp_id}/schedule", {"delivery": "instant"}, token)
    print(f"sent: campaign {camp_id} | {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
