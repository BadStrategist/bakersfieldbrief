"""Plain-English labels for CHP incident logs.

CHP's public feed uses dispatch shorthand: "1181-Trfc Collision-Minor Inj",
"MZP-Assist CT with Maintenance", "Sr99 N / 24th St Ofr", "JNO". Readers saw those raw on place
pages, /numbers/ and the Sunday Read. These helpers translate the common forms and leave anything
unrecognised readable rather than guessing at it.
"""
from __future__ import annotations

import re

# CHP 11-codes that appear in the Bakersfield (BFCC) log
_CODES = {
    "1125": "Traffic hazard",
    "1144": "Fatal crash",
    "1179": "Crash with injuries (ambulance sent)",
    "1180": "Crash with major injuries",
    "1181": "Crash with minor injuries",
    "1182": "Crash, no injuries",
    "1183": "Crash, injuries unknown",
    "1166": "Defective traffic signal",
    "1124": "Abandoned vehicle",
    "1126": "Disabled vehicle",
}

_WORDS = [
    (r"\bTrfc\b", "Traffic"), (r"\bInj\b", "injury"), (r"\bEnrt\b", "en route"),
    (r"\bVeh\b", "vehicle"), (r"\bAsst\b", "assist"), (r"\bCT\b", "Caltrans"),
    (r"\bUnkn?\b", "unknown"), (r"\bRdwy\b", "roadway"),
]

_SPECIAL = {
    "MZP-ASSIST CT WITH MAINTENANCE": "Assisting a Caltrans maintenance crew",
    "CZP-ASSIST WITH CONSTRUCTION": "Assisting a construction crew",
    "SIG ALERT": "Sig Alert (lanes blocked for 30 minutes or more)",
}


def plain_type(t: str) -> str:
    raw = (t or "").strip()
    if not raw:
        return "Incident"
    special = _SPECIAL.get(re.sub(r"\s+", " ", raw).upper())
    if special:
        return special
    m = re.match(r"^(\d{4})\b[-\s]*(.*)$", raw)
    if m and m.group(1) in _CODES:
        label = _CODES[m.group(1)]
        if re.search(r"\b1141\b", m.group(2)):          # 1141 = ambulance requested
            label += ", ambulance on the way" if "ambulance" not in label else ""
        return label
    # any other "CODE-Description" ("TADV-Traffic Advisory", "20002-Hit and Run No Injuries",
    # "1125A-Animal Hazard", "CFIRE-Car Fire"): drop the code, keep the words
    txt = re.sub(r"^[A-Z0-9]{2,6}\s*-\s*", "", raw, flags=re.I)
    for pat, rep in _WORDS:
        txt = re.sub(pat, rep, txt, flags=re.I)
    txt = re.sub(r"-", " ", txt).strip()
    txt = re.sub(r"\bw/", "with ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:1].upper() + txt[1:].lower()


_ROUTE = [(r"\bSr\s?-?(\d+)\b", r"SR-\1"), (r"\bI\s?-?(5|40|580)\b", r"I-\1"),
          (r"\bUs\s?-?(\d+)\b", r"US-\1")]
_DIRS = {"N": "northbound", "S": "southbound", "E": "eastbound", "W": "westbound",
         "Nb": "northbound", "Sb": "southbound", "Eb": "eastbound", "Wb": "westbound"}
_LOCWORDS = [(r"\bOfr\b", "off-ramp"), (r"\bOnr\b", "on-ramp"), (r"\bCon\b", "connector"),
             (r"\bJno\b", "just north of"), (r"\bJso\b", "just south of"),
             (r"\bJeo\b", "just east of"), (r"\bJwo\b", "just west of"),
             (r"\bAv\b", "Ave"), (r"\bBl\b", "Blvd")]


def plain_location(loc: str) -> str:
    s = (loc or "").strip()
    if not s:
        return ""
    for pat, rep in _ROUTE:
        s = re.sub(pat, rep, s, flags=re.I)
    # "NB SR-99 ..." -> "SR-99 northbound ..."
    s = re.sub(r"\b(NB|SB|EB|WB)\s+(SR-\d+|I-\d+|US-\d+)\b",
               lambda m: f"{m.group(2)} {_DIRS[m.group(1).capitalize()]}", s, flags=re.I)
    s = re.sub(r"\b(SR-\d+|I-\d+|US-\d+)\s+(Nb|Sb|Eb|Wb|N|S|E|W)\b",
               lambda m: f"{m.group(1)} {_DIRS[m.group(2).capitalize()]}", s, flags=re.I)
    for pat, rep in _LOCWORDS:
        s = re.sub(pat, rep, s, flags=re.I)
    s = s.replace(" / ", " at ")
    return s
