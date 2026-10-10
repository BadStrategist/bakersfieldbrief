#!/usr/bin/env python3
"""Deterministic incident extraction from Kern Overnight transcript digests.

The LLM phase-2 agent currently reads the digest and writes incidents from
scratch (the token- and time-heavy step). This module does the mechanical
80% with rules: type taxonomy, agency, area (via the street gazetteer),
notability heuristic, disposition, and dedupe. The agent then REVIEWS the
draft instead of writing it — the hybrid pattern.

Output incidents match the site schema:
  {type, time, agency, area, notability 1-5, disposition, summary}

Usage:
  python -c "from kern_overnight.extract import extract; ..."
"""
from __future__ import annotations

import re
from pathlib import Path

# keyword rule → display type (first match wins; order matters)
TYPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bstructure fire\b"), "structure fire"),
    (re.compile(r"\bvehicle fire\b"), "vehicle fire"),
    (re.compile(r"\bgrass fire\b"), "grass fire"),
    (re.compile(r"\bvegetation fire\b"), "vegetation fire"),
    (re.compile(r"\boutside fire\b"), "outside fire"),
    (re.compile(r"\belectrical fire\b"), "electrical fire"),
    (re.compile(r"\bfire alarm\b"), "commercial fire alarm"),
    (re.compile(r"\bfire\b"), "fire"),
    (re.compile(r"\bshooting\b"), "shooting"),
    (re.compile(r"\bstabbing\b|\bassault\b"), "assault with a weapon"),
    (re.compile(r"\bburglary\b"), "burglary"),
    (re.compile(r"\bhit[- ]and[- ]run\b"), "hit and run"),
    (re.compile(r"\bdomestic\b"), "domestic call"),
    (re.compile(r"\breckless\b"), "reckless driver"),
    (re.compile(r"\bfoot pursuit\b"), "foot pursuit"),
    (re.compile(r"\bwarrant\b"), "warrant service"),
    (re.compile(r"\bprobation\b"), "probation check"),
    (re.compile(r"\bsuspicious\b"), "suspicious person report"),
    (re.compile(r"\bstolen firear"), "stolen firearms search"),
    (re.compile(r"\bcode 33\b|\bofficer assist\b"), "officer assist"),
    (re.compile(r"\bmedical aid\b|\bmedical\b|\bambulance\b"), "medical aid"),
    (re.compile(r"\bman down\b"), "man down"),
    (re.compile(r"\bmental health\b|\bsuicidal\b"), "mental health crisis"),
    (re.compile(r"\bwelfare\b"), "welfare call"),
    (re.compile(r"\btheft\b|\bstolen\b"), "burglary"),
    (re.compile(r"\bpedestrian\b|\bvehicle vs\b"), "vehicle vs pedestrian"),
    (re.compile(r"\bcollision\b|\bcrash\b|\baccident\b"), "traffic collision"),
]

AGENCY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bkern county fire\b|\bkcfd\b"), "Kern County Fire Department"),
    (re.compile(r"\bsheriff\b|\bkcco\b"), "Kern County Sheriff's Office"),
    (re.compile(r"\bbpd\b|\bpolice\b"), "Bakersfield Police Department"),
    (re.compile(r"\bchp\b|\bhighway patrol\b"), "California Highway Patrol"),
    (re.compile(r"\bhall\b|\bambulance\b"), "Hall Ambulance"),
]

NOTABILITY_RULES: list[tuple[int, re.Pattern]] = [
    (5, re.compile(r"\bhelicopter\b|\bair attack\b|\bdozer\b|\b50% involvement\b")),
    (4, re.compile(r"\bfully involved\b|\bmutual aid\b|\bmultiple (?:units|engines)\b")),
    (3, re.compile(r"\bstructure\b|\bworking fire\b|\bcode 3\b")),
    (2, re.compile(r"\bvehicle\b|\bpedestrian\b|\binjury\b")),
]

DISP_RULES: list[tuple[str, re.Pattern]] = [
    ("cleared", re.compile(r"\bcode 4\b|\bcleared\b|\bunfounded\b")),
    ("cancelled", re.compile(r"\bcancell?ed\b|\bdisregard\b")),
    ("active", re.compile(r"\bcode 3\b|\ben route\b|\bresponding\b")),
]

# rows that are almost never incidents (radio chatter / coordination)
_SKIP_TEXT = re.compile(
    r"\btest\b|\bradio check\b|\b10-?9\b|\bcode 33\b.*\bclear\b|"
    r"\bpatrol(?:ing)?\b|\bchecking (?:on|the) (?:alley|area)\b|"
    r"\bphone (?:number|calls?)\b|\b(?:cell|work) phone\b", re.I)

from kern_overnight.privacy import ALWAYS_PRIVATE  # noqa: E402  one rule, one place

# privacy: rows carrying names/numbers/plates are skipped as sources
_PRIVACY = re.compile(
    r"\b\d{3}[-.) ]?\d{3}[-.) ]?\d{4}\b|"           # phone
    r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{5,7}\b|"            # plate-like (needs a digit)
    r"\bsocial security\b|born (?:in )?\d|"
    r"\bpatient(?: name)? is\b|victim(?:'s)? name\b", re.I)


def _extract_row(row: dict, streets: list[str]) -> dict | None:
    """One digest row → incident dict, or None if it's not incident material."""
    text = row.get("text", "")
    if len(text) < 25:
        return None
    if _SKIP_TEXT.search(text) or _PRIVACY.search(text):
        return None
    # The same hard rule the app rows get. A radio row carried a wrist wound
    # with a block address on 2026-10-10 and nothing screened it, because the
    # rule only ran over the emulator feed.
    if ALWAYS_PRIVATE.search(text):
        return None

    typ = next((t for p, t in TYPE_RULES if p.search(text)), None)
    if not typ:
        return None
    agency = next((a for p, a in AGENCY_RULES if p.search(text)), "Dispatch")
    notability = max((n for n, p in NOTABILITY_RULES if p.search(text)),
                     default=1)
    disp = next((d for d, p in DISP_RULES if p.search(text)), "active")

    area = ""
    from . import streetcheck as SC  # local import: gazetteer is heavy
    res = SC.scan(text, streets)
    for status, cand, detail in res:
        if status == "MATCH":
            area = detail
            break
        if status == "FUZZY":
            area = detail.split(" -> ")[-1].split(" (")[0]
            break
    if not area:
        area = "Bakersfield"

    return {
        "type": typ,
        "time": row.get("time_local", ""),
        "agency": agency,
        "area": area,
        "notability": notability,
        "disposition": disp,
        "summary": f"{typ}, {area} ({row.get('time_local', '')})",
        "_src": row.get("text", "")[:120],
    }


def _dedupe(incs: list[dict], window_min: int = 15) -> list[dict]:
    """Merge same-type+area incidents within the window; keep highest
    notability and earliest time."""
    merged: list[dict] = []
    for inc in sorted(incs, key=lambda i: (i["time"], -i["notability"])):
        absorbed = False
        for m in merged:
            if m["type"] != inc["type"] or m["area"] != inc["area"]:
                continue
            try:
                t1 = int(m["time"].split(":")[0]) * 60 + int(m["time"].split(":")[1])
                t2 = int(inc["time"].split(":")[0]) * 60 + int(inc["time"].split(":")[1])
            except (ValueError, IndexError):
                continue
            if abs(t1 - t2) <= window_min:
                m["notability"] = max(m["notability"], inc["notability"])
                m["_n"] = m.get("_n", 1) + 1
                absorbed = True
                break
        if not absorbed:
            inc["_n"] = 1
            merged.append(inc)
    return merged


def extract(rows: list[dict], streets: list[str] | None = None) -> list[dict]:
    """Digest rows → deduped incident list (LLM-ready draft)."""
    if streets is None:
        from . import streetcheck as SC
        streets = SC.load_streets()
    incs = []
    for r in rows:
        inc = _extract_row(r, streets)
        if inc:
            incs.append(inc)
    return _dedupe(incs)


if __name__ == "__main__":
    # The README documents `python -m kern_overnight.extract <date>` as stage 3 of
    # the per-stage workflow, but this module had no __main__, so the documented
    # command silently did nothing and exited 0 — a maintainer would believe the
    # incidents had been regenerated when no file was written. Mirror write.py's
    # harness: load the transcript, extract, write incidents/<date>.json.
    import datetime as _dt
    import json as _json
    import sys as _sys

    date = (_dt.date.fromisoformat(_sys.argv[1]) if len(_sys.argv) > 1
            else _dt.date.today())
    src = Path("transcripts") / f"{date.isoformat()}.jsonl"
    if not src.exists():
        _sys.exit(f"no transcript at {src} — run fetch/transcribe first")
    # Lazy import: run.py imports this module at load time, so importing it at
    # module scope here would be circular. Deferred, it is safe.
    from .run import _usable_rows
    rows = _usable_rows(src)
    if not rows:
        _sys.exit(f"no usable rows in {src.name}")
    incs = extract(rows)
    out = Path("incidents") / f"{date.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(incs, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"{len(incs)} incidents → {out}")
