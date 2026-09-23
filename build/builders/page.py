#!/usr/bin/env python3
"""Page shell: fills the layout template tokens shared by every page."""
from __future__ import annotations

import hashlib
import html as htmlmod
import json

from .. import common

SITE_NAME = "Bakersfield Daily Brief"


def render(*, title: str, desc: str, canonical: str, content: str,
           current: str = "", rel: str = "", built: str = "",
           jsonld: list | None = None, extra_head: str = "",
           extra_scripts: str = "", og_title: str | None = None,
           og_desc: str | None = None,
           og_image: str = "https://bakersfieldbrief.com/assets/img/emblem.png",
           statusbar: str = "", og_type: str = "website",
           robots: str = "index, follow") -> str:
    """Render a full page from templates/layout.html.

    rel: relative prefix from this page's dir to site root ("" or "../…")
    current: nav section to mark active (index|cityhall|trackers|sunday|other)
    statusbar: pre-built status-bar HTML (see build_statusbar) or ""
    """
    tpl = common.read_template("layout.html")
    og_title = og_title or title
    og_desc = og_desc or desc

    # nav current markers
    cur_flags = {k: "" for k in ("index", "cityhall", "trackers", "alpr", "places", "overnight",
                                 "sunday", "events", "about")}
    if current in cur_flags:
        cur_flags[current] = 'aria-current="page"'

    _year = built[:4] if (built and len(built) >= 4 and built[:4].isdigit()) else ""
    if not _year:
        import datetime as _dt
        _year = str(_dt.date.today().year)

    tokens = {
        "__TITLE__": htmlmod.escape(title),
        "__DESC__": htmlmod.escape(desc),
        "__CANONICAL__": canonical,
        "__OGTITLE__": htmlmod.escape(og_title),
        "__OGDESC__": htmlmod.escape(og_desc),
        "__OGIMAGE__": og_image,
        "__OGTYPE__": og_type,
        "__ROBOTS__": robots,
        "__BUILT__": built,
        "__YEAR__": _year,
        "__CSSV__": _asset_ver("assets/css/site.css"),
        "__JSV__": _asset_ver("assets/js/main.js"),
        "__REL__": rel,
        "__CONTENT__": content,
        "__EXTRAHEAD__": extra_head,
        "__EXTRASCRIPTS__": extra_scripts,
        "__JSONLD__": _jsonld((jsonld or []) + _breadcrumb_ld(content, canonical)),
        "__STATUSBAR__": statusbar or "",
    }
    for k, v in cur_flags.items():
        tokens[f"__CUR_{k}__"] = v

    for tok, val in tokens.items():
        tpl = tpl.replace(f"<!--{tok}-->", val)
    return tpl


def _asset_ver(rel_path: str) -> str:
    """Content-hash cache-buster (?v=<sha1[:10]>) for a built asset.

    Hashes the SOURCE bytes under assets/ (copied verbatim into site/ during
    the build), so the version equals the deployed file's content hash. NEVER
    date-based: a same-day CSS/JS edit must change the version or returning
    browsers keep serving the stale cached file (this bit us before).
    """
    try:
        b = (common.ROOT / rel_path).read_bytes()
        return hashlib.sha1(b).hexdigest()[:10]
    except OSError:
        return ""


def _breadcrumb_ld(content: str, canonical: str) -> list:
    """BreadcrumbList from the page's own visible breadcrumbs, so markup and page never differ.
    Visible breadcrumbs existed on trackers, places and city hall, but only /fair/ had the markup."""
    import re
    from urllib.parse import urljoin
    m = re.search(r'<nav class="breadcrumbs"[^>]*>(.*?)</nav>', content or "", re.S)
    if not m:
        return []
    base = "https://bakersfieldbrief.com" + (canonical or "/")
    parts = [p.strip() for p in re.split(r"&rsaquo;|›", m.group(1)) if p.strip()]
    items = []
    for i, part in enumerate(parts, 1):
        a = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', part, re.S)
        name = htmlmod.unescape(re.sub(r"<[^>]+>", "", a.group(2) if a else part)).strip()
        if not name:
            continue
        url = urljoin(base, a.group(1)) if a else base
        items.append({"@type": "ListItem", "position": len(items) + 1, "name": name, "item": url})
    if len(items) < 2:
        return []
    return [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}]


def _jsonld(blocks: list | None) -> str:
    if not blocks:
        return ""
    out = []
    for b in blocks:
        out.append(f'<script type="application/ld+json">{common.script_json(b)}</script>')
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
    elif not (weather or {}).get("ok"):
        # a failed NWS fetch is not an all-clear
        alert_txt = '<span class="sb-meeting">Weather alerts unavailable right now</span>'
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
    elif not (escribe or {}).get("ok"):
        meeting_txt = '<span class="sb-meeting">City meeting calendar unavailable right now</span>'
    else:
        meeting_txt = '<span class="sb-meeting">No upcoming meetings posted</span>'

    # right: weather
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    # labelled: a bare "66° / 86°" read as low / high, and "88° / 88°" as a broken reading
    if cur is not None and hi is not None:
        w = f"{cur}&deg; now &middot; high {hi}&deg;"
    elif hi is not None and lo is not None:
        w = f"high {hi}&deg; &middot; low {lo}&deg;"
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
            "url": "https://bakersfieldbrief.com/icon-512.png",
            "width": 512,
            "height": 512,
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


def publisher_logo() -> dict:
    """schema.org ImageObject for the publisher logo, with the REAL dimensions.

    The width/height here must match assets/img/emblem.png on disk (1200x630).
    They were hard-coded as 100x100 at three call sites while the file was a
    1200x630 wordmark — a false claim Google can drop the logo rich result over.
    One source of truth now; tests/test_site_icons.py checks it against the file.
    """
    return {
        "@type": "ImageObject",
        "url": "https://bakersfieldbrief.com/assets/img/emblem.png",
        "width": 1200,
        "height": 630,
    }


def webpage_jsonld(url: str, date_modified: str, name: str = "",
                   desc: str = "") -> dict:
    """Lightweight WebPage block with dateModified (and datePublished, both
    stamped with the current build date for data-tracker pages)."""
    block = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "url": f"https://bakersfieldbrief.com{url}",
        "dateModified": date_modified,
        "datePublished": date_modified,
        "inLanguage": "en",
    }
    if name:
        block["name"] = name
    if desc:
        block["description"] = desc
    return block


def website_jsonld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": "https://bakersfieldbrief.com/",
        "description": "Daily civic brief, meeting previews, and data trackers for Bakersfield and Kern County.",
        "isAccessibleForFree": True,
        "publisher": {"@type": "Organization", "name": SITE_NAME},
    }
