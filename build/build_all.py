#!/usr/bin/env python3
"""build_all.py — the whole site build.

  python build/build_all.py [--skip-sources] [--no-llm] [--alpr-change]

Pipeline:
  1. run every source module (isolated; failures recorded, never fatal)
  2. build every section from the collected data
  3. copy static assets into site/
  4. write robots.txt, sitemap.xml, CNAME
  5. write data/build_report.json (used by the site footer + the workflow)

--alpr-change: record the ALPR weekly change-log entry (used by the weekly job).
--no-llm:       force the LLM fallback path (local testing without a key).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import common  # noqa: E402
from build.sources import SOURCES  # noqa: E402
from build.builders import (daily, cityhall, trackers, static_pages,
                            places, guide, grapevine, events, feed,
                            numbers, letters,
                            overnight, sunday_read, map, fair, tehachapi,
                            tehachapi_weather, roads)  # noqa: E402
from build.builders import page as page_mod  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-sources", action="store_true", help="reuse last build report data")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM calls entirely")
    ap.add_argument("--alpr-change", action="store_true", help="record ALPR weekly change log")
    ap.add_argument("--guide", action="store_true", help="run the Thursday Weekend Guide build (scrapes venue whitelist)")
    ap.add_argument("--sunday", action="store_true", help="run the Sunday Read long-form feature (writes fresh weekly piece)")
    args = ap.parse_args()

    if args.no_llm:
        import os
        os.environ.pop("LLM_API_KEY", None)

    # ---------------------------------------------------------- clean
    shutil.rmtree(common.SITE, ignore_errors=True)
    common.SITE.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- sources
    ctx = types.SimpleNamespace(today=common.today_pacific(), build_report={},
                                guide=args.guide, sunday=args.sunday)
    results = {}
    cache_file = common.DATA / "source_cache.json"
    if args.skip_sources:
        if cache_file.exists():
            results = json.loads(cache_file.read_text(encoding="utf-8"))
            common.log("reusing cached source data (--skip-sources)")
        else:
            common.log("--skip-sources but no cache found; fetching anyway")
    if not results:
        for name, mod in SOURCES.items():
            try:
                res = mod.run(ctx, record_change=args.alpr_change) if name == "alpr" else mod.run(ctx)
            except Exception as e:  # noqa: BLE001 - isolation guarantee
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            results[name] = res
            status = "ok" if res.get("ok") else ("stub" if name == "blocked" else "FAIL")
            common.log(f"source {name}: {status}")
        cache_file.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------- builders
    ctx.statusbar = page_mod.build_statusbar(results.get("weather"), results.get("escribe"))
    builders = [("daily", daily), ("cityhall", cityhall),
                ("trackers", trackers),
                ("places", places), ("guide", guide),
                ("grapevine", grapevine), ("tehachapi", tehachapi),
                ("tehachapi_weather", tehachapi_weather),
                ("roads", roads),
                ("events", events),
                ("feed", feed), ("numbers", numbers), ("letters", letters),
                ("overnight", overnight),
                ("map", map),
                ("sunday_read", sunday_read),
                ("fair", fair),
                ("static", static_pages)]
    for bname, bmod in builders:
        try:
            files = bmod.build(ctx, results)
            common.log(f"builder {bname}: {len(files)} files")
        except Exception as e:  # noqa: BLE001
            import traceback
            common.log(f"builder {bname} FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    trackers.build_hub(ctx, results)
    common.log("builder trackers-hub done")

    # ---------------------------------------------------------- assets
    for src in ("css", "js", "fonts", "vendor", "img"):
        shutil.copytree(common.ASSETS / src, common.SITE / "assets" / src, dirs_exist_ok=True)
    _icons()
    common.log("assets copied")

    # ---------------------------------------------------------- robots / sitemap / CNAME
    _robots()
    _sitemap()
    _llms()
    _llms_full(results)
    _agentic_sitemap(results)
    (common.SITE / "CNAME").write_text("bakersfieldbrief.com\n", encoding="utf-8")

    # ---------------------------------------------------------- report
    report = {
        "built_at": common.now_pacific().isoformat(timespec="seconds"),
        "sources": {k: {"ok": v.get("ok", False), "error": v.get("error", ""),
                        **({} if v.get("ok") else {})}
                    for k, v in results.items()},
        "section": ctx.build_report,
    }
    (common.DATA / "build_report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")

    n_pages = len(list(common.SITE.rglob("*.html")))

    # custom domain record for Pages (repo root CNAME → built artifact)
    _cname = common.ROOT / "CNAME"
    if _cname.exists():
        (common.SITE / "CNAME").write_text(_cname.read_text(encoding="utf-8").strip() + "\n", encoding="utf-8")

    common.log(f"DONE — {n_pages} html pages in site/, report at data/build_report.json")
    if not all(v.get("ok", False) for k, v in results.items() if k != "blocked"):
        failed = [k for k, v in results.items() if not v.get("ok", False) and k != "blocked"]
        common.log(f"NOTE — sources with failures (site still builds): {failed}")


ICON_ROOT_FILES = ("favicon.ico", "favicon.svg", "apple-touch-icon.png",
                   "icon-96.png", "icon-192.png", "icon-512.png",
                   "site.webmanifest")


def _icons():
    """Copy the favicon set from assets/icons/ into the SITE ROOT.

    Browsers and Google request these at the domain root (/favicon.ico), so
    they cannot live under /assets/. Source art is committed under
    assets/icons/; the artwork is generated (rarely) by
    ~/AppData/Local/hermes/scripts/bb_make_icons.py. A missing file is logged,
    never fatal — an absent icon must not stop the daily build.
    """
    copied = 0
    for name in ICON_ROOT_FILES:
        try:
            shutil.copy2(common.ASSETS / "icons" / name, common.SITE / name)
            copied += 1
        except OSError as e:  # noqa: BLE001
            common.log(f"WARN — site icon {name} not copied: {e}")
    # Report the REAL count, not len(ICON_ROOT_FILES): a summary line that says
    # "copied (7)" while the WARN above says otherwise is a lie in the log.
    common.log(f"site icons copied ({copied}/{len(ICON_ROOT_FILES)})")


def _robots():
    common.write(common.SITE / "robots.txt", """User-agent: *
Allow: /
Sitemap: https://bakersfieldbrief.com/sitemap.xml
""")


def _sitemap():
    # Use the Pacific build date, NOT dt.date.today(). GitHub runners are UTC, so
    # between 16:00 and midnight PT dt.date.today() returns TOMORROW — stamping
    # <lastmod> a day in the future while llms-full.txt and the agentic sitemap
    # written in the same build use the Pacific date.
    today = common.iso_today()
    urls = []
    for p in common.SITE.rglob("index.html"):
        rel = p.relative_to(common.SITE).as_posix()
        rel = rel[: -len("index.html")]
        urls.append(f"https://bakersfieldbrief.com/{rel}")
    urls.append("https://bakersfieldbrief.com/")
    urls = sorted(set(urls))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    # The site rebuilds daily, so every build stamps today as lastmod for all
    # URLs — no stale dates when a page's content changes on a later day.
    for u in urls:
        xml.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>")
    xml.append("</urlset>")
    common.write(common.SITE / "sitemap.xml", "\n".join(xml) + "\n")

    # Cloudflare Pages _redirects — guessable URLs a human might type.
    common.write(common.SITE / "_redirects",
                 "/places/east-bakersfield/*  /places/bakersfield-east/:splat  301\n")


def _page_titles() -> dict:
    """path -> the page's own <title>, read from the HTML this build just wrote.

    This is the discovery files' source of truth: a page that exists in site/
    must appear in llms.txt and in sitemap_agentic_discovery.xml, so the lists
    are generated from the built output instead of a hand-written list that
    silently falls behind (it had fallen 66 pages behind by 2026-09-19).
    """
    out = {}
    for p in common.SITE.rglob("index.html"):
        path = "/" + p.relative_to(common.SITE).as_posix()[: -len("index.html")]
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = ""
        m = (re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
             or re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.S | re.I))
        text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()) if m else ""
        text = re.sub(r"\s*[|\-–—]\s*Bakersfield (Daily )?Brief\s*$", "", text).strip()
        out[path] = text or path
    return out


def _llms_extras(curated: str) -> str:
    """Markdown links for every built page the curated sections do not cover."""
    linked = set(re.findall(r"bakersfieldbrief\.com(/[^)\s]*)", curated))
    missing = [p for p in sorted(_page_titles()) if p not in linked]
    if not missing:
        return ""
    titles = _page_titles()
    lines = ["", "## Page index", "",
             "Every page this build produced, one line each.", ""]
    for p in missing:
        lines.append(f"- [{titles[p]}](https://bakersfieldbrief.com{p})")
    return "\n".join(lines) + "\n"


def _llms():
    """Write site/llms.txt — the AI-agent discovery file (llmstxt.org).

    The curated sections below carry the descriptions. A generated Page index
    is appended for every built page the curated sections miss, so a new page
    is never invisible to AI crawlers (GPTBot, ClaudeBot, PerplexityBot…).
    """
    curated = """# Bakersfield Daily Brief

> A free, automated civic news brief for Bakersfield and Kern County, California — built every morning from public records.

Bakersfield Daily Brief is an independent, automated local-news publication. Each day it assembles the Kern County news you'd otherwise miss: morning conditions (weather, air quality, fires, reservoirs), local headlines with links to the original reporting, the day's notable public meetings, overnight police-scanner activity, and running data trackers (ALPR / license-plate cameras, water levels, grapevine conditions).

The site is static and rebuilt fresh every morning at 6:00 AM Pacific from public agencies: City of Bakersfield meeting records (eSCRIBE), Kern County Board of Supervisors agenda, California ABC license filings, Kern County Environmental Health, CHP incidents, NWS alerts, EPA AirNow, CDEC reservoir data, CAL FIRE, Caltrans road conditions, and OpenStreetMap. Headlines link to original outlets; no article text is republished.

## Key Facts

- Independent, automated civic news for Bakersfield and Kern County, California.
- Free to read; funded by labeled, consent-based advertising.
- Rebuilt daily from public records; every item links to its source.
- Human editorial review behind meeting recaps and the corrections policy.
- No opinions, no ballot-measure stances, no republished article text.

## Daily & News

- [The Daily Brief](https://bakersfieldbrief.com/): today's conditions, headlines, and meetings.
- [The Kern Overnight](https://bakersfieldbrief.com/overnight/): police-scanner activity from the night before.
- [The Sunday Read](https://bakersfieldbrief.com/sunday-read/): long-form weekly feature.
- [Letters](https://bakersfieldbrief.com/letters/): letters to the Brief.

## City Hall & County

- [City Hall & County](https://bakersfieldbrief.com/city-hall/): meeting previews and recaps for Bakersfield and Kern County.
- [The Numbers](https://bakersfieldbrief.com/numbers/): the numeric dashboard behind the news.

## Data Trackers

- [Flock & ALPRs](https://bakersfieldbrief.com/surveillance/): automated license-plate reader locations.
- [Isabella Lake tracker](https://bakersfieldbrief.com/water/): reservoir levels.
- [Grapevine conditions](https://bakersfieldbrief.com/grapevine/): Tejon Pass / Grapevine road conditions.
- [Tehachapi Pass conditions](https://bakersfieldbrief.com/tehachapi-pass/): SR-58 road conditions and wind.
- [Tehachapi weather](https://bakersfieldbrief.com/tehachapi-weather/): pass-level wind and forecast.
- [Kern road conditions](https://bakersfieldbrief.com/roads/): I-5, SR-58, and SR-99 status in Bakersfield & Kern County.
- [Live Map](https://bakersfieldbrief.com/map/): interactive map of local data.

## Guides & Places

- [Kern County Fair 2026](https://bakersfieldbrief.com/fair/): dates, concert lineup, and tickets.
- [Weekend Guide](https://bakersfieldbrief.com/guide/): what's on around Kern County.
- [Events](https://bakersfieldbrief.com/events/): community events calendar.
- [Places](https://bakersfieldbrief.com/places/): neighborhood and community pages.

## About

- [About this site](https://bakersfieldbrief.com/about/): how the Brief works and what it publishes.
- [Editorial standards](https://bakersfieldbrief.com/editorial-standards/): production rules and sources.
- [Corrections](https://bakersfieldbrief.com/corrections/): how errors are fixed on the record.
- [Ownership & funding](https://bakersfieldbrief.com/ownership/): who operates the Brief.
- [Contact](https://bakersfieldbrief.com/contact/): corrections, source tips, and feedback.
"""
    common.write(common.SITE / "llms.txt", curated + _llms_extras(curated))


def _llms_full(results: dict) -> None:
    """Write site/llms-full.txt — current canonical answers per data tracker,
    stamped with the build date. Numbers are read live from the build results
    (never fabricated); any unavailable source degrades to an honest fallback.
    """
    today = common.iso_today()

    # --- surveillance ---
    alpr = results.get("alpr", {})
    if alpr.get("ok"):
        st = alpr.get("stats", {})
        surv = (f"{st.get('flock', 0)} Flock Safety cameras and "
                f"{st.get('total', 0)} total license-plate readers are mapped in "
                f"OpenStreetMap within the Bakersfield metro as of "
                f"{alpr.get('asof', today)}.")
    else:
        surv = "Live map of license-plate readers in the Bakersfield metro; data unavailable this build."

    # --- water ---
    iso = results.get("isabella", {})
    if iso.get("ok") and iso.get("storage"):
        elev = iso.get("elev_ft") or {}
        w = (f"Lake Isabella is at {iso.get('pct', 0)}% of capacity "
             f"({iso['storage'].get('value', 0):,} acre-feet"
             + (f", {elev.get('value', 0):,} ft elevation)" if elev.get("value") else ")"))
        w += f", as of {iso.get('asof', today)}."
    else:
        w = "Lake Isabella water level from CDEC; data unavailable this build."

    # --- grapevine (Caltrans routes) ---
    roads = results.get("roads", {})
    if roads.get("ok") and roads.get("routes"):
        statuses = "; ".join(f"{r.get('name')}: {r.get('pass_status') or r.get('status')}"
                             for r in roads["routes"])
        grape = f"{statuses}, as reported by Caltrans as of {roads.get('asof', today)}."
        sr58 = next((r for r in roads["routes"] if r.get("slug") == "sr58"), None)
        teh = (f"SR-58 Tehachapi Pass: {sr58.get('pass_status') or sr58.get('status')}, "
               f"as reported by Caltrans as of {sr58.get('reported_as_of') or roads.get('asof', today)}."
               if sr58 else
               "Tehachapi Pass SR-58 road conditions from Caltrans; data unavailable this build.")
        roads_all = (f"{statuses}, as reported by Caltrans as of {roads.get('asof', today)}. "
                     f"See per-route status for I-5 Grapevine, SR-58 Tehachapi, and SR-99.")
    else:
        grape = "Grapevine / Tejon Pass road conditions from Caltrans; data unavailable this build."
        teh = "Tehachapi Pass SR-58 road conditions from Caltrans; data unavailable this build."
        roads_all = "Kern County road conditions from Caltrans; data unavailable this build."

    # --- tehachapi weather ---
    tw = results.get("tehachapi_weather", {})
    tcur = tw.get("current", {})
    if tw.get("ok") and tcur.get("ok"):
        # Only state a wind figure the station actually reported — a missing
        # reading used to render as "wind — mph from ?" here.
        if tcur.get("wind_mph") is not None:
            _wind = (f"wind {tcur['wind_mph']} mph"
                     + (f" gusting to {tcur['gust_mph']} mph" if tcur.get("gust_mph") else "")
                     + f" from {tcur.get('wind_dir') or 'an unstated direction'}, ")
        else:
            _wind = "wind not reported by the station, "
        tehwx = (f"Tehachapi current conditions: {tcur.get('temperature', '—')}°F, "
                 f"{_wind}"
                 f"observed {tcur.get('observed') or 'by NWS'}.")
    else:
        tehwx = "Tehachapi weather from the National Weather Service; data unavailable this build."

    common.write(common.SITE / "llms-full.txt", f"""# Bakersfield Daily Brief — Full Text

> Machine-readable full content. Built {today} from public records. Each data tracker page below states its current canonical answer.

Bakersfield Daily Brief is an independent, automated civic-news brief for Bakersfield and Kern County, California. It rebuilds fresh every morning from public agencies: City of Bakersfield meeting records (eSCRIBE), Kern County Board of Supervisors agendas, ABC license filings, Kern County Environmental Health, CHP incidents, NWS alerts, EPA AirNow, CDEC reservoir data, CAL FIRE, Caltrans road conditions, and OpenStreetMap. Headlines link to original outlets; no article text is republished.

## Home

https://bakersfieldbrief.com/ — Today's conditions, headlines, meetings, and data-tracker links.

## Data Trackers

https://bakersfieldbrief.com/surveillance/ — {surv}

https://bakersfieldbrief.com/water/ — {w}

https://bakersfieldbrief.com/grapevine/ — {grape}

https://bakersfieldbrief.com/tehachapi-pass/ — {teh}

https://bakersfieldbrief.com/tehachapi-weather/ — {tehwx}

https://bakersfieldbrief.com/roads/ — {roads_all}

## City Hall & County

https://bakersfieldbrief.com/city-hall/ — Meeting previews and recaps for Bakersfield and Kern County.
https://bakersfieldbrief.com/numbers/ — The numeric dashboard behind the news.

## Guides & Places

https://bakersfieldbrief.com/guide/ — What's on around Kern County.
https://bakersfieldbrief.com/places/ — Neighborhood and community pages.
https://bakersfieldbrief.com/events/ — Community events calendar.
https://bakersfieldbrief.com/fair/ — Kern County Fair dates, lineup, and tickets.

## About

https://bakersfieldbrief.com/about/ — How the Brief works and what it publishes.
https://bakersfieldbrief.com/contact/ — Corrections, source tips, and feedback.
""")


def _agentic_sitemap(results: dict) -> None:
    """Write site/sitemap_agentic_discovery.xml — the agentic-sitemap discovery
    file (https://agentic-sitemaps.org) listing every built page with a
    one-line description and lastmod, so AI crawlers find the right entry points.

    The curated descriptions below cover the key entry points. Every other page
    the build produced is appended with its own <title>, so the file stays
    complete as pages are added (it had covered 7 of 88 built pages).
    """
    today = common.iso_today()
    curated = {
        "/": "Home — today's Bakersfield and Kern County conditions, headlines, and meetings.",
        "/water/": "Lake Isabella water level and elevation — live from California DWR/CDEC.",
        "/surveillance/": "Flock Safety and ALPR license-plate-reader camera map for Bakersfield and Kern County.",
        "/grapevine/": "Grapevine / Tejon Pass road conditions — live from Caltrans.",
        "/tehachapi-pass/": "Tehachapi Pass (SR-58) road conditions, wind, and weather — live from Caltrans and NWS.",
        "/tehachapi-weather/": "Tehachapi weather — current conditions and forecast from the National Weather Service.",
        "/roads/": "Bakersfield and Kern County road conditions right now — I-5 Grapevine, SR-58 Tehachapi, and SR-99, live from Caltrans.",
    }
    titles = _page_titles()
    pages = [(f"https://bakersfieldbrief.com{p}", curated.get(p) or titles[p]) for p in sorted(titles)]
    rows = "\n".join(
        f"  <url><loc>{html.escape(loc)}</loc><description>{html.escape(desc, quote=False)}</description>"
        f"<lastmod>{today}</lastmod></url>"
        for loc, desc in pages)
    common.write(common.SITE / "sitemap_agentic_discovery.xml",
                 f'<?xml version="1.0" encoding="UTF-8"?>\n'
                 f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}\n</urlset>\n')


if __name__ == "__main__":
    main()
