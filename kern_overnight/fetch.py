#!/usr/bin/env python3
"""Stage 1 — FETCH: last night's Broadcastify archives for feed 14029.

Feed 14029 = "Bakersfield Police, Fire and EMS" (RadioReference).
Overnight window: 21:00 previous evening through 06:00 local (Pacific).
Blocks are ~30-minute MP3s; archive filenames embed the block start as a
unix epoch, e.g. 14029-1786329296.mp3.

Download path: broadcastify-cli if installed, else direct HTTP with
RadioReference premium credentials (RR_USER / RR_PASS env vars).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PACIFIC = dt.timezone(dt.timedelta(hours=-7), "PDT")  # DST assumption for Aug; run.py adjusts
FEED_ID = "14029"
BLOCK_SECONDS = 30 * 60


class FetchError(RuntimeError):
    pass


def _epoch_from_name(name: str) -> int | None:
    m = re.search(rf"^{FEED_ID}-(\d{{10}})\.mp3$", name)
    return int(m.group(1)) if m else None


def overnight_blocks(date: dt.date, tz: dt.tzinfo) -> list[tuple[int, int]]:
    """(start_epoch, end_epoch) for each ~30-min block in the overnight window.

    Window: 21:00 previous evening through 06:00 of `date`, aligned to
    BLOCK_SECONDS boundaries."""
    start = dt.datetime.combine(date - dt.timedelta(days=1), dt.time(21, 0), tz)
    end = dt.datetime.combine(date, dt.time(6, 0), tz)
    blocks = []
    t = start
    while t < end:
        b_end = min(t + dt.timedelta(seconds=BLOCK_SECONDS), end)
        blocks.append((int(t.timestamp()), int(b_end.timestamp())))
        t = b_end
    return blocks


def _download_direct(url: str, dest: Path, user: str, password: str) -> None:
    req = urllib.request.Request(url)
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(
        f"{user}:{password}".encode()).decode())
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def fetch(date: dt.date, audio_dir: Path, tz: dt.tzinfo) -> list[Path]:
    """Download all overnight blocks for `date` into audio_dir; return paths."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    blocks = overnight_blocks(date, tz)
    if not blocks:
        raise FetchError("no overnight blocks computed for {date}")
    got: list[Path] = []

    # Prefer broadcastify-cli when present (handles premium auth + retries).
    cli = shutil.which("broadcastify-cli")
    if cli:
        for start, _end in blocks:
            dest = audio_dir / f"{FEED_ID}-{start}.mp3"
            if dest.exists() and dest.stat().st_size > 50_000:
                got.append(dest)
                continue
            print(f"    [ko-fetch] {start} via broadcastify-cli", flush=True)
            subprocess.run(
                [cli, "download", "--feed", FEED_ID, "--output", str(dest),
                 "--start", str(start), "--end", str(_end)],
                check=True, capture_output=True)
            if dest.exists() and dest.stat().st_size > 50_000:
                got.append(dest)
        return got

    # Fallback: direct HTTP with RadioReference premium credentials.
    user = os.environ.get("RR_USER", "").strip()
    password = os.environ.get("RR_PASS", "").strip()
    if not user or not password:
        raise FetchError(
            "broadcastify-cli not found AND RR_USER/RR_PASS not set. "
            "Install broadcastify-cli or export the RadioReference premium "
            "credentials to download feed 14029 archives.")
    for start, _end in blocks:
        dest = audio_dir / f"{FEED_ID}-{start}.mp3"
        if dest.exists() and dest.stat().st_size > 50_000:
            got.append(dest)
            continue
        url = (f"https://www.broadcastify.com/archives/feed/{FEED_ID}/"
               f"{FEED_ID}-{start}.mp3")
        print(f"    [ko-fetch] {start} direct", flush=True)
        _download_direct(url, dest, user, password)
        if dest.exists() and dest.stat().st_size > 50_000:
            got.append(dest)
    return got


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today()
    paths = fetch(d, Path("audio") / d.isoformat(), PACIFIC)
    print(f"fetched {len(paths)} blocks for {d}")
