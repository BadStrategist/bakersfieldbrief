#!/usr/bin/env python3
"""Which part of Bakersfield a street is in. The only source for that claim.

The 2026-10-09 report led with "Two shot on Pembroke Avenue in southwest
Bakersfield". Pembroke Avenue is north of the river, off Olive Drive. Nothing
in the incident data said "southwest": the writer guessed. A part of town is a
fact, so it comes from here, never from the model.

The six parts of town (owner's list, 2026-10-09) and the phrase used in copy:

  NW  Northwest / Rosedale          "northwest Bakersfield"
      Rosedale, Riverlakes Ranch, Fruitvale, Greenacres
  SW  Southwest                     "southwest Bakersfield"
      Seven Oaks, Belcourt, Haggin Oaks, Laurelglen, Stockdale Estates,
      Olde Stockdale
  E   East Bakersfield / Eastside   "east Bakersfield"
      Old Town Kern, Bakersfield Country Club, College Heights, East Niles
  C   Central & Downtown            "central Bakersfield"
      Downtown, Westchester, Oleander / Sunset
  N   North Bakersfield & Oildale   "north Bakersfield"
      Oildale, the Olive Drive area
  S   Southeast & South             "south Bakersfield"
  SE  Southeast & South             "southeast Bakersfield"
      Greenfield, Cottonwood, Casa Loma

street_regions.json maps every street in the City of Bakersfield Streets layer
to its part of town, by block where a street crosses a line. The lines
themselves, and the rebuild, live in scripts/build_street_regions.py.

No answer beats a wrong one: an unknown street, a block the table does not
cover, or a name that exists in two parts of town all return None, and the
report then names no part of town.

    python kern_overnight/regions.py lookup "5400 block of Pembroke Avenue"
    python kern_overnight/regions.py annotate incidents/2026-10-09.json
    python kern_overnight/regions.py check <report.md> <incidents.json> [--fix]
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

TABLE_FILE = Path(__file__).resolve().parent / "street_regions.json"

PHRASE = {
    "NW": "northwest Bakersfield", "SW": "southwest Bakersfield",
    "N": "north Bakersfield", "C": "central Bakersfield",
    "E": "east Bakersfield", "S": "south Bakersfield",
    "SE": "southeast Bakersfield",
}

_ABBR = {
    "st": "street", "ave": "avenue", "av": "avenue", "rd": "road",
    "dr": "drive", "ln": "lane", "ct": "court", "pl": "place",
    "hwy": "highway", "blvd": "boulevard", "cir": "circle", "pkwy": "parkway",
    "ter": "terrace", "north": "n", "south": "s", "east": "e", "west": "w",
    "mount": "mt",
}
_TYPES = set("street drive avenue road court way lane place highway boulevard "
             "circle loop parkway terrace run plaza alley trail point grove "
             "park path square view glen arc extension".split())
_SKIP = {"block", "of", "the", "hundred"}

# An incident placed in another town is never in a part of Bakersfield, even
# when that town has a street of the same name.
_ELSEWHERE = re.compile(
    r"\b(?:delano|wasco|shafter|mcfarland|arvin|lamont|weedpatch|taft|"
    r"maricopa|tehachapi|mojave|rosamond|ridgecrest|california city|boron|"
    r"lake isabella|kernville|wofford heights|bodfish|frazier park|lebec|"
    r"buttonwillow|lost hills|tupman|edison|keene|caliente|inyokern|"
    r"pine mountain club|stallion springs|bear valley|golden hills|"
    r"grapevine|gorman|glennville|woody)\b(?! (?:highway|hwy|road|rd|street|st|avenue|ave)\b)",
    re.I)


def names_another_town(text: str) -> bool:
    """Does the text place itself in a Kern town that is not Bakersfield?"""
    return bool(_ELSEWHERE.search(text or ""))


# What the copy can claim, and the parts of town that make the claim true.
# The loose ones ("north", "south", "west") accept either neighbor.
_CLAIMS = [
    (re.compile(r"\bsouthwest(?:ern)? Bakersfield\b", re.I), {"SW"}),
    (re.compile(r"\bnorthwest(?:ern)? Bakersfield\b", re.I), {"NW"}),
    (re.compile(r"\bnortheast(?:ern)? Bakersfield\b", re.I), {"E"}),
    (re.compile(r"\bsoutheast(?:ern)? Bakersfield\b", re.I), {"SE", "S"}),
    (re.compile(r"\beast(?:ern)? Bakersfield\b", re.I), {"E"}),
    (re.compile(r"\bwest(?:ern)? Bakersfield\b", re.I), {"NW", "SW"}),
    (re.compile(r"\bnorth(?:ern)? Bakersfield\b", re.I), {"N", "NW"}),
    (re.compile(r"\bsouth(?:ern)? Bakersfield\b", re.I), {"S", "SE", "SW"}),
    (re.compile(r"\bcentral Bakersfield\b", re.I), {"C"}),
    (re.compile(r"\bdowntown(?: Bakersfield)?\b", re.I), {"C"}),
    (re.compile(r"\bOildale\b(?! (?:Drive|Highway|Road))", re.I), {"N"}),
]


@lru_cache(maxsize=1)
def table() -> dict:
    return json.loads(TABLE_FILE.read_text(encoding="utf-8"))


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower().replace(".", ""))
    return [_ABBR.get(w, w) for w in words]


def _find(toks: list[str]) -> list[tuple[str, int | None]]:
    """Every table street named in the tokens, longest match first, each with
    the block number written in front of it (None when there is none)."""
    t, out, i = table(), [], 0
    while i < len(toks):
        hit = None
        for n in range(min(7, len(toks) - i), 1, -1):
            key = " ".join(toks[i:i + n])
            if key in t and (toks[i + n - 1] in _TYPES or n > 2):
                hit = (key, n)
                break
        if not hit:
            i += 1
            continue
        j = i - 1
        while j >= 0 and toks[j] in _SKIP:
            j -= 1
        num = int(toks[j]) if j >= 0 and toks[j].isdigit() else None
        out.append((hit[0], num))
        i += hit[1]
    return out


def _codes(key: str, num: int | None) -> set[str]:
    """Parts of town a street (at a block, when given) can be in. A bare name
    also covers its N/S/E/W twins, because dispatch drops the direction. Each
    table row is [first number, last number, part]; 0-0 is an unnumbered
    stretch."""
    t = table()
    keys = [key]
    if key.split()[0] not in ("n", "s", "e", "w"):
        keys += [f"{d} {key}" for d in "nsew" if f"{d} {key}" in t]
    out: set[str] = set()
    for k in keys:
        # the named street gets a block of slack for a rounded number; a twin
        # has to hold the number outright
        slack = 100 if k == key else 0
        out.update(r[2] for r in t[k] if num is None
                   or (r[1] and r[0] - slack <= num <= r[1] + slack))
    # with no number to go on, a rural tail does not make the street unknown
    return out - {"X"} if num is None and out != {"X"} else out


def region_code(area: str) -> str | None:
    """'the 5400 block of Pembroke Avenue' -> 'N'. None unless certain."""
    if not area or _ELSEWHERE.search(area):
        return None
    found = _find(_tokens(area))
    if not found:
        return None
    sets = [_codes(k, n) for k, n in found]
    common = set.intersection(*sets)
    if len(common) != 1 or "X" in common:
        return None
    return common.pop()


def region_of(area: str) -> str | None:
    """The phrase for copy ('north Bakersfield'), or None."""
    return PHRASE.get(region_code(area) or "")


def annotate(incidents: list[dict]) -> int:
    """Set each incident's 'region' from its area; drop one we cannot back."""
    n = 0
    for inc in incidents:
        phrase = region_of(str(inc.get("area") or ""))
        if phrase:
            inc["region"] = phrase
            n += 1
        else:
            inc.pop("region", None)
    return n


# ----------------------------------------------------------------- the check
def _street_regions(incidents: list[dict]) -> dict[str, set[str]]:
    """street -> parts of town, from the night's own incidents (block-exact)."""
    out: dict[str, set[str]] = {}
    for inc in incidents:
        area = str(inc.get("area") or "")
        code = region_code(area)
        if code:
            for key, _ in _find(_tokens(area)):
                out.setdefault(key, set()).add(code)
    return out


def _resolved(text: str, known: dict[str, set[str]]) -> set[str]:
    if _ELSEWHERE.search(text):
        return set()
    out: set[str] = set()
    for key, num in _find(_tokens(text)):
        if num is None and key in known:
            out |= known[key]
        else:
            out |= _codes(key, num) - {"X"}
    return out


def check(report: str, incidents: list[dict]) -> tuple[str, list[str]]:
    """Find part-of-town claims the streets beside them contradict.

    A claim is judged against the streets in its own sentence; when the
    sentence names none, against its paragraph, but only when every street in
    the paragraph is in one part of town. Returns (fixed_text, problems). The
    fix swaps in the right phrase and is made only when there is exactly one.
    """
    known = _street_regions(incidents)
    problems: list[str] = []
    paras = report.split("\n")
    for pi, para in enumerate(paras):
        para_regs = _resolved(para, known)
        parts = re.split(r"((?<=[.!?])\s+(?=[A-Z*\"']))", para)
        for si in range(0, len(parts), 2):
            sent = parts[si]
            regs = _resolved(sent, known)
            if not regs and len(para_regs) == 1:
                regs = para_regs
            if not regs:
                continue
            for rx, ok in _CLAIMS:
                for m in list(rx.finditer(sent))[::-1]:
                    if ok & regs:
                        continue
                    right = PHRASE[next(iter(regs))] if len(regs) == 1 else None
                    problems.append(
                        f"line {pi + 1}: says '{m.group(0)}' but the street is in "
                        f"{right or ' / '.join(sorted(PHRASE[r] for r in regs))}")
                    if right:
                        sent = sent[:m.start()] + right + sent[m.end():]
            parts[si] = sent
        paras[pi] = "".join(parts)
    return "\n".join(paras), problems


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "lookup" and len(argv) > 2:
        area = " ".join(argv[2:])
        print(f"{area}: {region_of(area) or 'unknown (name no part of town)'}")
        return 0
    if cmd == "annotate" and len(argv) > 2:
        path = Path(argv[2])
        incs = json.loads(path.read_text(encoding="utf-8"))
        n = annotate(incs)
        path.write_text(json.dumps(incs, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        print(f"region set on {n} of {len(incs)} incidents")
        return 0
    if cmd == "check" and len(argv) > 3:
        path = Path(argv[2])
        text = path.read_text(encoding="utf-8")
        fixed, problems = check(text, json.loads(
            Path(argv[3]).read_text(encoding="utf-8")))
        for p in problems:
            print("WRONG PART OF TOWN:", p)
        if not problems:
            print("parts of town OK")
            return 0
        if "--fix" in argv and fixed != text:
            path.write_text(fixed, encoding="utf-8")
            print(f"fixed in {path.name}")
            return 0
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
