#!/usr/bin/env python3
"""Street-name validation for Kern Overnight transcripts.

Scans a transcript JSONL (or any text file) for candidate street mentions
and checks them against the Bakersfield gazetteer (kern_overnight/streets.txt,
6,275 names from geographic.org). Outputs:

  MATCH   — name found in the gazetteer
  FUZZY   — no exact match; best fuzzy suggestion (ratio >= 0.85)
  UNKNOWN — no match and no close suggestion (likely a mis-transcription)

The morning agent runs this after transcription and uses the report to
correct street names before writing incidents.

Usage:
  python kern_overnight/streetcheck.py transcripts/2026-08-12.jsonl
  python kern_overnight/streetcheck.py --text "on the 2800 block of W Chester Av"
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

STREETS_FILE = Path(__file__).resolve().parent / "streets.txt"

_TYPE_WORDS = ("street|st|avenue|ave|blvd|boulevard|drive|dr|lane|ln|court|ct|"
               "road|rd|way|place|pl|circle|cir|loop|terrace|ter|parkway|pkwy|"
               "highway|hwy|trail|alley|walk|row|path|sq|square|plaza|landing|"
               "grove|ridge|view|crest|heights|vista|point|corner")

# candidate patterns: numbered-block, intersection, and bare name+type
# type words must be whole words (leading \b stops 'st' matching inside
# 'West'); all patterns case-insensitive since type words are lowercase
# but transcribed text is Title Case
_TYPE = r"\b(?:" + _TYPE_WORDS + r")\b"
_PATTERNS = [
    re.compile(rf"\b\d{{1,5}}\s+block of\s+([A-Za-z][\w .'-]*?(?:{_TYPE})\b)", re.I),
    re.compile(rf"\bat\s+([A-Za-z][\w .'-]*?(?:{_TYPE})\b)", re.I),
    re.compile(rf"\b([A-Z][A-Za-z]+(?:\s+[A-Za-z][\w.'-]*?){{0,3}}\s+(?:{_TYPE})\b)", re.I),
]

# Street names Whisper reliably mis-hears on the Kern feeds. The gazetteer
# spelling wins, always. Evidence: 'weibel' 25x and 'wibel' 2x across
# transcripts/, while the gazetteer holds exactly one entry, 'Wible Road'
# (Bakersfield). Never add a mapping without counting the occurrences in
# transcripts/ first.
#
# Guard rails, learned the hard way: 'Weibel' is also a local surname
# ("Megan Weibel" appears in transcripts/2026-08-14.jsonl), so a bare word
# swap corrupts names. A fold happens only in a street context:
#   A. after a locational word ("approaching Weibel", "on Weibel,")
#   B. before a street type word ("Weibel Avenue", "1914 Weibel Road")
#   C. before an intersection ("Weibel and Bell Terrace")
# Anything else, including a bare comma-separated mention, is left alone.
_MISHEARD_BASE = ("weibel", "wibel", "weible")
_MISHEARD_TYPE = (r"(?:avenue|ave|road|rd|street|st|boulevard|blvd|drive|dr|lane|ln|"
                  r"court|ct|way|place|pl|terrace|ter|parkway|pkwy)")
_MISHEARD_PREP = (r"on|at|in|near|off|of|approaching|leaving|passing|crossing|"
                  r"toward|to|from|between|behind|block of|northbound|southbound|"
                  r"eastbound|westbound|and")
_ALT = "|".join(_MISHEARD_BASE)
_MISHEARD_RE = re.compile(
    rf"\b(?P<pre>{_MISHEARD_PREP})\s+(?P<a>{_ALT})\b(?:\s+{_MISHEARD_TYPE})?"   # A
    rf"|\b(?P<b>{_ALT})\b\s+{_MISHEARD_TYPE}\b"                                  # B
    rf"|\b(?P<c>{_ALT})\b(?=\s+and\b)",                                          # C
    re.I)
_MISHEARD_TO = "Wible Road"


def _misheard_sub(m: "re.Match[str]") -> str:
    pre = m.group("pre")
    return f"{pre} {_MISHEARD_TO}" if pre else _MISHEARD_TO


def fix_text(text: str) -> str:
    """Rewrite known mis-hearings in raw ASR or incident text to the gazetteer
    spelling, but only in a street context (see the note above). Consumes a
    wrong type word, so 'Weibel Avenue' becomes 'Wible Road'."""
    if not text:
        return text
    return _MISHEARD_RE.sub(_misheard_sub, text)


def load_streets(path: Path = STREETS_FILE) -> list[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def normalize(name: str) -> str:
    """Lowercase, drop directionals/ordinal cruft, collapse spaces, and fold
    known mis-hearings onto the gazetteer spelling so those names come back as
    a MATCH instead of a low-confidence fuzzy guess."""
    n = fix_text(name)
    n = re.sub(r"\b(north|south|east|west|n|s|e|w)\b\.?", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" .,-").lower()
    # A candidate that is nothing but the mis-hearing is a street mention by
    # construction (callers pass street candidates, never lone surnames), so
    # fold it even though fix_text() needs a context word.
    if n in _MISHEARD_BASE:
        return _MISHEARD_TO.lower()
    return n


def check_name(name: str, streets: list[str], norm: dict[str, str]) -> tuple[str, str]:
    """Exact/fuzzy match; intersection phrases ('X and Y Road') pass if
    either segment matches the gazetteer."""
    segments = [s.strip() for s in re.split(r"\s+and\s+", name, flags=re.I) if s.strip()]
    for seg in segments:
        key = normalize(seg)
        if key in norm:
            return "MATCH", norm[key]
    # fuzzy over the full name, then per-segment
    for probe in [name] + segments:
        key = normalize(probe)
        best, best_ratio = "", 0.0
        for s_key, orig in norm.items():
            r = difflib.SequenceMatcher(None, key, s_key).ratio()
            if r > best_ratio:
                best, best_ratio = orig, r
            if best_ratio >= 0.95:
                break
        if best_ratio >= 0.85:
            return "FUZZY", f"{probe} -> {best} ({best_ratio:.2f})"
    return "UNKNOWN", name


_STOP_WORDS = {"the", "this", "that", "there", "units", "copy", "we've",
               "we're", "i'm", "it's", "going", "coming", "checking",
               "advising", "responding", "location", "possible", "half",
               "mile", "directly", "another", "same", "also", "and", "near",
               "off", "of", "at", "with"}


def scan(text: str, streets: list[str]) -> list[tuple[str, str, str]]:
    norm = {normalize(s): s for s in streets}
    seen, out = set(), []
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            cand = re.sub(r"\s+", " ", m.group(1)).strip()
            # strip leading connectives so 'and Wite Lane' -> 'Wite Lane'
            cand = re.sub(r"^(?:and|near|at|of|off|on)\s+", "", cand, flags=re.I)
            low = cand.lower()
            if len(cand) < 4 or low in seen:
                continue
            seen.add(low)
            # false-positive filters: sentence punctuation, block-phrases,
            # over-long captures, and leading filler words
            if any(ch in cand for ch in ".!?"):
                continue
            if " block of " in low or low.startswith("block of "):
                continue
            if len(cand.split()) > 6:
                continue
            if low.split()[0] in _STOP_WORDS:
                continue
            if re.match(r"^(one|two|three|four|five|six|seven|eight|nine|ten|zero)$",
                        low.split()[0]):
                continue  # radio prowords ('two point five') are not streets
            status, detail = check_name(cand, streets, norm)
            out.append((status, cand, detail))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", help="transcript JSONL or text file")
    ap.add_argument("--text", help="inline text to check (instead of a file)")
    args = ap.parse_args(argv)

    streets = load_streets()
    if not streets:
        print(f"streets.txt missing or empty at {STREETS_FILE}")
        return 1

    if args.text:
        text = args.text
    elif args.path:
        p = Path(args.path)
        raw = p.read_text(encoding="utf-8")
        if p.suffix == ".jsonl":
            rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
            text = "\n".join(f"{r.get('time_local','?')} | {r.get('text','')}"
                             for r in rows)
        else:
            text = raw
    else:
        ap.error("need a path or --text")

    results = scan(text, streets)
    counts = {"MATCH": 0, "FUZZY": 0, "UNKNOWN": 0}
    for status, _, _ in results:
        counts[status] += 1

    print(f"gazetteer: {len(streets)} streets | candidates: {len(results)} "
          f"| {counts['MATCH']} matched / {counts['FUZZY']} fuzzy / "
          f"{counts['UNKNOWN']} unknown")
    for status, cand, detail in results:
        if status != "MATCH":
            print(f"  {status}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
