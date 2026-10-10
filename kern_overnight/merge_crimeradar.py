"""Merge the CrimeRadar emulator's overnight incidents into incidents/<date>.json.

WHY THIS EXISTS: the publish extracts incidents/<date>.json from the transcript
and REWRITES the file. Anything written into it earlier is lost. So the emulator
rows are staged first (crimeradar_monitor.py --emit) and merged here, after the
extraction, as an explicit step.

The staging file carries EVERY app row in the report window (19:00 -> 07:00).
This step decides which of them the transcript already covers, because only now
does the transcript's incident list exist. Rules:

  * the transcript's own rows are never touched;
  * the emulator section is REBUILT on every run (transcript rows + the staged
    rows that survive the filters), so the merge is idempotent and re-running it
    after a re-extraction puts the rows back;
  * a staged row is dropped when a transcript incident near the same time shares
    its distinctive words (already covered), or when it trips the privacy rules
    the report enforces (patient / hospital / self-harm traffic);
  * the notability floor depends on what the transcript covers. The radio window
    is not a constant: it is the spans the transcript's own blocks give
    (radio_spans), so the evening and morning shoulders count as radio hours the
    moment their blocks arrive. Rows outside those spans are the ONLY source for
    that part of the night and merge at GAP_NOTABILITY (2 = every row, routine
    calls included). Inside them the transcript leads and only the serious rows
    (MIN_NOTABILITY, 3) are merged. No readable transcript: no radio hours at
    all, so every hour is a gap hour;
  * with no transcript incidents on disk it merges NOTHING: a report must never
    be built from emulator rows alone;
  * a staging file that does not carry the Kern feed the screen showed merges
    NOTHING: the app follows its own location picker, and on 2026-10-09 it was
    serving Mendocino County;
  * nothing here may raise. It runs inside the publish's critical path.

readiness() answers a different question from merge(): is there a verified
second source for this report at all? The publish gate asks it (gate(), which
also honours the human release file). Exit codes of --ready / --gate:
0 ready (or released), 10 absent, 11 stale, 12 wrong feed, 13 History did not
reach the window start.

Deterministic, no emulator needed.

Usage: python kern_overnight/merge_crimeradar.py YYYY-MM-DD
       python kern_overnight/merge_crimeradar.py --ready YYYY-MM-DD
       python kern_overnight/merge_crimeradar.py --gate YYYY-MM-DD
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS = ROOT / "incidents"
STAGE = ROOT / "work" / "crimeradar"

SOURCE = "crimeradar"

# The one feed this report may take rows from, as the app's Replay tab names it.
# The monitor stamps what the screen actually said; nothing here assumes it.
FEED_NAME = "Bakersfield Police, Fire and EMS"
FEED_LOCATION = "Kern, California"

READY, ABSENT, STALE, WRONG_FEED, INCOMPLETE = 0, 10, 11, 12, 13
# The emit runs at 07:15 and the app aggregates with a lag, so a good staging
# file is written after the night ends and its newest row is from the small
# hours. One written before 06:30, or whose newest row is older than 04:00, did
# not see the end of the night (2026-10-09: the guest had lost its network).
EMIT_EARLY_MIN = 30
NEWEST_LAG_MIN = 180


def is_kern_feed(feed) -> bool:
    """Did the screen say this is the Kern feed? Anything else is not."""
    return (isinstance(feed, dict) and feed.get("name") == FEED_NAME
            and feed.get("location") == FEED_LOCATION)

# Words too common in dispatch headlines to prove two rows are the same event.
STOP = {
    "reported", "report", "reports", "possible", "possibly", "person", "people",
    "police", "county", "area", "near", "after", "with", "from", "that", "this",
    "been", "into", "call", "caller", "units", "unit", "responding", "requested",
    "request", "check", "incident", "bakersfield", "kern", "street", "avenue",
    "road", "drive", "lane", "boulevard", "block", "north", "south", "east",
    "west", "officers", "officer", "deputies", "scene", "about", "while", "said",
    "were", "they", "their", "have", "issue", "highway", "city", "home",
    "single", "vehicle", "vehicles", "found", "stop", "main", "traffic",
    "northbound", "southbound", "eastbound", "westbound", "male", "female",
}

# Staged rows below this notability are not merged. 3 (default) merges only the
# serious rows; 2 would also merge routine ones (traffic stops) as log lines.
MIN_NOTABILITY = int(os.environ.get("CR_MERGE_MIN_NOTABILITY", "3"))

# The report window is 19:00 -> 07:00. Which of those hours the RADIO feed
# actually carries is not a constant anywhere: it is whatever the transcript for
# this report covers. The spans are therefore read from the transcript's own rows
# (radio_spans), never assumed. Outside them the emulator is the ONLY source, so
# its rows merge at GAP_NOTABILITY (2 = everything, including the routine calls
# that fill the log section) instead of the serious-only MIN_NOTABILITY.
GAP_NOTABILITY = int(os.environ.get("CR_MERGE_GAP_NOTABILITY", "2"))

# One RadioReference archive block: 30.5 minutes, measured across a night.
BLOCK_SECONDS = 1829

# The night is local Pacific. This mirrors fetch.PACIFIC (a fixed -7 offset; the
# runner adjusts for DST) so this module stays importable on its own, which is
# how the monitor and the tests load it.
PACIFIC = dt.timezone(dt.timedelta(hours=-7), "PDT")

TRANSCRIPTS = ROOT / "transcripts"


def _block_epoch(source_file) -> int | None:
    """The epoch a transcript row's `source_file` names: `<feed>-<epoch>.mp3`."""
    m = re.search(r"-(\d{9,11})\.\w+$", str(source_file or ""))
    return int(m.group(1)) if m else None


def radio_spans(date_iso: str,
                transcript_dir: Path = TRANSCRIPTS) -> list[tuple[int, int]]:
    """The stretches of the night the radio transcript for <date> covers.

    Read from the transcript itself: every row names the block it came from
    (`<feed>-<epoch>.mp3`), and those epochs are the only honest statement of
    which blocks arrived. A block is BLOCK_SECONDS long. No transcript, or no
    parseable epochs: an empty list, which makes every hour a gap hour.
    """
    spans = set()
    try:
        lines = (Path(transcript_dir) / f"{date_iso}.jsonl").read_text(
            encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return []
    for line in lines:
        try:
            epoch = _block_epoch(json.loads(line).get("source_file"))
        except Exception:  # noqa: BLE001
            continue
        if epoch is not None:
            spans.add((epoch, epoch + BLOCK_SECONDS))
    return sorted(spans)


def _night_instant(hhmm: str, date_iso: str) -> float | None:
    """The instant a clock time names in the night of report <date_iso>."""
    m = minutes(hhmm)
    if m is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso or ""):
        return None
    night = dt.date.fromisoformat(date_iso) - dt.timedelta(days=1)
    h, mi = divmod(m, 60)
    d = night if h >= 19 else night + dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time(h, mi), PACIFIC).timestamp()


def in_radio(hhmm: str, spans: list[tuple[int, int]] | None,
             date_iso: str = "") -> bool:
    """Is this clock time inside a stretch the transcript actually covers?

    No spans means no readable transcript, so nothing is radio: every hour is a
    gap hour and the emulator merges at GAP_NOTABILITY. An unreadable time is
    treated as radio: the stricter floor.
    """
    instant = _night_instant(hhmm, date_iso)
    if instant is None:
        return True
    return any(a <= instant < b for a, b in (spans or []))

# The report's privacy HARD RULES: no patient details, nothing from
# ambulance-to-hospital traffic. An app headline is published as-is, so a row
# that breaks them is dropped rather than rewritten. Editorial rule (owner,
# 2026-10-04): most medical calls stay out; a SEVERE one is news and stays in.
#
# Never published, however serious: self-harm, mental-health and maternity calls.
ALWAYS_PRIVATE = re.compile(
    r"\b(suicid\w*|self[- ]harm\w*|psychiatric|mental health|5150|delusion\w*|"
    r"maternity|pregnan\w*|in labor)\b", re.I)
# Routine medical traffic: out unless the same headline is also SEVERE.
MEDICAL = re.compile(
    r"\b(patient|hospital|ambulance|medical|overdos\w*|seizure\w*|cardiac|"
    r"breathing|unresponsive|unconscious|cpr|pain|traumatic|ill|sick|fainted|"
    r"mercy|memorial|adventist|kaiser|dignity health|kern medical)\b", re.I)
SEVERE = re.compile(
    r"\b(cpr|unconscious|unresponsive|not breathing|cardiac arrest|drown\w*|"
    r"fatal\w*|dead|deceased|doa|life[- ]threatening|critical(?:ly)?|"
    r"major injur\w*|traumatic injur\w*|shot|gunshot|stabb\w*|electrocut\w*|"
    r"burn(?:ed|s)? victim)\b", re.I)

# "1234 Main St" -> "Main St": exact addresses are generalised, never published.
HOUSE_NO = re.compile(r"\b\d{2,5}\s+(?=(?:[NSEW]\.?\s+)?[A-Z][a-z])")


def fp(hhmm: str, text: str) -> str:
    """Fingerprint an incident by clock time plus its first distinctive words."""
    return f"{hhmm}|{' '.join(re.findall(r'[a-z]{4,}', text.lower())[:3])}"


def _stem(w: str) -> str:
    """crash/crashed/crashes/crashing -> crash; chest and chestnut stay apart."""
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[:-len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


def stems(text: str) -> set[str]:
    """Distinctive word stems of a headline or summary."""
    return {_stem(w) for w in re.findall(r"[a-z]{4,}", (text or "").lower())
            if w not in STOP}


def minutes(hhmm: str) -> int | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(hhmm or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if h < 24 and mi < 60 else None


def gap(a: str, b: str) -> int | None:
    """Minutes between two clock times; the night crosses midnight."""
    x, y = minutes(a), minutes(b)
    if x is None or y is None:
        return None
    d = abs(x - y)
    return min(d, 1440 - d)


def covered_by(hhmm: str, title: str, transcript: list[dict],
               wide: int = 60, tight: int = 15) -> dict | None:
    """The transcript incident that already covers this app row, or None.

    Matched per incident, not against the whole night's vocabulary: two shared
    stems within `wide` minutes, or one within `tight` minutes.
    """
    want = stems(title)
    if not want:
        return None
    for inc in transcript:
        if not isinstance(inc, dict):
            continue
        d = gap(hhmm, inc.get("time", ""))
        if d is None or d > wide:
            continue
        hits = want & stems(f"{inc.get('type', '')} {inc.get('summary', '')} "
                            f"{inc.get('area', '')}")
        if len(hits) >= 2 or (hits and d <= tight):
            return inc
    return None


def is_severe(text: str) -> bool:
    return bool(SEVERE.search(text or ""))


def is_private(text: str, medical: bool = False) -> bool:
    """Must this headline stay out of the report and the reels?

    `medical` marks a row the app itself filed as a medical emergency, for
    headlines that carry no medical word ("Person down near park").
    """
    text = text or ""
    if ALWAYS_PRIVATE.search(text):
        return True
    return bool(medical or MEDICAL.search(text)) and not is_severe(text)


def scrub(text: str) -> str:
    return HOUSE_NO.sub("", text or "")


def _write_atomic(dest: Path, data) -> None:
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dest)


def plan(staged: list, ours: list, spans: list[tuple[int, int]] | None = None,
         date_iso: str = "") -> dict:
    """Split staged rows into kept / covered / private / invalid / minor. Pure.

    The notability floor depends on the spans the radio transcript covers:
    serious-only inside them, everything outside them (see GAP_NOTABILITY). With
    no spans every hour is a gap hour. Kept rows outside the spans are reported
    separately as `gap` so the log stays honest about where the report had no
    radio feed to fall back on.
    """
    transcript = [i for i in ours
                  if not (isinstance(i, dict) and i.get("source") == SOURCE)]
    keep, covered, private, invalid, minor, gap, seen = [], [], [], [], [], [], set()
    for r in staged:
        if not isinstance(r, dict) or minutes(r.get("time", "")) is None \
                or not str(r.get("summary") or "").strip():
            invalid.append(r)
            continue
        if is_private(r["summary"]):
            private.append(r)
            continue
        hot = in_radio(r["time"], spans, date_iso)
        floor = MIN_NOTABILITY if hot else GAP_NOTABILITY
        try:
            if int(r.get("notability", 2)) < floor:
                minor.append(r)
                continue
        except (TypeError, ValueError):
            pass
        if covered_by(r["time"], r["summary"], transcript):
            covered.append(r)
            continue
        k = fp(r["time"], r["summary"])
        if k in seen:
            continue
        seen.add(k)
        row = dict(r)
        row["summary"] = scrub(row["summary"])
        row["area"] = scrub(str(row.get("area") or ""))
        row["source"] = SOURCE
        keep.append(row)
        if not hot:
            gap.append(row)
    return {"transcript": transcript, "keep": keep, "covered": covered,
            "private": private, "invalid": invalid, "minor": minor, "gap": gap}


def merge(date_iso: str, incidents_dir: Path = INCIDENTS,
          stage_dir: Path = STAGE,
          transcript_dir: Path | None = None) -> dict:
    """Rebuild the emulator section of incidents/<date>.json. Never raises."""
    out = {"date": date_iso, "staged": 0, "merged": 0, "covered": 0,
           "private": 0, "gap": 0, "changed": False, "note": ""}
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso or ""):
            out["note"] = "bad date"
            return out
        src = Path(stage_dir) / f"emulator_incidents_{date_iso}.json"
        dest = Path(incidents_dir) / f"{date_iso}.json"
        if not src.exists():
            out["note"] = "no staged emulator incidents, nothing to do"
            return out
        try:
            doc = json.loads(src.read_text(encoding="utf-8"))
            staged = doc.get("incidents", []) if isinstance(doc, dict) else None
        except Exception as exc:  # noqa: BLE001
            out["note"] = f"staging file unreadable ({exc}); merging nothing"
            return out
        if not isinstance(staged, list):
            out["note"] = "staging file malformed; merging nothing"
            return out
        out["staged"] = len(staged)
        if not is_kern_feed(doc.get("feed")):
            out["note"] = (f"staging file is not stamped with the Kern feed "
                           f"(feed: {doc.get('feed')!r}); merging nothing")
            return out
        if not dest.exists():
            out["note"] = f"{dest.name} does not exist yet; merging nothing"
            return out
        try:
            ours = json.loads(dest.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            out["note"] = f"{dest.name} unreadable ({exc}); merging nothing"
            return out
        if not isinstance(ours, list):
            out["note"] = f"{dest.name} is not a list; merging nothing"
            return out
        spans = radio_spans(date_iso, transcript_dir or TRANSCRIPTS)
        p = plan(staged, ours, spans, date_iso)
        out.update(covered=len(p["covered"]), private=len(p["private"]),
                   gap=len(p["gap"]))
        if not p["transcript"]:
            out["note"] = (f"{dest.name} has no transcript incidents; refusing to "
                           "build a report from emulator rows alone")
            return out
        new = p["transcript"] + p["keep"]
        out["merged"] = len(p["keep"])
        if new != ours:
            _write_atomic(dest, new)
            out["changed"] = True
        out["note"] = (f"{len(p['transcript'])} transcript + {len(p['keep'])} emulator "
                       f"({len(p['gap'])} filling hours the radio feed does not carry)")
    except Exception as exc:  # noqa: BLE001
        out["note"] = f"merge failed ({exc}); nothing merged"
    return out


def _when(text) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text))
    except ValueError:
        return None


def readiness(date_iso: str, stage_dir: Path = STAGE) -> dict:
    """Is there a verified second source for the report dated <date_iso>?

    `code` is READY (0) or the first reason it is not: ABSENT, STALE,
    WRONG_FEED, INCOMPLETE. Never raises. When the staging file is missing, the
    reason quotes emit_status_<date>.json so a failed emit reads differently
    from an emit that never ran.
    """
    out = {"date": date_iso, "code": ABSENT, "ok": False, "reason": "", "feed": None}
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso or ""):
            out["reason"] = "bad date"
            return out
        src = Path(stage_dir) / f"emulator_incidents_{date_iso}.json"
        if not src.exists():
            why = "the emit left no status file, so it never reached the monitor"
            try:
                st = json.loads((Path(stage_dir) / f"emit_status_{date_iso}.json")
                                .read_text(encoding="utf-8"))
                why = (f"the emit at {st.get('ran', '?')} exited {st.get('rc', '?')} "
                       f"({st.get('outcome', '?')}): {st.get('reason', '')}")
            except Exception:  # noqa: BLE001
                pass
            out["reason"] = f"no staged emulator incidents; {why}"
            return out
        try:
            doc = json.loads(src.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            out["reason"] = f"staging file unreadable ({exc})"
            return out
        if not isinstance(doc, dict) or not isinstance(doc.get("incidents"), list):
            out["reason"] = "staging file malformed"
            return out
        out["feed"] = doc.get("feed")
        if not is_kern_feed(doc.get("feed")):
            out.update(code=WRONG_FEED, reason=(
                f"staged rows are not from the Kern feed (the screen said "
                f"{doc.get('feed')!r})"))
            return out
        end = dt.datetime.combine(dt.date.fromisoformat(date_iso), dt.time(7, 0))
        made, newest = _when(doc.get("generated")), _when(doc.get("history_newest"))
        if doc.get("date") != date_iso or made is None or made.date() != end.date() \
                or made < end - dt.timedelta(minutes=EMIT_EARLY_MIN):
            out.update(code=STALE, reason=(
                f"staging file was generated {doc.get('generated')!r} for "
                f"{doc.get('date')!r}, not after the night of {date_iso} ended"))
            return out
        if newest is None or newest < end - dt.timedelta(minutes=NEWEST_LAG_MIN):
            out.update(code=STALE, reason=(
                f"newest History row is {doc.get('history_newest')!r}; the app "
                "had stopped updating before the night ended"))
            return out
        if doc.get("history_complete") is not True:
            out.update(code=INCOMPLETE, reason=(
                f"History only reached back to {doc.get('history_oldest')!r}; "
                "the start of the night is not staged"))
            return out
        out.update(code=READY, ok=True, reason=(
            f"{len(doc['incidents'])} rows staged from {FEED_NAME}, "
            f"History {doc.get('history_oldest')} to {doc.get('history_newest')}"))
    except Exception as exc:  # noqa: BLE001
        out.update(code=ABSENT, ok=False, reason=f"readiness check failed ({exc})")
    return out


def gate(date_iso: str, stage_dir: Path = STAGE) -> dict:
    """May the report dated <date_iso> be pushed? readiness(), or a human release.

    The release is a non-empty file work/crimeradar/release_<date>.txt (say who
    and why in it). It is scoped to one date, so yesterday's release never
    carries a later report out. Never raises.
    """
    r = readiness(date_iso, stage_dir)
    r["released_by"] = "second source" if r["ok"] else ""
    if not r["ok"]:
        try:
            flag = Path(stage_dir) / f"release_{date_iso}.txt"
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso or "") \
                    and flag.read_text(encoding="utf-8").strip():
                r["released_by"] = flag.name
        except Exception:  # noqa: BLE001
            pass
    r["release"] = bool(r["released_by"])
    return r


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] in ("--ready", "--gate"):
        r = (gate if sys.argv[1] == "--gate" else readiness)(sys.argv[2])
        if r["ok"]:
            print(f"[cr] second source ready for {r['date']}: {r['reason']}")
            return READY
        print(f"[cr] second source NOT ready for {r['date']} "
              f"(code {r['code']}): {r['reason']}")
        if r.get("release"):
            print(f"[cr] released by a human: {r['released_by']}")
            return READY
        return r["code"]
    if len(sys.argv) < 2:
        print("usage: merge_crimeradar.py [--ready|--gate] YYYY-MM-DD", file=sys.stderr)
        return 2
    r = merge(sys.argv[1])
    print(f"[cr] merge {r['date']}: {r['staged']} staged, {r['merged']} merged "
          f"({r['gap']} of them filling hours the radio feed does not carry), "
          f"{r['covered']} already covered, {r['private']} withheld (privacy), "
          f"{'file updated' if r['changed'] else 'file unchanged'} - {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
