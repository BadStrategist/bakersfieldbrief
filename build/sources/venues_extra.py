"""More Bakersfield venue calendars (added 2026-09-22), each verified by fetching it.

  simpletix   Bakersfield Community Theatre: list page -> each show page's schema.org Event
  temblor     Temblor Brewing: concert/comedy cards on the home page
  ics         iCal feeds (CSU Bakersfield and Bakersfield College athletics), home games only
  squarespace Bakersfield Symphony: Squarespace event list (the ?format=json/ical URLs are
              disallowed by its robots.txt, so the HTML page is read instead)

Every parser returns [{"name", "when", "url"}] like the ones in venues.py; "when" is Pacific
local time as "YYYY-MM-DD HH:MM" (or a date the events page can parse). A failure raises and is
isolated by venues.run(), so one broken venue never touches the others.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re

from .. import common

HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
HORIZON_DAYS = 60     # athletics feeds list a whole season; keep the next two months


def local_when(start: str) -> str:
    """ISO start (with or without an offset) -> Pacific 'YYYY-MM-DD HH:MM'. UTC stamps used to be
    cut at 16 characters, so a 7:30 PM show stored as 02:30Z showed on the next day."""
    s = (start or "").strip()
    if not s:
        return ""
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:16].replace("T", " ")
    if d.tzinfo is not None:
        d = d.astimezone(common.PACIFIC)
    return d.strftime("%Y-%m-%d %H:%M") if len(s) > 10 else d.strftime("%Y-%m-%d")


def ld_events(page_html: str) -> list[dict]:
    """schema.org Events from a page, including ones nested in @graph or itemListElement."""
    out = []

    def walk(x):
        if isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            t = x.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(tt or "").endswith("Event") for tt in types) and x.get("name"):
                out.append(x)
            for k in ("@graph", "itemListElement", "item", "subEvent"):
                if k in x:
                    walk(x[k])
    for b in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page_html, re.S):
        try:
            walk(json.loads(b))
        except Exception:  # noqa: BLE001
            continue
    return out


def _fmt(ev: dict, fallback_url: str) -> dict:
    return {"name": html.unescape(str(ev.get("name", ""))).strip(),
            "when": local_when(str(ev.get("startDate") or "")),
            "url": ev.get("url") or fallback_url}


def simpletix(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=20, retries=1)
    links = []
    for u in re.findall(r'https://www\.simpletix\.com/e/[A-Za-z0-9\-]+', r.text):
        if u not in links:
            links.append(u)
    events = []
    for u in links[:12]:
        try:
            # decode as UTF-8 ourselves: requests guessed Latin-1 and mangled "★" in show names
            page = common.fetch(u, headers=HEADERS, timeout=15, retries=0).content.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - one show page failing skips that show only
            continue
        seen = set()
        today = common.iso_today()
        for ev in ld_events(page):
            e = _fmt(ev, u)
            e["name"] = re.sub(r"\s*[★☆•]\s*", ": ", e["name"])
            key = (e["name"], e["when"][:10])
            if e["name"] and key not in seen and e["when"][:10] >= today:
                seen.add(key)
                events.append(e)
    return events


def temblor(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=20, retries=1)
    events = []
    for when, name, meta, url in re.findall(
            r'<p class="ed">(.*?)</p>\s*<h3 class="et">(.*?)</h3>\s*(?:<p class="em">(.*?)</p>)?\s*'
            r'<a href="([^"]+)"', r.text, re.S):
        when_t = html.unescape(re.sub(r"<[^>]+>", "", when)).replace("·", "|")
        m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", when_t)
        kind = re.sub(r"\s*·\s*", ", ", html.unescape(re.sub(r"<[^>]+>", "", meta or ""))).strip()
        title = html.unescape(re.sub(r"<[^>]+>", "", name)).strip()
        events.append({"name": f"{title} ({kind.lower()})" if kind else title,
                       "when": m.group(1) if m else "",
                       "url": html.unescape(url)})
    return events


def _ics_events(text: str) -> list[dict]:
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()      # unfold continuation lines
    out, cur = [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT" and cur is not None:
            out.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            k, val = ln.split(":", 1)
            key = k.split(";")[0].upper()
            val = val.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()
            cur[key] = val
            if key == "DTSTART":
                cur["_dtparams"] = k
    return out


def _ics_start(e: dict) -> dt.datetime | None:
    v = e.get("DTSTART", "")
    try:
        if len(v) == 8:
            return dt.datetime.strptime(v, "%Y%m%d").replace(tzinfo=common.PACIFIC)
        d = dt.datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
        if v.endswith("Z"):
            return d.replace(tzinfo=dt.timezone.utc).astimezone(common.PACIFIC)
        return d.replace(tzinfo=common.PACIFIC)        # TZID feeds here are Pacific
    except ValueError:
        return None


def ics(v) -> list[dict]:
    """Home games only: CSUB by a Bakersfield LOCATION, Bakersfield College by 'vs. Bakersfield'."""
    r = common.fetch(v["url"], headers=HEADERS, timeout=25, retries=1)
    now = common.now_pacific()
    end = now + dt.timedelta(days=HORIZON_DAYS)
    rule = v.get("home_rule", "")
    events = []
    for e in _ics_events(r.text):
        start = _ics_start(e)
        if start is None or not (now <= start <= end):
            continue
        summary = e.get("SUMMARY", "").strip()
        loc = e.get("LOCATION", "")
        if rule == "location_bakersfield":
            if not loc.lower().startswith("bakersfield") or "select-a-seat" in summary.lower():
                continue
        elif rule == "vs_bakersfield":
            if not re.search(r"vs\.? Bakersfield\s*$", summary, re.I):
                continue
        if rule == "vs_bakersfield":
            # "(Football) Pasadena City vs. Bakersfield" -> "Bakersfield College Football vs. Pasadena City"
            m = re.match(r"\((.*?)\)\s*(.*?)\s+vs\.?\s+Bakersfield\s*$", summary, re.I)
            name = (f"{v.get('prefix', '')}{m.group(1)} vs. {m.group(2)}" if m
                    else f"{v.get('prefix', '')}{summary}")
        else:
            summary = re.sub(r"^California State University,? Bakersfield\s+", "", summary)
            name = f"{v.get('prefix', '')}{summary}"
        url = html.unescape(e.get("URL") or v.get("site", v["url"]))
        if url.startswith("/"):
            url = re.match(r"https?://[^/]+", v["url"]).group(0) + url
        # a midnight start in these feeds means "time not set", not 12 AM
        when = start.strftime("%Y-%m-%d") if (start.hour, start.minute) == (0, 0) else start.strftime("%Y-%m-%d %H:%M")
        events.append({"name": name.strip(), "when": when, "url": url})
    return events[:40]


def squarespace(v) -> list[dict]:
    r = common.fetch(v["url"], headers=HEADERS, timeout=20, retries=1)
    base = re.match(r"https?://[^/]+", v["url"]).group(0)
    events = []
    for art in re.findall(r'<article class="eventlist-event eventlist-event--upcoming.*?</article>', r.text, re.S):
        t = re.search(r'class="eventlist-title-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', art, re.S) or \
            re.search(r'href="([^"]+)"[^>]*class="eventlist-title-link"[^>]*>(.*?)</a>', art, re.S)
        d = re.search(r'<time class="event-date" datetime="(\d{4}-\d{2}-\d{2})"', art)
        if not t or not d:
            continue
        tm = re.search(r'<time class="event-time-(?:localized|12hr)[^"]*"[^>]*>(.*?)</time>', art, re.S)
        when = d.group(1)
        if tm:
            hm = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp])", html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))))
            if hm:
                h = int(hm.group(1)) % 12 + (12 if hm.group(3).lower() == "p" else 0)
                when = f"{d.group(1)} {h:02d}:{hm.group(2)}"
        href = t.group(1)
        events.append({"name": html.unescape(re.sub(r"<[^>]+>", "", t.group(2))).strip(),
                       "when": when,
                       "url": href if href.startswith("http") else base + href})
    return events


def gaslight(v) -> list[dict]:
    """Gaslight Melodrama Theatre: the schedule page lists each production as
    <h4>September 18 - November 14</h4><h2>A Funny Fright In The <span>Night</span></h2>.
    Weekly show times aren't published in a readable form, so a production is one entry for its
    run (never invented performance times): "Now playing, through Nov 14" or "Opens Nov 27, runs
    through Dec 23". Only runs that haven't ended and open within 60 days are kept."""
    r = common.fetch(v["url"], headers=HEADERS, timeout=20, retries=1)
    page = r.content.decode("utf-8", "replace")
    today = common.today_pacific()
    ym = re.search(r"(20\d\d) Schedule", page)
    year = int(ym.group(1)) if ym else today.year
    events = []
    for rng, title in re.findall(r"<h4>\s*([A-Za-z]+ \d{1,2}\s*-\s*(?:[A-Za-z]+ )?\d{1,2})\s*</h4>\s*<h2>(.*?)</h2>",
                                 page, re.S):
        m = re.match(r"([A-Za-z]+) (\d{1,2})\s*-\s*(?:([A-Za-z]+) )?(\d{1,2})", rng)
        try:
            start = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {year}", "%B %d %Y").date()
            end = dt.datetime.strptime(f"{m.group(3) or m.group(1)} {m.group(4)} {year}", "%B %d %Y").date()
        except (ValueError, AttributeError):
            continue
        if end < start:                      # a run that crosses New Year
            end = end.replace(year=year + 1)
        if end < today or (start - today).days > HORIZON_DAYS:
            continue
        name = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", title)).split())
        running = start <= today
        label = (f"Now playing, through {end:%b} {end.day}" if running
                 else f"Opens {start:%b} {start.day}, runs through {end:%b} {end.day}")
        events.append({"name": name, "when": (today if running else start).isoformat(),
                       "label": label, "start": start.isoformat(), "end": end.isoformat(),
                       "url": v.get("site", v["url"])})
    return events


PARSERS = {"simpletix": simpletix, "temblor": temblor, "ics": ics, "squarespace": squarespace,
           "gaslight": gaslight}
