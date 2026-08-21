#!/usr/bin/env python3
"""Send the rendered daily brief email via Buttondown (if configured).

Usage: python scripts/send_newsletter.py
- Requires BUTTONDOWN_API_KEY (and BUTTONDOWN_USERNAME) in .env or env.
- Reads email/latest/brief.html + brief.txt (rendered by the daily build).
- POSTs to the Buttondown API with status "about_to_send" so the email is
  actually SENT (the API defaults to draft; the Live-Dangerously header is
  the one-time confirmation for immediate sends).
- On success prints the issue URL; without a key prints the ready-to-send
  path. Exit 0 with no key (CI never breaks on an unconfigured send).

Add BUTTONDOWN_API_KEY + BUTTONDOWN_USERNAME to the repo's GitHub secrets
and the daily.yml 6am send step goes live automatically.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build import common  # noqa: E402  (loads .env)

HTML = ROOT / "email" / "latest" / "brief.html"
TXT = ROOT / "email" / "latest" / "brief.txt"
API = "https://api.buttondown.com/v1/emails"


def main() -> int:
    key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    if not HTML.exists():
        print(f"no rendered brief at {HTML} — run the build first")
        return 1
    if not key:
        print(f"email ready at {HTML} — set BUTTONDOWN_API_KEY to send automatically")
        return 0

    txt = TXT.read_text(encoding="utf-8") if TXT.exists() else ""
    html = HTML.read_text(encoding="utf-8")
    d = common.today_pacific()
    subject = f"The Bakersfield Daily Brief — {d.strftime('%A, %B')} {d.day}, {d.year}"

    payload = {
        "subject": subject,
        "body": txt or "Daily brief attached. See https://bakersfieldbrief.com/",
        # try to include the styled HTML; if the API rejects it we retry
        # with the plain-text/markdown body only.
        "status": "about_to_send",
    }

    def _post(body_payload: dict) -> dict:
        req = urllib.request.Request(
            API,
            data=json.dumps(body_payload).encode(),
            headers={
                "Authorization": f"Token {key}",
                "Content-Type": "application/json",
                "X-API-Version": "2026-04-01",
                # one-time confirmation for immediate sends; harmless after
                # the account is whitelisted
                "X-Buttondown-Live-Dangerously": "true",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    try:
        data = _post({**payload, "html": html})
    except Exception as exc:  # noqa: BLE001
        # The API may reject an html field — retry with markdown body only.
        try:
            data = _post(payload)
            print(f"(sent as markdown — html field rejected: {exc})")
        except Exception as exc2:  # noqa: BLE001
            print(f"send failed: {exc2}")
            return 1
    print(f"sent: {data.get('absolute_url') or data.get('url') or '(no url)'} "
          f"[status={data.get('status')}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
