"""The report's privacy HARD RULES, in ONE place, for BOTH sources.

The rules used to live in merge_crimeradar and screen only app rows. A RADIO row
carries the same kind of detail: on 2026-10-10 the 10:13 p.m. welfare check said
a man "had cuts on his wrist", with a block address, and nothing screened it,
because ALWAYS_PRIVATE only ran over the emulator feed. One rule, one place, so
the radio and app paths cannot drift apart.

Editorial rule (owner, 2026-10-04): most medical calls stay out; a SEVERE one is
news and stays in.
"""
import re

# Never published, however serious, from EITHER source: self-harm, mental-health
# and maternity calls.
ALWAYS_PRIVATE = re.compile(
    r"\b(suicid\w*|self[- ]harm\w*|psychiatric|mental health|5150|delusion\w*|"
    r"maternity|pregnan\w*|in labor|"
    r"cuts? on (?:his|her|their) wrist|slit (?:his|her|their) wrist)\b", re.I)
# Routine medical traffic: out unless the same headline is also SEVERE.
MEDICAL = re.compile(
    r"\b(patient|hospital|ambulance|medical|overdos\w*|seizure\w*|cardiac|"
    r"breathing|unresponsive|unconscious|cpr|pain|traumatic|ill|sick|fainted|"
    r"mercy|memorial|adventist|kaiser|dignity health|kern medical|"
    r"ankle|wrist|knee|hip|leg|fracture\w*|sprain\w*|laceration\w*|"
    r"stroke|diabetic|allergic|choking|dizz\w*|vomit\w*|"
    r"lift assist|ground[- ]level fall)\b", re.I)
# A fall is routine medical only when a PERSON is its subject. "Woman falls and
# injures ankle" (2026-10-10 6:56 a.m.) is not news; "tree falls on car" is.
FALL = re.compile(
    r"\b(man|woman|person|child|boy|girl|resident|elderly|senior|pedestrian|"
    r"cyclist|worker)\b[^.;]{0,20}\b(falls?|fell|fallen)\b", re.I)
SEVERE = re.compile(
    r"\b(cpr|unconscious|unresponsive|not breathing|cardiac arrest|drown\w*|"
    r"fatal\w*|dead|deceased|doa|life[- ]threatening|critical(?:ly)?|"
    r"major injur\w*|traumatic injur\w*|shot|gunshot|stabb\w*|electrocut\w*|"
    r"burn(?:ed|s)? victim)\b", re.I)


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
    if FALL.search(text):
        return not is_severe(text)
    return bool(medical or MEDICAL.search(text)) and not is_severe(text)
