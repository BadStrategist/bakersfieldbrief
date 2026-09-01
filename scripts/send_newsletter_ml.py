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


def _content_is_degraded() -> list[str]:
    """HARD SEND GATE — mirror of the watchdog's content checks (bb_email_watchdog.py).

    The CI send path must refuse to send a degraded email just like the
    watchdog does, so NO path (CI schedule, manual dispatch, watchdog) can
    ever put a broken brief in front of subscribers. Returns a list of
    missing/empty section names; [] means content is complete.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not HTML.exists():
        return ["no rendered brief"]
    text = HTML.read_text(encoding="utf-8", errors="replace")
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    human = f"{now.strftime('%B')} {now.day}, {now.year}"
    iso = now.strftime("%Y-%m-%d")
    # weather: a real temperature reading, not the degraded placeholder.
    # Weather prose lives in the LLM brief body, so this also catches the
    # "LLM brief never generated" failure. Accept either a degree symbol
    # (72° / 97°) or the spelled-out "85 degrees" form the LLM emits.
    has_temp = ("°" in text) or ("degrees" in text and ("high near" in text or "low around" in text))
    # something good: the rendered card carries the kicker + prose. The HTML
    # template emits '<!-- Something Good card -->' only when content exists,
    # but guard on TWO occurrences (comment + kicker) so a bare template
    # comment can't pass the gate.
    checks = {
        "weather": has_temp and "Weather data unavailable" not in text,
        "something good": text.count("Something Good") >= 2,
        # overnight: the card is degraded to a headline + count + Full Report
        # link when the LLM narrative is empty (the emailer emits the prose
        # paragraphs only if the brief body generated them). The narrative is
        # the text AFTER the 'Full Report' link — require real prose there,
        # not just the deterministic headline block. Guards the exact 2026-09-01
        # failure where the overnight narrative was empty.
        "overnight": _has_overnight_narrative(text),
        "date": (iso in text) or (human in text),
    }
    return [k for k, ok in checks.items() if not ok]


def _has_overnight_narrative(text: str) -> bool:
    """True if the Kern Overnight card carries real narrative prose.

    The emailer renders the deterministic headline + incident count + a
    'Full Report' link always; the LLM-written narrative paragraphs are only
    emitted when the brief body contains them. So the narrative is everything
    between the 'Full Report' link and the end of the overnight card. Extract
    that region (stripping tags/comments) and require enough prose to be a
    real report rather than an empty card.
    """
    import re
    card = _slice_between(text, "Kern Overnight card", "Today's Weather card")
    tail = card
    marker = tail.lower().rfind("full report")
    if marker != -1:
        tail = tail[marker + len("full report"):]
    tail = re.sub(r"<!--.*?-->", "", tail, flags=re.S)
    tail = re.sub(r"<[^>]+>", " ", tail)
    tail = re.sub(r"\s+", " ", tail).strip()
    # A real narrative is long prose with several sentence boundaries; an
    # empty card leaves at most a few boilerplate words here.
    return tail.count(". ") >= 3 and len(tail) >= 120


def _slice_between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i == -1:
        return ""
    j = text.find(end, i)
    return text[i:j] if j != -1 else text[i:]


def main() -> int:
    token = _token()
    group = _group()
    if not HTML.exists():
        print(f"no rendered brief at {HTML} — run the build first")
        return 1

    # HARD GATE: never send a broken email. If the rendered brief is degraded
    # (missing weather / something good / date — e.g. the LLM brief body never
    # got generated), refuse to send and report. A human must fix the build.
    degraded = _content_is_degraded()
    if degraded:
        print("BLOCKED send: rendered brief is degraded (missing: " + ", ".join(degraded) + ")")
        print("The email was NOT sent. Fix the build (check LLM_BASE_URL/LLM_MODEL),")
        print("rebuild, verify email/latest/brief.html, then send manually.")
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
