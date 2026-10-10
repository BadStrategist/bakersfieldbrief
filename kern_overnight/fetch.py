#!/usr/bin/env python3
"""Stage 1 — FETCH: last night's Broadcastify archives for feed 14029.

Feed 14029 = "Bakersfield Police, Fire and EMS" (RadioReference).
Overnight window: 19:00 previous evening through 07:00 local (Pacific).
Blocks are ~30-minute MP3s; archive filenames embed the block start as a
unix epoch, e.g. 14029-1786329296.mp3.

Download path: broadcastify-cli if installed, else direct HTTP with
RadioReference premium credentials (RR_USER / RR_PASS env vars).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

PACIFIC = dt.timezone(dt.timedelta(hours=-7), "PDT")  # DST assumption for Aug; run.py adjusts
FEED_ID = "14029"
# Backup feed: Bakersfield Police / Kern County Sheriff (police-side coverage only,
# no fire or EMS). Used only when the primary feed yields no blocks for the window.
BACKUP_FEED_ID = os.environ.get("KO_BACKUP_FEED", "47440")
BLOCK_SECONDS = 30 * 60
# The overnight window is defined ONCE, here: 19:00 the previous evening to
# 07:00 local. Broadcastify holds the 19:00-21:00 and 05:30-07:00 hours; the
# code simply never asked for them.
WINDOW_START = dt.time(19, 0)
WINDOW_END = dt.time(7, 0)
ROOT = Path(__file__).resolve().parent.parent


class FetchError(RuntimeError):
    pass


def _epoch_from_name(name: str, feed_id: str | None = None) -> int | None:
    """Epoch start from a block filename. Accepts any feed id; filter with feed_id."""
    m = re.search(r"^(\d{4,6})-(\d{10})\.mp3$", name)
    if not m:
        return None
    if feed_id is not None and m.group(1) != str(feed_id):
        return None
    return int(m.group(2))


def window_bounds(date: dt.date, tz: dt.tzinfo) -> tuple[int, int]:
    """(w_start, w_end) epochs of the night that belongs to `date`."""
    return (int(dt.datetime.combine(date - dt.timedelta(days=1),
                                    WINDOW_START, tz).timestamp()),
            int(dt.datetime.combine(date, WINDOW_END, tz).timestamp()))


def in_window(start_epoch: int, w_start: int, w_end: int) -> bool:
    """True if a block belongs to the night. OVERLAP, not containment.

    The archive's first evening block starts at 19:16 or 18:58, so
    `w_start <= startTs < w_end` dropped the block that straddles 19:00 and
    the 19:00-21:00 hours were never fetched at all.
    """
    return start_epoch + BLOCK_SECONDS > w_start and start_epoch < w_end


def overnight_blocks(date: dt.date, tz: dt.tzinfo) -> list[tuple[int, int]]:
    """(start_epoch, end_epoch) for each ~30-min block in the overnight window.

    Window: 19:00 previous evening through 07:00 of `date`, aligned to
    BLOCK_SECONDS boundaries."""
    start = dt.datetime.combine(date - dt.timedelta(days=1), WINDOW_START, tz)
    end = dt.datetime.combine(date, WINDOW_END, tz)
    blocks = []
    t = start
    while t < end:
        b_end = min(t + dt.timedelta(seconds=BLOCK_SECONDS), end)
        blocks.append((int(t.timestamp()), int(b_end.timestamp())))
        t = b_end
    return blocks


def _load_cookie() -> str | None:
    """Reuse a stored bcfyuser1 session cookie if present."""
    try:
        data = json.loads((ROOT / "kern_overnight" / ".bcfy_cookie.json").read_text(encoding="utf-8"))
        return data.get("bcfyuser1")
    except Exception:  # noqa: BLE001
        return None


def _store_cookie(token: str) -> None:
    (ROOT / "kern_overnight" / ".bcfy_cookie.json").write_text(
        json.dumps({"bcfyuser1": token}), encoding="utf-8")


def _login() -> str:
    """Broadcastify premium login (same flow as broadcastify-cli):
    POST /login/ {username, password, action=auth, redirect} → bcfyuser1 cookie."""
    user = os.environ.get("RR_USER", "").strip()
    password = os.environ.get("RR_PASS", "").strip()
    if not user or not password:
        raise FetchError(
            "RR_USER / RR_PASS not set (and broadcastify-cli not installed). "
            "Export the RadioReference premium credentials to download feed 14029.")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    headers = {
        "user-agent": ua,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.5",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.broadcastify.com",
        "referer": "https://www.broadcastify.com/login/",
        "dnt": "1",
    }
    data = {"username": user, "password": password,
            "action": "auth", "redirect": "https://www.broadcastify.com"}
    r = requests.post("https://www.broadcastify.com/login/", headers=headers,
                      data=data, allow_redirects=False, timeout=60)
    if r.status_code != 302:
        raise FetchError(f"Broadcastify login failed (HTTP {r.status_code}) — "
                         "check RR_USER/RR_PASS premium credentials")
    m = re.search(r"bcfyuser1=([^;]+)", r.headers.get("set-cookie", ""))
    if not m:
        raise FetchError("Broadcastify login did not return a session cookie")
    _store_cookie(m.group(1))
    print("    [ko-fetch] logged in (new session cookie)", flush=True)
    return m.group(1)


def _download_with_cookie(url: str, dest: Path) -> None:
    token = _load_cookie()
    if not token:
        token = _login()
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    r = requests.get(url, headers={"user-agent": ua,
                                   "cookie": f"bcfyuser1={token}"},
                     timeout=180, stream=True)
    if r.status_code == 403 and token:
        token = _login()  # stale session — one fresh attempt
        r = requests.get(url, headers={"user-agent": ua,
                                       "cookie": f"bcfyuser1={token}"},
                         timeout=180, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    return r.url  # final URL (after redirects) — embeds the epoch filename


def _archive_entries(date: dt.date, feed_id: str = FEED_ID) -> list[dict]:
    """Archive entries for one calendar date via the live archives API."""
    d = f"{date.month:02d}%2F{date.day:02d}%2F{date.year}"
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    tok = _load_cookie() or _login()
    r = requests.get(
        f"https://www.broadcastify.com/archives/api/archives.php?feedId={feed_id}&date={d}",
        headers={"user-agent": ua, "cookie": f"bcfyuser1={tok}"}, timeout=60)
    if r.status_code == 403:
        tok = _login()
        r = requests.get(
            f"https://www.broadcastify.com/archives/api/archives.php?feedId={feed_id}&date={d}",
            headers={"user-agent": ua, "cookie": f"bcfyuser1={tok}"}, timeout=60)
    r.raise_for_status()
    return r.json().get("archives", [])


def _audio_url(archive_id: str) -> str:
    """Resolve an archive id to its direct MP3 URL via the play API."""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    tok = _load_cookie() or _login()
    r = requests.get(
        f"https://www.broadcastify.com/archives/api/play.php?id={archive_id}",
        headers={"user-agent": ua, "cookie": f"bcfyuser1={tok}"}, timeout=60)
    if r.status_code == 403:
        tok = _login()
        r = requests.get(
            f"https://www.broadcastify.com/archives/api/play.php?id={archive_id}",
            headers={"user-agent": ua, "cookie": f"bcfyuser1={tok}"}, timeout=60)
    r.raise_for_status()
    url = r.json().get("url")
    if not url:
        raise FetchError(f"play.php returned no audio URL for {archive_id}")
    return url


def _download_archive(archive_id: str, start_ts: int, audio_dir: Path,
                      feed_id: str = FEED_ID) -> Path:
    """Download one archive to audio_dir/<feedId>-<startTs>.mp3 (epoch name)."""
    dest = audio_dir / f"{feed_id}-{start_ts}.mp3"
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest          # already held: never spend a play.php call on it
    url = _audio_url(archive_id)
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    r = requests.get(url, headers={"user-agent": ua}, timeout=180, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    return dest


def _collect(audio_dir: Path, w_start: int, w_end: int, feed_id: str) -> list[Path]:
    """Usable blocks of one feed already on disk inside the overnight window."""
    out: list[Path] = []
    for p in sorted(audio_dir.glob(f"{feed_id}-*.mp3")):
        e = _epoch_from_name(p.name)
        if e is not None and in_window(e, w_start, w_end) and p.stat().st_size > 50_000:
            out.append(p)
    return out


def fetch(date: dt.date, audio_dir: Path, tz: dt.tzinfo) -> list[Path]:
    """Download all overnight blocks for `date` into audio_dir; return paths."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    blocks = overnight_blocks(date, tz)
    if not blocks:
        raise FetchError("no overnight blocks computed for {date}")
    span = sorted({dt.datetime.fromtimestamp(b[0], tz).date() for b in blocks})
    w_start, w_end = window_bounds(date, tz)

    # Prefer broadcastify-cli when present (handles premium auth + retries).
    cli = shutil.which("broadcastify-cli")
    if cli:
        for d in span:
            subprocess.run([cli, "download", "--feed-id", FEED_ID,
                            "--date", f"{d.month:02d}/{d.day:02d}/{d.year}",
                            "--output", str(audio_dir)],
                           check=True, capture_output=True)
    else:
        # Live archives API with the premium session cookie (verified Aug 2026).
        for d in span:
            for entry in _archive_entries(d):
                if not in_window(entry["startTs"], w_start, w_end):
                    continue  # skip out-of-window archives (saves bandwidth)
                try:
                    p = _download_archive(entry["id"], entry["startTs"], audio_dir)
                    print(f"    [ko-fetch] got {p.name}", flush=True)
                except requests.HTTPError as e:
                    print(f"    [ko-fetch] {entry['id']} failed: "
                          f"HTTP {e.response.status_code}", flush=True)
                    continue

    got = _collect(audio_dir, w_start, w_end, FEED_ID)
    if not got:
        # Primary feed down or empty for the whole window: try the backup feed once.
        print(f"    [ko-fetch] feed {FEED_ID} produced no usable blocks for the window; "
              f"falling back to {BACKUP_FEED_ID}", flush=True)
        for d in span:
            try:
                entries = _archive_entries(d, BACKUP_FEED_ID)
            except (requests.RequestException, FetchError) as e:
                print(f"    [ko-fetch] backup listing for {d} failed: {e}", flush=True)
                continue
            for entry in entries:
                if not in_window(entry["startTs"], w_start, w_end):
                    continue
                try:
                    p = _download_archive(entry["id"], entry["startTs"], audio_dir,
                                          BACKUP_FEED_ID)
                    print(f"    [ko-fetch] backup got {p.name}", flush=True)
                except requests.HTTPError as e:
                    print(f"    [ko-fetch] backup {entry['id']} failed: "
                          f"HTTP {e.response.status_code}", flush=True)
                    continue
        got = _collect(audio_dir, w_start, w_end, BACKUP_FEED_ID)
        if got:
            print(f"    [ko-fetch] backup feed {BACKUP_FEED_ID} supplied "
                  f"{len(got)} blocks (police-side audio only)", flush=True)
    return got


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    paths = fetch(d, Path("audio") / d.isoformat(), PACIFIC)
    print(f"fetched {len(paths)} blocks for {d}")
