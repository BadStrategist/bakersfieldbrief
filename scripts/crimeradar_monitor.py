#!/usr/bin/env python3
"""CrimeRadar emulator monitor — independent severity signal for the Kern Overnight.

Reads the CrimeRadar app (package com.newsbreak.crimeradar) running in the local
Android emulator over adb, classifies every posting it surfaces, and flags the
HIGH-severity ones. This is a second PATH, not an independent source: the app
credits the same Broadcastify feed (14029) our own pipeline pulls, so both die
together if that feed does. What it adds is a second reading of the same audio:
an incident it shows and our /overnight/ report misses is a real coverage gap.

Why adb and not the UI: the emulator exposes the app over the android CLI
(uiautomator + screencap + input), so the whole monitor runs headless and can be
driven from a cron job with no window focus and no screen scraping.

Requires: an emulator device online (`adb devices`) with CrimeRadar installed.

Usage:
  python scripts/crimeradar_monitor.py --once            # one poll, print hits
  python scripts/crimeradar_monitor.py --once --json     # machine-readable
  python scripts/crimeradar_monitor.py --once --detail   # open new HIGH items
  python scripts/crimeradar_monitor.py --diff 2026-10-03 # vs incidents/<date>.json
  python scripts/crimeradar_monitor.py --watch --interval 300

Env: CR_ADB (adb path), CR_DEVICE (default emulator-5554),
     CR_DISCORD_WEBHOOK / DISCORD_WEBHOOK_URL to post alerts.

Exit codes: 0 ok, 1 verify/reel error, 2 device offline, 4 the app is on screen
but shows no cards (poll) or History has no row in the window (emit), 5 the
read path failed some other way, 6 emulator busy, 7 a system dialog covers the
screen, 8 the screen cannot be read (keyguard, black screen, another app on
top), 9 the app is not showing the Kern feed. Every alarm says what was on
screen; none guesses at a cause. An --emit also writes
work/crimeradar/emit_status_<date>.json on every exit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "kern_overnight"))
import merge_crimeradar as mc  # noqa: E402  (coverage + privacy rules live there)
OUT = ROOT / "work" / "crimeradar"
INCIDENTS = ROOT / "incidents"

ADB = os.environ.get("CR_ADB", r"C:\Users\tscac\Android\Sdk\platform-tools\adb.exe")
DEVICE = os.environ.get("CR_DEVICE", "emulator-5554")
PKG = "com.newsbreak.crimeradar"

# ------------------------------------------------------------------ severity
# CrimeRadar's own Alert Categories (verified in the app: Me -> Alert Settings ->
# Alert Categories), mapped to a tier. The app publishes no per-item severity
# field, so the category is the only first-class classifier; titles escalate.
TIER = {
    # T1 — life threat / active violence / fire. Must be visible in the report.
    "Fatality Report": 1,
    "Assault Report": 1,
    "Weapons": 1,
    "Robbery Report": 1,
    "Fire": 1,
    # T2 — serious, person at risk or a major disruption.
    "Missing Person": 2,
    "Domestic Dispute": 2,
    "Sex-Related Incident": 2,
    "Medical Emergency": 2,
    "Traffic": 2,
    "Stolen Vehicle": 2,
    # T3 — everything else the app can surface.
    "Disturbance": 3, "Fraud Report": 3, "Other Incidents": 3,
    "Property Damage": 3, "Substance Use": 3, "Suspicious Activity": 3,
    "Theft Report": 3,
}

# Title keywords that force a tier regardless of category (dispatch posts a
# shooting under a variety of category labels).
ESCALATE = [
    (1, re.compile(r"\bshoot|shots fired|gunshot|stab|homicide|fatality|dead|doa|"
                   r"fatal|weapon|gun\b|knife|armed|hostage|barricade|kidnap|abduct|"
                   r"missing child|explosion|structure fire|working fire|"
                   r"air unit|helicopter|pursuit|\bchase\b|road rage|"
                   r"assault with", re.I)),
    # Big fires and severe medical count as serious; a trash fire, a car fire
    # or a "small" fire does not.
    (2, re.compile(r"\binjur|collision|\bcrash\b|rollover|vehicle vs|pedestrian|"
                   r"hit and run|seizure|overdose|cardiac|not breathing|trapped|"
                   r"wrong[- ]way|hazmat|\bcpr\b|unconscious|unresponsive|drown|"
                   r"(?<!small )(?:apartment|house|home|building|commercial|"
                   r"residential|garage|warehouse|brush|vegetation|grass|wildland)"
                   r"\s+fire|fully involved|multi[- ]alarm", re.I)),
]

CHROME = {
    "Bakersfield", "Nationwide", "NEW", "Share", "For You", "Recent", "Nearby",
    "Home", "Map", "Replay", "Notifications", "Me", "Alerts", "Activities",
    "Upgrade", "Dispatch Audio", "View on map", "Post",
}
AGE_RE = re.compile(r"^(\d+)\s*(minute|hour|day)s?\s+ago$", re.I)
PLACE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*mi\s*[·\-]\s*(.+)$")
TITLE_OK = re.compile(r"[A-Za-z]{3,}")   # a real card title contains a word

# ---------------------------------------------------------------- audio cache
# CrimeRadar plays dispatch audio through ExoPlayer with a disk cache at
# /sdcard/Android/data/<pkg>/cache/audio_cache/<bucket>/<uid>.<offset>.<ts>.v3.exo
# Those files are RAW upstream MP3 (verified: ID3v2.4 header, 48 kbps, no
# ExoPlayer framing). One clip = every span sharing a uid, ordered by offset,
# concatenated. Readable over adb with no root and no re-encode.
PKG = "com.newsbreak.crimeradar"
CACHE_DIR = f"/sdcard/Android/data/{PKG}/cache/audio_cache"
PLAY_BTN = (113, 570)     # white play circle on the detail player card
CARD_TAP_X = 264          # x used to open a feed card


# ---------------------------------------------------------------------- adb
def _run(cmd: list, timeout: int = 30, text: bool = True) -> subprocess.CompletedProcess:
    """subprocess.run that never inherits stdin.

    The Hermes cron runner starts scripts with an INVALID stdin handle, and on
    Windows a child spawned with capture_output then dies with WinError 6 before
    it runs. That made every scheduled poll report "device not online" while the
    emulator was up. stdin is therefore always DEVNULL.
    """
    kw = {"errors": "replace"} if text else {}
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=text, timeout=timeout, **kw)


def adb(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    touch_lock()
    return _run([ADB, "-s", DEVICE, *args], timeout=timeout)


def device_online() -> bool:
    try:
        out = _run([ADB, "devices"], timeout=15).stdout
    except Exception as e:  # noqa: BLE001
        # A failure to RUN adb is not evidence the device is offline: say so.
        print(f"[cr] adb could not be run: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    return any(re.match(rf"^{re.escape(DEVICE)}\s+device\s*$", line)
               for line in out.splitlines())


# ----------------------------------------------------------------------- lock
# One emulator, one screen: two runs driving it at once tap each other's pages.
# The lock is a file with a heartbeat (every adb call touches it), so a run that
# died cannot hold it: it goes stale after LOCK_STALE seconds of silence.
LOCK = OUT / "emulator.lock"
LOCK_STALE = 600
_HAVE_LOCK = False


def touch_lock() -> None:
    if _HAVE_LOCK:
        try:
            os.utime(LOCK, None)
        except OSError:
            pass


def acquire_lock(wait_s: int = 0) -> bool:
    global _HAVE_LOCK
    OUT.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait_s
    while True:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {dt.datetime.now().isoformat()}".encode())
            os.close(fd)
            _HAVE_LOCK = True
            return True
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime > LOCK_STALE:
                    LOCK.unlink()
                    continue
            except OSError:
                continue
        if time.time() >= deadline:
            return False
        time.sleep(5)


def release_lock() -> None:
    global _HAVE_LOCK
    if _HAVE_LOCK:
        _HAVE_LOCK = False
        try:
            LOCK.unlink()
        except OSError:
            pass


# --------------------------------------------------------------- screen guard
# A read that fails says WHAT was on screen. On 2026-10-06..09 three different
# faults (a System UI ANR dialog, a keyguard, the app set to Mendocino County)
# all surfaced as "the app UI has likely changed", which sent the diagnosis the
# wrong way for three days. Each now has its own exception and exit code.
class ScreenError(RuntimeError):
    """The screen is not one this run can use. `code` is the exit code."""
    code = 5


class SystemDialog(ScreenError):
    """An Android dialog (ANR, crash) owns the screen: every tap would hit it."""
    code = 7


class Unreadable(ScreenError):
    """No usable dump: keyguard, black screen, or another app on top."""
    code = 8


class WrongFeed(ScreenError):
    """The app is readable but is not showing the Kern feed."""
    code = 9


def on_screen(xml: str) -> dict:
    """What a dump actually shows: {package, title, texts}."""
    nodes = list(_nodes(xml))
    pkgs: dict[str, int] = {}
    for n in nodes:
        if n.get("package"):
            pkgs[n["package"]] = pkgs.get(n["package"], 0) + 1
    texts = [html.unescape(n["text"]) for n in nodes if n.get("text")]
    title = ""
    for rid in ("alertTitle", "toolbar_title"):
        n = _by_id(xml, rid)
        if n and n.get("text"):
            title = html.unescape(n["text"])
            break
    return {"package": max(pkgs, key=pkgs.get) if pkgs else "",
            "title": title or (texts[0] if texts else ""), "texts": texts[:6]}


def describe(screen: dict) -> str:
    return (f"package {screen['package'] or 'unknown'}, title \"{screen['title']}\", "
            f"text: {' | '.join(screen['texts']) or '(none)'}")


def system_dialog(xml: str) -> str | None:
    """The title of an Android ANR/crash dialog covering the screen, or None."""
    if not (_by_id(xml, "aerr_wait") or _by_id(xml, "aerr_close")
            or _by_id(xml, "aerr_restart")):
        return None
    return on_screen(xml)["title"] or "untitled system dialog"


def device_state() -> dict:
    """Foreground package and keyguard flag from the system itself, no UI dump."""
    out = {"package": "", "keyguard": None}
    try:
        m = re.search(r"topResumedActivity=ActivityRecord\{\S+ \S+ ([\w.]+)/",
                      adb("shell", "dumpsys", "activity", "activities").stdout or "")
        if m:
            out["package"] = m.group(1)
        m = re.search(r"isKeyguardShowing=(true|false)",
                      adb("shell", "dumpsys", "window").stdout or "")
        if m:
            out["keyguard"] = m.group(1) == "true"
    except Exception:  # noqa: BLE001
        pass
    return out


def alarm_text(e: Exception) -> str:
    """The alarm line for a failed read.

    uiautomator returns nothing at all on a locked or black screen, so for an
    unreadable one the system's own view (foreground package, keyguard) is added.
    """
    msg = str(e)
    if isinstance(e, Unreadable):
        st = device_state()
        kg = {True: "showing", False: "not showing"}.get(st["keyguard"], "unknown")
        msg += (f". The system reports foreground package "
                f"{st['package'] or 'unknown'}, keyguard {kg}")
    return msg


def dump_ui(tag: str = "cr", tries: int = 3) -> str:
    """uiautomator dump -> pull -> local XML text (Windows-safe destination).

    Raises SystemDialog when the dump is an Android ANR/crash dialog (callers
    tap right after a dump, and the tap would land on the dialog) and Unreadable
    when no dump can be had.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    remote = f"/sdcard/{tag}.xml"
    local = OUT / f"{tag}.xml"
    why = ""
    for attempt in range(tries):
        # Remove BOTH copies first. uiautomator fails routinely (no idle state
        # while audio plays), and the previous dump would otherwise still be on
        # the device and on disk: the caller would parse an old screen as if it
        # were live, and the zero-cards canary could never fire.
        adb("shell", "rm", "-f", remote)
        try:
            local.unlink()
        except FileNotFoundError:
            pass
        d = adb("shell", "uiautomator", "dump", remote)
        r = adb("pull", remote, str(local))
        if local.exists() and local.stat().st_size > 0:
            xml = local.read_text(encoding="utf-8", errors="replace")
            if "<hierarchy" in xml:
                dialog = system_dialog(xml)
                if dialog:
                    raise SystemDialog(f"a system dialog covers the screen: \"{dialog}\" "
                                       f"(package {on_screen(xml)['package']}); no tap was sent")
                return xml
        why = (d.stderr or d.stdout or r.stderr or r.stdout or "").strip()[:200]
        time.sleep(1.5)
    raise Unreadable(f"the screen cannot be read: uiautomator dump failed after "
                     f"{tries} tries ({why or 'no output'})")


def screencap(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    p = _run([ADB, "-s", DEVICE, "exec-out", "screencap", "-p"], text=False)
    dest.write_bytes(p.stdout)
    return dest


# --------------------------------------------------------------- overlay guard
# The CLI does NOT bypass ads, tips, or paywalls: they are real UI layers and a
# blind `input tap` lands on the overlay instead of the target. That failure is
# real, not theoretical: the first-run "Play Local Dispatch Feeds" tip ate the
# History tap and the sleep ran the sweep against the wrong screen.
#
# Rules:
#   * tips are tapped shut,
#   * a paywall sheet is backed out of, NEVER tapped (its buttons start a video
#     ad or claim the daily free minutes, a side effect an unattended job must
#     not cause),
#   * every caller dumps the UI again after this returns, so the next tap is
#     aimed at a screen that was just read back.
OVERLAY_TIP = ("Got it", "Not now", "No thanks", "Maybe later", "Dismiss")
OVERLAY_PAYWALL = ("Upgrade to Premium", "Watch an ad for more",
                   "Free for 5 minutes per day", "Start 5 free minutes",
                   "Ad will close in", "Sponsored")


def overlay_label(xml: str) -> str | None:
    """The label of a dismissible tip covering the screen, or None."""
    for m in _NODE.finditer(xml):
        if m.group(1) in OVERLAY_TIP:
            return m.group(1)
    return None


def dismiss_overlays(tag: str = "cro", rounds: int = 3) -> list[str]:
    """Clear tips, interstitials, and paywall sheets before any interaction.

    Returns the labels handled, newest last. Empty list = nothing was covering
    the screen.
    """
    handled: list[str] = []
    for _ in range(rounds):
        xml = dump_ui(tag)
        if any(t in xml for t in OVERLAY_PAYWALL):
            adb("shell", "input", "keyevent", "4")      # back out, never tap
            handled.append("BACK:paywall")
            time.sleep(2)
            continue
        label = overlay_label(xml)
        if not label:
            break
        for m in _NODE.finditer(xml):
            if m.group(1) == label:
                x1, y1, x2, y2 = map(int, m.groups()[1:])
                adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
                handled.append(label)
                time.sleep(1.5)
                break
    return handled


def normalise_feed() -> None:
    """Return the app to Home > Recent so a poll sees the same view every time."""
    adb("shell", "input", "keyevent", "4")  # back out of any detail/settings page
    time.sleep(1)
    dismiss_overlays()
    adb("shell", "input", "tap", "66", "1466")    # Home tab
    time.sleep(2)
    adb("shell", "input", "tap", "360", "279")    # Recent sub-tab
    time.sleep(2)


_NODE = re.compile(r'<node[^>]*?text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


# ------------------------------------------------------------ feed identity
# The app serves whatever region its own location picker holds. The guest GPS
# does not change it (verified 2026-10-09: every provider had last location=null
# while the app sat on a Mendocino County address and served Ukiah and Willits
# rows). So the region is read off the screen on every run and never assumed.
KERN_CHIP = "Bakersfield"


def home_feed(xml: str) -> tuple[str, bool]:
    """(location chip text, is it the selected tab) on the Home screen.

    The chip is one of two tabs, the other being Nationwide, so it only names
    the feed on screen while it is the selected one.
    """
    n = _by_id(xml, "txt_location_feed_tab")
    if not n:
        return "", False
    return html.unescape(n.get("text", "")), n.get("selected") == "true"


def replay_feeds(xml: str) -> list[dict]:
    """The feeds the Replay page offers, as printed: [{name, location}]."""
    out, name = [], ""
    for n in _nodes(xml):
        rid, text = n.get("resource-id", ""), html.unescape(n.get("text", ""))
        if rid.endswith(":id/title") and text:
            name = text
        elif rid.endswith(":id/location") and text:
            out.append({"name": name, "location": text})
    return out


def history_feed(xml: str, replay: list[dict]) -> dict:
    """The feed a History list belongs to, as printed: {name, location}.

    The list opens under its own hero card, which prints both. Scrolled, the
    hero collapses into a toolbar title that carries the name only; the location
    is then the one the Replay page printed under that same name.
    """
    name, loc = _by_id(xml, "top_feeds_hero_title"), _by_id(xml, "top_feeds_hero_location")
    if name and name.get("text"):
        return {"name": html.unescape(name["text"]),
                "location": html.unescape((loc or {}).get("text", ""))}
    bar = _by_id(xml, "toolbar_title")
    name = html.unescape(bar.get("text", "")) if bar else ""
    return {"name": name, "location": next(
        (f["location"] for f in replay if f["name"] == name), "")}


def parse_feed(xml: str) -> list[dict]:
    """Feed card list: [{category, age, title, place, cy}]."""
    items = []
    for m in _NODE.finditer(xml):
        text = m.group(1)
        if not text or text in CHROME:
            continue
        x1, y1, x2, y2 = map(int, m.groups()[1:])
        items.append({"t": text, "cy": (y1 + y2) // 2})
    cards, i = [], 0
    while i < len(items):
        if AGE_RE.match(items[i]["t"]):
            category = items[i - 1]["t"] if i > 0 else ""
            age = items[i]["t"]
            title = items[i + 1]["t"] if i + 1 < len(items) else ""
            place = ""
            if i + 2 < len(items):
                pm = PLACE_RE.match(items[i + 2]["t"])
                if pm:
                    place = pm.group(2)
            cards.append({"category": category, "age": age, "title": title,
                          "place": place, "cy": items[i]["cy"]})
            i += 3
        else:
            i += 1
    # The last card in the feed is clipped by the bottom nav bar: its title and
    # place are never rendered, so the parser reads the next stray node (a bare
    # digit) as the title. Require a real word. A dropped card is recovered by
    # the History sweep, which reads the app's own log instead of the feed.
    return [c for c in cards if TITLE_OK.search(c["title"])]


# ------------------------------------------------------------------ classify
def classify(card: dict) -> tuple[int, str]:
    tier = TIER.get(card["category"], 3)
    why = f"category:{card['category']}"
    for t, pat in ESCALATE:
        if t < tier and pat.search(card["title"]):
            tier, why = t, f"title:{pat.pattern[:28]}"
            break
    return tier, why


TIER_NAME = {1: "CRITICAL", 2: "HIGH", 3: "ROUTINE"}


def key_of(card: dict) -> str:
    return hashlib.sha1(f"{card['category']}|{card['title']}".encode()).hexdigest()[:12]


SEEN_TTL_H = 36          # a headline seen this long ago is new again
MAX_AUDIO_TRIES = 3      # polls that may try to capture one posting's clip


def load_seen() -> dict:
    """key -> {first, tries, done}.

    `done` means the clip was captured; a failed capture is retried on the next
    poll instead of being lost. Entries expire after SEEN_TTL_H so a headline
    that recurs on a later night ("Vehicle fire ...") is treated as new.
    """
    f = OUT / "seen.json"
    now = dt.datetime.now()
    try:
        raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception:
        raw = {}
    if isinstance(raw, list):       # legacy format: a bare list of keys
        raw = {k: {"first": now.isoformat(timespec="seconds"), "tries": 0,
                   "done": True} for k in raw}
    out: dict = {}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        try:
            first = dt.datetime.fromisoformat(v["first"])
        except Exception:
            continue
        if now - first <= dt.timedelta(hours=SEEN_TTL_H):
            out[k] = {"first": v["first"], "tries": int(v.get("tries", 0)),
                      "done": bool(v.get("done"))}
    return out


def _write_atomic(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dest)


def save_seen(seen: dict) -> None:
    _write_atomic(OUT / "seen.json", json.dumps(seen, sort_keys=True))


def relocate(card: dict) -> bool:
    """Refresh card['cy'] from a live dump of the feed.

    The feed moves between the poll's first read and a later tap (new postings
    push cards down), so a stored y would open a different incident. False when
    the card is no longer on screen.
    """
    for c in parse_feed(dump_ui("cr")):
        if key_of(c) == key_of(card):
            card["cy"] = c["cy"]
            return True
    return False


def _on_card(xml: str, card: dict) -> bool:
    """Is the open detail page the one for this card (its headline is shown)?"""
    head = (card.get("title") or "")[:24]
    return bool(head) and head in xml


# -------------------------------------------------------------- detail page
def open_detail(card: dict, stamp: str) -> dict:
    """Tap a card and harvest its detail page (transcript, time, address)."""
    dismiss_overlays()
    adb("shell", "input", "tap", "264", str(card["cy"]))
    time.sleep(4)
    xml = dump_ui("crd")
    if not _on_card(xml, card):
        adb("shell", "input", "keyevent", "4")
        time.sleep(2)
        raise RuntimeError("tap opened a different page than this card")
    texts = [m.group(1) for m in _NODE.finditer(xml) if m.group(1)]
    detail = {"raw": texts[:40]}
    for i, t in enumerate(texts):
        if t.startswith("Heard on:"):
            detail["agency"] = t.split(":", 1)[1].strip()
        if re.match(r"^[A-Z][a-z]{2} \d{1,2}, \d{4} · ", t):
            detail["timestamp"] = t
        if re.match(r"^\d{1,3}(\.\d+)? mi ", t) or re.search(r"Bakersfield, CA \d{5}", t):
            detail.setdefault("address", t)
    # transcript lines: prose on the page, minus boilerplate and the headline
    noise = ("Premium:", "Heard on:", "Not official report", "As discussed",
             "Dispatch Audio", "View on map", card.get("title", ""))
    prose = [t for t in texts
             if len(t) > 45 and not any(t.startswith(n) for n in noise if n)]
    detail["transcript"] = prose[:3]
    clip = [t for t in texts if re.match(r"^-\d{2}:\d{2}$", t)]
    detail["clip_seconds"] = clip[0] if clip else ""
    detail["screenshot"] = str(screencap(OUT / f"{stamp}_{key_of(card)}.png"))
    adb("shell", "input", "keyevent", "4")
    time.sleep(2)
    return detail


# ------------------------------------------------------------------- diff
# ------------------------------------------------------------- audio capture
CLIPS = OUT / "clips"
RAW_CACHE = OUT / "audio_cache"
CHUNK = 51200             # ExoPlayer span size: a final span at this size = more data existed


def _ffprobe() -> str:
    for c in ("ffprobe",):
        p = shutil.which(c)
        if p:
            return p
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/tools/ffmpeg-9.0.1-win32-x64/bin/ffprobe.exe"
    return str(p) if p.exists() else "ffprobe"


def probe_seconds(path: Path) -> float:
    """Clip duration via ffprobe, or 0.0 when it cannot read the file."""
    try:
        r = _run([_ffprobe(), "-v", "error", "-show_entries",
                  "format=duration", "-of", "default=nw=1:nk=1", str(path)])
        return round(float((r.stdout or "0").strip() or 0), 2)
    except Exception:  # noqa: BLE001
        return 0.0


def cache_snapshot() -> dict[str, int]:
    """{span filename: byte size} for every span currently on the device."""
    r = adb("shell", "ls", "-lR", CACHE_DIR, timeout=40)
    spans: dict[str, int] = {}
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if parts and parts[-1].endswith(".v3.exo"):
            try:
                spans[parts[-1]] = int(parts[4])
            except (ValueError, IndexError):
                continue
    return spans


def pull_cache() -> Path:
    """Mirror the ExoPlayer cache tree to disk (whole dir, one adb pull).

    The local copy is wiped first: `adb pull` into an existing tree leaves files
    from previous clips behind, and since rebuild_clips() walks everything it
    finds, stale spans would be rebuilt and attributed to the current posting.
    """
    if RAW_CACHE.exists():
        shutil.rmtree(RAW_CACHE)
    RAW_CACHE.mkdir(parents=True, exist_ok=True)
    adb("pull", CACHE_DIR, str(RAW_CACHE), timeout=180)
    return RAW_CACHE


def rebuild_clips(only_uids: set[str] | None = None) -> list[dict]:
    """Concatenate spans by uid -> playable MP3 per clip.

    Span names are <uid>.<startOffset>.<timestamp>.v3.exo and the buckets are
    unordered, so group across the whole tree and sort by offset. A partial uid
    (missing its first span, pruned by ExoPlayer) is reported, not silently cut.
    """
    CLIPS.mkdir(parents=True, exist_ok=True)
    root = RAW_CACHE
    tree = next((p for p in root.rglob("audio_cache") if p.is_dir()), root)
    spans: dict[str, list[tuple[int, Path]]] = {}
    for p in tree.rglob("*.v3.exo"):
        bits = p.name.split(".")
        if len(bits) < 3:
            continue
        try:
            spans.setdefault(bits[0], []).append((int(bits[1]), p))
        except ValueError:
            continue
    out = []
    for uid, lst in sorted(spans.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        if only_uids is not None and uid not in only_uids:
            continue
        lst.sort()
        partial = lst[0][0] != 0
        # ExoPlayer writes fixed 51200-byte span files. A final span sitting at
        # the cap means more of the stream MAY exist, but a clip that ends on a
        # chunk boundary looks the same, so this is advisory only. Completeness
        # is decided by duration against the player's own -MM:SS.
        final_span_at_cap = lst[-1][1].stat().st_size >= CHUNK
        dest = CLIPS / f"{uid}.mp3"
        with dest.open("wb") as fh:
            for _, p in lst:
                fh.write(p.read_bytes())
        out.append({"uid": uid, "path": str(dest), "bytes": dest.stat().st_size,
                    "spans": len(lst), "seconds": probe_seconds(dest),
                    "partial": partial, "final_span_at_cap": final_span_at_cap})
    return out


def _nodes(xml: str):
    """Yield every node's attributes as a dict (uiautomator attribute order varies)."""
    for m in re.finditer(r"<node\b[^>]*>", xml):
        yield dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(0)))


def _by_id(xml: str, rid: str) -> dict | None:
    for d in _nodes(xml):
        if d.get("resource-id", "").endswith(f":id/{rid}"):
            return d
    return None


def _center(node: dict | None) -> tuple[int, int] | None:
    if not node:
        return None
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def _mmss(text: str) -> float | None:
    m = re.match(r"^-?(\d+):(\d{2})$", (text or "").strip())
    return float(int(m.group(1)) * 60 + int(m.group(2))) if m else None


def player_state(xml: str) -> dict:
    """Play button centre, remaining and elapsed seconds from the detail player.

    Keyed off resource-ids, not fixed coordinates: the player card shifts down
    as the headline wraps onto more lines, so a hardcoded play position misses.
    """
    rem = _by_id(xml, "transcript_play_remaining_duration")
    cur = _by_id(xml, "transcript_play_current_duration")
    btn = _by_id(xml, "transcript_play_button_container")
    return {"btn": _center(btn),
            "remaining": _mmss(rem.get("text", "")) if rem else None,
            "elapsed": _mmss(cur.get("text", "")) if cur else None}


def capture_audio(card: dict, stamp: str, clip_secs: float = 0.0) -> dict:
    """Play one posting's clip through, then rebuild it from the cache.

    The cache is left intact (deleting the directory breaks the app's live
    ExoPlayer instance, which then stops caching entirely). Instead we take a
    span snapshot before and after: a clip never played before arrives as a new
    uid. If nothing new appears the clip was already cached, and we fall back to
    matching a cached clip by duration against the player's own countdown.
    """
    before = cache_snapshot()
    dismiss_overlays()
    adb("shell", "input", "tap", str(CARD_TAP_X), str(card["cy"]))
    time.sleep(4)
    xml = dump_ui("crd")
    if not _on_card(xml, card):
        adb("shell", "input", "keyevent", "4")
        return {"error": "tap opened a different page than this card"}
    st = player_state(xml)
    if not st["btn"] or st["remaining"] is None:
        adb("shell", "input", "keyevent", "4")
        return {"error": "detail player not found (card did not open?)"}
    if clip_secs <= 0:
        clip_secs = st["remaining"]
    # re-read the player after any dismissal: an interstitial must not eat the
    # play tap, and the button position is re-derived from the live tree.
    dismiss_overlays()
    st = player_state(dump_ui("crd"))
    if not st["btn"]:
        adb("shell", "input", "keyevent", "4")
        return {"error": "play button gone after overlay dismissal"}
    adb("shell", "input", "tap", str(st["btn"][0]), str(st["btn"][1]))

    # follow the player's own progress: playing through is what pulls the tail
    deadline = time.time() + clip_secs + 25.0
    last, stalled = st["elapsed"], 0
    while time.time() < deadline:
        time.sleep(2.5)
        try:
            st2 = player_state(dump_ui("crt", tries=1))
        except RuntimeError:
            continue    # no idle state while audio plays: not evidence of a stall
        if st2["remaining"] is not None and st2["remaining"] <= 0.5:
            last = st2["elapsed"]
            break
        if st2["elapsed"] is not None and st2["elapsed"] > (last or -1):
            last, stalled = st2["elapsed"], 0
        else:
            stalled += 1
            if stalled >= 3:        # 7.5s with no progress: playback never started
                break
    adb("shell", "input", "keyevent", "4")

    after = cache_snapshot()
    grew = sorted(set(after) - set(before))
    pull_cache()
    clips = rebuild_clips()
    if grew:
        uids = {n.split(".")[0] for n in grew}
        picked = [c for c in clips if c["uid"] in uids]
        source = "new-spans"
    else:
        # Already cached: identify it by duration, but ONLY when exactly one
        # cached clip fits. Two clips of similar length would otherwise both be
        # filed under this headline, and the wrong audio could reach a reel.
        fits = [c for c in clips
                if not c["partial"] and abs(c["seconds"] - clip_secs) <= 1.5]
        picked = fits if len(fits) == 1 else []
        source = "duration-match" if picked else f"ambiguous:{len(fits)}-cached-fit"
    complete = [c for c in picked
                if not c["partial"] and abs(c["seconds"] - clip_secs) <= 3.0]
    for c in complete:
        slug = re.sub(r"[^a-z0-9]+", "-", card["title"].lower())[:40].strip("-")
        named = CLIPS / f"{stamp}_{card.get('tier_name','')}_{slug}_{c['uid']}.mp3"
        Path(c["path"]).replace(named)
        c["path"] = str(named)
        c["expected_seconds"] = clip_secs
    return {"player_seconds": clip_secs, "elapsed_at_end": last,
            "matched_by": source, "spans_new": grew,
            "clips": complete, "rejected": len(clips) - len(complete)}


# --------------------------------------------------------------- history sweep
# The Replay tab's History list is the app's own incident log: one row per
# incident with an ABSOLUTE timestamp, and the free tier scrolls back a rolling
# ~24 h (verified: at 19:15 PT on Oct 3 the list reached Oct 2, 19:24). The date
# FILTER beyond "Today" is paywalled, so the scroll is the only free path back.
# This is what extends coverage past the radio feed's own hours (about
# 21:00 -> 05:30): the emulator carries the 19:00-21:00 and 05:30-07:00 ends of
# the night on its own.
HIST_ROW = re.compile(r"^(?:Today|Yesterday|[A-Z][a-z]{2} \d{1,2}, \d{4})\s+\d{1,2}:\d{2} [AP]M$")
HIST_CHROME = {"Most Recent", "Latest Incidents", "History", "Play All",
               "Incidents History", "Top Feeds For You", "Trending Alerts",
               "Bakersfield Police, Fire and EMS", "Kern, California"}


def tap_id(rid: str, tag: str = "crt", dy: int = 0) -> bool:
    """Tap the centre of the node with this resource-id. Returns False if absent."""
    n = _by_id(dump_ui(tag), rid)
    c = _center(n) if n else None
    if not c:
        return False
    adb("shell", "input", "tap", str(c[0]), str(c[1] + dy))
    return True


def goto_history() -> list[dict]:
    """Replay tab -> History list. Returns the feeds the Replay page named.

    The History control sits in the 'Latest Incidents' header row, which is only
    on screen after the Replay page is scrolled, so scroll until it appears.
    """
    adb("shell", "input", "keyevent", "4")
    time.sleep(1)
    adb("shell", "input", "tap", "360", "1430")     # Replay tab
    time.sleep(3)
    feeds, xml = [], ""
    for _ in range(6):
        dismiss_overlays()          # a tip or paywall sheet can appear at any time
        xml = dump_ui("crr")
        feeds += [f for f in replay_feeds(xml) if f not in feeds]
        node = _by_id(xml, "history_label")
        if node:
            c = _center(node)
            adb("shell", "input", "tap", str(c[0]), str(c[1]))
            time.sleep(3)
            return feeds
        adb("shell", "input", "swipe", "360", "1100", "360", "700", "300")
        time.sleep(2)
    raise RuntimeError("could not reach Replay > History. On screen: "
                       + describe(on_screen(xml)))


def parse_history(xml: str) -> list[dict]:
    """History rows in list order (newest first): [{when, title, cy}]."""
    items = []
    for m in _NODE.finditer(xml):
        t = m.group(1)
        if t:
            x1, y1, x2, y2 = map(int, m.groups()[1:])
            items.append({"t": t, "cy": (y1 + y2) // 2})
    rows = []
    for i, it in enumerate(items):
        if not HIST_ROW.match(it["t"]):
            continue
        title = ""
        for j in range(i + 1, min(i + 5, len(items))):
            cand = items[j]["t"]
            if HIST_ROW.match(cand) or cand in HIST_CHROME:
                break
            if len(cand) > 12:
                title = cand
                break
        if title:
            rows.append({"when": it["t"], "title": title, "cy": it["cy"]})
    return rows


# What the screen said the last History sweep was reading: {name, location}
# (see history_feed). Empty until a sweep has read them.
SWEPT_FEED: dict = {}


def history_sweep(max_scrolls: int = 60) -> list[dict]:
    """Scroll the History list to its floor and return every distinct row.

    Raises WrongFeed, before reading a row, unless the screen names the Kern
    feed. Raises when it reads nothing: an empty History is a broken read path,
    never a quiet day.
    """
    global SWEPT_FEED
    SWEPT_FEED = {}
    feeds = goto_history()
    seen, rows, dry, xml = set(), [], 0, ""
    for i in range(max_scrolls):
        xml = dump_ui("crh")
        if i == 0:
            SWEPT_FEED = history_feed(xml, feeds)
            if not mc.is_kern_feed(SWEPT_FEED):
                adb("shell", "input", "keyevent", "4")
                time.sleep(1)
                adb("shell", "input", "keyevent", "4")
                raise WrongFeed(
                    f"History is for \"{SWEPT_FEED['name'] or 'an unnamed feed'}\" "
                    f"({SWEPT_FEED['location'] or 'no location shown'}), not "
                    f"\"{mc.FEED_NAME}\" ({mc.FEED_LOCATION}). No row was read from it")
        new = 0
        for r in parse_history(xml):
            k = f"{r['when']}|{r['title']}"
            if k not in seen:
                seen.add(k)
                # Resolve "Today"/"Yesterday" NOW, while the label is true. A
                # sweep that straddles midnight otherwise dates its first rows
                # a day late.
                when = hist_dt(r["when"])
                r["at"] = when.isoformat(sep=" ") if when else ""
                rows.append(r)
                new += 1
        # One screen with nothing new is not the floor (a swipe that did not
        # register looks the same); two in a row is.
        dry = 0 if new else dry + 1
        if dry >= 2 and i > 2:
            break
        adb("shell", "input", "swipe", "360", "1200", "360", "350", "200")
        time.sleep(1)
    adb("shell", "input", "keyevent", "4")
    time.sleep(1)
    adb("shell", "input", "keyevent", "4")
    if not rows:
        raise RuntimeError("History parsed 0 rows. On screen at the last read: "
                           + describe(on_screen(xml)))
    return rows


def _at(day: dt.date, hh: str, mm: str, ap: str) -> dt.datetime:
    h = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
    return dt.datetime.combine(day, dt.time(h, int(mm)))


def hist_dt(when: str) -> dt.datetime | None:
    """Absolute datetime for a History row's 'Today 6:55 PM' / 'Oct 2, 2026 7:28 PM'."""
    now = dt.datetime.now()
    m = re.match(r"^(Today|Yesterday)\s+(\d{1,2}):(\d{2}) ([AP]M)$", when)
    if m:
        back = 1 if m.group(1) == "Yesterday" else 0
        at = _at(now.date() - dt.timedelta(days=back), m.group(2), m.group(3), m.group(4))
        # History never lists the future: a "Today 11:58 PM" read just after
        # midnight belongs to the day before.
        if at > now + dt.timedelta(minutes=10):
            at -= dt.timedelta(days=1)
        return at
    m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})\s+(\d{1,2}):(\d{2}) ([AP]M)$", when)
    if m:
        day = dt.date(int(m.group(3)), dt.datetime.strptime(m.group(1), "%b").month,
                      int(m.group(2)))
        return _at(day, m.group(4), m.group(5), m.group(6))
    return None


def report_window(date_iso: str, start_hour: int = 19, end_hour: int = 7) -> tuple[dt.datetime, dt.datetime]:
    """The night a report dated <date_iso> covers: previous day 19:00 -> that day 07:00.

    The report window is 7 PM -> 7 AM. The radio feed the transcript comes from
    only carries about 21:00 -> 05:30, so the emulator owns 19:00-21:00 and
    05:30-07:00 outright and fills them with its own rows and clips. A report
    dated Oct 3 therefore covers the night of Oct 2 19:00 through Oct 3 07:00.
    """
    d = dt.date.fromisoformat(date_iso)
    return (dt.datetime.combine(d - dt.timedelta(days=1), dt.time(start_hour, 0)),
            dt.datetime.combine(d, dt.time(end_hour, 0)))


def verify_report(date_iso: str) -> dict:
    """Which app-logged incidents in the report window does our transcript cover?

    Sweeps History, keeps rows inside the report window, and matches each one
    against the transcript's incidents PER INCIDENT (near in time and sharing
    distinctive words; see merge_crimeradar.covered_by). Rows this pipeline
    merged earlier (source: crimeradar) never count as coverage, so a re-run
    cannot talk itself into "covered".

    incidents/<date>.json may not exist yet (the 07:15 emit runs before the
    publish creates it): every in-window row is then reported as missed.
    """
    rows = history_sweep()
    src = INCIDENTS / f"{date_iso}.json"
    ours: list = []
    if src.exists():
        try:
            ours = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            ours = []
    if not isinstance(ours, list):
        ours = []
    transcript = [i for i in ours
                  if isinstance(i, dict) and i.get("source") != mc.SOURCE]
    lo, hi = report_window(date_iso)
    covered, misses, outside, times = [], [], [], []
    for r in rows:
        try:
            when = dt.datetime.fromisoformat(r["at"]) if r.get("at") else hist_dt(r["when"])
        except ValueError:
            when = hist_dt(r["when"])
        r["at"] = when.isoformat(sep=" ") if when else ""
        if when is not None:
            times.append(when)
        if when is None or not (lo <= when <= hi):
            outside.append(r)
            continue
        hit = mc.covered_by(when.strftime("%H:%M"), r["title"], transcript)
        tier = 3
        for t, pat in ESCALATE:
            if t < tier and pat.search(r["title"]):
                tier = t
                break
        # The radio feed only carries about 21:00 -> 05:30. A row outside those
        # hours cannot be "missed by the transcript": the emulator is its only
        # source, so it is reported separately instead of as a coverage failure.
        row = {**r, "tier": tier, "gap": not mc.in_radio_hours(when.strftime("%H:%M")),
               "matched": f"{hit.get('time', '')} {hit.get('type', '')}" if hit else ""}
        (covered if hit else misses).append(row)
    return {"date": date_iso, "window": f"{lo:%Y-%m-%d %H:%M} → {hi:%Y-%m-%d %H:%M}",
            "app_rows": len(rows), "in_window": len(covered) + len(misses),
            "have_incidents": src.exists(), "ours": len(transcript),
            "feed": dict(SWEPT_FEED),
            "newest": f"{max(times):%Y-%m-%d %H:%M}" if times else "",
            "oldest": f"{min(times):%Y-%m-%d %H:%M}" if times else "",
            # False = the History list did not scroll back to the window start,
            # so the early part of the night is not in this sweep.
            "complete": bool(times) and min(times) <= lo,
            "covered": covered, "missed": misses,
            "outside_window": len(outside),
            "high_missed": [m for m in misses if m["tier"] <= 2 and not m["gap"]],
            "high_gap": [m for m in misses if m["tier"] <= 2 and m["gap"]]}


FEED_NAME = mc.FEED_NAME   # the feed the app itself credits

# A History row carries only a clock time and a one-line title, so the report's
# "type" has to come from the wording. First match wins, so keep the specific
# patterns above the general ones.
TYPE_HINTS = [
    ("shots fired", "Shots fired"), ("shooting", "Shooting"), ("shot ", "Shots fired"),
    ("stab", "Stabbing"), ("homicide", "Homicide"), ("fatality", "Fatality"),
    ("assault", "Assault"), ("fight", "Fight"), ("robbery", "Robbery"),
    ("weapon", "Weapons"), ("armed", "Weapons"), ("hostage", "Hostage"),
    ("barricade", "Barricade"), ("kidnap", "Kidnapping"), ("pursuit", "Pursuit"),
    ("chase", "Pursuit"), ("structure fire", "Structure fire"), ("fire", "Fire"),
    ("collision", "Traffic collision"), ("crash", "Traffic collision"),
    ("hit and run", "Hit and run"), ("traffic", "Traffic"), ("vehicle", "Vehicle"),
    ("missing", "Missing person"), ("domestic", "Domestic dispute"),
    ("medical", "Medical emergency"), ("overdose", "Overdose"), ("drowning", "Drowning"),
    ("theft", "Theft"), ("burglar", "Burglary"), ("vandal", "Vandalism"),
    ("trespass", "Trespassing"), ("disturbance", "Disturbance"),
]
# A History row is one unverified line with no disposition, so it never outranks
# "Around the county" (3) and a routine one is a log line (2). It must not be
# able to become "The big one" (4+).
TIER_NOTABILITY = {1: 3, 2: 3, 3: 2}


def _type_of(title: str) -> str:
    t = title.lower()
    for pat, label in TYPE_HINTS:
        if pat in t:
            return label
    return "Incident"


def _fp(hhmm: str, title: str) -> str:
    """Fingerprint an incident by clock time plus its first distinctive words."""
    words = re.findall(r"[a-z]{4,}", title.lower())[:3]
    return f"{hhmm}|{' '.join(words)}"


def _night_polls(date_iso: str) -> list[dict]:
    """Every poll record from the night a report dated <date_iso> covers.

    Polls are filed by the calendar day they ran, and the night spans two: the
    19:00-23:59 polls sit in the previous day's file. Reading only the report
    date's file dropped every pre-midnight clip and street.
    """
    lo, hi = report_window(date_iso)
    hi += dt.timedelta(hours=1)
    d = dt.date.fromisoformat(date_iso)
    out = []
    for day in (d - dt.timedelta(days=1), d):
        p = OUT / f"polls_{day.isoformat()}.jsonl"
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
                ts = dt.datetime.strptime(rec.get("ts", ""), "%Y%m%d-%H%M%S")
            except Exception:
                continue
            if lo <= ts <= hi:
                out.append(rec)
    return out


def _poll_places(date_iso: str) -> dict:
    """title -> street, taken from the night's feed polls.

    A feed card renders its location in `address_tv` as "N.N mi · <street>" and
    parse_feed stores the street as `place`, so the poll records already hold the
    per-incident location that a History row does not carry.
    """
    out: dict[str, str] = {}
    for rec in _night_polls(date_iso):
        for c in rec.get("cards") or []:
            t = (c.get("title") or "").strip()
            pl = (c.get("place") or "").strip()
            if t and pl:
                out.setdefault(t, pl)
    return out


_STREETS: list | None = None
_STREET_SUFFIX = re.compile(
    r"\b(St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Boulevard|Ln|Lane|Way|Hwy|Highway"
    r"|Ct|Court|Pl|Place|Cir|Circle|Ter|Terrace|Pkwy|Parkway|Trl|Trail|Loop|Aly)\.?$",
    re.I)


def _area_for(title: str, poll_places: dict) -> str:
    """Recover a History row's location, or "" when it cannot be known.

    A History row carries only a time and a one-line title. Order of recovery:
    the feed card for the same headline (its exact street), then a scan of the
    headline against the project's street gazetteer ("...on White Lane").
    """
    global _STREETS
    hit = poll_places.get(title.strip())
    if hit:
        return hit
    try:
        import sys as _sys
        if _STREETS is None:
            _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kern_overnight"))
            import streetcheck  # type: ignore
            _STREETS = streetcheck.load_streets()
        cands = []
        for tup in streetcheck.scan(title, _STREETS):
            if not tup or not tup[0]:
                continue
            name = (tup[2] if len(tup) > 2 and tup[2] else tup[0]).strip()
            if not name:
                continue
            # scan() also yields scanned phrases ("pain at Bank St"), so prefer a
            # candidate that ends in a street suffix, then the shortest one.
            cands.append(((0 if _STREET_SUFFIX.search(name) else 1), len(name), name))
        if cands:
            cands.sort()
            return cands[0][2]
    except Exception:
        pass
    return ""


def emit_incidents(date_iso: str, dry: bool = False) -> dict:
    """Stage the app's in-window incidents for the publish to merge.

    STAGING ONLY: this never writes incidents/<date>.json. That file is created
    and rewritten by the publish, so anything written here would be lost, and it
    does not even exist at 07:15. kern_overnight/merge_crimeradar.py merges the
    staged rows after the extraction.

    Every in-window row is staged. Which ones the transcript already covers is
    decided at merge time, when the transcript's incident list finally exists.
    `dry` is accepted for old callers and changes nothing.

    A History row carries no detail text, so the summary is the app's own
    one-line title and the location is recovered from the feed card for the same
    headline, else from the street gazetteer (see _area_for).

    Nothing is staged unless the sweep verified the Kern feed, and every staged
    row carries the feed name the screen printed, not a constant.
    """
    v = verify_report(date_iso)
    feed = v.get("feed") or {}
    if not mc.is_kern_feed(feed):
        return {"error": f"the History sweep did not verify the Kern feed (the "
                         f"screen said {feed!r}); nothing staged",
                "alarm": True, "wrong_feed": True, "feed": feed}
    rows = sorted(v["covered"] + v["missed"], key=lambda r: r["at"])
    if not rows:
        # Never overwrite a good staging file with nothing: an empty window means
        # the sweep read the wrong screen or stopped short, not a silent night.
        return {"error": f"History has no rows inside {v['window']} "
                         f"({v['app_rows']} rows read, newest {v['newest'] or 'n/a'}); "
                         "staging left untouched", "alarm": True, "feed": feed}
    poll_places = _poll_places(date_iso)
    rows_out = []
    for r in rows:
        rows_out.append({
            "type": _type_of(r["title"]),
            "time": r["at"][11:16],
            "agency": feed["name"],
            "area": _area_for(r["title"], poll_places),
            "notability": TIER_NOTABILITY.get(r.get("tier", 3), 2),
            "disposition": "",
            "summary": r["title"].rstrip(".") + ".",
            "source": mc.SOURCE,
        })
    stage = OUT / f"emulator_incidents_{date_iso}.json"
    _write_atomic(stage, json.dumps(
        {"date": date_iso, "window": v["window"],
         "generated": dt.datetime.now().isoformat(timespec="seconds"),
         "feed": feed,
         "history_newest": v["newest"], "history_oldest": v["oldest"],
         "history_complete": v["complete"], "incidents": rows_out},
        indent=1, ensure_ascii=False))
    # What the merge would do against the incidents on disk right now (preview).
    ours = []
    try:
        ours = json.loads((INCIDENTS / f"{date_iso}.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    plan = mc.plan(rows_out, ours if isinstance(ours, list) else [])
    return {"date": date_iso, "staged": len(rows_out), "stage": str(stage),
            "feed": feed,
            "have_incidents": v["have_incidents"], "would_merge": plan["keep"],
            "covered": len(plan["covered"]), "private": len(plan["private"]),
            "newest": v["newest"], "oldest": v["oldest"], "complete": v["complete"]}


def _detail_dt(stamp: str) -> dt.datetime | None:
    """'Oct 3, 2026 · 9:48 PM PDT' (the detail page's own timestamp) -> datetime."""
    m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4}) · (\d{1,2}):(\d{2}) ([AP]M)",
                 stamp or "")
    if not m:
        return None
    try:
        day = dt.date(int(m.group(3)), dt.datetime.strptime(m.group(1), "%b").month,
                      int(m.group(2)))
    except ValueError:
        return None
    return _at(day, m.group(4), m.group(5), m.group(6))


def reel_export(date_iso: str, out_dir: Path | None = None) -> dict:
    """Collect the night's CRITICAL/HIGH clips into one folder for the morning reel.

    Reads the day's poll records, keeps only COMPLETE clips (a partial clip is a
    half-written ExoPlayer prefetch and must never reach a reel), dedupes by
    incident, orders CRITICAL first then longest, and copies with a numeric
    prefix plus a manifest.json the reel builder can consume.
    """
    polls = _night_polls(date_iso)
    if not polls:
        return {"error": f"no poll records for the night of {date_iso}"}
    dest = out_dir or (OUT / f"reel_{date_iso}")
    best: dict[str, dict] = {}
    for row in polls:
        for c in row.get("cards", []):
            if c.get("tier", 3) > 2:
                continue
            if mc.is_private(c.get("title", ""),
                             medical=c.get("category") == "Medical Emergency"):
                continue    # patient / hospital traffic never reaches a reel
            for clip in (c.get("audio") or {}).get("clips", []):
                if clip.get("partial") or not Path(clip["path"]).exists():
                    continue
                k = c.get("key") or str(clip.get("uid"))
                if k not in best or clip["seconds"] > best[k]["clip"]["seconds"]:
                    # the detail page's exact timestamp beats "N minutes ago"
                    exact = _detail_dt((c.get("detail") or {}).get("timestamp", ""))
                    best[k] = {"card": c, "clip": clip,
                               "approx": exact or _approx_dt(row.get("ts", ""),
                                                             c.get("age", ""))}
    ranked = sorted(best.values(),
                    key=lambda x: (x["card"].get("tier", 3), -x["clip"]["seconds"]))
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("[0-9][0-9]_*.mp3"):   # a re-run must not leave stale clips
        old.unlink()
    manifest = []
    for i, item in enumerate(ranked, 1):
        c, clip = item["card"], item["clip"]
        slug = re.sub(r"[^a-z0-9]+", "-", c["title"].lower())[:44].strip("-")
        name = f"{i:02d}_{c.get('tier_name','HIGH')}_{slug}.mp3"
        target = dest / name
        shutil.copy2(clip["path"], target)
        manifest.append({"order": i, "file": name, "tier": c.get("tier_name"),
                         "category": c.get("category"), "title": c["title"],
                         "place": c.get("place"), "approx_time": str(item["approx"] or ""),
                         "seconds": clip["seconds"], "source_clip": clip["path"]})
    _write_atomic(dest / "manifest.json", json.dumps(
        {"date": date_iso, "clips": manifest}, indent=1, ensure_ascii=False))
    return {"date": date_iso, "dir": str(dest), "count": len(manifest), "clips": manifest}


def _approx_dt(ts: str, age: str) -> dt.datetime | None:
    """Approximate an incident's clock time from a poll stamp and its 'N min ago'."""
    m = re.match(r"^(\d+)\s*(minute|hour|day)s?\s+ago$", age, re.I)
    if not m:
        return None
    try:
        t = dt.datetime.strptime(ts, "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    unit = m.group(2).lower()
    n = int(m.group(1))
    return t - dt.timedelta(**{f"{unit}s": n})


# -------------------------------------------------------------- diff
def diff_report(date_iso: str, cards: list[dict]) -> dict:
    """High-severity CrimeRadar items with no plausible match in our incidents."""
    src = INCIDENTS / f"{date_iso}.json"
    if not src.exists():
        return {"error": f"no {src.name}"}
    ours = json.loads(src.read_text(encoding="utf-8"))
    ours_types = " ".join(f"{i.get('type','')} {i.get('summary','')} {i.get('area','')}"
                          for i in ours).lower()
    ours_kw = set(re.findall(r"[a-z]{4,}", ours_types))
    gaps, covered = [], []
    for c in cards:
        tier, _ = classify(c)
        if tier > 2:
            continue
        words = [w for w in re.findall(r"[a-z]{5,}", c["title"].lower())
                 if w not in ("reported", "speeding", "person", "having")]
        hit = [w for w in words if w in ours_kw]
        row = {**c, "tier": tier, "matched": hit}
        (covered if hit else gaps).append(row)
    return {"date": date_iso, "ours": len(ours), "high_seen": len(covered) + len(gaps),
            "covered": covered, "gaps": gaps}


# ---------------------------------------------------------------- reporting
def post_discord(text: str) -> bool:
    url = os.environ.get("CR_DISCORD_WEBHOOK") or os.environ.get("DISCORD_WEBHOOK_URL") or ""
    if not url:
        env = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith(("DISCORD_WEBHOOK_URL=", "CR_DISCORD_WEBHOOK=")):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    if not url:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps({"content": text[:1900]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[cr] discord post failed: {e}", file=sys.stderr)
        return False


def poll(detail: bool = False, do_diff: str | None = None, as_json: bool = False,
         discord: bool = False, audio: bool = False) -> int:
    normalise_feed()
    xml = dump_ui("cr")
    cards = parse_feed(xml)
    if not cards:
        # Canary: the feed always renders cards, so zero is a broken read path.
        # Without this the monitor would report "0 new" and exit 0 forever: a
        # SILENT short report. Retry once, then alarm with a distinct exit code
        # and what the screen showed. The cause is not guessed at.
        normalise_feed()
        dismiss_overlays("crc", rounds=2)
        time.sleep(2)
        xml = dump_ui("cr")
        cards = parse_feed(xml)
        if not cards:
            screen = on_screen(xml)
            if screen["package"] != PKG:
                raise Unreadable(f"the screen is not the app: {describe(screen)}")
            print(f"[cr] ALARM: feed parsed 0 cards after a retry. On screen: "
                  f"{describe(screen)}. The read path is broken; this is NOT a "
                  "quiet night.", file=sys.stderr)
            return 4
    chip, selected = home_feed(xml)
    if chip != KERN_CHIP or not selected:
        # Refuse before anything is recorded: a poll record feeds the staged
        # rows' streets and the reel's clips.
        raise WrongFeed(
            f"the Home location chip reads \"{chip or '(not on screen)'}\""
            f"{'' if selected else ' and is not the selected tab'}, not "
            f"\"{KERN_CHIP}\". No poll record was written; on screen: "
            + describe(on_screen(xml)))
    now = dt.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    seen = load_seen()
    fresh = []
    for c in cards:
        k = key_of(c)
        c["key"], (c["tier"], c["why"]) = k, classify(c)
        c["tier_name"] = TIER_NAME[c["tier"]]
        if k not in seen:
            fresh.append(c)
            seen[k] = {"first": now.isoformat(timespec="seconds"), "tries": 0,
                       "done": False}
    high = [c for c in cards if c["tier"] <= 2]
    new_high = [c for c in fresh if c["tier"] <= 2]
    # Clips are RETRIED: a HIGH posting whose capture failed (an overlay ate the
    # tap, the player stalled) is tried again on later polls, up to the cap.
    todo = [c for c in high
            if not seen[c["key"]]["done"]
            and seen[c["key"]]["tries"] < MAX_AUDIO_TRIES] if audio else []
    save_seen(seen)

    if detail:
        for c in new_high + [t for t in todo if t not in new_high]:
            try:
                if relocate(c):
                    c["detail"] = open_detail(c, stamp)
                else:
                    c["detail_error"] = "card no longer on screen"
            except Exception as e:  # noqa: BLE001
                c["detail_error"] = str(e)
        normalise_feed()

    if audio:
        for c in todo:
            ent = seen[c["key"]]
            secs = 0.0
            m = re.match(r"^-(\d+):(\d+)$", (c.get("detail") or {}).get("clip_seconds", ""))
            if m:
                secs = int(m.group(1)) * 60 + int(m.group(2))
            try:
                if relocate(c):
                    ent["tries"] += 1
                    c["audio"] = capture_audio(c, stamp, secs)
                    if c["audio"].get("clips"):
                        ent["done"] = True
                else:
                    c["audio_error"] = "card no longer on screen"
            except Exception as e:  # noqa: BLE001
                c["audio_error"] = str(e)
            save_seen(seen)
            normalise_feed()

    OUT.mkdir(parents=True, exist_ok=True)
    row = {"ts": stamp, "device": DEVICE, "feed": chip, "n_cards": len(cards),
           "new": len(fresh), "high": len(high), "cards": cards}
    with (OUT / f"polls_{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    result = {"ts": stamp, "cards": len(cards), "new": len(fresh),
              "high": high, "new_high": new_high}
    if do_diff:
        result["diff"] = diff_report(do_diff, cards)

    if as_json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print(f"[cr] {stamp}  {len(cards)} postings, {len(fresh)} new, "
              f"{len(high)} at HIGH+")
        for c in high:
            flag = "NEW " if c["key"] and c in new_high else "    "
            print(f"  {flag}[{c['tier_name']}] {c['category']} — {c['title']} "
                  f"({c['age']}, {c['place']})  <{c['why']}>")
        d = result.get("diff")
        if d and not d.get("error"):
            print(f"\n[cr] coverage vs incidents/{d['date']}.json — "
                  f"we have {d['ours']}; {len(d['covered'])} matched, "
                  f"{len(d['gaps'])} HIGH+ unmatched")
            for g in d["gaps"]:
                print(f"  GAP [{TIER_NAME[g['tier']]}] {g['category']} — {g['title']}")

    if discord and new_high:
        lines = [f"🚨 **CrimeRadar high-severity** ({stamp[:15]} PT) — "
                 f"{len(new_high)} new"]
        for c in new_high:
            lines.append(f"[{c['tier_name']}] {c['category']} — {c['title']} "
                         f"({c['age']}, {c['place']})")
        post_discord("\n".join(lines))
    return 0


def main() -> int:
    # Under the cron runner stdout is a cp1252 pipe, and the arrows and dashes
    # this prints crashed the whole run with UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="CrimeRadar emulator severity monitor")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--detail", action="store_true", help="open new HIGH items")
    ap.add_argument("--diff", metavar="YYYY-MM-DD", help="diff vs incidents/<date>.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--discord", action="store_true")
    ap.add_argument("--audio", action="store_true",
                    help="play new HIGH clips and rebuild them as MP3 (implies --detail)")
    ap.add_argument("--rebuild", action="store_true",
                    help="offline: pull the cache tree and rebuild every clip, no polling")
    ap.add_argument("--history", action="store_true",
                    help="sweep Replay > History (~24 h of app-logged incidents)")
    ap.add_argument("--verify", metavar="YYYY-MM-DD",
                    help="sweep History and report HIGH+ incidents we have no match for")
    ap.add_argument("--reel", metavar="YYYY-MM-DD",
                    help="export the day's complete CRITICAL/HIGH clips for the morning reel")
    ap.add_argument("--emit", metavar="YYYY-MM-DD",
                    help="stage the app's in-window incidents for the publish to merge")
    ap.add_argument("--dry", action="store_true",
                    help="accepted for old callers; --emit never writes incidents/")
    a = ap.parse_args()
    status: dict = {}
    rc = 5
    try:
        rc = _guarded(a, status)
        return rc
    except BaseException as e:
        status.setdefault("reason", f"{type(e).__name__}: {e}")
        raise
    finally:
        if a.emit:
            write_emit_status(a.emit, rc, status)


EMIT_OUTCOME = {0: "staged", 2: "device_offline", 4: "empty_window", 5: "read_failed",
                6: "busy", 7: "system_dialog", 8: "unreadable", 9: "wrong_feed"}


def write_emit_status(date_iso: str, rc: int, status: dict) -> None:
    """Record how an emit ended, on EVERY exit, as emit_status_<date>.json.

    Without it a failed emit and an emit that never ran both look like "no
    staging file", which the publish used to read as "nothing to do". Writing
    it must never change the exit code.
    """
    try:
        _write_atomic(OUT / f"emit_status_{date_iso}.json", json.dumps({
            "date": date_iso, "ran": dt.datetime.now().isoformat(timespec="seconds"),
            "rc": rc, "ok": rc == 0, "outcome": EMIT_OUTCOME.get(rc, "failed"),
            "reason": status.get("reason", ""), "feed": status.get("feed"),
            "staged": status.get("staged", 0),
            "history_complete": status.get("complete"),
            "history_newest": status.get("newest", ""),
            "history_oldest": status.get("oldest", ""),
            "stage": status.get("stage", "")}, indent=1, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        print(f"[cr] could not write emit_status_{date_iso}.json: {e}", file=sys.stderr)


def _guarded(a, status: dict) -> int:
    """Lock, device check, dispatch. Every failure leaves its reason in `status`."""
    # --reel on its own only reads poll records; everything else drives the app.
    needs_emulator = bool(a.verify or a.emit or a.history or a.rebuild) or not a.reel
    if not needs_emulator:
        return _dispatch(a, status)
    is_poll = not (a.verify or a.emit or a.history or a.rebuild or a.reel)
    # A poll yields to a run already in progress (the next one is 15 min away);
    # the once-a-morning jobs wait for it instead.
    if not acquire_lock(0 if is_poll else 900):
        if is_poll:
            print("[cr] skipped: another run is driving the emulator")
            return 0
        status["reason"] = "emulator still busy after 15 min; giving up"
        print(f"[cr] ALARM: {status['reason']}", file=sys.stderr)
        return 6
    try:
        for _ in range(6):          # an emulator just restarted by the preflight
            if device_online():     # can still be settling
                break
            time.sleep(10)
        else:
            status["reason"] = f"device {DEVICE} not online (adb {ADB})"
            print(f"[cr] {status['reason']}", file=sys.stderr)
            return 2
        return _dispatch(a, status)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        # A broken read path must be loud and distinct, never a quiet success:
        # the exit code names the kind of failure, the text what was on screen.
        status["reason"] = alarm_text(e)
        if SWEPT_FEED:
            status["feed"] = dict(SWEPT_FEED)
        print(f"[cr] ALARM: {status['reason']}", file=sys.stderr)
        return getattr(e, "code", 5)
    finally:
        release_lock()


def _dispatch(a, status: dict | None = None) -> int:
    status = {} if status is None else status
    if a.verify or a.reel or a.emit:
        rc = 0
        if a.verify:
            v = verify_report(a.verify)
            if v.get("error"):
                print(f"[cr] {v['error']}", file=sys.stderr)
                rc = 1
            else:
                print(f"[cr] verify {v['date']}  window {v['window']}")
                print(f"  app logged {v['app_rows']} ({v['in_window']} in window, "
                      f"{v['outside_window']} outside); we have {v['ours']}; "
                      f"{len(v['covered'])} covered, {len(v['missed'])} missed")
                if not v["have_incidents"]:
                    print(f"  NOTE: incidents/{v['date']}.json does not exist, so "
                          "nothing could be matched")
                if not v["complete"]:
                    print(f"  NOTE: History only reaches back to {v['oldest']}; the "
                          "start of the window is not in this sweep")
                for m in v["high_missed"]:
                    print(f"  MISSED [{TIER_NAME[m['tier']]}] {m['when']} — {m['title']}")
                if not v["high_missed"]:
                    print("  no HIGH+ miss in the radio hours")
                if v["high_gap"]:
                    # Not a failure: the radio feed never carries these hours, so
                    # the emulator is the only source and the merge fills them.
                    print(f"  emulator-only hours (no radio feed): "
                          f"{len(v['high_gap'])} HIGH+ row(s) the merge supplies")
                    for m in v["high_gap"]:
                        print(f"    [{TIER_NAME[m['tier']]}] {m['when']} — {m['title']}")
                _write_atomic(OUT / f"verify_{a.verify}.json",
                              json.dumps(v, indent=1, ensure_ascii=False))
        if a.reel:
            r = reel_export(a.reel)
            if r.get("error"):
                print(f"[cr] {r['error']}", file=sys.stderr)
                rc = 1
            else:
                print(f"[cr] reel {r['date']}: {r['count']} clips -> {r['dir']}")
                for c in r["clips"]:
                    print(f"  {c['file']}  {c['seconds']}s  {c['category']} — {c['title']}")
        if a.emit:
            e = emit_incidents(a.emit, dry=a.dry)
            status.update({k: e[k] for k in ("feed", "staged", "stage", "complete",
                                             "newest", "oldest") if k in e})
            if e.get("error"):
                status["reason"] = e["error"]
                print(f"[cr] ALARM: {e['error']}", file=sys.stderr)
                rc = WrongFeed.code if e.get("wrong_feed") else 4
            else:
                print(f"[cr] emit {e['date']}: {e['staged']} rows staged "
                      f"(History {e['oldest']} to {e['newest']}) -> {e['stage']}")
                if not e["complete"]:
                    print("  NOTE: History did not reach back to the window start; "
                          "the early night is not staged")
                if e["have_incidents"]:
                    print(f"  against the incidents on disk the merge would add "
                          f"{len(e['would_merge'])} ({e['covered']} already covered, "
                          f"{e['private']} withheld for privacy)")
                    for i in e["would_merge"]:
                        print(f"  + {i['time']} [{i['type']}] {i['summary']}")
                else:
                    print(f"  incidents/{e['date']}.json does not exist yet (normal "
                          "before the publish); the merge decides what is added")
        return rc
    if a.history:
        rows = history_sweep()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"history_{dt.date.today().isoformat()}.json").write_text(
            json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"[cr] history: {len(rows)} app-logged incidents")
        print(f"  newest: {rows[0]['when']}  {rows[0]['title']}" if rows else "  (none)")
        print(f"  oldest: {rows[-1]['when']}  {rows[-1]['title']}" if rows else "  (none)")
        return 0
    if a.rebuild:
        pull_cache()
        clips = rebuild_clips()
        for c in clips:
            bad = ("PARTIAL " if c["partial"] else "") + ("CAP-SPAN " if c["final_span_at_cap"] else "")
            print(f"{bad}{c['path']}  {c['seconds']}s  {c['bytes']}B  spans={c['spans']}")
        nbad = sum(1 for c in clips if c["partial"])
        print(f"[cr] {len(clips)} clips, {nbad} partial (do not use for reels)")
        return 0
    if a.audio:
        a.detail = True
    if a.watch:
        while True:
            try:
                poll(a.detail, a.diff, a.json, a.discord, a.audio)
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"[cr] ALARM: {alarm_text(e)}", file=sys.stderr)
            time.sleep(a.interval)
    return poll(a.detail, a.diff, a.json, a.discord, a.audio)


if __name__ == "__main__":
    sys.exit(main())