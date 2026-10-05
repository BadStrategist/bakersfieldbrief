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
  * the notability floor depends on the clock. The radio feed only carries about
    21:00 -> 05:30, so rows outside those hours are the ONLY source for that part
    of the night and merge at GAP_NOTABILITY (2 = every row, routine calls
    included). Inside radio hours the transcript leads and only the serious rows
    (MIN_NOTABILITY, 3) are merged;
  * with no transcript incidents on disk it merges NOTHING: a report must never
    be built from emulator rows alone;
  * nothing here may raise. It runs inside the publish's critical path.

Deterministic, no emulator needed.

Usage: python kern_overnight/merge_crimeradar.py YYYY-MM-DD
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

# The report window is 19:00 -> 07:00, but the RADIO feed the transcript comes
# from only carries roughly 21:00 -> 05:30. Outside those hours the emulator is
# the ONLY source, so its rows merge at GAP_NOTABILITY (2 = everything,
# including the routine calls that fill the log section) instead of the
# serious-only MIN_NOTABILITY. Inside radio hours the transcript leads and the
# higher floor keeps the emulator from padding the report.
RADIO_START = dt.time(21, 0)
RADIO_END = dt.time(5, 30)
GAP_NOTABILITY = int(os.environ.get("CR_MERGE_GAP_NOTABILITY", "2"))


def in_radio_hours(hhmm: str) -> bool:
    """Is this clock time inside the hours the radio feed actually carries?

    The night crosses midnight, so radio hours are 21:00-23:59 and 00:00-05:29.
    An unreadable time is treated as radio hours: the stricter rule.
    """
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(hhmm or ""))
    if not m:
        return True
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return True
    return dt.time(h, mi) >= RADIO_START or dt.time(h, mi) < RADIO_END

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


def plan(staged: list, ours: list) -> dict:
    """Split staged rows into kept / covered / private / invalid / minor. Pure.

    The notability floor depends on the clock: serious-only inside the radio
    hours, everything outside them (see GAP_NOTABILITY). Kept rows outside the
    radio hours are reported separately as `gap` so the log stays honest about
    where the report had no radio feed to fall back on.
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
        radio = in_radio_hours(r["time"])
        floor = MIN_NOTABILITY if radio else GAP_NOTABILITY
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
        if not radio:
            gap.append(row)
    return {"transcript": transcript, "keep": keep, "covered": covered,
            "private": private, "invalid": invalid, "minor": minor, "gap": gap}


def merge(date_iso: str, incidents_dir: Path = INCIDENTS,
          stage_dir: Path = STAGE) -> dict:
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
        p = plan(staged, ours)
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


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: merge_crimeradar.py YYYY-MM-DD", file=sys.stderr)
        return 2
    r = merge(sys.argv[1])
    print(f"[cr] merge {r['date']}: {r['staged']} staged, {r['merged']} merged "
          f"({r['gap']} of them filling hours the radio feed does not carry), "
          f"{r['covered']} already covered, {r['private']} withheld (privacy), "
          f"{'file updated' if r['changed'] else 'file unchanged'} - {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
