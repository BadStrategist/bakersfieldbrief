#!/usr/bin/env python3
"""Post a condensed Brief + Kern Overnight summary to the Bakersfield Brief
Facebook page, with a hard publish gate: NEVER post unless both the daily
brief body AND the overnight report actually exist for the target date.

Design:
  * Date defaults to today (America/Los_Angeles); --date YYYY-MM-DD overrides.
  * Gate: data/briefs/<date>.json (body) and data/overnight_reports/<date>.md
    must both exist and be non-trivial. Missing either -> SKIP, exit 0
    (a skip is not an error; the pipeline reports it).
  * Duplicate guard: refuses to post if the page feed already contains a post
    with today's brief URL (idempotent re-runs).
  * Post: top story headline + overnight "big one" line + link + local tags.
  * Verify: reads back /posts and confirms the new post id appears.
  * Token: FB_PAGE_TOKEN env var (GitHub secret) or
    %LOCALAPPDATA%/hermes/secrets/fb_page_token.txt (local dev).
Exit codes: 0 ok/skipped, 1 gate fail (no post), 2 API error, 3 not verified.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
BRIEFS = ROOT / "data" / "briefs"
OVERNIGHTS = ROOT / "data" / "overnight_reports"
PAGE_ID = os.environ.get("FB_PAGE_ID", "1298315170026203")
API = "https://graph.facebook.com/v26.0"
HASHTAGS = "#Bakersfield #KernCounty #BakersfieldNews"
LOCAL_TAGS = ["KGET 17", "23ABC News", "City of Bakersfield"]  # mentioned, not @-tagged (API-safe)


def today_iso() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def get_token() -> str:
    tok = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if tok:
        return tok
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "secrets" / "fb_page_token.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    raise SystemExit("FB_PAGE_TOKEN not set and no local token file found")


def gate_check(date: str) -> tuple[str, str] | None:
    """Return (brief_body, overnight_md) or None with a reason if gate fails."""
    bp = BRIEFS / f"{date}.json"
    op = OVERNIGHTS / f"{date}.md"
    reasons = []
    brief = ""
    if not bp.exists():
        reasons.append(f"brief body missing: {bp.name}")
    else:
        try:
            brief = (json.loads(bp.read_text(encoding="utf-8")) or {}).get("body", "")
            if len(brief.strip()) < 200:
                reasons.append(f"brief body too short ({len(brief)} chars)")
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"brief body unreadable: {exc}")
    overnight = ""
    if not op.exists():
        reasons.append(f"overnight report missing: {op.name}")
    else:
        overnight = op.read_text(encoding="utf-8").strip()
        if len(overnight) < 300:
            reasons.append(f"overnight report too short ({len(overnight)} chars)")
    if reasons:
        print(f"SKIP {date}: publish gate failed — " + "; ".join(reasons))
        return None
    return brief, overnight


def archive_headline(date: str) -> str:
    """The day's headline from data/briefs_archive.json (the brief's own title)."""
    p = ROOT / "data" / "briefs_archive.json"
    try:
        entries = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    for e in entries:
        if e.get("date") == date:
            return (e.get("headline") or "").strip()
    return ""


def extract_top_story(brief: str, date: str) -> str:
    """Prefer the archive headline (the day's real title); fall back to the
    first substantive paragraph after the greeting."""
    hl = archive_headline(date)
    if hl:
        return hl
    paras = [p.strip() for p in brief.split("\n\n") if p.strip()]
    for p in paras:
        if p.lower().startswith("good morning"):
            continue
        if p.startswith("##"):
            continue
        # strip markdown and take first sentence
        plain = re.sub(r"[*#_]", "", p).strip()
        first = re.split(r"(?<=[.!?])\s+", plain)[0].strip()
        if len(first) > 30:
            return first
    # fallback: first non-greeting line of the whole body
    return brief.split("\n\n")[0][:220]


def extract_big_one(overnight: str) -> str:
    """The '## The big one' section first sentence, or the opening paragraph."""
    m = re.search(r"##\s*The big one\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    text = m.group(1) if m else overnight
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0].strip()
    if len(first) > 40:
        return first
    # fall back to the report's opening paragraph lead
    return text.strip()[:220]


def already_posted(token: str, date: str) -> bool:
    url = f"{API}/{PAGE_ID}/posts?fields=message,created_time&limit=25&access_token={token}"
    r = requests.get(url, timeout=20)
    if r.status_code != 200:
        print(f"WARN: could not check existing posts ({r.status_code}) — continuing")
        return False
    needle = f"briefs/{date}/"
    for p in r.json().get("data", []):
        if needle in (p.get("message") or ""):
            print(f"SKIP {date}: post with {needle} already exists")
            return True
    return False


def compose_post(date: str, brief: str, overnight: str) -> str:
    top = extract_top_story(brief, date)
    big = extract_big_one(overnight)
    link = f"https://bakersfieldbrief.com/briefs/{date}/"
    body = (
        f"{top}\n\n"
        f"Overnight: {big}\n\n"
        f"Full brief + overnight report: {link}\n\n"
        f"{HASHTAGS}"
    )
    return body


def post(token: str, message: str) -> str:
    r = requests.post(
        f"{API}/{PAGE_ID}/feed",
        json={"message": message, "access_token": token},
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"API error posting: {r.status_code} {r.text[:300]}")
    pid = (r.json() or {}).get("id", "")
    if not pid:
        raise SystemExit(f"API returned no post id: {r.text[:300]}")
    return pid


def verify(token: str, pid: str) -> bool:
    r = requests.get(f"{API}/{PAGE_ID}/posts?fields=id,message&limit=5&access_token={token}", timeout=20)
    if r.status_code != 200:
        print(f"WARN: verify read failed ({r.status_code})")
        return False
    return any(p.get("id") == pid for p in r.json().get("data", []))


def main() -> int:
    date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else today_iso()
    token = get_token()
    gate = gate_check(date)
    if gate is None:
        return 0  # skip is not an error
    brief, overnight = gate
    if already_posted(token, date):
        return 0
    message = compose_post(date, brief, overnight)
    print(f"POSTING for {date} ({len(message)} chars):\n{message}\n---")
    pid = post(token, message)
    print(f"posted id={pid}")
    if verify(token, pid):
        print(f"VERIFIED: {pid} visible in page feed")
        return 0
    print(f"NOT VERIFIED: {pid} not found in feed readback — manual check needed")
    return 3


if __name__ == "__main__":
    sys.exit(main())
