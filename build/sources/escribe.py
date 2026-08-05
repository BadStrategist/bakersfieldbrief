#!/usr/bin/env python3
"""eSCRIBE: City of Bakersfield meetings + agendas.

POST https://pub-bakersfield.escribemeetings.com/MeetingsCalendarView.aspx/GetCalendarMeetings
body {"calendarStartDate": YYYY-MM-DD, "calendarEndDate": YYYY-MM-DD}

Returns meetings with IDs; agendas are parseable HTML at
  Meeting.aspx?Id=<guid>&Agenda=Agenda&lang=English   (no PDF parsing needed)

Also keyword-watches agenda items for "Flock" / "ALPR" (surveillance beat).
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common

API = "https://pub-bakersfield.escribemeetings.com/MeetingsCalendarView.aspx/GetCalendarMeetings"
AGENDA_BASE = "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?Id={guid}&Agenda=Agenda&lang=English"
WATCH_WORDS = ("flock", "alpr", "license plate reader", "automated license", "surveillance")

DAYS_AHEAD = 21


def run(ctx):
    try:
        today = ctx.today
        meetings = fetch_meetings(today, today + dt.timedelta(days=DAYS_AHEAD))

        # agenda details for upcoming meetings (next 7 days) + keyword watch
        upcoming = []
        watched = []
        for m in meetings:
            try:
                s = _parse_start(m["start"])
            except Exception:
                s = None
            if s is None:
                continue
            m["start_iso"] = s.isoformat()
            if today <= s.date() <= today + dt.timedelta(days=7):
                items = _fetch_agenda(m["id"])
                m["items"] = items
                hits = [i for i in items if _watch_hit(i)]
                if hits:
                    watched.append({"meeting": m["name"], "date": m["start_iso"],
                                    "items": hits, "url": m["url"]})
                upcoming.append(m)

        # recently held meetings (past 14 days) for "What They Decided" cards
        recent = []
        for m in fetch_meetings(today - dt.timedelta(days=14), today):
            try:
                s = _parse_start(m["start"])
            except Exception:
                continue
            if s.date() < today:
                m["start_iso"] = s.isoformat()
                recent.append(m)
        recent.sort(key=lambda m: m.get("start_iso", ""), reverse=True)

        return {"ok": True, "meetings": meetings, "upcoming": upcoming,
                "recent": recent[:6], "watched": watched, "asof": common.iso_today()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def fetch_meetings(start: dt.date, end: dt.date) -> list[dict]:
    """Raw meeting list from the eSCRIBE calendar API (any date window)."""
    r = common.fetch(API, method="POST",
                     json={"calendarStartDate": start.isoformat(),
                           "calendarEndDate": end.isoformat()})
    payload = r.json().get("d")
    if isinstance(payload, str):
        payload = __import__("json").loads(payload)
    meetings = []
    for m in payload or []:
        meeting = {
            "id": m.get("MeetingId") or m.get("ID"),
            "name": m.get("MeetingName") or m.get("Title"),
            "start": m.get("StartDate") or m.get("FormattedStart"),
            "formatted": m.get("FormattedStart"),
            "desc": (m.get("Description") or "").strip(),
            "url": AGENDA_BASE.format(guid=m.get("MeetingId") or m.get("ID")),
        }
        if meeting["id"] and meeting["name"]:
            meetings.append(meeting)
    return meetings


def _parse_start(s):
    if not s:
        raise ValueError("no start")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%m/%d/%Y %I:%M %p",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    # ISO with T and zone, e.g. 2026-08-04T18:00:00
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)", s)
    if m:
        return dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M")
    raise ValueError(f"unparsed start {s!r}")


def _fetch_agenda(guid, max_items: int = 60) -> list[dict]:
    """Parse agenda HTML into [{"num","title","text"}]. Returns [] on any failure.

    eSCRIBE marks items with class 'AgendaItemContainer' / 'AgendaItemTitleRow',
    but the most robust extraction is over the stripped text: numbered lines
    like '3. Update on Measure N' or '3) Closed session report'.
    """
    try:
        r = common.fetch(AGENDA_BASE.format(guid=guid), timeout=25)
        text = r.text
    except Exception:  # noqa: BLE001
        return []

    body = re.sub(r"<script.*?</script>", "", text, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<(br|/p|/div|/li|/tr)[^>]*>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)

    items = []
    for ln in body.splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        m = re.match(r"^(\d{1,3})[.)]\s+(.+)$", s)
        if m and len(m.group(2)) > 2 and not m.group(2).lower().startswith("agenda"):
            title = m.group(2)
            items.append({"num": m.group(1), "title": title, "text": s})

    if not items:  # fallback: classed containers
        for block in re.findall(r'<div[^>]*class="[^"]*AgendaItemContainer[^"]*"[^>]*>(.*?)</div>', text, re.S):
            txt = re.sub(r"<[^>]+>", " ", block)
            txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
            if txt and not txt.lower().startswith("agenda"):
                items.append({"num": "", "title": txt, "text": txt})

    seen, out = set(), []
    for it in items:
        key = (it["num"], it["title"][:40])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= max_items:
            break
    return out


def _watch_hit(item: dict) -> bool:
    hay = (item.get("title", "") + " " + item.get("text", "")).lower()
    return any(w in hay for w in WATCH_WORDS)
