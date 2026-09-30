#!/usr/bin/env python3
"""Graph API publisher for the daily social legs: Facebook reel, Instagram reel,
Facebook story, Instagram story — the primary path. The Business Suite browser
automation (brief_reel/publish_social.py) is the backup for any leg this fails.

Why this is primary now (2026-09-29): API posts on this page were "withheld"
because the Meta app (HermesAutoPoster) was Unpublished, i.e. dev mode, where
app-made posts are visible only to app roles. The app is published, and the
page token carries instagram_basic + instagram_content_publish.

Every leg is idempotent on its own: before publishing, it checks the live
platform for a same-day item and skips if one exists, so re-runs, the browser
backup and the API never double-post. Each leg's failure is isolated and
reported; one bad leg never blocks the others.

Library use:  social_api.publish_all(token, date, reel_mp4, caption) -> dict
CLI:          python scripts/social_api.py --date YYYY-MM-DD --reel path.mp4
              [--caption-file f.txt] [--legs fb_reel,ig_reel,fb_story,ig_story]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_facebook as PF  # noqa: E402

API = PF.API
PAGE_ID = PF.PAGE_ID
LA = ZoneInfo("America/Los_Angeles")
LEGS = ("fb_reel", "ig_reel", "fb_story", "ig_story")


class LegError(Exception):
    pass


def _la_date(ts: str) -> str:
    """ISO timestamp ('2026-09-29T23:06:04+0000' or unix seconds) -> LA date."""
    if not ts:
        return ""
    try:
        if str(ts).isdigit():
            when = datetime.fromtimestamp(int(ts), ZoneInfo("UTC"))
        else:
            s = str(ts).replace("Z", "+00:00")
            if len(s) > 5 and s[-5] in "+-" and s[-3] != ":":
                s = s[:-2] + ":" + s[-2:]  # +0000 -> +00:00
            when = datetime.fromisoformat(s)
        return when.astimezone(LA).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _get(path: str, token: str, **params) -> dict:
    r = requests.get(f"{API}/{path}", params={**params, "access_token": token}, timeout=30)
    body = r.json() if r.content else {}
    if r.status_code != 200 or "error" in body:
        raise LegError(f"GET {path}: {r.status_code} {str(body)[:200]}")
    return body


def _post(path: str, token: str, **data) -> dict:
    r = requests.post(f"{API}/{path}", data={**data, "access_token": token}, timeout=60)
    body = r.json() if r.content else {}
    if r.status_code != 200 or "error" in body:
        raise LegError(f"POST {path}: {r.status_code} {str(body)[:200]}")
    return body


def _rupload(url: str, token: str, video: Path) -> None:
    """Single-shot binary upload to rupload.facebook.com (FB video + IG resumable).
    offset/file_size headers are REQUIRED or the upload never completes."""
    size = video.stat().st_size
    with open(video, "rb") as fh:
        r = requests.post(url, data=fh, timeout=300, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream"})
    if r.status_code not in (200, 201):
        raise LegError(f"upload failed: {r.status_code} {r.text[:200]}")


def ig_user_id(token: str) -> str:
    ig = (_get(PAGE_ID, token, fields="instagram_business_account")
          .get("instagram_business_account") or {}).get("id")
    if not ig:
        raise LegError("no Instagram account linked to the page (or token lacks instagram_basic)")
    return ig


# ---- same-day checks (ground truth = the live platform) -------------------

def fb_reel_today(token: str, date: str) -> str | None:
    for p in _get(f"{PAGE_ID}/posts", token, fields="permalink_url,created_time,message",
                  limit=25).get("data", []):
        if "/reel/" in (p.get("permalink_url") or "") and PF._post_is_for_date(p, date):
            return p.get("permalink_url")
    return None


def fb_story_today(token: str, date: str) -> str | None:
    for s in _get(f"{PAGE_ID}/stories", token).get("data", []):
        if _la_date(s.get("creation_time", "")) == date and s.get("status") != "ARCHIVED":
            return s.get("url") or s.get("post_id") or "story"
    return None


def ig_reel_today(token: str, ig: str, date: str) -> str | None:
    for m in _get(f"{ig}/media", token, fields="media_product_type,timestamp,permalink",
                  limit=15).get("data", []):
        if m.get("media_product_type") == "REELS" and _la_date(m.get("timestamp", "")) == date:
            return m.get("permalink") or m.get("id")
    return None


def ig_story_today(token: str, ig: str, date: str) -> str | None:
    for m in _get(f"{ig}/stories", token, fields="timestamp,permalink").get("data", []):
        if _la_date(m.get("timestamp", "")) == date:
            return m.get("permalink") or m.get("id")
    return None


# ---- publishers ------------------------------------------------------------

def _fb_video(edge: str, token: str, video: Path, **finish) -> str:
    """Start -> rupload -> finish for /video_reels and /video_stories."""
    start = _post(f"{PAGE_ID}/{edge}", token, upload_phase="start")
    vid, url = start.get("video_id"), start.get("upload_url")
    if not (vid and url):
        raise LegError(f"{edge} start returned {str(start)[:200]}")
    _rupload(url, token, video)
    # upload must be complete before finish (processing runs after publish)
    for _ in range(20):
        st = _get(vid, token, fields="status").get("status", {})
        if (st.get("uploading_phase") or {}).get("status") == "complete":
            break
        time.sleep(3)
    body = _post(f"{PAGE_ID}/{edge}", token, upload_phase="finish", video_id=vid, **finish)
    if not body.get("success"):
        raise LegError(f"{edge} finish returned {str(body)[:200]}")
    return body.get("post_id") or vid


def publish_fb_reel(token: str, video: Path, caption: str) -> str:
    vid = _fb_video("video_reels", token, video, video_state="PUBLISHED", description=caption)
    return f"https://www.facebook.com/reel/{vid.split('_')[-1]}/" if vid else ""


def publish_fb_story(token: str, video: Path) -> str:
    return _fb_video("video_stories", token, video)


def _ig_media(token: str, ig: str, video: Path, media_type: str, caption: str = "") -> str:
    data = {"media_type": media_type, "upload_type": "resumable"}
    if caption:
        data["caption"] = caption
    if media_type == "REELS":
        data["share_to_feed"] = "true"
    c = _post(f"{ig}/media", token, **data)
    cid, uri = c.get("id"), c.get("uri")
    if not (cid and uri):
        raise LegError(f"IG container returned {str(c)[:200]}")
    _rupload(uri, token, video)
    for _ in range(60):  # IG transcodes; reels usually finish in 30-90s
        code = _get(cid, token, fields="status_code,status").get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise LegError(f"IG container {code}")
        time.sleep(5)
    else:
        raise LegError("IG container never finished processing")
    mid = _post(f"{ig}/media_publish", token, creation_id=cid).get("id")
    if not mid:
        raise LegError("IG media_publish returned no id")
    try:
        return _get(mid, token, fields="permalink").get("permalink") or mid
    except LegError:
        return mid


def publish_all(token: str, date: str, reel: Path, caption: str,
                legs: tuple[str, ...] = LEGS) -> dict:
    """Publish each missing leg; return {leg: {"ok", "url"|"error", "skipped"?}}."""
    out: dict[str, dict] = {}
    ig = None
    try:
        ig = ig_user_id(token)
    except LegError as e:
        for leg in ("ig_reel", "ig_story"):
            if leg in legs:
                out[leg] = {"ok": False, "error": str(e)}
    plan = {
        "fb_reel": (lambda: fb_reel_today(token, date),
                    lambda: publish_fb_reel(token, reel, caption)),
        "ig_reel": (lambda: ig_reel_today(token, ig, date),
                    lambda: _ig_media(token, ig, reel, "REELS", caption)),
        "fb_story": (lambda: fb_story_today(token, date),
                     lambda: publish_fb_story(token, reel)),
        "ig_story": (lambda: ig_story_today(token, ig, date),
                     lambda: _ig_media(token, ig, reel, "STORIES")),
    }
    for leg in legs:
        if leg in out:
            continue
        check, publish = plan[leg]
        try:
            existing = check()
            if existing:
                out[leg] = {"ok": True, "skipped": True, "url": existing}
            else:
                out[leg] = {"ok": True, "url": publish()}
        except (LegError, requests.RequestException) as e:
            out[leg] = {"ok": False, "error": str(e)[:300]}
        print(f"[api] {leg}: {out[leg]}", flush=True)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=PF.today_iso())
    ap.add_argument("--reel", required=True)
    ap.add_argument("--caption-file")
    ap.add_argument("--legs", default=",".join(LEGS))
    a = ap.parse_args(argv[1:])
    caption = Path(a.caption_file).read_text(encoding="utf-8") if a.caption_file else ""
    legs = tuple(x for x in a.legs.split(",") if x in LEGS)
    res = publish_all(PF.get_token(), a.date, Path(a.reel), caption, legs)
    return 0 if all(v.get("ok") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
