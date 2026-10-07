#!/usr/bin/env python3
"""KO social publish — post the day's reel + story to the Facebook page and Instagram.

Runs AFTER the site build and AFTER the daily email. PRIMARY path (2026-09-29):
the Graph API via scripts/social_api.py (reel + story to Facebook and Instagram,
each leg idempotent). The Meta Business Suite UI below is the BACKUP, used only
for legs the API could not publish. (The old "API posts withheld" problem was the
Meta app sitting Unpublished; the token now carries instagram_content_publish.)

Pipeline order (deliberate):
    site build (ko_publish 07:00) -> email (bb_email_watchdog 08:10-08:32)
    -> THIS (08:45, ko_social_publish.py)

What it does, deterministically (no LLM):
  1. Gate on the same report gate the email/kit use (scripts/post_facebook.py).
  2. Build brief.json, the dispatch soundtrack (bed ALWAYS mixed under, clips
     picked by rule, most-interesting story first) and the 1080x1920 reel.
  3. Publish the reel to the page + Instagram, auto captions OFF (radio ASR is
     unusable and would ship as visible garbage).
  4. Publish the same MP4 as a Facebook story + Instagram story via the Story
     composer (the only reliable Instagram-story path).
  5. Verify from the Business Suite lists, not from the composer toast.

Idempotent: work/social/<date>.json records what is already published, so a retry
after a timeout never double-posts. Refuses to publish anything when the audio
pick or the render fails.

Usage
-----
  python publish_social.py [--date YYYY-MM-DD] [--verify-only] [--dry-run] [--force]

Exit: 0 = published/verified, 1 = failure, 3 = gate blocked (nothing published).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import post_facebook as PF  # noqa: E402

# Advisory Jev screener (see jev_decide.py). Deliberately optional: if it cannot be
# imported, or the key/network/model is unavailable, the pipeline must behave exactly
# as it did before it existed. Nothing it returns can block or authorise a publish.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import jev_decide as JEV  # noqa: E402
except Exception:  # noqa: BLE001
    JEV = None

PY = Path(sys.executable)
CDP = "http://127.0.0.1:9222"
# Hard floor (operator rule, 2026-09-20). A 17 s reel published once because
# nothing checked the artifact the composer received; the floor now lives on
# the publish path, not only in the pacing math.
MIN_REEL = 25.0
PAGE_ID = "1298315170026203"
BIZ_ID = "1825373238619760"
# The reel wizard lives at reels_composer, NOT at /latest/composer. /latest/composer
# opens the POST composer ("Create post", with an ad-post interstitial), where
# composer_state() correctly reports 'other' and the flow then falls into the
# fresh-tab reset and hangs. Verified live 2026-09-19 by clicking "Create reel" on
# Business Suite home and reading the resulting URL and composer state.
COMPOSER = f"https://business.facebook.com/latest/reels_composer/?asset_id={PAGE_ID}&business_id={BIZ_ID}"
STORY_COMPOSER = f"https://business.facebook.com/latest/story_composer/?asset_id={PAGE_ID}&business_id={BIZ_ID}"
CONTENT = f"https://business.facebook.com/latest/content?asset_id={PAGE_ID}&business_id={BIZ_ID}"
STATE_DIR = ROOT / "work" / "social"


def _head_of(caption: str, n: int = 40) -> str:
    """Match key for both legs: leading caption text, whitespace collapsed."""
    return " ".join(caption.split())[:n]


def fb_post_live(head: str, hours: int = 36) -> dict:
    """Ground truth for the FACEBOOK reel leg: read the Page's own feed.

    The Business Suite content list lags for minutes and its badges lie (on
    2026-09-22 the run reported `reel_crossposted_to_instagram=False` and
    PARTIAL while the reel was public on both platforms). The feed is
    authoritative about what the Page published, so it decides whether the leg
    needs publishing at all. A leg that is already live is NEVER republished:
    operator rule, 2026-09-22, "don't post again if you've already posted today".
    """
    import urllib.parse
    import urllib.request

    try:
        tok = PF.get_token()
    except SystemExit as e:  # noqa: BLE001
        return {"ok": False, "reason": f"no page token ({e})"}
    q = urllib.parse.urlencode({"fields": "id,message,created_time,permalink_url",
                                "limit": "25", "access_token": tok})
    try:
        with urllib.request.urlopen(
                f"https://graph.facebook.com/v26.0/{PAGE_ID}/posts?{q}", timeout=30) as r:
            data = json.load(r).get("data", [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"graph error: {str(e)[:80]}"}
    key = head[:24]
    now = datetime.now(ZoneInfo("UTC"))
    for p in data:
        msg = " ".join((p.get("message") or "").split())
        if key and key in msg:
            ct = p.get("created_time") or ""
            try:
                age = (now - datetime.fromisoformat(
                    ct.replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:  # noqa: BLE001
                age = -1.0
            if 0 <= age <= hours:
                return {"ok": True, "permalink": p.get("permalink_url"),
                        "created_time": ct, "age_h": round(age, 1)}
            return {"ok": False, "stale_hours": round(age, 1),
                    "permalink": p.get("permalink_url"),
                    "reason": f"matching post is {round(age, 1)}h old"}
    return {"ok": False,
            "reason": f"none of the last {len(data)} feed posts match the caption head"}


def log(msg: str) -> None:
    print(f"[social] {msg}", flush=True)


def today_la() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)


# --------------------------------------------------------------------------- #
# assets
# --------------------------------------------------------------------------- #
def build_assets(date: str) -> tuple[Path, Path, str] | None:
    """Gate + build reel/soundtrack. Returns (reel, brief_json, caption) or None."""
    # The CI build (daily.yml) writes data/briefs/<date>.json and pushes it at
    # ~07:07-07:11 PT, AFTER this machine's last pull (the 07:00 ko_publish job).
    # Nothing else fetches origin before the 08:45 slot, so the gate below read a
    # stale working copy and blocked with "brief body missing" on 2026-10-02 and
    # 2026-10-03. Overlay origin/main's data dirs first (the same fetch + sparse
    # checkout the Facebook photo path uses), then gate.
    try:
        PF._git_pull_latest()
    except Exception as exc:  # noqa: BLE001
        log(f"WARN: git fetch/overlay failed ({exc}) - gating on local data")
    gate = PF.gate_check(date)
    if gate is None:
        log(f"GATE BLOCKED - report for {date} is not complete/ready")
        return None
    brief, overnight = gate

    out = STATE_DIR / date
    out.mkdir(parents=True, exist_ok=True)
    brief_json = out / "brief.json"
    rc = run([PY, ROOT / "scripts" / "make_brief_json.py", "--date", date,
              "--out", brief_json])
    if rc.returncode != 0 or not brief_json.exists():
        log(f"FATAL brief.json failed: {rc.stderr.strip()[:200]}")
        return None

    soundtrack = out / "soundtrack.mp3"
    if not soundtrack.exists():
        rc = run([PY, ROOT / "scripts" / "brief_reel" / "make_dispatch_audio.py",
                  "--date", date, "--brief", brief_json, "--out", soundtrack], timeout=1800)
        log(rc.stdout.strip()[-300:] or rc.stderr.strip()[-300:])
    if not soundtrack.exists():
        log("FATAL dispatch soundtrack failed — refusing to publish a reel "
            "without the agreed audio (bed + dispatch clips)")
        return None

    # The reel's scenes must match the dispatch clips that actually made it into
    # the soundtrack; otherwise the picture drifts from the audio and the reel
    # runs short (a 3-story brief with 2 clips rendered 17 s of 4 s scenes).
    _prune_brief_to_audio(brief_json, soundtrack)

    reel = out / "reel.mp4"
    rebuild = True
    sound_dur = _duration(soundtrack)
    if reel.exists() and reel.stat().st_size > 100_000:
        rebuild = reel.stat().st_mtime < soundtrack.stat().st_mtime
        # Length is the contract: a reel is about 30 s, never under 25.
        if abs(_duration(reel) - sound_dur) > 1.0:
            rebuild = True
    if rebuild:
        dur = sound_dur
        rc = run([PY, ROOT / "scripts" / "brief_reel" / "render_reel.py", brief_json,
                  "--out", reel.with_suffix(""), "--music", soundtrack,
                  "--duration", str(dur)], timeout=1800)
        if rc.returncode != 0 or not reel.exists() or reel.stat().st_size <= 100_000:
            log(f"FATAL reel render failed: {rc.stderr.strip()[:300]}")
            return None
        log(f"rendered {reel.name} ({reel.stat().st_size // 1024} KB, {dur}s)")
    else:
        log(f"reusing {reel.name}")

    reel_dur = _duration(reel)
    if reel_dur < MIN_REEL:
        log(f"FATAL reel is {reel_dur}s, under the {MIN_REEL:.0f}s floor — "
            f"refusing to publish. Check the dispatch clip count and the story "
            f"count in {brief_json.name}.")
        return None

    caption = PF.compose_post(date, brief, overnight)
    return reel, brief_json, caption


def _prune_brief_to_audio(brief_json: Path, soundtrack: Path) -> None:
    """Drop brief stories that produced no verified dispatch clip.

    The render splits the duration evenly over the stories it is given, and the
    soundtrack spends fixed seconds per clip, so any story without a clip shows
    a scene with no audio and compresses every scene. Keep them in step.
    """
    try:
        audit = json.loads(
            soundtrack.with_suffix(".json").read_text(encoding="utf-8"))
        idx = audit.get("reel_indices")
        cfg = json.loads(brief_json.read_text(encoding="utf-8"))
        if not isinstance(idx, list) or not idx:
            return
        keep = [cfg["stories"][i] for i in idx if 0 <= i < len(cfg["stories"])]
        if not keep or len(keep) == len(cfg["stories"]):
            return
        cfg["stories"] = keep
        brief_json.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                              encoding="utf-8")
        log(f"brief.json limited to the {len(keep)} stories that carry dispatch audio")
    except Exception as exc:  # noqa: BLE001
        log(f"WARN could not align brief.json with the soundtrack: {exc}")


def _duration(path: Path) -> int:
    try:
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], timeout=60)
        return max(4, int(round(float(r.stdout.strip()))))
    except Exception:  # noqa: BLE001
        return 23


# --------------------------------------------------------------------------- #
# browser helpers
# --------------------------------------------------------------------------- #
def click_named(page, names: list[str], min_y: int = 0, bottom_most: bool = True,
                quiet: bool = False) -> bool:
    """Click by coordinates: role locators get swallowed in these composers."""
    box = page.evaluate(
        """([names, minY, bottomMost]) => {
            const hits = [];
            for (const e of document.querySelectorAll('div[role=button],div[role=tab],button,a,[role=tab]')) {
              const t = (e.innerText || '').trim();
              if (names.includes(t)) {
                const r = e.getBoundingClientRect();
                const off = e.getAttribute('aria-disabled') === 'true' || e.disabled === true;
                if (r.width > 0 && r.height > 0 && !off && r.y >= minY) {
                  hits.push({t, x: r.x + r.width / 2, y: r.y + r.height / 2});
                }
              }
            }
            if (!hits.length) return null;
            hits.sort((a, b) => bottomMost ? b.y - a.y : a.y - b.y);
            return hits[0];
        }""", [names, min_y, bottom_most])
    if not box:
        return False
    page.mouse.click(box["x"], box["y"])
    return True


def attach(page, path: Path, label: str = "Add photo/video") -> bool:
    with page.expect_file_chooser(timeout=60000) as fc:
        if not click_named(page, [label], bottom_most=False):
            return False
    fc.value.set_files(str(path))
    return True


def fill_caption(page, caption: str) -> int:
    """Type the caption into the composer's contenteditable. Returns its length.

    A JS focus() does NOT stick in the FB editor (draft.js re-focuses its own
    node), so the only reliable way in is a real mouse click inside the box.
    """
    box = page.evaluate("""() => {
        const el = document.querySelector("div[contenteditable='true']");
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width < 60 || r.height < 12) return null;
        return {x: Math.round(r.x + 30), y: Math.round(r.y + r.height / 2)};
    }""")
    if not box:
        return 0
    for attempt in (1, 2):
        page.mouse.click(box["x"], box["y"])
        page.wait_for_timeout(500)
        pre = page.evaluate("""() => {
            const el = document.querySelector("div[contenteditable='true']");
            return el ? (el.innerText || '').length : 0;
        }""")
        if pre > 5:                           # a resumed draft already had text
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(400)
        page.keyboard.insert_text(caption)
        page.wait_for_timeout(1500)
        n = page.evaluate("""() => {
            const el = document.querySelector("div[contenteditable='true']");
            return el ? (el.innerText || '').length : 0;
        }""")
        if n >= max(12, int(len(caption) * 0.8)):
            return n
        if attempt == 1:                      # clear and retry once
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(400)
    return n


def captions_off(page, attempts: int = 4) -> bool:
    """Uncheck auto captions on the Share step. HARD RULE: radio ASR captions never ship.

    Two traps, both seen live 2026-09-19:
      * The control only exists on the Share step, so this must run AFTER the wizard
        reaches it. Running it earlier silently no-ops and then reports success.
      * The tick is drawn by CSS on a styled div; the real input is zero-sized, so a
        checkbox query matches nothing and a size filter discards it. The old check
        therefore read "off" while the box was visibly ticked.

    So: read the row's own text for state, and click the box at the row's left edge.
    """
    probe = """() => {
        const cands = [...document.querySelectorAll('div')].filter(d => {
            if (!/^Closed captions/.test((d.innerText || '').trim())) return false;
            const r = d.getBoundingClientRect();
            return r.width > 300 && r.height > 20 && r.height < 90;
        });
        if (!cands.length) return null;
        // smallest such div is the row itself, not the enclosing section
        cands.sort((a, b) => {
            const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return ra.width * ra.height - rb.width * rb.height;
        });
        const d = cands[0], r = d.getBoundingClientRect(), t = d.innerText || '';
        return {
            on: /Auto-generated captions on/i.test(t),
            off_hint: /Apply closed captions/i.test(t),
            x: Math.round(r.x + 16), y: Math.round(r.y + r.height / 2),
            text: t.replace(/\\n+/g, ' | ').slice(0, 140),
        };
    }"""
    st = page.evaluate(probe)
    if not st:
        log("captions: Closed captions row not found on this step")
        return False
    for i in range(attempts):
        if not st["on"]:
            log(f"captions: off (row shows '{st['text']}')")
            return True
        log(f"captions: on, clicking box at ({st['x']},{st['y']}) attempt {i + 1}")
        page.mouse.click(st["x"], st["y"])
        page.wait_for_timeout(1800)
        st = page.evaluate(probe) or {"on": True, "text": "row vanished"}
    log(f"captions: STILL ON after {attempts} clicks (row shows '{st['text']}')")
    return False


def advance_to_share(page, timeout_s: int = 240, step_ms: int = 4000) -> bool:
    """Click the footer Next until the Share step appears.

    Blind clicks are not reliable here: the Edit step mounts asynchronously after
    the upload, so a Next click fired too early finds no button and the wizard
    stalls on Edit, while a passive poll afterwards waits forever. Click, verify,
    repeat.
    """
    share_now = "() => document.body.innerText.includes('Share now')"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.evaluate(share_now):
            return True
        click_named(page, ["Next"])
        page.wait_for_timeout(step_ms)
    return page.evaluate(share_now)


def wait_until(page, expr: str, timeout_s: int = 300, step_ms: int = 4000) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.evaluate(expr):
                return True
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(step_ms)
    return False


# --------------------------------------------------------------------------- #
# publish steps
# --------------------------------------------------------------------------- #
def _story_dialog(page):
    """Return the open story dialog, if any, and which way it is switching."""
    return page.evaluate("""() => {
        for (const d of document.querySelectorAll('div[role=dialog]')) {
            const r = d.getBoundingClientRect();
            if (r.width < 200) continue;
            const t = (d.innerText || '');
            const flat = t.split(String.fromCharCode(10)).join(' | ').slice(0, 200);
            return {text: flat, turning_on: /Always share stories/i.test(t)};
        }
        return null;
    }""")


def _dismiss_story_dialog(page) -> None:
    """Resolve the story dialog. Never leave it open: it covers the footer."""
    d = _story_dialog(page)
    if not d:
        return
    if d["turning_on"]:
        # This dialog defaults to "Always share stories": confirming turns story
        # sharing on for EVERY future post, permanently. Back out instead.
        log("story share: got the 'Always share stories' dialog - cancelling it")
        click_named(page, ["Cancel"], bottom_most=False, quiet=True)
    else:
        # Default radio is "Don't share this post", which is what we want.
        log("story share: got the 'Stop sharing' dialog - confirming it")
        click_named(page, ["Confirm"], bottom_most=False, quiet=True)
    page.wait_for_timeout(1500)
    if _story_dialog(page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)
    if _story_dialog(page):
        log("story share: WARNING a dialog is still open - the Share click may miss")


def story_share_off(page) -> bool:
    """Turn the composer's own "Share to ... story" toggle OFF, and VERIFY it.

    The story composer already publishes to Facebook story and Instagram story, so
    leaving this one on puts the same reel in the story twice.

    Returns True only when the toggle is OFF. The old version returned "was it
    already off", which read as "on" everywhere it was consumed, and it confirmed
    whichever dialog appeared without reading it.
    """
    sw = page.evaluate("""() => {
        const out = [];
        for (const e of document.querySelectorAll('div[role=switch],input[type=checkbox],div[role=checkbox]')) {
            let t = (e.getAttribute('aria-label') || '');
            let n = e;
            for (let i = 0; i < 3 && n; i++) { t += ' ' + (n.innerText || ''); n = n.parentElement; }
            if (!/story/i.test(t)) continue;
            const r = e.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) continue;
            out.push({on: (e.getAttribute('aria-checked') === 'true') || e.checked === true,
                      x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)});
        }
        return out;
    }""")
    on = [s for s in sw if s["on"]]
    if not on:
        _dismiss_story_dialog(page)
        return True
    page.mouse.click(on[0]["x"], on[0]["y"])
    page.wait_for_timeout(2500)
    _dismiss_story_dialog(page)
    after = page.evaluate("""() => {
        for (const e of document.querySelectorAll('div[role=switch],input[type=checkbox],div[role=checkbox]')) {
            let t = (e.getAttribute('aria-label') || '');
            let n = e;
            for (let i = 0; i < 3 && n; i++) { t += ' ' + (n.innerText || ''); n = n.parentElement; }
            if (!/story/i.test(t)) continue;
            const r = e.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) continue;
            if ((e.getAttribute('aria-checked') === 'true') || e.checked === true) return true;
        }
        return false;
    }""")
    if after:
        log("story share: toggle STILL ON after clicking it")
    return not after


def get_page(browser):
    """First page of the default context, creating one when the browser is empty."""
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.bring_to_front()
    # Bounded waits: if the composer wedges the CDP socket, every call must raise
    # instead of hanging, so the stage fails in minutes and the cron can retry.
    page.set_default_timeout(45000)
    page.set_default_navigation_timeout(60000)
    return page


def composer_state(page) -> str:
    """'create' | 'media' | 'share' for a real Create reel composer, else 'other'."""
    return page.evaluate("""() => {
        const t = document.body.innerText;
        if (!t.includes('Create reel')) return 'other';   // resumed post draft, etc.
        const hasBox = !!document.querySelector("div[contenteditable='true']");
        // The reel Create step shows its caption box BEFORE any media is attached,
        // so hasBox is not a media signal. The add control is: "Add Video" /
        // "Add Photos" in the reel wizard, "Add photo/video" in the story composer.
        const addRe = /^add (video|photos?|photo\\/video)$/i;
        const hasAdd = [...document.querySelectorAll('div[role=button],button,a')]
            .some(e => addRe.test((e.innerText || '').trim())
                       && e.getBoundingClientRect().width > 0);
        if (hasAdd) return 'create';
        if (hasBox && t.includes('Share now')) return 'share';
        if (hasBox) return 'media';
        return 'other';
    }""")


def discard_draft(page) -> bool:
    """Close/discard whatever the composer is showing, then reload a clean one."""
    for label in ("Discard", "Delete draft", "Close", "Cancel"):
        if click_named(page, [label], bottom_most=False, quiet=True):
            page.wait_for_timeout(2500)
            if click_named(page, ["Discard", "Delete", "Confirm"], bottom_most=False, quiet=True):
                page.wait_for_timeout(2500)
            break
    goto(page, COMPOSER)
    return wait_composer(page, timeout_s=60)


def goto(page, url: str, timeout_ms: int = 90000, settle_ms: int = 6000) -> None:
    """Navigate tolerantly: FB is a slow SPA and 'domcontentloaded' can time out."""
    try:
        page.goto(url, wait_until="commit", timeout=timeout_ms)
    except Exception:
        pass
    page.wait_for_timeout(settle_ms)


def wait_composer(page, timeout_s: int = 90) -> str:
    """Poll until the composer reports a known state (or give up with 'other')."""
    deadline = time.time() + timeout_s
    state = composer_state(page)
    while state == "other" and time.time() < deadline:
        page.wait_for_timeout(3000)
        state = composer_state(page)
    return state


# --------------------------------------------------------------------------- #
# advisory Jev screens (shadow mode: they never gate or authorise anything)
# --------------------------------------------------------------------------- #
def share_step_evidence(page, caption_len: int, caps_off: bool, story_off: bool) -> dict:
    """The observable facts of the Share step, for the advisory screen."""
    obs: dict = {}
    try:
        obs = page.evaluate("""() => {
            // No backslash escapes in these patterns on purpose: this block is a
            // Python string holding JS, and a stray escape once put a literal
            // newline inside a regex literal, which threw and silently emptied
            // the whole evidence bundle.
            const t = document.body.innerText;
            const flat = t.split(String.fromCharCode(10)).join(' | ');
            const seg = (re) => ((flat.match(re) || [''])[0]).slice(0, 200);
            return {
              share_to_section: seg(/Share to[^|]{0,160}/),
              reel_preview: seg(/[A-Za-z ]*reel preview/i),
              copyright_line: ((t.split(String.fromCharCode(10))
                                 .find(l => /copyright/i.test(l)) || '')).slice(0, 160),
              share_now_visible: t.includes('Share now'),
              says_captions_on: /auto-generated captions on/i.test(t),
              instagram_mentioned: /instagram/i.test(t),
            };
        }""")
    except Exception:  # noqa: BLE001
        obs = {}
    import re
    line = (obs.pop("copyright_line", "") or "").strip()
    obs["copyright_line"] = line
    # The Share step says "No copyright issues were found." when it is CLEAN, so a
    # naive /copyright issues/ match flags every good run (it did, live 2026-09-19).
    obs["copyright_warning"] = bool(line) and not re.search(r"no copyright issues", line, re.I)
    return {
        "step_reached": "share",
        "video_attached": True,
        "caption_chars": caption_len,
        "auto_captions_off": bool(caps_off),
        "reel_story_share": "off" if story_off else "STILL_ON",
        **obs,
    }


def jev_screen_share_step(page, caption_len: int, caps_off: bool, story_off: bool) -> None:
    """Log Jev's read of the Share step. Advisory: the code above has already decided."""
    if JEV is None:
        return
    ev = share_step_evidence(page, caption_len, caps_off, story_off)
    r = JEV.screen_publish_evidence(ev)
    if not r.get("ok"):
        log(f"jev screen: unavailable ({r.get('why')})")
        return
    ans = (r.get("answers") or {}).get("verdict") or {}
    choice, conf = ans.get("choice"), ans.get("confidence")
    log(f"jev screen: {choice} (conf {conf}, {r.get('ms')}ms)")
    if choice != "proceed":
        log(f"jev screen DISSENT: says {choice}, code says proceed - see jev-shadow.jsonl")


def jev_triage_failure(res: dict, state: dict) -> None:
    """Classify a failed run for the report and the retry policy. Advisory."""
    if JEV is None:
        return
    r = JEV.triage_failure({"reason": res.get("why"), "publish_result": res,
                            "date": state.get("date")})
    if not r.get("ok"):
        log(f"jev triage: unavailable ({r.get('why')})")
        return
    ans = (r.get("answers") or {}).get("category") or {}
    log(f"jev triage: {ans.get('choice')} (conf {ans.get('confidence')})")
    state["jev"] = {"triage": ans.get("choice"),
                    "confidence": ans.get("confidence"),
                    "model": r.get("model")}


def publish_reel(page, reel: Path, caption: str, dry_run: bool = False) -> dict:
    dur = _duration(reel)
    if dur < MIN_REEL:
        log(f"reel publish REFUSED: {reel.name} is {dur}s, under the {MIN_REEL:.0f}s floor")
        return {"ok": False, "why": f"reel under {MIN_REEL:.0f}s ({dur}s)"}
    goto(page, COMPOSER)
    click_named(page, ["Done"], bottom_most=False)          # "include more media" popup
    page.wait_for_timeout(1500)

    # Business Suite keeps composer drafts, so a previous run can leave the wizard
    # mid-flow (or with the media already attached). Walk back to a known state
    # instead of clicking blindly into a resumed draft.
    state = wait_composer(page)
    for _ in range(3):
        if state in ("create", "media", "share"):
            break
        click_named(page, ["Previous", "Back"], bottom_most=False)
        page.wait_for_timeout(3000)
        state = composer_state(page)
    if state == "other":
        # A REUSED tab can resume a stale composer mode/draft; a fresh tab is the
        # only reliable reset (losing a draft is fine, we re-enter the caption).
        page = page.context.new_page()
        page.bring_to_front()
        goto(page, COMPOSER)
        click_named(page, ["Close"], bottom_most=False, quiet=True)
        page.wait_for_timeout(1500)
        state = wait_composer(page, timeout_s=60)
    if state == "other":
        state = discard_draft(page)             # clear a resumed draft, reload clean
    if state == "share":                        # already on the last step of a draft
        state = discard_draft(page)
    if state == "other":
        return {"ok": False, "why": "composer is not a clean Create reel step"}
    if state == "share":
        return {"ok": False, "why": "composer stuck on a draft Share step"}

    if state == "create":
        # The reel wizard splits this control in two ("Add Video" / "Add Photos");
        # only the story composer labels it "Add photo/video".
        if not attach(page, reel, label="Add Video"):
            return {"ok": False, "why": "no Add Video control"}
        state = "media"

    if not wait_until(page, """() => !!document.querySelector("div[contenteditable='true']")""",
                      timeout_s=420):
        return {"ok": False, "why": "composer never became ready after upload"}

    n = fill_caption(page, caption)
    if n < 40:
        return {"ok": False, "why": f"caption did not land (len={n})"}

    if not advance_to_share(page):
        return {"ok": False, "why": "never reached the Share step"}

    # The "Closed captions" control only exists on the Share step. Refuse to
    # publish rather than ship auto-generated captions over radio audio.
    cap_off = captions_off(page)
    if not cap_off:
        return {"ok": False, "why": "auto captions still ON - refusing to publish"}

    story_off = story_share_off(page)          # the story step handles the story

    jev_screen_share_step(page, n, cap_off, story_off)

    if dry_run:
        shot = STATE_DIR / "dryrun-share-step.png"
        try:
            page.screenshot(path=str(shot))
        except Exception:
            pass
        return {"ok": True, "dry_run": True, "reached_share_step": True, "caps_off": cap_off,
                "story_share_off": story_off, "screenshot": str(shot),
                "why": "stopped before the Share click"}

    if not click_named(page, ["Share"], min_y=600):
        return {"ok": False, "why": "footer Share button not found"}

    left = wait_until(page, """() => !document.body.innerText.includes('Copyright issues')
                               || document.body.innerText.includes('is being published')""",
                      timeout_s=240)
    click_named(page, ["Maybe later"], bottom_most=False)   # boost upsell
    page.wait_for_timeout(3000)
    page.screenshot(path=str(STATE_DIR / "reel-published.png"))
    return {"ok": left, "captions_off": cap_off, "caption_len": n}


def publish_story(page, reel: Path) -> dict:
    goto(page, STORY_COMPOSER)
    if not attach(page, reel):
        return {"ok": False, "why": "no Add photo/video control"}
    armed = wait_until(page, """() => {
        for (const e of document.querySelectorAll('div[role=button],button')) {
          if ((e.innerText || '').trim() === 'Share' &&
              e.getAttribute('aria-disabled') !== 'true') {
            const r = e.getBoundingClientRect();
            if (r.width > 0 && r.y > 600) return true;
          }
        }
        return false;
    }""", timeout_s=420)
    if not armed:
        return {"ok": False, "why": "story Share never armed (processing stuck)"}
    if not click_named(page, ["Share"], min_y=600):
        return {"ok": False, "why": "story footer Share not found"}
    seen = wait_until(page, """() => document.body.innerText.includes('is being published')""",
                      timeout_s=180)
    page.screenshot(path=str(STATE_DIR / "story-submitted.png"))
    return {"ok": seen}


# --------------------------------------------------------------------------- #
# verification (never trust the composer toast)
# --------------------------------------------------------------------------- #
STORY_FRESH_MIN = 240  # a story from an earlier run must never pass as this run's


def newest_story_age_min(ages: list[str]) -> int | None:
    """Youngest age in minutes from verify's age strings (['17h', '5m'])."""
    best: int | None = None
    for a in ages or []:
        s = str(a)
        if not s or s[-1] not in ("m", "h"):
            continue  # only minutes/hours are trusted as ages
        try:
            n = int(s[:-1])
        except ValueError:
            continue
        mins = n * 60 if s.endswith("h") else n
        best = mins if best is None else min(best, mins)
    return best


def story_flags(v: dict) -> tuple[bool, bool, int | None, int | None]:
    """(facebook_fresh, instagram_fresh, fb_age_min, ig_age_min) from a verify() run."""
    fb_age = newest_story_age_min(v["story_ages"].get("Facebook", []))
    ig_age = newest_story_age_min(v["story_ages"].get("Instagram", []))
    return (fb_age is not None and fb_age <= STORY_FRESH_MIN,
            ig_age is not None and ig_age <= STORY_FRESH_MIN, fb_age, ig_age)


def verify(page, caption: str) -> dict:
    head = " ".join(caption.split())[:40]
    out: dict = {"head": head, "posts": None, "stories": {}, "story_ages": {}}

    goto(page, CONTENT, settle_ms=12000)
    click_named(page, ["Posts & reels"], bottom_most=False)
    page.wait_for_timeout(12000)
    # Take the SHORTEST row that still carries the caption: an outer container also
    # contains the text but hides the duration and the platform badges.
    out["posts"] = page.evaluate("""(head) => {
        const cands = [];
        for (const d of document.querySelectorAll('div')) {
          const t = (d.innerText || '');
          if (t.includes(head) && t.length < 900) {
            // Platform badges sit on an ancestor, so walk up a few levels.
            let labels = [];
            let node = d;
            for (let i = 0; i < 5 && node; i++) {
              const found = [...node.querySelectorAll('svg,img')]
                .map(s => s.getAttribute('aria-label') || s.getAttribute('alt') || '')
                .filter(Boolean);
              if (found.length) { labels = found; break; }
              node = node.parentElement;
            }
            const m = t.match(/(^|\\s)(\\d{1,2}:\\d{2})(\\s|$)/);
            cands.push({len: t.length, dur: m ? m[2] : null,
                        text: t.replace(/\\n+/g, ' | ').slice(0, 300),
                        labels: [...new Set(labels)].slice(0, 8)});
          }
        }
        // A reel row shows its duration; a plain post row does not. Prefer the
        // row that carries a duration, then the tightest match.
        cands.sort((a, b) => (a.dur ? 0 : 1) - (b.dur ? 0 : 1) || a.len - b.len);
        return cands[0] || null;
    }""", head)

    click_named(page, ["Stories"], bottom_most=False)
    page.wait_for_timeout(12000)
    cols = page.evaluate("""() => {
        const out = {};
        for (const d of document.querySelectorAll('div')) {
          const t = (d.innerText || '').trim();
          if ((t === 'Facebook' || t === 'Instagram') && !out[t]) {
            const par = d.closest('div[class]')?.parentElement;
            if (par) out[t] = par.innerText.slice(0, 400).replace(/\\n+/g, ' | ');
          }
        }
        return out;
    }""")
    out["stories"] = cols
    import re

    for plat, txt in cols.items():
        ages = re.findall(r"(\d+)\s*([mh])\b", txt or "")
        out["story_ages"][plat] = [f"{n}{u}" for n, u in ages]
    page.screenshot(path=str(STATE_DIR / "verified.png"))
    return out


def verify_safe(page, browser, caption: str, tries: int = 2) -> dict:
    """verify() that survives the Business Suite tab dying under it.

    The keeper closes that tab when its --hold expires and after a publish, so
    page.wait_for_timeout raised TargetClosedError INSIDE verify() and killed the
    process AFTER both legs had already published (2026-09-22: reel live on the
    Page feed, story up on both platforms, run RED, five days of the same). Reopen
    a page on the same CDP connection and try again. Only when every try dies,
    return an error dict: the caller reports UNVERIFIED instead of a traceback, so
    the exit code stays honest (not ok) without losing the run's output.
    """
    last = None
    for i in range(tries):
        try:
            return verify(page, caption)
        except Exception as e:  # noqa: BLE001 - the playwright error classes are not one base
            last = f"{type(e).__name__}: {e}".splitlines()[0]
            log(f"verify attempt {i + 1}/{tries} died: {last}")
            try:
                page = get_page(browser)
            except Exception as e2:  # noqa: BLE001
                last = f"{type(e2).__name__}: {e2}".splitlines()[0]
                break
    return {"head": " ".join(caption.split())[:40], "posts": None, "stories": {},
            "story_ages": {}, "error": last}


# --------------------------------------------------------------------------- #
def ensure_session(port: int = 9222, timeout_s: int = 240) -> str:
    """Make sure a healthy, signed-in Chrome is answering on the CDP port.

    The cron runs unattended, so the stage must not depend on anyone having started
    the keeper by hand. If no healthy session exists, launch the keeper DETACHED
    (Playwright closes its browser when the launcher exits, so a child keeper would
    die with this process and take every later attach down), then wait for it.
    """
    import subprocess

    here = Path(__file__).resolve().parent
    helper = str(here / "browser_session.py")

    def healthy() -> bool:
        try:
            return subprocess.run([sys.executable, helper, "status", "--port", str(port)],
                                  capture_output=True, timeout=120).returncode == 0
        except Exception:  # noqa: BLE001
            return False

    if healthy():
        return "reused"
    log(f"no healthy CDP session on {port} - starting the agent browser")
    flags = 0
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [sys.executable, helper, "start", "--hold", "7200", "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
    except Exception as e:  # noqa: BLE001
        log(f"could not launch the browser keeper: {e}")
        return "unavailable"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(5)
        if healthy():
            return "started"
    return "unavailable"


def api_publish(date: str, reel: Path, caption: str) -> dict:
    """Publish via the Graph API (scripts/social_api.py), Facebook leg of each
    pair first; the Instagram twin only when the Facebook one is up. Never
    raises: an API outage just hands every leg to the browser backup."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import social_api as SA
        token = PF.get_token()
        out: dict = {}
        for fb_leg, ig_leg in (("fb_reel", "ig_reel"), ("fb_story", "ig_story")):
            out.update(SA.publish_all(token, date, reel, caption, (fb_leg,)))
            if out[fb_leg].get("ok"):
                out.update(SA.publish_all(token, date, reel, caption, (ig_leg,)))
            else:
                out[ig_leg] = {"ok": False, "error": f"held: {fb_leg} failed, browser posts both"}
        return out
    except BaseException as e:  # noqa: BLE001 - incl. SystemExit from get_token
        log(f"API publish unavailable: {type(e).__name__}: {e}")
        return {}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify-caption", default=None,
                    help="caption text to look for during verification (default: the composed caption)")
    a = ap.parse_args(argv[1:])

    date = a.date or today_la()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{date}.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    assets = build_assets(date)
    if assets is None:
        return 3

    # PRIMARY and ONLY: Graph API (reel + story to Facebook and Instagram).
    # The Playwright fallback is retired (see the API-failure branch below). The old
    # pairing rule existed only because the browser posted to both platforms at once.
    if not a.verify_only and not a.dry_run:
        api = api_publish(date, assets[0], assets[2])
        state["api"] = api
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        if api and all(v.get("ok") for v in api.values()):
            print("SOCIAL_REPORT")
            print(f"date={date}")
            for leg, v in api.items():
                print(f"{leg}={'ok' if v.get('ok') else 'FAILED'} "
                      f"{'(already up) ' if v.get('skipped') else ''}{v.get('url', '')}")
            print("path=api (browser not needed)")
            print("verify=ok")
            state["done"] = True
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            return 0
        # NO browser fallback. This used to fall through to Playwright: the path with the
        # duplicate-story and one-sided-story history in its own comments, and the one no
        # test can exercise without posting for real. The retry slot re-runs THIS API path
        # and social_api.publish_all skips legs that are already live, so a transient
        # failure is retried without a second posting engine.
        bad = ", ".join(k for k, v in (api or {}).items() if not v.get("ok"))
        print("SOCIAL_REPORT")
        print(f"date={date}")
        for leg, v in (api or {}).items():
            print(f"{leg}=FAILED {v.get('url', '')} {v.get('error', '')}".rstrip())
        print("path=api")
        print("verify=failed")
        log(f"API failed for legs: {bad or '(none reported ok)'} - browser fallback retired, "
            "the retry slot re-runs the API")
        return 5

    s = ensure_session()
    log(f"browser session: {s}")
    if s == "unavailable":
        log("no usable CDP session - cannot publish or verify")
        return 4
    reel, brief_json, caption = assets
    cap_sha = hashlib.sha256(caption.encode("utf-8")).hexdigest()[:16]

    head = _head_of(caption)
    if not a.verify_only:
        from playwright.sync_api import sync_playwright

        # PRE-FLIGHT (read-only), two sources for two reasons:
        #  * the Page feed is ground truth for the Facebook leg, and a leg that is
        #    already live is never republished (operator rule, 2026-09-22:
        #    "don't post again if you've already posted today");
        #  * the Business Suite story list is the only local record of story state,
        #    and the retry slot used to rewrite the story blindly (two stories nine
        #    minutes apart, seen live 2026-09-17).
        fb_pre = fb_post_live(head)
        log("preflight facebook reel: " + (
            f"LIVE {fb_pre.get('permalink')} ({fb_pre.get('age_h')}h old)"
            if fb_pre["ok"] else f"missing ({fb_pre.get('reason')})"))

        with sync_playwright() as pw:
            b = pw.chromium.connect_over_cdp(CDP, timeout=90000)
            page = get_page(b)
            pre = verify_safe(page, b, a.verify_caption or caption)
            story_fb_pre, story_ig_pre, fb_age_pre, ig_age_pre = story_flags(pre)
            log(f"preflight stories: facebook={story_fb_pre} ({fb_age_pre} min) "
                f"instagram={story_ig_pre} ({ig_age_pre} min)")

            story_done = story_fb_pre and story_ig_pre
            if fb_pre["ok"] and story_done and not a.force:
                log("nothing to publish: the reel is live on the feed and both "
                    "stories are up")
                state.update({"date": date, "cap_sha": cap_sha,
                              "preflight": {"facebook_reel": fb_pre,
                                            "story_fb_min": fb_age_pre,
                                            "story_ig_min": ig_age_pre},
                              "done": True})
                state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                return 0

            res: dict = {"ok": True, "skipped": "facebook reel already live"}
            if not fb_pre["ok"] or a.force:
                res = publish_reel(page, reel, caption, dry_run=a.dry_run)
                log(f"reel publish: {res}")
                if a.dry_run:
                    log("DRY RUN - stopped before the Share click; nothing published")
                    return 0
                if not res.get("ok"):
                    jev_triage_failure(res, state)
                    state.update({"date": date, "cap_sha": cap_sha, "reel": res,
                                  "preflight": {"facebook_reel": fb_pre}})
                    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                    return 1
            else:
                log("reel: skipped, it is already live on Facebook")

            if a.dry_run:
                log("DRY RUN - nothing published")
                return 0

            state = {"date": date, "cap_sha": cap_sha, "reel": res, "story": None,
                     "preflight": {"facebook_reel": fb_pre,
                                   "story_fb_min": fb_age_pre,
                                   "story_ig_min": ig_age_pre},
                     "published_at": datetime.now(
                         ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds")}
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

            if story_done:
                log("story: skipped, both platforms already have a fresh story")
            elif story_fb_pre or story_ig_pre:
                log("story: SKIPPED one-sided - the composer writes both platforms at "
                    "once, so republishing would duplicate the side that is up. Post "
                    "the missing side by hand.")
                state["story"] = {"ok": False, "why": "one-sided story, not republished"}
            else:
                st = publish_story(page, reel)
                log(f"story publish: {st}")
                state["story"] = st
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # verify - a just-published reel is still PROCESSING and does not appear in the
    # content list for several minutes, so a single pass reports a false negative
    # (seen live 2026-09-19: "not found" at 10:03, present with both platform badges
    # at 10:09, which made a successful day look like a failure in the report).
    # Re-check, but only when this run published; --verify-only stays a snapshot.
    attempts = 1 if a.verify_only else 5
    v = {}
    i = 0
    for i in range(attempts):
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                b = pw.chromium.connect_over_cdp(CDP, timeout=90000)
                page = get_page(b)
                v = verify_safe(page, b, a.verify_caption or caption)
        except Exception as e:  # noqa: BLE001 - a gone CDP connection is reported, not raised
            v = {"head": " ".join(caption.split())[:40], "posts": None, "stories": {},
                 "story_ages": {}, "error": f"{type(e).__name__}: {e}".splitlines()[0]}
            log(f"verify: could not reach the browser ({v['error']})")
        if v.get("posts") or v.get("error") or i == attempts - 1:
            # A dead page is not a slow content list: the 90s re-check would
            # repeat the same crash, and the retry slot re-verifies with a fresh
            # browser. Break and report UNVERIFIED.
            break
        log(f"verify: not in the content list yet (try {i + 1}/{attempts}) - "
            f"a fresh reel processes for a few minutes; re-checking in 90s")
        time.sleep(90)
    if i and not v.get("error"):
        log(f"verify: appeared on try {i + 1}")
    if v.get("error"):
        log(f"verify: page died mid-check ({v['error']}) - this run reports "
            "UNVERIFIED, not PARTIAL")

    fb_now = fb_post_live(head)
    state["verify"] = v
    state["verify_error"] = v.get("error")
    state["verified_at"] = datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(
        timespec="seconds")

    posts = v.get("posts") or {}
    labels = [str(x) for x in (posts.get("labels") or [])]
    story_fb, story_ig, fb_age, ig_age = story_flags(v)
    # The Facebook leg is ground truth (the Page feed). The Instagram leg has no
    # local source of truth: the agent browser holds no Instagram session, the page
    # token has no instagram_basic, and Instagram serves a login shell to this host
    # (all three checked 2026-09-22). So report it as assumed-by-crosspost: neither
    # verified nor failed.
    reel_fb = bool(fb_now.get("ok"))
    ok = reel_fb and story_fb and story_ig
    state["legs"] = {"facebook_reel": reel_fb,
                     "instagram_reel": "assumed via the page's Instagram crosspost",
                     "story_facebook": story_fb, "story_instagram": story_ig}
    state["done"] = ok
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print("SOCIAL_REPORT")
    print(f"date={date}")
    print(f"reel_facebook_live={reel_fb} permalink={fb_now.get('permalink')} "
          f"age_h={fb_now.get('age_h')}")
    print(f"reel_facebook_evidence={fb_now.get('reason') or 'page feed'}")
    print("reel_instagram=assumed (page crosspost; no local IG session or token)")
    print(f"reel_in_content_list={bool(posts)} platform_badges={labels}")
    print(f"posts_row={(posts.get('text') or 'not found')[:160]}")
    print(f"story_facebook_ages={v['story_ages'].get('Facebook', [])}")
    print(f"story_instagram_ages={v['story_ages'].get('Instagram', [])}")
    print(f"story_facebook_age_min={fb_age} fresh(max {STORY_FRESH_MIN})={story_fb}")
    print(f"story_instagram_age_min={ig_age} fresh(max {STORY_FRESH_MIN})={story_ig}")
    print(f"story_facebook={v['stories'].get('Facebook', '')[:100]}")
    print(f"story_instagram={v['stories'].get('Instagram', '')[:100]}")
    if v.get("error"):
        print(f"verify=UNVERIFIED (the content list page died mid-check: {v['error']})")
        print("verify_hint=the reel and story were both submitted; the 9:00 retry "
              "slot re-checks with a fresh browser")
    else:
        print(f"verify={'ok' if ok else 'PARTIAL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
