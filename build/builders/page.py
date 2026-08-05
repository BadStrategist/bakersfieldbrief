#!/usr/bin/env python3
"""Page shell: fills the layout template tokens shared by every page."""
from __future__ import annotations

import html as htmlmod
import json

from .. import common

SITE_NAME = "Bakersfield Daily Brief"


def render(*, title: str, desc: str, canonical: str, content: str,
           current: str = "", rel: str = "", built: str = "",
           jsonld: list | None = None, extra_head: str = "",
           extra_scripts: str = "", og_title: str | None = None,
           og_desc: str | None = None, statusbar: str = "") -> str:
    """Render a full page from templates/layout.html.

    rel: relative prefix from this page's dir to site root ("" or "../…")
    current: nav section to mark active (index|cityhall|openings|trackers|workmoney|sunday|other)
    statusbar: pre-built status-bar HTML (see build_statusbar) or ""
    """
    tpl = common.read_template("layout.html")
    og_title = og_title or title
    og_desc = og_desc or desc

    # nav current markers
    cur_flags = {k: "" for k in ("index", "cityhall", "openings", "trackers", "places", "workmoney", "sunday")}
    if current in cur_flags:
        cur_flags[current] = 'aria-current="page"'

    tokens = {
        "__TITLE__": htmlmod.escape(title),
        "__DESC__": htmlmod.escape(desc),
        "__CANONICAL__": canonical,
        "__OGTITLE__": htmlmod.escape(og_title),
        "__OGDESC__": htmlmod.escape(og_desc),
        "__BUILT__": built,
        "__REL__": rel,
        "__CONTENT__": content,
        "__EXTRAHEAD__": extra_head,
        "__EXTRASCRIPTS__": extra_scripts,
        "__JSONLD__": _jsonld(jsonld),
        "__STATUSBAR__": statusbar or "",
    }
    for k, v in cur_flags.items():
        tokens[f"__CUR_{k}__"] = v

    for tok, val in tokens.items():
        tpl = tpl.replace(f"<!--{tok}-->", val)
    return tpl


def _jsonld(blocks: list | None) -> str:
    if not blocks:
        return ""
    out = []
    for b in blocks:
        out.append(f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>')
    return "\n  ".join(out)


def build_statusbar(weather: dict, escribe: dict) -> str:
    """Top status strip (Tucson-style): alerts + next meeting on the left,
    live Bakersfield weather on the right. All values come from fetched data;
    anything missing degrades gracefully."""
    import html as h

    # left: alerts
    alerts = (weather or {}).get("alerts", [])
    if alerts:
        top = alerts[0]
        alert_txt = (f'<span class="sb-alert">{h.escape(top.get("event", "Weather alert"))} active</span>')
    else:
        alert_txt = '<span class="sb-ok"><span class="dot"></span>No active weather alerts</span>'

    # left: next meeting
    upcoming = (escribe or {}).get("upcoming", [])
    if upcoming:
        m = upcoming[0]
        name = m.get("name", "City meeting")
        when = m.get("start_iso", "")
        day, time = _meeting_when(when)
        meeting_txt = (f'<span class="sb-meeting"><strong>Next meeting:</strong> '
                       f'{h.escape(name[:38])} &middot; {day} {h.escape(time)}</span>')
    else:
        meeting_txt = '<span class="sb-meeting">No upcoming meetings posted</span>'

    # right: weather
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    if cur is not None and hi is not None:
        w = f"{cur}&deg; / {hi}&deg;"
    elif hi is not None and lo is not None:
        w = f"{hi}&deg; / {lo}&deg;"
    elif cur is not None:
        w = f"{cur}&deg;"
    else:
        w = "weather n/a"
    weather_txt = f'<span class="sb-weather">{w} <span class="sb-city">Bakersfield</span></span>'

    return (f'<div class="statusbar"><div class="container statusbar-inner">'
            f'<span class="sb-left">{alert_txt}<span class="sep">&middot;</span>{meeting_txt}</span>'
            f'<span class="sb-right">{weather_txt}</span></div></div>')


def _meeting_when(iso: str) -> tuple[str, str]:
    import datetime as dt
    try:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                d = dt.datetime.strptime(iso, fmt)
                break
            except ValueError:
                continue
        else:
            return "", ""
        day = d.strftime("%a").upper()
        t = d.strftime("%I:%M %p").lstrip("0")
        return day, t
    except Exception:  # noqa: BLE001
        return "", ""


def org_jsonld() -> dict:
    """Full NewsMediaOrganization block (the schema.org type for news
    publishers — newspapers, TV stations, digital newsrooms). Includes the
    publisher-identity fields Google's news rich-result guidance expects:
    logo, contact point, policies. All URLs are honest targets we ship."""
    return {
        "@context": "https://schema.org",
        "@type": "NewsMediaOrganization",
        "name": SITE_NAME,
        "url": "https://bakersfieldbrief.com/",
        "logo": {
            "@type": "ImageObject",
            "url": "https://bakersfieldbrief.com/assets/img/logo.svg",
            "width": 100,
            "height": 100,
        },
        "description": "A free, automated daily civic news brief for Bakersfield and Kern County, California.",
        "areaServed": "Bakersfield and Kern County, California",
        "foundingDate": "2026-08-04",
        "email": "editor@bakersfieldbrief.com",
        "contactPoint": {
            "@type": "ContactPoint",
            "email": "editor@bakersfieldbrief.com",
            "contactType": "editorial",
            "areaServed": "US",
            "availableLanguage": "en",
        },
        "masthead": "https://bakersfieldbrief.com/about/",
        "publishingPrinciples": "https://bakersfieldbrief.com/about/",
        "correctionsPolicy": "https://bakersfieldbrief.com/about/",
        "actionableFeedbackPolicy": "https://bakersfieldbrief.com/contact/",
        "ownershipFundingInfo": "https://bakersfieldbrief.com/about/",
        "ethicsPolicy": "https://bakersfieldbrief.com/about/",
        "isAccessibleForFree": True,
    }


def website_jsonld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": "https://bakersfieldbrief.com/",
        "description": "Daily civic brief, meeting previews, openings & closings, and data trackers for Bakersfield and Kern County.",
        "isAccessibleForFree": True,
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
