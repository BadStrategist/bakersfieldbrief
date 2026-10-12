#!/usr/bin/env python3
"""Kern Overnight call counts by kind, for the home page band.

One night, one file: the caller hands in the rows of incidents/<date>.json. Never count from
data/incidents_geo.json: build_feed stamps evening calls with the next day's date, so a clock
filter on its "t" mixes two nights (10 of 25 rows were the wrong night on 2026-10-07).

The "type" field is free text (328 spellings in 58 nights, many of them the same label in two
cases or with underscores). normalize() folds case, underscores and spacing, and CHIP_OF maps
every folded label to exactly one chip. Nothing is matched by substring: "alarm" is not a
burglary and "Shots fired, unfounded" is not a fire.
"""
from __future__ import annotations

import os
import re
from collections import Counter

from .. import common

OTHER = "Other calls"

# Row order is display order: most serious first, danger to people at the top, and the same
# order every morning. Judgement calls, the owner's to change: an alarm is not a fire or a
# burglary until someone confirms it, so every alarm is in Alarms. Robbery is in Burglary and
# theft, and so is a forced entry threat. Weapons calls, assaults and fights are one row.
# "incident" and "vehicle" say nothing about the call, so they are in Other.
# A barricade, a hostage call and a kidnapping are danger to a person, so they
# are in Weapons and assaults; trespassing is Suspicious activity. "Fatality" is
# not a type: it does not say whether a crash or a homicide killed someone, so
# the monitor no longer stages it and the row is typed by what happened.
MAP = {
    "Weapons and assaults": (
        "weapons call", "weapon call", "weapon", "weapon disturbance", "weapons offense",
        "shooting", "shooting call", "reported shooting", "shots fired",
        "shots fired, unfounded", "shots heard", "gunshot wound", "stabbing",
        "stabbing investigation", "assault with a deadly weapon", "assault with deadly weapon",
        "assault with a weapon", "armed subject", "armed subject / officer safety",
        "brandishing firearm", "brandishing report", "disturbance with firearm",
        "firearms incident", "person with a gun", "person with knife",
        "road rage with a firearm", "suspicious person with a weapon",
        "kidnapping / assault with a firearm", "stolen firearms search",
        "weapons", "homicide", "barricade", "hostage", "kidnapping",
        "assault", "assault, possible domestic", "fight", "large fight",
        "assault call and standoff", "assault investigation", "assault medical staging",
        "assault report involving a child", "assault threats disturbance",
        "assault with injury", "battery", "battery reported", "casino assault report",
        "domestic assault", "domestic battery report",
    ),
    "Fires": (
        "fire", "outside fire", "vehicle fire", "brush fire", "grass fire", "structure fire",
        "possible fire", "fire investigation", "burning complaint", "backyard fire",
        "building fire", "camp fire", "campfire", "car fire", "commercial fire", "dumpster fire",
        "electrical fire", "field fire", "fire call", "fire cause investigation",
        "fire report", "fire response", "illegal burning", "kitchen fire", "outdoor fire",
        "possible structure fire", "refuse fire", "rubbish fire", "shed fire", "small fire",
        "smoke investigation", "structure fire call", "structure fire investigation",
        "structure fire report", "trash fire", "vegetation fire", "vegetation fire check",
        "vehicle fire check", "vehicle fire possible occupant", "vehicle fires", "wildfire",
        "working fire", "attempted arson", "suspicious fires arson",
    ),
    "Crashes and traffic": (
        "collision", "traffic collision", "hit and run", "hit and run collision",
        # "crash" on its own: the radio leg stages it on 6 rows in one night (2026-10-12),
        # and the bare label used to fall out of the map as a row of its own.
        "crash", "crashes", "car crash", "vehicle crash", "traffic crash", "auto crash",
        "single car crash", "single vehicle crash", "multi car crash",
        "hit-and-run collision", "multi vehicle crash", "rollover", "vehicle rollover",
        "dui", "dui arrest", "dui crash", "dui driver", "dui report", "possible dui",
        "impaired driver", "impaired driver report", "reckless driving", "reckless driver",
        "wrong-way driver", "street racing", "street takeover", "road rage",
        "vehicle pursuit", "pursuit", "pursuit and arrest", "pursuit and crash",
        "pursuit ended crash", "stolen vehicle pursuit",
        "traffic", "traffic hazard", "traffic enforcement", "traffic incident",
        "traffic signal outage", "roadway hazard", "road closure", "disabled vehicle",
        "stranded motorist", "vehicle stop", "vehicle into building", "vehicle into pole",
        "vehicle into power pole", "vehicle into wall", "vehicle off the roadway",
        "vehicle versus pedestrian", "vehicle vs pedestrian", "vehicle versus pole",
        "vehicle vs animal hit run", "vehicle vs bicycle", "vehicle vs curb",
        "vehicle stuck on railroad tracks", "train vs pedestrian", "pedestrian in traffic",
        "pedestrian on highway", "person on a moving vehicle",
        "search after possible collision into a building",
        "multi-vehicle crash",
    ),
    "Medical and overdose": (
        "medical aid", "cardiac arrest", "person down", "man down", "medical aid welfare",
        "medical aid with fire report", "water rescue", "water rescue / medical",
        "medical emergency", "drowning",
        "overdose", "overdose response",
    ),
    "Missing persons": (
        "missing juvenile", "missing person", "missing child", "missing children",
        "missing person check", "missing person search", "runaway juvenile",
    ),
    "Disturbances and welfare": (
        "disturbance", "domestic disturbance", "domestic violence", "welfare check",
        "landlord-tenant dispute", "domestic", "domestic call", "domestic in progress",
        "domestic possible in progress", "domestic violence call",
        "domestic violence with injury", "domestic welfare check", "family disturbance",
        "family violence", "juvenile disturbance", "juvenile nuisance", "physical disturbance",
        "verbal disturbance", "child welfare", "self harm welfare", "suicidal subject",
        "mental health", "mental health crisis", "mental health hold", "large gathering",
        "fireworks complaint", "public intoxication", "threats", "criminal threats",
        "call for help", "pedestrian check",
        "domestic dispute",
    ),
    "Burglary and theft": (
        "burglary", "theft", "vehicle theft", "robbery", "armed robbery",
        "armed robbery investigation", "robbery investigation", "strong-arm robbery",
        "attempted burglary", "attempted entry", "forced entry", "burglary in progress",
        "commercial burglary", "residential burglary in progress", "copper theft",
        "grand theft auto", "shoplifting", "stolen vehicle", "stolen vehicle recovery",
        "theft from vehicle", "theft in progress", "theft report",
        "forced entry threat",
    ),
    "Suspicious activity": (
        "suspicious circumstances", "suspicious circumstance",
        "suspicious circumstances at a school", "suspicious person", "suspicious persons",
        "suspicious subjects", "suspicious vehicle", "suspicious vehicle report",
        "suspicious prowler video", "prowler", "loitering", "loitering complaint",
        "trespassing",
    ),
    "Alarms": (
        "alarm", "burglary alarm", "audible alarm", "commercial alarm", "commercial fire alarm",
        "emergency alarm", "fire alarm", "medical alarm", "residential alarm", "robbery alarm",
    ),
    OTHER: (
        "vandalism", "animal bite", "animal complaint", "911 disconnect", "911 hang-up",
        "open-line call", "gas leak", "gas odor", "hazmat", "hazardous condition",
        "downed power lines", "flooding", "loud explosion report", "incident", "vehicle",
        "arrest", "escapee search", "felony warrant", "warrant service", "probation check",
        "restraining order service", "foot pursuit", "foot pursuit / arrest",
        "foot pursuit and search", "perimeter search", "search for a suspect",
        "homicide-related check", "kidnapping report", "possibly held against will",
        "officer assist", "public assist", "public service", "repo assist",
    ),
}

CHIP_OF: dict[str, str] = {}
for _chip, _labels in MAP.items():
    for _label in _labels:
        if _label in CHIP_OF:
            raise RuntimeError(f"night_counts: label in two chips: {_label!r}")
        CHIP_OF[_label] = _chip


class NightCountError(RuntimeError):
    """The overnight numbers do not add up. The build must stop, not print them."""


def normalize(typ) -> str:
    """'Traffic collision', 'traffic_collision' and ' traffic  collision' are one label."""
    return re.sub(r"\s+", " ", str(typ or "incident").replace("_", " ")).strip().lower()


def chips(incs: list[dict]) -> tuple[list[tuple[str, int]], str, list[str]]:
    """Rows of one night's file -> ([(row label, count), ...] in display order, the breakdown
    of the Other row, unmapped labels).

    Every row lands in exactly one chip, so the counts sum to len(incs); that is checked here
    and again on the rendered band. The breakdown names every type inside Other with its count
    ("5 incident, 1 public service"). When Other is more than a fifth of the night, its largest
    type gets a row of its own, just above it.

    A label that is not in MAP is counted in Other under its own name and logged. Set
    KO_STRICT_TYPES=1 to stop the build on it instead.
    """
    by_chip: Counter = Counter()
    other: Counter = Counter()
    unmapped: list[str] = []
    for inc in incs:
        label = normalize(inc.get("type"))
        chip = CHIP_OF.get(label)
        if chip is None:
            if label not in unmapped:
                unmapped.append(label)
            chip = OTHER
        if chip == OTHER:
            other[label] += 1
        else:
            by_chip[chip] += 1
    if unmapped:
        msg = f"night_counts: incident type not in the map: {unmapped}"
        if os.environ.get("KO_STRICT_TYPES") == "1":
            raise NightCountError(msg)
        common.log(f"WARNING {msg} (counted in Other, named under the row)")

    total = len(incs)
    out = [(chip, by_chip[chip]) for chip in MAP if by_chip[chip]]
    while len(other) > 1 and sum(other.values()) * 5 > total:
        label, n = other.most_common(1)[0]
        del other[label]
        out.append((label[:1].upper() + label[1:], n))
    inside = ""
    if other:
        inside = ", ".join(f"{n} {label}" for label, n in other.most_common())
        out.append((OTHER, sum(other.values())))

    if sum(n for _, n in out) != total:
        raise NightCountError(
            f"night_counts: chips sum to {sum(n for _, n in out)}, the night has {total} calls")
    return out, inside, unmapped
