#!/usr/bin/env python3
"""Send the rendered daily brief email via Buttondown (if configured).

Usage: python scripts/send_newsletter.py
- Requires BUTTONDOWN_API_KEY (and BUTTONDOWN_USERNAME) in .env or env.
- Reads email/latest/brief.html + brief.txt (rendered by the daily build).
- On success prints the issue URL; without a key prints the ready-to-send path.

Add BUTTONDOWN_API_KEY to the repo's GitHub secrets and the daily.yml
send step goes live automatically."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build import common  # noqa: E402  (loads .env)

HTML = ROOT / "email" / "latest" / "brief.html"
TXT = ROOT / "email" / "latest" / "brief.txt"


def main() -> int:
    key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    username = os.environ.get("BUTTONDOWN_USERNAME", "").strip()
    if not HTML.exists():
        print(f"no rendered brief at {HTML} — run the build first")
        return 1
    if not key:
        print(f"email ready at {HTML} — set BUTTONDOWN_API_KEY to send automatically")
        return 0

    import urllib.request

    body = (TXT.read_text(encoding="utf-8") if TXT.exists() else
            "Daily brief attached. See https://bakersfieldbrief.com/")
    html_body = HTML.read_text(encoding="utf-8")
    subject = f"The Bakersfield Daily Brief — {common.today_pacific().strftime('%A, %B %-d, %Y')}".replace(" 0", " ")
    payload = f"subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}&html={urllib.parse.quote(html_body)}"
    req = urllib.request.Request(
        f"https://api.buttondown.com/v1/emails/",
        data=payload.encode(),
        headers={"Authorization": f"Token {key}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        print(f"sent: {data.get('url', '(no url)')}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"send failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
