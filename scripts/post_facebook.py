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
  * Post type: a 30s Reel (brand card + news audio bed, Ken Burns zoom) —
    Reels get the best organic reach on Facebook. Falls back to a photo
    post of the same card only if the reel can't be assembled or uploaded.
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
    """Longer FB caption — the card image holds the compact summary, so this
    text complements it rather than repeating it word-for-word."""
    top = extract_top_story(brief, date)
    link = f"https://bakersfieldbrief.com/briefs/{date}/"

    # fuller body: first substantive paragraph of the brief (the Kern Overnight
    # section lead), which carries the night's story in prose
    paras = [p.strip() for p in brief.split("\n\n") if p.strip()]
    detail = ""
    for p in paras:
        if p.lower().startswith("good morning"):
            continue
        if p.startswith("##"):
            continue
        plain = re.sub(r"[*#_]", "", p).strip()
        if len(plain) > 60:
            detail = plain[:900]
            break
    if not detail:
        detail = top

    return (
        f"🌅 {top}\n\n"
        f"{detail}\n\n"
        f"📰 Full brief + overnight report: {link}\n\n"
        f"{HASHTAGS}"
    )


def post_photo(token: str, image_path: str, message: str) -> str:
    """Upload the daily card as a photo post with caption (photo posts get
    more reach than text-only on Facebook)."""
    import mimetypes
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    with open(image_path, "rb") as fh:
        files = {"source": (image_path.name, fh, mime)}
        data = {"message": message, "access_token": token}
        r = requests.post(f"{API}/{PAGE_ID}/photos", files=files, data=data, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"API error posting photo: {r.status_code} {r.text[:300]}")
    pid = (r.json() or {}).get("id", "")
    if not pid:
        raise SystemExit(f"API returned no post id: {r.text[:300]}")
    return pid


def post_reel(token: str, video_path: str, message: str) -> str:
    """Publish a Reel via the video_reels upload protocol.

    Meta's Reels upload supports two flows: the older chunked session
    (start -> transfer -> finish) and the newer single-shot direct upload
    URL (POST the whole file to upload_url, then poll status). Both end
    with a separate publish call. Reels get the best organic reach on
    Facebook, so this is the primary daily post; photo is the fallback.
    """
    import mimetypes
    size = Path(video_path).stat().st_size
    mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"

    # Phase 1: start the upload session
    r = requests.post(f"{API}/{PAGE_ID}/video_reels", data={
        "upload_phase": "start",
        "file_size": size,
        "access_token": token,
    }, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"reel upload start failed: {r.status_code} {r.text[:300]}")
    sess = r.json()
    upload_session_id = sess.get("upload_session_id")
    upload_url = sess.get("upload_url")

    if upload_url:
        # Newer flow: single-shot POST of the whole file to rupload
        # (application/octet-stream, offset 0, file_size).
        with open(video_path, "rb") as fh:
            r = requests.post(
                upload_url,
                data=fh,
                headers={
                    "Authorization": f"OAuth {token}",
                    "Content-Type": "application/octet-stream",
                    "offset": "0",
                    "file_size": str(size),
                },
                timeout=300,
            )
        if r.status_code not in (200, 201):
            raise SystemExit(f"reel direct upload failed: {r.status_code} {r.text[:300]}")
        video_id = sess.get("video_id", "")
        if not video_id:
            raise SystemExit(f"no video_id from start: {r.text[:300]}")
        print(f"  upload response: {r.text[:120]}")
    else:
        # Older flow: chunked session.
        if not upload_session_id:
            raise SystemExit(f"no upload_session_id: {r.text[:300]}")
        start = int(sess.get("start_offset", 0))
        end = int(sess.get("end_offset", size))
        with open(video_path, "rb") as fh:
            while start < size:
                fh.seek(start)
                chunk = fh.read(end - start)
                r = requests.post(f"{API}/{PAGE_ID}/video_reels", data={
                    "upload_phase": "transfer",
                    "upload_session_id": upload_session_id,
                    "start_offset": start,
                    "end_offset": end,
                    "access_token": token,
                }, files={"video_file_chunk": (Path(video_path).name, chunk, mime)}, timeout=120)
                if r.status_code != 200:
                    raise SystemExit(f"reel chunk transfer failed at {start}: {r.status_code} {r.text[:300]}")
                body = r.json()
                start = int(body.get("start_offset", end))
                end = int(body.get("end_offset", size))

        r = requests.post(f"{API}/{PAGE_ID}/video_reels", data={
            "upload_phase": "finish",
            "upload_session_id": upload_session_id,
            "access_token": token,
        }, timeout=60)
        if r.status_code != 200:
            raise SystemExit(f"reel upload finish failed: {r.status_code} {r.text[:300]}")
        video_id = (r.json() or {}).get("video_id", "")
        if not video_id:
            raise SystemExit(f"no video_id after finish: {r.text[:300]}")

    # Wait for Meta to finish processing before publishing.
    import time
    for attempt in range(12):
        st = requests.get(f"{API}/{video_id}?fields=status&access_token={token}", timeout=20)
        try:
            status = (st.json()["status"].get("processing_phase") or {}).get("status", "complete")
        except Exception:  # noqa: BLE001
            status = "complete"
        if status in ("complete", "finished", "ready"):
            break
        print(f"  video processing: {status} (attempt {attempt + 1}/12) — waiting 10s")
        time.sleep(10)

    # Publish the reel: finish the upload session with video_state=PUBLISHED.
    # (POSTing to /video_id with published=true is the OLD video flow and
    # errors with "Post Already Published" — reels publish via finish.)
    r = requests.post(f"{API}/{PAGE_ID}/video_reels", data={
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": message,
        "access_token": token,
    }, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"reel publish failed: {r.status_code} {r.text[:300]}")
    body = r.json()
    if not body.get("success"):
        raise SystemExit(f"reel publish returned no success: {r.text[:300]}")
    post_id = body.get("post_id", "") or video_id
    print(f"  reel video_id={video_id} post_id={post_id}")
    return post_id


def verify(token: str, pid: str, date: str) -> bool:
    """Confirm the post is live. Meta mints a DIFFERENT post id for photo
    uploads than the photo id the POST returns, so match on the caption's
    unique marker (today's brief URL) instead of the id. The page feed
    edge can lag the POST response by several seconds, so poll briefly
    before declaring failure (otherwise CI false-flags live posts)."""
    needle = f"briefs/{date}/"
    for attempt in range(4):
        r = requests.get(f"{API}/{PAGE_ID}/posts?fields=id,message&limit=10&access_token={token}", timeout=20)
        if r.status_code == 200:
            for p in r.json().get("data", []):
                if needle in (p.get("message") or ""):
                    print(f"  found live post: {p.get('id')}")
                    return True
        else:
            print(f"WARN: verify read failed ({r.status_code})")
        if attempt < 3:
            import time
            print(f"  feed not yet showing the post (attempt {attempt + 1}/4) — waiting 5s")
            time.sleep(5)
    return False


def main() -> int:
    date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else today_iso()
    token = get_token()
    gate = gate_check(date)
    if gate is None:
        return 0  # skip is not an error
    brief, overnight = gate
    if already_posted(token, date):
        return 0

    # generate today's card (the image the post carries)
    import subprocess
    card = ROOT / "site" / "assets" / "img" / "social" / f"{date}.png"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_social_card.py"),
         "--date", date, "--out", str(card)],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(rc.stdout.strip() or rc.stderr.strip())
    if rc.returncode != 0 or not card.exists():
        print(f"SKIP {date}: card generation failed — no image to post")
        return 0
    if card.stat().st_size < 10000:
        print(f"SKIP {date}: card suspiciously small ({card.stat().st_size} B)")
        return 0

    message = compose_post(date, brief, overnight)
    print(f"POSTING for {date} ({len(message)} chars):\n{message}\n---")

    # Primary: the daily Reel (multi-panel card + news bed). Reels get the
    # best organic reach on Facebook. Fall back to a photo post only if
    # the reel can't be assembled or uploaded — never ship nothing.
    reel_dir = ROOT / "site" / "assets" / "img" / "social" / "reel"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_social_card.py"),
         "--date", date, "--out", str(card), "--reel-dir", str(reel_dir)],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(rc.stdout.strip() or rc.stderr.strip())
    panels = [reel_dir / f"{date}-p{i}.png" for i in range(1, 5)]
    panels_ok = rc.returncode == 0 and all(p.exists() for p in panels)

    reel = ROOT / "site" / "assets" / "img" / "social" / f"{date}-reel.mp4"
    reel_ok = False
    if panels_ok:
        rc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_reel.py"),
             *[a for p in panels for a in ("--panels", str(p))],
             "--audio", str(ROOT / "assets" / "audio" / "news_reel_bed.wav"),
             "--out", str(reel)],
            cwd=ROOT, capture_output=True, text=True,
        )
        print(rc.stdout.strip() or rc.stderr.strip())
        reel_ok = rc.returncode == 0 and reel.exists() and reel.stat().st_size > 100_000

    if reel_ok:
        try:
            pid = post_reel(token, reel, message)
            print(f"posted id={pid}")
            if verify(token, pid, date):
                print(f"VERIFIED: {pid} live in page feed (reel)")
                return 0
            print(f"NOT VERIFIED: {pid} not found in feed readback — manual check needed")
            return 3
        except SystemExit as exc:
            print(f"REEL FAILED ({exc}) — falling back to photo post")

    # Fallback: photo post (card carries the same summary).
    pid = post_photo(token, card, message)
    print(f"posted id={pid}")
    if verify(token, pid, date):
        print(f"VERIFIED: {pid} live in page feed (photo fallback)")
        return 0
    print(f"NOT VERIFIED: {pid} not found in feed readback — manual check needed")
    return 3


if __name__ == "__main__":
    sys.exit(main())
