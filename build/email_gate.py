#!/usr/bin/env python3
"""Single source of truth for the daily-brief email content gate.

Every section of the rendered email must be present and non-degenerate before
the brief is allowed to send. The CI send path (scripts/send_newsletter_ml.py)
and the Hermes watchdog (bb_email_watchdog.py) both refuse to ship a degraded
brief, so this logic lives in ONE module instead of two drifting copies — the
2026-09-01 degraded email shipped because the overnight narrative was checked
in neither path.

Pure stdlib only (re, pathlib, zoneinfo, datetime) so any Python >= 3.10 can
import it: the watchdog runs under Hermes's python, the send gate under the
repo's venv python. No repo dependencies are pulled in.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def content_is_degraded(html_path) -> list[str]:
    """Return the names of missing/empty sections; [] means the email is complete.

    Reads the rendered brief.html and checks every section the email carries:
    weather, something good, overnight narrative, date, local headlines, and
    the Flock/ALPR tracker card. Any one degraded => that section is returned,
    and every caller MUST refuse to send.
    """
    p = Path(html_path)
    if not p.exists():
        return ["no rendered brief"]
    text = p.read_text(encoding="utf-8", errors="replace")

    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    human = f"{now.strftime('%B')} {now.day}, {now.year}"
    iso = now.strftime("%Y-%m-%d")

    # weather: a real temperature reading, not the degraded placeholder.
    # Accept the degree symbol (72°), a number + "degrees" (61 degrees), or a
    # high/low phrase that carries a number ("high near 82", "high expected to
    # reach only 82", "low dipping to around 60"). The LLM's prose varies, so
    # only requiring "°" or the literal "high near"/"low around" phrases
    # false-flagged GOOD emails on 2026-09-01 and 2026-09-02.
    has_temp = (
        ("°" in text)
        or bool(re.search(r"\b\d{1,3}\s*degrees?\b", text))
        or bool(re.search(r"\b(high|low)\b[^.]{0,80}?\b\d{1,3}\b", text))
    )

    checks = {
        "weather": has_temp and "Weather data unavailable" not in text,
        # the baked weather graphic (bakersfieldbrief.com/assets/img/weather-card.jpg)
        # must be embedded in the Today's Weather card — it is regenerated every
        # build from live NWS + AirNow data, so a card missing it means the
        # redraw failed and the send must be blocked (never a degraded/stale card).
        "weather image": _has_weather_image(text),
        # something good: the template emits the card + kicker only when content
        # exists; guard on TWO occurrences (comment + kicker) so a bare template
        # comment can't pass.
        "something good": text.count("Something Good") >= 2,
        # overnight: the card degrades to headline + count + Full Report link
        # when the LLM narrative is empty; require real prose after the link.
        "overnight": _has_overnight_narrative(text),
        # today's date must be in the body (ISO or human label).
        "date": (iso in text) or (human in text),
        # local headlines: at least one real source link in the card.
        "headlines": _has_headlines(text),
        # Flock/ALPR tracker card must be present and complete (image + real
        # camera counts + a new-camera line). This is the daily flagship section.
        "flock/alpr": _has_flock_card(text),
    }
    return [k for k, ok in checks.items() if not ok]


# -------------------------------------------------------------------------- helpers

def _slice_between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i == -1:
        return ""
    j = text.find(end, i)
    return text[i:j] if j != -1 else text[i:]


def _has_weather_image(text: str) -> bool:
    """True if the Today's Weather card embeds the live weather graphic.

    The emailer regenerates weather-card.jpg from today's NWS observation +
    forecast and AirNow AQI on every build and embeds it as a live URL. A
    render failure drops the image (fail-closed in emailer.py), so a complete
    email must carry the image reference inside the weather card. This mirrors
    the Flock tracker card's presence check.
    """
    card = _slice_between(text, "Today's Weather card", "Something Good card")
    if not card:
        return False
    return "weather-card.jpg" in card


def _overnight_tail(text: str) -> str:
    """The overnight narrative prose: text after the 'Full Report' link inside
    the Kern Overnight card, with HTML comments/tags stripped and whitespace
    collapsed. Returns '' when there is no card or no narrative text.

    Matches the card by its visible kicker text ('Kern Overnight' and
    \"Today's Weather\") rather than the exact HTML comment markers, so the
    check survives a template comment change. Both strings appear in the card
    regardless of comment verbatimness (they are the rendered kickers too).
    """
    i = text.find("Kern Overnight")
    if i == -1:
        return ""
    j = text.find("Today's Weather", i)
    card = text[i:j] if j != -1 else text[i:]
    marker = card.lower().rfind("full report")
    if marker != -1:
        card = card[marker + len("full report"):]
    card = re.sub(r"<!--.*?-->", "", card, flags=re.S)
    card = re.sub(r"<[^>]+>", " ", card)
    return re.sub(r"\s+", " ", card).strip()


def _has_overnight_narrative(text: str) -> bool:
    """True if the Kern Overnight card carries real narrative prose.

    Distinguishes a REAL overnight summary — even a short 2-3 sentence one
    that carries a real number (incident count / time) — from a genuinely
    MISSING one, where the card degrades to boilerplate with no real data.

    Sentence boundaries are counted structurally ([.!?] followed by whitespace
    or end-of-string), NOT via the brittle '. ' marker — real prose may join
    sentences with newlines, which '. ' misses.

    * >= 2 sentences is required (a missing card leaves 0-1 boilerplate lines).
    * A short 2-sentence summary must carry a digit (a count/time), otherwise
      it is only boilerplate ("Scanner brief from 9pm to 5am. Locations
      generalized."), not a real overnight rundown. Longer prose (>= 3
      sentences) passes on volume alone.
    """
    tail = _overnight_tail(text)
    if not tail:
        return False
    sentences = len(re.findall(r"[.!?](?=\s|$)", tail))
    if sentences < 2:
        return False
    has_digit = bool(re.search(r"\d", tail))
    return has_digit or sentences >= 3


def _has_headlines(text: str) -> bool:
    """True if the Local Headlines card carries at least one real source link.

    Headline rows are <a href="http..."> links to the original reporting; the
    card's only external links are the headlines themselves (the follow/CTA and
    footer links point at bakersfieldbrief.com / social). Require >= 1 external
    headline link so an empty news feed can never ship as a blank card.
    """
    card = _slice_between(text, "Local Headlines card", "One Thing to Watch card")
    if not card:
        return False
    links = re.findall(r'href="(https?://[^"]+)"', card)
    external = [u for u in links if "bakersfieldbrief.com" not in u]
    return len(external) >= 1


def _has_flock_card(text: str) -> bool:
    """True if the Flock/ALPR tracker card is present and complete.

    This is the daily flagship section (the email's 'One Thing to Watch' card
    becomes 'Flock & ALPR Tracker' when the alpr source is OK). A sloppy card
    — missing the tracker image, or a camera count of 0, or no new-camera line
    — must block the send rather than ship half a tracker.
    """
    card = _slice_between(text, "One Thing to Watch card", "follow CTA")
    if not card:
        return False
    # The Flock kicker ("Flock &amp; ALPR Tracker") identifies this as the
    # tracker card rather than the meeting-agenda fallback.
    if "Flock" not in card:
        return False
    if "tracker-map-card.jpg" not in card:
        return False
    if "ALPR cameras" not in card:
        return False
    # Real camera totals: the emailer emits "<strong>{flock}</strong> of
    # <strong>{total}</strong> ALPR cameras" — require a numeric total >= 1.
    total = re.search(r"of\s*<strong>\s*(\d+)\s*</strong>\s*ALPR cameras", card)
    if not total or int(total.group(1)) < 1:
        return False
    # A new-camera line ("N new camera[s] mapped ..." or "No new cameras mapped").
    if "new camera" not in card:
        return False
    # Freshness: the card must carry a "Data as of YYYY-MM-DD" line whose date
    # is recent. The alpr source stamps asof=today every successful build, so
    # a card that is present but stale (a 11-day-old image, as shipped on
    # 2026-09-01) must block. 3-day window absorbs timezone/build lag without
    # letting an old card through.
    m = re.search(r"Data as of\s+(\d{4}-\d{2}-\d{2})", card)
    if not m:
        return False
    from datetime import date, timedelta
    try:
        asof = date.fromisoformat(m.group(1))
    except ValueError:
        return False
    if abs((date.today() - asof).days) > 3:
        return False
    return True
