#!/usr/bin/env python
"""Read Facebook vs Instagram views for recent reels from Business Suite insights.

Why this exists: the Graph page token has no `read_insights` and no
`instagram_basic`, so `/{reel_id}/video_insights` returns
`(#200) read_insights permission missing`, and Instagram serves a login shell to
logged-out requests from this host. The posting admin CAN read the numbers in
Business Suite without any Instagram login -- provided a Chrome profile on this
box is signed into Facebook.

It drives the LOCAL signed-in Chrome over CDP (Playwright connect_over_cdp),
never the Hermes browser tools: those run on remote Browserbase and cannot see a
local profile.

Usage (from the repo root, project venv):
    python scripts/brief_reel/probe_ig_views.py                 # newest post
    python scripts/brief_reel/probe_ig_views.py --limit 5       # newest five
    python scripts/brief_reel/probe_ig_views.py --port 9223

Appends to work/social/ig-insights/ig-views.json (one row per day, newest first)
and writes a screenshot per reel for evidence.

Signed-out guard: Business Suite redirects to
`business.facebook.com/business/loginpage/?next=...`. That is reported as
SIGNED_OUT (exit 4) and nothing is written, so the tracking file can never fill
with login-page noise.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "work" / "social" / "ig-insights"
STORE = OUT_DIR / "ig-views.json"
PAGE_ID = "1298315170026203"
TOK_PATH = Path.home() / "AppData" / "Local" / "hermes" / "secrets" / "fb_page_token.txt"

VIEWS_RE = re.compile(r"(\d+)\s+from Facebook\s+(\d+)\s+from Instagram", re.I)
TOTAL_RE = re.compile(r"Views\s*\n\s*\u200b?\s*\n?\s*(\d+)", re.I)
FOLLOW_RE = re.compile(r"([\d,\.]+)\s*(?:total )?followers", re.I)


def graph(path: str) -> dict:
    tok = TOK_PATH.read_text(encoding="utf-8").strip()
    sep = "&" if "?" in path else "?"
    url = f"https://graph.facebook.com/v26.0/{path}{sep}access_token={urllib.parse.quote(tok)}"
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.load(r)


def recent_posts(limit: int) -> list[dict]:
    d = graph(f"{PAGE_ID}/posts?fields=id,created_time,permalink_url&limit={max(limit * 2, 12)}")
    rows = [p for p in d.get("data", []) if "/reel/" in (p.get("permalink_url") or "")]
    return rows[:limit]


def insights_url(content_id: str) -> str:
    return (
        "https://business.facebook.com/latest/insights/object_insights/"
        f"?asset_id={PAGE_ID}&content_id={content_id}&nav_ref=bizweb_insights_uta_table"
    )


def scrape(browser, content_id: str, shot: Path) -> dict | None:
    """Open the insights page for one reel. Returns None when signed out."""
    pg = browser.contexts[0].new_page()
    try:
        pg.goto(insights_url(content_id), wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(12000)
        if "loginpage" in pg.url or "/login" in pg.url:
            print("SIGNED_OUT:", pg.url.split("?")[0])
            return {"signed_out": True}
        body = pg.inner_text("body")
        m = VIEWS_RE.search(body)
        row = {
            "content_id": content_id,
            "views_total": (TOTAL_RE.search(body).group(1) if TOTAL_RE.search(body) else None),
            "from_facebook": m.group(1) if m else None,
            "from_instagram": m.group(2) if m else None,
            "ig_followers_seen": (FOLLOW_RE.search(body).group(1) if FOLLOW_RE.search(body) else None),
        }
        pg.screenshot(path=str(shot))
        return row
    finally:
        try:
            pg.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1, help="how many recent reels to read")
    ap.add_argument("--port", type=int, default=9223, help="CDP port of the signed-in Chrome")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    posts = recent_posts(args.limit)
    if not posts:
        print("no reel posts found on the page feed")
        return 3

    rows: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        for p in posts:
            cid = p["id"].split("_")[-1]
            day = datetime.fromisoformat(p["created_time"]).astimezone(timezone.utc).strftime("%Y-%m-%d")
            print(f"--- {day} content_id={cid} {p.get('permalink_url','')}")
            row = scrape(browser, cid, OUT_DIR / f"views-{day}-{cid[:8]}.png")
            if row is None:
                continue
            if row.get("signed_out"):
                print("ABORT: Chrome on CDP %d is signed OUT of Facebook." % args.port)
                print("Sign in once in that profile, then re-run. Nothing was written.")
                return 4
            row["day"] = day
            print("   ", json.dumps(row))
            rows.append(row)

    old: list[dict] = []
    if STORE.exists():
        try:
            old = json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            old = []
    merged = {r["day"]: r for r in old}
    for r in rows:
        merged[r["day"]] = r
    ordered = [merged[k] for k in sorted(merged, reverse=True)]
    STORE.write_text(json.dumps(ordered, indent=1), encoding="utf-8")
    print(f"\nwrote {STORE} ({len(ordered)} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
