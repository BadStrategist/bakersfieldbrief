#!/usr/bin/env python3
"""Stage 5 — RUN: orchestrate fetch → transcribe → extract → write → deliver.

Usage:  python -m kern_overnight.run [YYYY-MM-DD]   (default: last night)
Designed for cron at 06:15 America/Los_Angeles. Fails loudly at every stage —
an empty or broken brief is never produced silently.

Directory layout (repo root):
  audio/DATE/  transcripts/DATE.jsonl  incidents/DATE.json  briefs/DATE.md
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kern_overnight import fetch as ko_fetch        # noqa: E402
from kern_overnight import transcribe as ko_stt     # noqa: E402
from kern_overnight import extract as ko_extract    # noqa: E402
from kern_overnight import write as ko_write        # noqa: E402

DEFAULT_TZ = dt.timezone(dt.timedelta(hours=-7), "PDT")  # Pacific (DST, Aug)


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    while d.weekday() != 6:
        d += dt.timedelta(days=1)
    return d + dt.timedelta(weeks=n - 1)


def pacific_tz(day: dt.date) -> dt.tzinfo:
    """America/Los_Angeles offset for the day (PST -8 / PDT -7)."""
    start = _nth_sunday(day.year, 3, 2)   # second Sunday of March
    end = _nth_sunday(day.year, 11, 1)    # first Sunday of November
    if start <= day < end:
        return dt.timezone(dt.timedelta(hours=-7), "PDT")
    return dt.timezone(dt.timedelta(hours=-8), "PST")


def _usable_rows(transcript: Path) -> list[dict]:
    """Load a transcript JSONL into digest-style rows (conf > -0.45, len > 30),
    matching the deterministic extraction that runs on real digest rows."""
    import json as _json
    rows = []
    if not transcript.exists():
        return rows
    for ln in transcript.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = _json.loads(ln)
        except _json.JSONDecodeError:
            continue
        text = (r.get("text") or "").strip()
        if r.get("confidence", 0.0) > -0.45 and len(text) > 30:
            rows.append(r)
    return rows


KNOWN_FLAGS = {"--phase1", "--phase2", "--extract-only"}


def main(argv: list[str]) -> int:
    # An unknown flag used to be IGNORED, so the run fell through to the FULL
    # pipeline: fetch + transcribe, and the transcribe opens the JSONL in mode
    # "w" and TRUNCATES it. A typo (`--phase-1`, `--phse1`) therefore silently
    # wiped a good night's transcript. Hit for real 2026-10-03 from a probe that
    # passed a bogus flag. Refuse instead of guessing.
    unknown = [a for a in argv[1:] if a.startswith("--") and a not in KNOWN_FLAGS]
    if unknown:
        print(f"[ko] FATAL: unknown flag(s): {' '.join(unknown)}", file=sys.stderr)
        print(f"[ko] known flags: {' '.join(sorted(KNOWN_FLAGS))} "
              f"(a positional argument is an ISO date)", file=sys.stderr)
        print("[ko] refusing to run: unknown flags used to fall through to the "
              "full pipeline, which truncates the transcript.", file=sys.stderr)
        return 2

    date = dt.date.today()
    phase1 = "--phase1" in argv
    phase2 = "--phase2" in argv
    extract_only = "--extract-only" in argv
    for a in argv[1:]:  # positional args are dates; flags never parsed as dates
        if not a.startswith("--"):
            date = dt.date.fromisoformat(a)
    tz = pacific_tz(date)
    d = date.isoformat()

    audio_dir = ROOT / "audio" / d
    transcript = ROOT / "transcripts" / f"{d}.jsonl"
    incidents = ROOT / "incidents" / f"{d}.json"
    brief = ROOT / "briefs" / f"{d}.md"

    # ---- 0 EXTRACT-ONLY: turn an ALREADY-ON-DISK transcript into incidents.
    # Never re-fetch or re-transcribe (the ~60-min hang when a publish job found
    # incidents missing but a full transcript already existed). Only stages 3-5.
    if extract_only:
        print(f"[ko] extract-only {d} from existing transcript", flush=True)
        rows = _usable_rows(transcript)
        print(f"[ko]     {len(rows)} usable transcript rows", flush=True)
        if not rows:
            print(f"[ko] FATAL: no usable rows in {transcript.name}", file=sys.stderr)
            return 1
        incs = ko_extract.extract(rows)
        print(f"[ko]     {len(incs)} incidents", flush=True)
        incidents.parent.mkdir(parents=True, exist_ok=True)
        incidents.write_text(json.dumps(incs, indent=1, ensure_ascii=False),
                             encoding="utf-8")
        print(f"[ko] wrote incidents/{d}.json ({len(incs)})", flush=True)
        return 0

    # ---- 1 FETCH
    print(f"[ko] 1/5 fetch feed {ko_fetch.FEED_ID} for {d} ({tz.tzname(None)})", flush=True)
    blocks = ko_fetch.fetch(date, audio_dir, tz)
    print(f"[ko]     {len(blocks)} audio blocks", flush=True)

    # ---- 2 TRANSCRIBE
    print("[ko] 2/5 transcribe", flush=True)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    vocab = ko_stt.load_vocab(ROOT / "kern_overnight" / "vocab.txt")
    # BOTH phases are incremental runs: append=False rewrites the file, so a
    # phase-1 retry on its own would truncate the transcript and delete every
    # tail row a previous phase-2 run had added.
    n_rows = ko_stt.transcribe(audio_dir, transcript, tz, vocab,
                               append=phase1 or phase2)
    print(f"[ko]     {n_rows} transmissions", flush=True)

    if phase1 or phase2:
        phase = "1 (early blocks)" if phase1 else "2 (tail blocks)"
        print(f"[ko] transcribe-only phase {phase} done: {n_rows} new rows "
              f"→ {transcript.name}", flush=True)
        return 0

    # ---- 3 EXTRACT
    print("[ko] 3/5 extract incidents (LLM)", flush=True)
    # extract() takes digest ROWS, not paths. Passing the transcript/incidents
    # Paths here crashed stage 3 with "TypeError: 'WindowsPath' object is not
    # iterable" on every full (non --extract-only) run, so stages 4-5 never ran.
    # Use the same loader as the --extract-only path so both agree.
    incs = ko_extract.extract(_usable_rows(transcript))
    print(f"[ko]     {len(incs)} incidents", flush=True)

    # ---- 4 WRITE
    print("[ko] 4/5 write brief (LLM)", flush=True)
    text = ko_write.write_brief(incs, date)

    # ---- 5 DELIVER (draft for human review — nothing auto-publishes)
    print("[ko] 5/5 deliver draft", flush=True)
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text(text, encoding="utf-8")
    print(f"[ko] DONE → {brief.relative_to(ROOT)} ({len(text)} chars)", flush=True)
    print("[ko] draft ready for human review; nothing published.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
