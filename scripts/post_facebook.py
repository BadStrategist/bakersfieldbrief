#!/usr/bin/env python3
"""Post a condensed Brief + Kern Overnight summary to the Bakersfield Brief
Facebook page, with a hard publish gate: NEVER post unless both the daily
brief body AND the overnight report actually exist for the target date.

Design:
  * Date defaults to today (America/Los_Angeles); --date YYYY-MM-DD overrides.
  * Gate: data/briefs/<date>.json (body) and data/overnight_reports/<date>.md
    must both exist and be non-trivial. Missing either -> SKIP, exit 0
    (a skip is not an error; the pipeline reports it). The overnight
    report must ALSO be complete: no partial-coverage marker and the
    required sections present (a report published early with partial
    transcription never reaches socials).
  * NO GUESSING gate: the overnight must be LIVE on the deployed website
    (https://bakersfieldbrief.com/overnight/ renders <section id="<date>">)
    before posting — a repo file that hasn't deployed is not publication.
    CI deploys BEFORE this step; the script polls briefly for CDN
    propagation and skips if the report never appears live.
  * Retry: when only the overnight is missing/incomplete, wait and re-pull
    (up to FB_RETRY_MINUTES, default 25) — the local KO cron pushes the
    report ~7:00-7:10 PT, after the 7:00 PT CI checkout. --retry-minutes N
    or FB_RETRY_MINUTES=0 disables the wait.
  * Duplicate guard: refuses to post if the page feed already contains an
    actual daily post (reel or photo) with today's brief URL (idempotent
    re-runs). Plain link posts that merely mention the URL never count, so
    no day is skipped by a newsletter promo.
  * Post: top story headline + overnight "big one" line + link + local tags.
  * Post type: a 30s animated Reel (scripted story cards over the treated
    photo-background library, mixed with our news audio bed) — Reels get the
    best organic reach on Facebook. Falls back to a photo post of the same
    day's still card only if the reel can't be assembled or uploaded.
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
# Instagram hard-caps tags at 5 per post (official Help Center: more than 5 and the
# caption will not post), and the same caption goes to Facebook, so stay at or under 5.
# Evidence: big local news accounts run 0 tags (KGET 0/6, BakersfieldNow 0/7); 23ABC
# uses 3-7 anchored on #bakersfield + #kerncounty; #bakersfieldca is the common second
# spelling; #661bakersfield is a genuine low-competition local tag. #BakersfieldNews
# was dropped: no local account was found using it.
HASHTAGS = "#Bakersfield #KernCounty #BakersfieldCA #661Bakersfield"
LOCAL_TAGS = ["KGET 17", "23ABC News", "City of Bakersfield"]  # mentioned, not @-tagged (API-safe)
SITE_OVERNIGHT_URL = "https://bakersfieldbrief.com/overnight/"
SITE_OVERNIGHT_ARCHIVE_URL = "https://bakersfieldbrief.com/overnight/archive/"


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


def overnight_live_on_site(date: str) -> bool:
    """NO GUESSING: verify the overnight report for `date` is actually
    PUBLISHED on the live website, not merely present in the repo. The site
    renders each published report with <section id=\"<date>\"> on the
    /overnight/ page (and the archive). Only a report that is live there may
    be posted to socials — a repo file that hasn't deployed yet is not
    publication."""
    for url in (SITE_OVERNIGHT_URL, SITE_OVERNIGHT_ARCHIVE_URL):
        try:
            r = requests.get(url, timeout=25)
            if r.status_code == 200 and f'id="{date}"' in r.text:
                return True
        except requests.RequestException as exc:  # noqa: BLE001
            print(f"  WARN: site check {url} failed: {exc}")
    return False


def gate_problems(date: str) -> list[str]:
    """List of publish-gate problems for date (empty list = ready to post).

    A report is complete only when it is published (in
    data/overnight_reports/) AND carries no partial-coverage marker AND
    has the required structural sections. Phase 2 is allowed to publish
    early with partial transcription — the marker is what stops a partial
    report from being posted to socials.
    """
    bp = BRIEFS / f"{date}.json"
    op = OVERNIGHTS / f"{date}.md"
    reasons = []
    if not bp.exists():
        reasons.append(f"brief body missing: {bp.name}")
    else:
        try:
            brief = (json.loads(bp.read_text(encoding="utf-8")) or {}).get("body", "")
            if len(brief.strip()) < 200:
                reasons.append(f"brief body too short ({len(brief)} chars)")
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"brief body unreadable: {exc}")
    if not op.exists():
        reasons.append(f"overnight report missing: {op.name}")
    else:
        overnight = op.read_text(encoding="utf-8").strip()
        low = overnight.lower()
        if len(overnight) < 300:
            reasons.append(f"overnight report too short ({len(overnight)} chars)")
        if "partial coverage" in low or "transcription was still running" in low:
            reasons.append("overnight report marked PARTIAL (transcription incomplete)")
        elif not (overnight.startswith("# ") and "## Night notes" in overnight):
            reasons.append("overnight report missing required sections (not fully written)")
    return reasons


def gate_check(date: str) -> tuple[str, str] | None:
    """Return (brief_body, overnight_md) or None with a reason if gate fails."""
    reasons = gate_problems(date)
    if reasons:
        print(f"SKIP {date}: publish gate failed — " + "; ".join(reasons))
        return None
    brief = (json.loads((BRIEFS / f"{date}.json").read_text(encoding="utf-8")) or {}).get("body", "")
    overnight = (OVERNIGHTS / f"{date}.md").read_text(encoding="utf-8").strip()
    return brief, overnight


def _git_pull_latest() -> None:
    """Fetch origin/main and overlay the data dirs the gate reads, so a
    report pushed by the local KO cron (after this job's checkout) becomes
    visible. Uses fetch + sparse checkout of data/ — works on the detached
    HEAD that actions/checkout leaves, with no rebase/conflict risk.
    Non-fatal: on failure the next poll just re-checks local state."""
    import subprocess
    r = subprocess.run(
        ["git", "fetch", "origin", "main"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"  WARN: git fetch failed ({r.returncode}): {(r.stderr or '')[-200:]}")
        return
    r = subprocess.run(
        ["git", "checkout", "origin/main", "--",
         "data/overnight_reports", "data/briefs"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        print(f"  WARN: git checkout of data/ failed ({r.returncode}): {(r.stderr or '')[-200:]}")
        return
    # `git checkout <ref> -- <path>` also writes the INDEX, so this overlay left
    # data/briefs/<date>.json and data/overnight_reports/<date>.md STAGED. On this
    # box that is a trap: data/ is CI-owned, so the next source commit would sweep
    # them in. Reset the INDEX only; the worktree keeps origin's content, which is
    # the whole point of the overlay.
    subprocess.run(
        ["git", "reset", "-q", "--", "data/overnight_reports", "data/briefs"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


def wait_for_gate(date: str, minutes: float) -> tuple[str, str] | None:
    """Poll the publish gate until a COMPLETE brief+overnight exists or the
    budget is exhausted. Only retries when the overnight is the missing
    piece (a missing brief is a hard failure the KO pipeline can't fix).
    Pulls from origin between polls so a report pushed by the local KO
    cron (phase 2 lands ~7:00-7:10 PT, after the 7:00 CI checkout) is
    picked up. Returns (brief, overnight) or None."""
    import time
    if minutes <= 0:
        return gate_check(date)
    problems = gate_problems(date)
    if not problems:
        return gate_check(date)
    if any("brief" in p for p in problems):
        print(f"SKIP {date}: gate failed on the brief — not retrying: " + "; ".join(problems))
        return None
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        left = int((deadline - time.time()) / 60)
        print(f"  gate not ready (overnight) — pulling latest, retrying in 30s (≤{left} min left)")
        _git_pull_latest()
        time.sleep(30)
        if not gate_problems(date):
            return gate_check(date)
    print(f"SKIP {date}: overnight still incomplete after {minutes:.0f} min — manual check needed")
    return None


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


_STOP = {"the", "and", "for", "with", "that", "this", "from", "have", "were",
         "has", "its", "are", "was", "over", "after", "into", "about", "his",
         "her", "them", "they", "said", "says", "not", "but", "been", "will"}


def _headline_grounded_in_body(headline: str, brief: str) -> bool:
    """The archive headline may only lead the post if it is actually grounded
    in the brief body it is posted with. The archive is regenerated by later
    builds and can drift from the body file (a film review headline once
    drifted in while the body never mentioned it) — a headline that isn't in
    the body must NEVER lead the post. Checks significant-word overlap:
    >= 60% of the headline's content words must appear in the body."""
    if not headline:
        return False
    hw = {w for w in re.findall(r"[a-z']+", headline.lower())
          if len(w) > 3 and w not in _STOP}
    if len(hw) < 3:
        return False
    bw = set(re.findall(r"[a-z']+", brief.lower()))
    overlap = len(hw & bw) / len(hw)
    return overlap >= 0.6


def extract_top_story(brief: str, date: str) -> str:
    """The post lead — MUST be the Kern Overnight scanner content, never the
    archive headline. The archive headline is the LLM's title for the daily
    brief and can be any top story, including national wire items (a film
    review led the 2026-08-18 reel as "Jeff Daniels channeled Reagan in The
    Brink of War"; 'Lanterns' did the same on 08-17). Grounding in the WHOLE
    body proves nothing — Top stories legitimately carry those items — so the
    archive headline is never safe here. Return the first substantive
    paragraph's first sentence (the Kern Overnight lead)."""
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


def _truncate_sentences(text: str, limit: int) -> str:
    """Cut text to WHOLE sentences that fit within `limit` chars — never
    mid-word (compose_post once shipped '...Columbus Street esca' from a
    hard [:900] slice). If even the first sentence exceeds the limit, cut at
    a word boundary with an ellipsis."""
    if len(text) <= limit:
        return text
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(s) + 1 > limit:
            break
        out += s + " "
    out = out.strip()
    if out:
        return out
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"


def extract_big_one(overnight: str) -> str:
    """The '## The big one' section first sentence, or the opening paragraph."""
    m = re.search(r"##\s*The big one\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    text = m.group(1) if m else overnight
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0].strip()
    if len(first) > 40:
        return first
    # fall back to the report's opening paragraph lead
    return text.strip()[:220]


def _is_daily_post(p: dict) -> bool:
    """A post counts as 'the daily post' only if it is an actual reel or photo
    upload — those are the two shapes the daily publish produces. Plain link
    posts (newsletter promos, in-depth teasers) that happen to mention the
    brief URL must NEVER satisfy the duplicate guard, or a real daily post
    gets skipped (the 'don't skip days' rule)."""
    perm = p.get("permalink_url") or ""
    if "/reel/" in perm or "/photos/" in perm or "/photo/" in perm:
        return True
    # Older photo posts can have a plain /posts/<id> permalink; the message
    # shape is still the daily post (🌅 lead + brief URL + hashtags).
    msg = p.get("message") or ""
    return "🌅" in msg and "#BakersfieldNews" in msg


def _post_is_for_date(p: dict, date: str) -> bool:
    """Is this post's own publish time on the day we care about?

    The caption now links to a FIXED overnight URL, so the URL can no longer
    identify a given day's post the way the old per-day brief URL did
    (/briefs/<date>/). Match created_time in the site's timezone instead, or the
    duplicate guard and the live check both stop working.
    """
    ct = (p.get("created_time") or "").strip()
    if not ct:
        return False
    try:
        when = datetime.fromisoformat(ct.replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/Los_Angeles"))
    except ValueError:
        return False
    return when.strftime("%Y-%m-%d") == date


def already_posted(token: str, date: str) -> bool:
    url = f"{API}/{PAGE_ID}/posts?fields=message,permalink_url,created_time&limit=25&access_token={token}"
    r = requests.get(url, timeout=20)
    if r.status_code != 200:
        print(f"WARN: could not check existing posts ({r.status_code}) — continuing")
        return False
    for p in r.json().get("data", []):
        if _is_daily_post(p) and _post_is_for_date(p, date):
            print(f"SKIP {date}: daily post for {date} already exists ({p.get('permalink_url', '')})")
            return True
    return False


def compose_post(date: str, brief: str, overnight: str) -> str:
    """Longer FB caption — the card image holds the compact summary, so this
    text complements it rather than repeating it word-for-word."""
    top = extract_top_story(brief, date)
    # Social posts land on the OVERNIGHT report, never the daily brief. The reel
    # and the story both summarize the night's scanner activity, so the overnight
    # page is the page that matches what the viewer just watched.
    link = SITE_OVERNIGHT_URL

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
            detail = _truncate_sentences(plain, 900)
            break
    if not detail:
        detail = top

    return (
        f"🌅 {top}\n\n"
        f"{detail}\n\n"
        f"📰 Full overnight report: {link}\n\n"
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
    own publish date instead of the id. Only an actual
    reel/photo post counts — never a plain link post that happens to mention
    the URL. The page feed edge can lag the POST response by several seconds,
    so poll briefly before declaring failure (otherwise CI false-flags live
    posts)."""
    for attempt in range(4):
        r = requests.get(f"{API}/{PAGE_ID}/posts?fields=id,message,permalink_url,created_time&limit=10&access_token={token}", timeout=20)
        if r.status_code == 200:
            for p in r.json().get("data", []):
                if _is_daily_post(p) and _post_is_for_date(p, date):
                    print(f"  found live post: {p.get('id')} ({p.get('permalink_url', '')})")
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
    retry_minutes = float(os.environ.get("FB_RETRY_MINUTES", "25"))
    if "--retry-minutes" in sys.argv:
        retry_minutes = float(sys.argv[sys.argv.index("--retry-minutes") + 1])
    gate = wait_for_gate(date, retry_minutes)
    if gate is None:
        return 0  # skip is not an error
    brief, overnight = gate

    # NO GUESSING: a repo file is not publication. The overnight must be LIVE
    # on the deployed website (the CI deploy runs before this step). Poll
    # briefly for CDN propagation; if it never shows up, skip — a later run
    # (e.g. the push-triggered rebuild) will deploy it and post.
    import time as _time
    site_ok = overnight_live_on_site(date)
    if not site_ok:
        deadline = _time.time() + max(180.0, retry_minutes * 60)
        while _time.time() < deadline and not site_ok:
            print(f"  overnight not yet LIVE on site — waiting 15s")
            _time.sleep(15)
            site_ok = overnight_live_on_site(date)
    if not site_ok:
        print(f"SKIP {date}: overnight report NOT verified live on {SITE_OVERNIGHT_URL} — not posting (a later run will deploy it)")
        return 0

    if already_posted(token, date):
        return 0

    # Build today's brief.json — the config the reel renderer reads. It is
    # derived deterministically from committed data (brief body + overnight +
    # incidents), so no LLM call is needed and re-runs reproduce the reel.
    import subprocess
    brief_json = ROOT / "site" / "assets" / "img" / "social" / f"{date}-brief.json"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_brief_json.py"),
         "--date", date, "--out", str(brief_json)],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(rc.stdout.strip() or rc.stderr.strip())
    if rc.returncode != 0 or not brief_json.exists():
        print(f"SKIP {date}: brief.json generation failed — no reel to post")
        return 0
    if brief_json.stat().st_size < 500:
        print(f"SKIP {date}: brief.json suspiciously small ({brief_json.stat().st_size} B)")
        return 0

    message = compose_post(date, brief, overnight)
    print(f"POSTING for {date} ({len(message)} chars):\n{message}\n---")

    # Music bed: the daily rotation chosen by make_brief_json (brief.json's
    # `music` field) — read it back so the renderer uses exactly what the
    # config picked. Absolute path: the renderer resolves relative music
    # against ITS OWN dir, so relative repo paths break.
    music_rel = (json.loads(brief_json.read_text(encoding="utf-8"))
                 .get("music", "assets/audio/news_reel_bed.wav"))
    music_abs = music_rel if os.path.isabs(music_rel) else str(ROOT / music_rel)

    # Primary: PHOTO post of the daily card. On this new page, photo posts
    # are the ONLY format verified to render publicly on the page timeline —
    # reels are withheld from the page view until the page builds trust
    # (verified 2026-08-19: the Aug 17 photo post serves publicly and appears
    # in the page HTML, while all four reels are absent from the timeline).
    # The reel is posted as a best-effort SECOND post (reels still reach the
    # Reels feed and build posting history). Never ship nothing: if the card
    # is missing, fall back to the reel; if both are missing, skip.
    reel_dir = ROOT / "site" / "assets" / "img" / "social"
    stem = reel_dir / f"{date}-reel"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "brief_reel" / "render_reel.py"),
         str(brief_json),
         "--out", str(stem),
         "--music", music_abs],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(rc.stdout.strip() or rc.stderr.strip())
    reel = stem.with_suffix(".mp4")
    card = stem.with_suffix(".png")  # renderer also emits the still card
    reel_ok = rc.returncode == 0 and reel.exists() and reel.stat().st_size > 100_000

    if card.exists() and card.stat().st_size >= 10000:
        pid = post_photo(token, card, message)
        print(f"posted id={pid}")
        if verify(token, pid, date):
            print(f"VERIFIED: {pid} live in page feed (photo card)")
            # Best-effort second post: the reel. Photo already verified, so a
            # reel failure must NOT fail the run (exit 0).
            if reel_ok:
                try:
                    rpid = post_reel(token, reel, message)
                    print(f"reel posted id={rpid}")
                except SystemExit as exc:
                    print(f"REEL BONUS SKIPPED ({exc}) — photo post already live")
            return 0
        print(f"NOT VERIFIED: {pid} not found in feed readback — manual check needed")
        return 3

    # Fallback: reel only when no card was rendered.
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
            print(f"REEL FAILED ({exc})")

    print(f"SKIP {date}: no card and no reel — nothing to post")
    return 0


if __name__ == "__main__":
    sys.exit(main())
