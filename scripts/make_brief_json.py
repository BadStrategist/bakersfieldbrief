#!/usr/bin/env python3
"""Deterministic brief.json generator for the daily animated reel.

Reads the SAME committed data the site pipeline uses — the brief body
(data/briefs/<date>.json), the overnight report (data/overnight_reports/
<date>.md) and the structured incident log (incidents/<date>.json) — and
emits a brief.json that scripts/brief_reel/render_reel.py renders into the
30-second animated reel (MP4) + still card (PNG) for the Facebook/IG post.

No LLM and no API keys: Claude's design puts "write brief.json" on an LLM,
but every field here is derived deterministically from committed data, so
the daily reel is reproducible, auditable and costs nothing.

Usage:
  python scripts/make_brief_json.py --date YYYY-MM-DD --out path/brief.json
  (defaults: today America/Los_Angeles, out site/assets/img/social/<date>-brief.json)

Exit codes: 0 ok, 1 missing data, 2 schema violation.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
BRIEFS = ROOT / "data" / "briefs"
OVERNIGHTS = ROOT / "data" / "overnight_reports"
INCIDENTS = ROOT / "incidents"

BRAND = "The Bakersfield Brief"
KICKER = "THE KERN OVERNIGHT · WHILE YOU SLEPT"
TAGLINE = "The city talks. We listen."
URL = "bakersfieldbrief.com"
CTA = "Follow for tomorrow’s overnight"
MUSIC = "assets/audio/news_reel_bed.wav"  # fallback bed; daily rotation below

# Daily-rotation reel-bed stack (user-supplied, 2026-08-18). Each calendar
# day gets a DIFFERENT bed: 1 → 2 → 3 → 1 ... (deterministic — the same
# date always maps to the same bed, so re-renders reproduce the reel).
REEL_BEDS = ("assets/audio/reel_bed_1.mp3",
             "assets/audio/reel_bed_2.mp3",
             "assets/audio/reel_bed_3.mp3")


def music_for_date(date: str) -> str:
    """Pick today's music bed by rotating through REEL_BEDS on the date's
    ordinal day number. Falls back to MUSIC if a bed file is missing."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        bed = REEL_BEDS[d.toordinal() % len(REEL_BEDS)]
        if (ROOT / bed).exists():
            return bed
    except ValueError:
        pass
    return MUSIC

# incident type -> reel headline label (kept short, factual, no clickbait).
# Types are matched AFTER normalisation (lowercase, spaces->underscores), so
# 'vehicle fire' and 'vehicle_fire' land on the same label. Unknown types
# fall back to a generic label + the 'city' scene.
TYPE_LABEL = {
    "shooting": "Shots fired",
    "reported_shooting": "Reported shooting",
    "domestic_violence": "Domestic violence in progress",
    "domestic_call": "Domestic violence call",
    "domestic_violence_with_injury": "Domestic violence with injury",
    "domestic_disturbance": "Domestic disturbance",
    "family_disturbance": "Family disturbance",
    "juvenile_disturbance": "Juvenile disturbance",
    "verbal_disturbance": "Verbal disturbance",
    "disturbance": "Disturbance",
    "brandishing_firearm": "Firearm brandished",
    "assault_with_deadly_weapon": "Assault with a deadly weapon",
    "assault_with_a_weapon": "Assault with a weapon",
    "assault_report_involving_a_child": "Assault involving a child",
    "vegetation_fire": "Grass fire",
    "grass_fire": "Grass fire",
    "structure_fire": "Structure fire",
    "structure_fire_report": "Structure fire",
    "structure fire": "Structure fire",
    "commercial_fire": "Commercial fire",
    "outside_fire": "Outside fire",
    "vehicle_fire": "Vehicle fire",
    "vehicle fire": "Vehicle fire",
    "electrical_fire": "Electrical fire",
    "attempted_arson": "Attempted arson",
    "fire": "Fire reported",
    "fire_alarm": "Fire alarm",
    "commercial_fire_alarm": "Commercial fire alarm",
    "fire_cause_investigation": "Fire investigation",
    "vehicle_vs_pedestrian": "Vehicle vs. pedestrian",
    "traffic_collision": "Traffic collision",
    "traffic collision": "Traffic collision",
    "hit_and_run": "Hit-and-run",
    "dui": "DUI arrest",
    "dui_report": "DUI report",
    "reckless_driver": "Reckless driver",
    "road_rage": "Road rage",
    "street_racing": "Street racing",
    "vehicle_pursuit": "Vehicle pursuit",
    "foot_pursuit": "Foot pursuit",
    "stolen_vehicle": "Stolen vehicle",
    "vehicle_into_building": "Vehicle into building",
    "roadway_hazard": "Roadway hazard",
    "traffic_enforcement": "Traffic enforcement",
    "burglary": "Possible burglary",
    "attempted_burglary": "Attempted burglary",
    "theft": "Theft reported",
    "vandalism": "Vandalism",
    "stolen_firearms_search": "Stolen firearms search",
    "welfare_check": "Welfare check",
    "welfare check": "Welfare check",
    "suicidal_subject": "Suicidal subject",
    "mental_health_crisis": "Mental health crisis",
    "mental_health_hold": "Mental health hold",
    "mental_health": "Mental health call",
    "man_down": "Man down",
    "medical_aid": "Medical aid",
    "medical aid": "Medical aid",
    "medical_alarm": "Medical alarm",
    "officer_assist": "Officer assist",
    "warrant_service": "Warrant service",
    "probation_check": "Probation check",
    "suspicious_person": "Suspicious person",
    "suspicious person": "Suspicious person",
    "suspicious_vehicle": "Suspicious vehicle",
    "suspicious_circumstances": "Suspicious circumstances",
    "hazardous_condition": "Hazardous condition",
    "hazardous condition": "Hazardous condition",
    "juvenile_nuisance": "Juvenile nuisance",
}
TYPE_SCENE = {
    "shooting": "police", "reported_shooting": "police",
    "domestic_violence": "police", "domestic_call": "police",
    "domestic_violence_with_injury": "police", "domestic_disturbance": "police",
    "family_disturbance": "police", "juvenile_disturbance": "police",
    "verbal_disturbance": "police", "disturbance": "police",
    "brandishing_firearm": "police", "assault_with_deadly_weapon": "police",
    "assault_with_a_weapon": "police", "assault_report_involving_a_child": "police",
    "burglary": "police", "attempted_burglary": "police", "theft": "police",
    "vandalism": "police", "stolen_firearms_search": "police",
    "warrant_service": "police", "probation_check": "police",
    "suspicious_person": "police", "suspicious_vehicle": "police",
    "suspicious_circumstances": "police", "juvenile_nuisance": "police",
    "officer_assist": "police", "stolen_vehicle": "police",
    "vehicle_pursuit": "highway", "foot_pursuit": "police",
    "hit_and_run": "highway", "traffic_collision": "highway",
    "traffic collision": "highway", "dui": "highway", "dui_report": "highway",
    "reckless_driver": "highway", "road_rage": "highway",
    "street_racing": "highway", "roadway_hazard": "highway",
    "traffic_enforcement": "highway", "vehicle_vs_pedestrian": "highway",
    "vehicle_into_building": "highway",
    "vegetation_fire": "fire", "grass_fire": "fire",
    "structure_fire": "fire", "structure_fire_report": "fire",
    "structure fire": "fire", "commercial_fire": "fire",
    "outside_fire": "fire", "vehicle_fire": "fire", "vehicle fire": "fire",
    "electrical_fire": "fire", "attempted_arson": "fire", "fire": "fire",
    "fire_alarm": "fire", "commercial_fire_alarm": "fire",
    "fire_cause_investigation": "fire",
    "welfare_check": "city", "welfare check": "city",
    "suicidal_subject": "medical", "mental_health_crisis": "medical",
    "mental_health_hold": "medical", "mental_health": "medical",
    "man_down": "medical", "medical_aid": "medical", "medical aid": "medical",
    "medical_alarm": "medical", "hazardous_condition": "medical",
    "hazardous condition": "medical",
}
DEFAULT_SCENE = "city"


def _norm_type(t: str) -> str:
    """'vehicle fire' / 'Vehicle Fire' -> 'vehicle_fire'."""
    return re.sub(r"\s+", "_", (t or "").strip().lower())


# Types that say nothing on their own. Only these keep the generic label.
VAGUE_TYPES = {"", "incident", "vehicle", "traffic", "traffic_incident",
               "weapon", "weapons", "domestic", "call", "other", "unknown"}
# A caller's word for a grave crime is a report, and the label says so.
REPORTED_TYPES = {"kidnapping": "Reported kidnapping",
                  "kidnapping_report": "Reported kidnapping",
                  "hostage": "Reported hostage situation"}
# A caller's hedge is part of what the call said, so a label never drops one.
HEDGE_RE = re.compile(r"\b(unfounded|unconfirmed|possible|alleged|reported|"
                      r"suspicious|unknown|in progress|attempted)\b", re.I)


def label_for(raw_type: str) -> str:
    """Reel label for an incident type. A type the table does not hold is
    shown in its own words ('armed robbery' -> 'Armed robbery'), never as
    'Incident reported': the type field is free text, 221 distinct types were
    off the table by 2026-10-12, and 13 of 22 reels led with a headline that
    named no event. A compound type keeps its first part
    ('kidnapping / assault with a firearm' -> 'Kidnapping')."""
    t = _norm_type(raw_type)
    if t in TYPE_LABEL:
        return TYPE_LABEL[t]
    if t in VAGUE_TYPES:
        return "Incident reported"
    if t in REPORTED_TYPES:
        return REPORTED_TYPES[t]
    body = t.replace("_", " ").strip()
    # A hedge the caller wrote stays in the label. "Shots fired, unfounded" read
    # as "Shots fired" claims more than the call did, and the compound rule
    # below is what dropped it (found by review 2026-10-12).
    words = body if HEDGE_RE.search(body) else re.split(r"\s*[/,]\s*", body)[0].strip()
    if not words or len(words.split()) > 6:
        return "Incident reported"
    return _sentence_case(words, raw_type)


# Acronyms that turn up lower-cased in the type field ('possible_dui'), which no
# capitalisation rule can recover on its own.
ACRONYMS = {"dui", "dwi", "k9", "atv", "suv", "atf", "fbi", "chp", "kcso", "bpd",
            "swat", "emt"}


def _sentence_case(text: str, raw: str) -> str:
    """Sentence case, keeping a token the source spelled in capitals:
    'possible DUI' keeps its acronym ('Possible dui' was wrong)."""
    caps = ({w.upper() for w in re.split(r"[^A-Za-z0-9]+", raw or "")
             if len(w) >= 2 and w.isupper()}
            | {a.upper() for a in ACRONYMS})
    out = []
    for i, w in enumerate(text.split()):
        core = w.strip(",.;:")
        if core.upper() in caps:
            out.append(w.upper())
        else:
            out.append(w if i else w[:1].upper() + w[1:])
    return " ".join(out)


# Hook test: the opener alternates by date inside the window and is the title
# card outside it. Twelve days is two full cycles of opener x music bed (2 x 3),
# so each opener runs twice on each bed.
HOOK_TEST = ("2026-10-14", "2026-10-25")


def hook_for_date(date: str) -> str:
    """Always 'cold': story 1 from frame 0, so the thumbnail is the lead story.
    The cold/title A/B test (2026-10-14 to 10-25) ended early on 2026-10-20 when
    the owner judged the title card unprofessional."""
    return "cold"


def today_iso() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def date_label(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d").upper()


def _clean_area(area: str) -> str:
    """'Ming Avenue, FoodMaxx' -> 'Ming Avenue, FoodMaxx';
    'Bakersfield (location unclear on the air)' -> 'Bakersfield'."""
    area = re.sub(r"\([^)]*\)", "", area or "")
    return re.sub(r"\s{2,}", " ", area).strip().strip(",").strip()


STREET_SUFFIX = ("street", "avenue", "road", "court", "drive", "blvd",
                 "boulevard", "lane", "way", "highway", "hwy", "freeway",
                 "interstate", "99", "58", "178", "i-5")
CITY_WORDS = ("bakersfield", "kern county", "kernville", "delano", "wasco",
              "ridgecrest", "tehachapi", "arfvin", "shafter", "ocala")


def _preposition(area: str) -> str:
    """'on' for street-name areas, 'at' for path/venue areas, 'in' for city
    names, else 'near'."""
    a = area.lower()
    if " near " in a or " off " in a or a.startswith(("bike path", "riverbed", "canal", "park")):
        return "at"
    if any(s in a for s in STREET_SUFFIX):
        return "on"
    if a in CITY_WORDS:
        return "in"
    return "near"


# A place that already carries its locator keeps it: "Shots fired near Lynwood
# and Height streets" reads, "on near Lynwood and Height streets" does not. 22 of
# the 1,033 areas on disk start this way ("south of Kelso Creek", "off King
# Street, east Kern").
LOCATOR_RE = re.compile(
    r"^(near|at|on|off|in|inside|outside|between|behind|along|across|"
    r"(just\s+)?(south|north|east|west)\s+of)\b", re.I)


def _place_phrase(area: str) -> str:
    """The label-to-place phrase: 'on Oak Street', 'in Delano', or the area's own
    words when it already carries the locator."""
    a = (area or "").strip()
    if not a:
        return ""
    if LOCATOR_RE.match(a):
        return a
    return f"{_preposition(a)} {a}".strip()


# Trailing function words that make a truncated clause read as machine-cut
# ("...after a vehicle they", "...after an initial report of"). Dropped before
# an ellipsis is added so the cap lands on a real word.
_DANGLING = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "with", "from", "by", "as", "that", "which", "who", "whom", "whose", "when",
    "where", "while", "after", "before", "during", "into", "onto", "over",
    "under", "near", "they", "he", "she", "it", "we", "you", "them", "his",
    "her", "its", "their", "our", "your", "my", "was", "were", "is", "are",
    "be", "been", "being", "had", "has", "have", "left", "one", "two", "three",
    "another", "both", "each", "such", "been", "about", "than", "then",
}


def _cut_words(t: str, n: int) -> str:
    """Cap a string at n characters ON A WORD BOUNDARY, never mid-word."""
    t = (t or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(",;: ").strip()


def _no_em_dash(t: str) -> str:
    """House style: shipped copy never contains an em dash (it reads as AI slop)."""
    t = (t or "").replace(" \u2014 ", ", ").replace("\u2014", ",")
    return re.sub(r"\s*,\s*,+", ", ", t).strip()


def _first_sentence(text: str, max_words: int = 20) -> str:
    """First sentence of an incident summary, skipping a.m./p.m. abbreviations
    AND decimal dots (273.6), capped at max_words. When the cap lands mid-
    phrase, backs off to the last comma/em-dash/colon boundary within the
    cap (or the full sentence if it's already shorter)."""
    i = 0
    while i < len(text):
        c = text[i]
        if c in ".!?":
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1:i + 2]
            number_dot = c == "." and prev.isdigit() and nxt.isdigit()
            # a.m./p.m. (and other 2-letter abbreviations): skip the period
            # when the next char is a letter OR closing punctuation ("p.m.,").
            abbrev = c == "." and prev.isalpha() and (nxt.isalpha() or nxt in ".,;:")
            if not (number_dot or abbrev):
                break
        i += 1
    s = text[:i + 1].strip() if i < len(text) else text.strip()
    words = s.split()
    if len(words) <= max_words:
        return s
    cut = words[:max_words]
    # back off to the last natural boundary within the cap (comma/em-dash/colon)
    for idx in range(len(cut) - 1, -1, -1):
        if cut[idx].rstrip(",").endswith((",", "—", ":", ";")):
            return " ".join(cut[:idx + 1]).rstrip(",").strip()
    # No natural boundary inside the cap. Never ship a mid-phrase fragment:
    # drop trailing function words and mark the cut so it reads as deliberate.
    while cut and cut[-1].strip(",;:.").lower() in _DANGLING:
        cut.pop()
    if not cut:
        cut = words[:max_words]
    return " ".join(cut).rstrip(",;: ") + " \u2026"


def _first_sentence_full(text: str) -> str:
    """First sentence WITHOUT the word cap — isolates the brief's editorial
    lead ('The night's most serious call ... was reported on Monterey
    Street.') from the rest of the paragraph, which may go on to name lesser
    calls that must NOT outrank it (an Animas Court DV once won the reel
    merely because it appeared later in the same paragraph)."""
    i = 0
    while i < len(text):
        c = text[i]
        if c in ".!?":
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1:i + 2]
            number_dot = c == "." and prev.isdigit() and nxt.isdigit()
            abbrev = c == "." and prev.isalpha() and (nxt.isalpha() or nxt in ".,;:")
            if not (number_dot or abbrev):
                break
        i += 1
    return text[:i + 1].strip() if i < len(text) else text.strip()


def _fmt_time(hhmm: str) -> str:
    """'23:00' -> '11:00 PM'; '00:04' -> '12:04 AM'."""
    try:
        return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return ""


def load_incidents(date: str) -> list[dict]:
    p = INCIDENTS / f"{date}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return [x for x in data if isinstance(x, dict)]


def most_serious_paragraph(brief: str, overnight: str) -> str:
    """The night's most serious incident as written in the brief — used to
    pick WHICH incident leads the reel (mirrors make_social_card's rule:
    the brief's own editorial framing, then a wrong-way crash, then the
    report's 'The big one')."""
    m = re.search(r"The night[’']s most serious (?:call|incident)s?", brief)
    if m:
        end = brief.find("\n\n", m.start())
        return brief[m.start():(end if end != -1 else len(brief))]
    m = re.search(r"\*\*[^*]*wrong-way[^*]*\*\*[^\n]*", brief)
    if m:
        end = brief.find("\n\n", m.start())
        return brief[m.start():(end if end != -1 else len(brief))]
    m = re.search(r"##\s*The big one\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    if m:
        return m.group(1)
    return brief.strip()[:300]


def _severity(inc: dict) -> int:
    """night_counts.severity: the one ranking the night card and the post use."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from build.builders import night_counts
    return night_counts.severity(inc)


def pick_stories(date: str, brief: str, overnight: str, n: int = 3) -> list[dict]:
    """Ordered stories for the reel, most serious first: n to render, then the
    rest of the ranking (the publisher swaps one in when a story's radio clip
    turns out to be about some other call).

    Owner rule 2026-10-20: lead with the serious events, never a fire when a
    person was in danger. So the order is night_counts.severity first; the
    brief's framing (the incident named in its most-serious paragraph) and
    notability only break ties inside a tier. Incidents that came only from the
    CrimeRadar app have no radio audio, so they never make the reel: the clip
    builder would cut whatever other call was on the air at that minute
    (2026-10-20: the Terrace Way assault aired a seizure call on Buck Owens Blvd).
    Scene variety stays a LAST-SLOT tiebreaker inside the same tier.
    """
    incidents = [i for i in load_incidents(date) if i.get("source") != "crimeradar"]
    if not incidents:
        return []

    serious_para = most_serious_paragraph(brief, overnight)
    serious_first = _first_sentence_full(serious_para).lower()
    serious_all = serious_para.lower()

    def named(inc: dict) -> int:
        area = _clean_area(inc.get("area", "")).lower().split(",")[0]
        if area and area in serious_first:
            return 0
        if area and area in serious_all:
            return 1
        return 2

    ranked = sorted(incidents, key=lambda x: (_severity(x), named(x),
                                              -(x.get("notability") or 0),
                                              x.get("time") or ""))
    chosen, used = [], set()
    for inc in ranked:
        if len(chosen) >= n:
            break
        if inc in chosen:
            continue
        scene = TYPE_SCENE.get(_norm_type(inc.get("type", "")), DEFAULT_SCENE)
        if len(chosen) == n - 1 and scene in used:
            # last slot: a different scene of the SAME tier and no lower
            # notability may take it; never a less serious call for a prettier
            # background, and never a story already in the reel.
            alt = next((r for r in ranked if r not in chosen and r is not inc
                        and TYPE_SCENE.get(_norm_type(r.get("type", "")), DEFAULT_SCENE) != scene
                        and _severity(r) == _severity(inc)
                        and (r.get("notability") or 0) >= (inc.get("notability") or 0)), None)
            if alt is not None:
                inc = alt
        chosen.append(inc)
        used.add(TYPE_SCENE.get(_norm_type(inc.get("type", "")), DEFAULT_SCENE))
    return chosen + [r for r in ranked if r not in chosen]


_WEAPON_LABELS = (("machetes", "Machetes reported"), ("machete", "Machete reported"),
                  ("knife", "Knife reported"), ("knives", "Knives reported"),
                  ("taser", "Taser reported"), ("firearm", "Gun reported"),
                  ("handgun", "Gun reported"), ("rifle", "Gun reported"), ("gun", "Gun reported"))


def _weapon_label(summary: str) -> str:
    """'weapons' says nothing on screen; the weapon the caller named does."""
    low = (summary or "").lower()
    for word, label in _WEAPON_LABELS:
        if re.search(rf"\b{word}\b", low):
            return label
    return "Weapons call"


def story_json(inc: dict) -> dict:
    area = _clean_area(inc.get("area", "")) or "Bakersfield"
    head_area = area.split(",")[0].strip()  # 'Coffee Road, Bank of America' -> 'Coffee Road'
    t = _norm_type(inc.get("type", ""))
    label = label_for(inc.get("type", ""))
    if t.startswith("weapon"):
        label = _weapon_label(inc.get("summary", ""))
    summary = inc.get("summary", "") or ""
    sub = _first_sentence(summary)
    scene = TYPE_SCENE.get(t, "")
    # An unmapped type carries no scene: leave it empty so the reel picks one
    # from the headline words. Writing the DEFAULT_SCENE here gave every
    # unmapped story the same "city" background, so two stories in a row
    # showed the identical image (reported 2026-09-20: "keeps flashing the
    # same black highway image").
    return {
        "headline": _no_em_dash(_cut_words(f"{label} {_place_phrase(head_area)}", 120)),
        "subhead": _no_em_dash(sub),
        "time": _fmt_time(inc.get("time", "")),
        "place": _no_em_dash(_cut_words(area.upper(), 60)),
        "scene": scene,
        # The cold opener sets the event and the place as two lines. No area
        # on the incident means no place line, never a default city.
        "label": label,
        "where": (_no_em_dash(_cut_words(_place_phrase(head_area), 80))
                  if _clean_area(inc.get("area", "")) else ""),
    }


def build(date: str) -> dict:
    bp = BRIEFS / f"{date}.json"
    op = OVERNIGHTS / f"{date}.md"
    if not bp.exists() or not op.exists():
        raise SystemExit(f"SKIP {date}: missing brief body or overnight report")
    brief = json.loads(bp.read_text(encoding="utf-8")).get("body", "")
    overnight = op.read_text(encoding="utf-8")
    if len(brief) < 200 or len(overnight) < 300:
        raise SystemExit(f"SKIP {date}: brief/overnight too short")

    ranked = [story_json(s) for s in pick_stories(date, brief, overnight)]
    stories, alternates = ranked[:3], ranked[3:6]
    if not stories:
        raise SystemExit(f"SKIP {date}: no incidents to build a reel from")
    # drop empty time/place keys the renderer can't use
    for s in stories + alternates:
        for k in ("time", "place"):
            if not s[k]:
                del s[k]

    return {
        "date_label": date_label(date),
        "brand": BRAND,
        "kicker": KICKER,
        "tagline": TAGLINE,
        "url": URL,
        "cta": CTA,
        "music": music_for_date(date),
        "backgrounds": "auto",
        "hook": hook_for_date(date),
        # Every story on the dark night card (the plain cream title flash read as
        # "horrible and unprofessional", owner 2026-10-20), with read-along
        # captions added by build_captions.py.
        "style": "night",
        "stories": stories,
        # Next in the ranking: the publisher swaps one in for a story whose
        # radio clip is not about that story. Never rendered.
        "alternates": alternates,
    }


def validate(cfg: dict) -> None:
    for k in ("brand", "date_label", "kicker", "tagline", "url", "stories"):
        if k not in cfg:
            raise SystemExit(f"brief.json missing required key: {k}")
    if not (1 <= len(cfg["stories"]) <= 4):
        raise SystemExit("stories must have 1-4 items")
    for s in cfg["stories"]:
        for k in ("headline",):
            if not s.get(k):
                raise SystemExit(f"story missing required key: {k}")


def main() -> int:
    date = (sys.argv[sys.argv.index("--date") + 1]
            if "--date" in sys.argv else today_iso())
    out_p = (Path(sys.argv[sys.argv.index("--out") + 1])
             if "--out" in sys.argv
             else ROOT / "site" / "assets" / "img" / "social" / f"{date}-brief.json")
    cfg = build(date)
    validate(cfg)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"brief.json saved: {out_p} ({len(cfg['stories'])} stories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
