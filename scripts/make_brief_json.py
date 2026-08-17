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
MUSIC = "assets/audio/news_reel_bed.wav"  # repo path; post_facebook passes --music abs

# incident type -> reel headline label (kept short, factual, no clickbait).
# Types are matched AFTER normalisation (lowercase, spaces->underscores), so
# 'vehicle fire' and 'vehicle_fire' land on the same label. Unknown types
# fall back to a generic label + the 'city' scene.
TYPE_LABEL = {
    "shooting": "Shots fired",
    "reported_shooting": "Shots fired",
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
            abbrev = c == "." and prev.isalpha() and nxt.isalpha()
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
    return " ".join(cut)


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


def pick_stories(date: str, brief: str, overnight: str) -> list[dict]:
    """Ordered stories for the reel: [most-serious, next notable, next notable].

    Story 1 is the incident whose area appears in the brief's most-serious
    paragraph (fallback: highest notability). Stories 2-3 are the remaining
    incidents by (notability desc, time asc). Scene variety is a LAST-SLOT
    tiebreaker only: never skip a higher-notability incident to avoid a
    repeated background, but if the 3rd pick would duplicate a scene already
    used, prefer a different-scene incident of the same (or better) notability.
    """
    incidents = load_incidents(date)
    if not incidents:
        return []

    serious = most_serious_paragraph(brief, overnight).lower()
    lead = None
    for inc in sorted(incidents, key=lambda x: (-(x.get("notability") or 0),
                                                x.get("time") or "")):
        area = _clean_area(inc.get("area", "")).lower()
        if area and area.split(",")[0] in serious:
            lead = inc
            break
    if lead is None and incidents:
        lead = max(incidents, key=lambda x: (x.get("notability") or 0))

    rest = [x for x in incidents if x is not lead]
    rest.sort(key=lambda x: (-(x.get("notability") or 0), x.get("time") or ""))
    chosen = [lead]
    used = {TYPE_SCENE.get(_norm_type(lead.get("type", "")), DEFAULT_SCENE)}
    for inc in rest:
        if len(chosen) >= 3:
            break
        scene = TYPE_SCENE.get(_norm_type(inc.get("type", "")), DEFAULT_SCENE)
        if len(chosen) == 2 and scene in used:
            # last slot: prefer a different scene, but only if it doesn't
            # cost notability — a same-scene incident with HIGHER notability
            # still wins over a prettier-but-lesser background.
            alt = next((r for r in rest if r is not inc and
                        TYPE_SCENE.get(_norm_type(r.get("type", "")), DEFAULT_SCENE) != scene
                        and (r.get("notability") or 0) >= (inc.get("notability") or 0)),
                       None)
            if alt is not None:
                chosen.append(alt)
                used.add(TYPE_SCENE.get(_norm_type(alt.get("type", "")), DEFAULT_SCENE))
                continue
        chosen.append(inc)
        used.add(scene)
    return chosen[:3]


def story_json(inc: dict) -> dict:
    area = _clean_area(inc.get("area", "")) or "Bakersfield"
    head_area = area.split(",")[0].strip()  # 'Coffee Road, Bank of America' -> 'Coffee Road'
    t = _norm_type(inc.get("type", ""))
    label = TYPE_LABEL.get(t, "Incident reported")
    summary = inc.get("summary", "") or ""
    sub = _first_sentence(summary)
    scene = TYPE_SCENE.get(t, DEFAULT_SCENE)
    return {
        "headline": f"{label} {_preposition(head_area)} {head_area}"[:120],
        "subhead": sub,
        "time": _fmt_time(inc.get("time", "")),
        "place": area.upper()[:60],
        "scene": scene,
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

    stories = [story_json(s) for s in pick_stories(date, brief, overnight)]
    if not stories:
        raise SystemExit(f"SKIP {date}: no incidents to build a reel from")
    # drop empty time/place keys the renderer can't use
    for s in stories:
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
        "music": MUSIC,
        "backgrounds": "auto",
        "stories": stories,
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
