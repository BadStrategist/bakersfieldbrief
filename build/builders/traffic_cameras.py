#!/usr/bin/env python3
"""Traffic cameras page, /traffic-cameras/, and the camera blocks on the road trackers.

Order on the page: the road status in plain words (the same Caltrans report and the same
spoken forms the Grapevine page uses), the agency's own report time, then every Caltrans
camera in Kern County as the evidence, then the explainer copy.

Rules this page keeps:
 - Every fact is in the HTML as built. assets/js/cameras.js only swaps in newer pictures and
   reads each picture's age; it adds no fact a crawler would miss.
 - A camera Caltrans lists as out of service says so. A picture that fails to load says the
   picture is unavailable. Neither one prints a zero, a dash or an empty frame.
 - Pictures are requested from /api/cameras?img=<id>, which looks the address up in Caltrans'
   own list. No picture address is ever put together here.
 - These are Caltrans traffic cameras. Nothing here is shared with /surveillance/.
"""
from __future__ import annotations

import html
import re

from .. import common
from . import page as page_mod
from . import roads as roads_b
from .fog_delays import _fog_advisories
from .grapevine import (_STATUS_COPY, _TAG_CLS, _elsewhere_phrase, NO_PROBLEM_LABEL)

_PHONE = "1-800-427-7623"
_QUICKMAP = "https://quickmap.dot.ca.gov/"
_IMG = "/api/cameras?img="
# Caltrans publishes every still at this size (checked on the JPEGs, 2026-10-11).
_W, _H = 320, 260

_ROUTE_LINK = {
    "i5": ("grapevine/", "Is the Grapevine open? Full I-5 report"),
    "sr58": ("tehachapi-pass/", "Tehachapi Pass (SR-58) report and wind"),
    "sr99": ("roads/", "All three highways, rechecked live"),
}
_STRETCH = {"i5": "the pass", "sr58": "the pass", "sr99": "this stretch"}
_LEAD_ROUTES = ("I-5", "SR-99", "SR-58")

# The grade cameras for the two pass pages, by Caltrans postmile. I-5: Lebec down to the
# Route 99 split. SR-58: Towerline Road at the foot of the climb, east to Mojave.
_GRAPEVINE_MAX_PM = 16.0
_TEHACHAPI_MIN_PM = 65.0
# One camera per highway for the /roads/ hub. The ids are Caltrans' own file names; one that
# leaves the feed is simply not shown.
_ROADS_PICK = ("ker5attruckescaperampshoulder", "sr58tehachapisummit", "ker99atcaliforniaave")


def _plain(text) -> str:
    """Source text with long dashes rewritten: this page prints none."""
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(text or ""))


def _e(text) -> str:
    return html.escape(_plain(text))


def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _every(minutes) -> str:
    if not minutes:
        return ""
    return "about every minute" if minutes == 1 else f"about every {minutes} minutes"


def _feet(v) -> str:
    return f"{round(v):,} feet" if v is not None else ""


def _route_key(route: str):
    if route in _LEAD_ROUTES:
        return (0, _LEAD_ROUTES.index(route), "")
    m = re.search(r"(\d+)", route)
    return (1, int(m.group(1)) if m else 9999, route)


def by_route(cams: list) -> list[tuple[str, list]]:
    """[(route, cameras in postmile order)], I-5, SR-99 and SR-58 first."""
    groups: dict[str, list] = {}
    for c in cams:
        groups.setdefault(c.get("route") or "Other", []).append(c)
    out = []
    for route in sorted(groups, key=_route_key):
        rows = sorted(groups[route], key=lambda c: (c.get("postmile") is None,
                                                    c.get("postmile") or 0, c.get("label", "")))
        out.append((route, rows))
    return out


def _meta(c: dict) -> str:
    bits = [f"{c['route']} {c['direction']}".strip()]
    if c.get("near"):
        bits.append(f"near {c['near']}")
    return " · ".join(b for b in bits if b)


def card(c: dict, heading: str = "h4") -> str:
    """One camera. The name, route and place are printed whatever happens to the picture."""
    cid = html.escape(c["id"])
    attrs = (f'id="cam-{cid}" data-cam="{cid}" data-label="{_e(c["label"])}" '
             f'data-caltrans-name="{_e(c["caltrans_name"])}" data-district="{_e(c["district"])}"')
    if c.get("elevation_ft") is not None:
        attrs += f' data-elev="{round(c["elevation_ft"])}"'
    name = f'<{heading} class="cam-name">{{}}</{heading}>'
    meta = f'<p class="cam-meta">{_e(_meta(c))}</p>'
    if not c.get("in_service"):
        return (f'<li class="cam is-out" {attrs}>'
                f'<span class="cam-pic"><span class="cam-flag">Out of service</span></span>'
                f'<div class="cam-body">{name.format(_e(c["name"]))}{meta}'
                f'<p class="cam-age">Caltrans lists this camera as out of service.</p></div></li>')
    if not c.get("image_url"):
        return (f'<li class="cam is-error" {attrs}>'
                f'<span class="cam-pic"><span class="cam-flag">Picture unavailable right now</span></span>'
                f'<div class="cam-body">{name.format(_e(c["name"]))}{meta}'
                f'<p class="cam-age">Caltrans lists no picture for this camera right now.</p></div></li>')
    src = _IMG + cid
    every = _every(c.get("update_min"))
    age = f"New picture {every}" if every else "Picture time is read when the page loads"
    link = f'<a class="cam-open" href="{src}">{_e(c["name"])}</a>'
    # The inline handler is the whole failure path: it needs no script file to have loaded.
    return (f'<li class="cam" {attrs} data-every="{c.get("update_min") or ""}">'
            f'<span class="cam-pic"><img src="{src}" alt="Caltrans traffic camera: {_e(c["label"])}'
            f'{", near " + _e(c["near"]) if c.get("near") else ""}" width="{_W}" height="{_H}" '
            f'loading="lazy" decoding="async" '
            f'onerror="this.closest(\'.cam\').classList.add(\'is-error\')">'
            f'<span class="cam-flag">Picture unavailable right now</span></span>'
            f'<div class="cam-body">{name.format(link)}{meta}'
            f'<p class="cam-age" data-default="{html.escape(age)}">{html.escape(age)}</p></div></li>')


def counts(cams: list) -> tuple[int, int, int]:
    live = sum(1 for c in cams if c.get("in_service"))
    return len(cams), live, len(cams) - live


def count_sentence(cams: list, where: str = "in Kern County") -> str:
    """'44 Caltrans cameras in Kern County: 43 in service, 1 out of service.' No zero is printed."""
    total, live, out = counts(cams)
    head = f"{_n(total, 'Caltrans camera', 'Caltrans cameras')} {where}"
    if not out:
        return f"{head}, all listed in service."
    if not live:
        return f"{head}. Caltrans lists none of them in service right now."
    return f"{head}: {live} in service, {out} out of service, by Caltrans' own list."


def frequency_sentence(cams: list) -> str:
    """How often Caltrans says it replaces the pictures, from the feed's own field."""
    by: dict[int, int] = {}
    for c in cams:
        if c.get("in_service") and c.get("update_min"):
            by[c["update_min"]] = by.get(c["update_min"], 0) + 1
    if not by:
        return ""
    if len(by) == 1:
        return f"Caltrans replaces each picture {_every(next(iter(by)))}."
    bits = [f"{n} {_every(m)}" for m, n in sorted(by.items())]
    return ("Caltrans replaces these pictures on its own schedule: "
            + ", ".join(bits[:-1]) + f" and {bits[-1]}.")


def block(sources: dict, rel: str, kind: str) -> str:
    """The camera block for /grapevine/, /tehachapi-pass/ and /roads/. '' when there is no list."""
    data = (sources or {}).get("cameras") or {}
    cams = data.get("cameras") or []
    if not cams:
        return ""
    if kind == "grapevine":
        pick = [c for c in cams if c["route"] == "I-5" and (c.get("postmile") or 999) <= _GRAPEVINE_MAX_PM]
        title, anchor = "Cameras on the Grapevine", "All Kern County traffic cameras"
        order = "Listed from the top of the Kern County grade down to the Route 99 split."
        pick.sort(key=lambda c: c.get("postmile") or 0)
    elif kind == "tehachapi":
        pick = [c for c in cams if c["route"] == "SR-58" and (c.get("postmile") or 0) >= _TEHACHAPI_MIN_PM]
        title, anchor = "Cameras over Tehachapi Pass", "Every Caltrans camera in Kern County"
        order = "Listed west to east, from the foot of the climb to Mojave."
        pick.sort(key=lambda c: c.get("postmile") or 0)
    else:
        ids = {c["id"]: c for c in cams}
        pick = [ids[i] for i in _ROADS_PICK if i in ids]
        title, anchor = "Highway cameras", "Bakersfield and Kern County traffic cameras"
        order = "One camera from each highway."
    if not pick:
        return ""
    total = len(cams)
    return f"""
    <section class="block cam-block" id="cameras" data-cams>
      <div class="sign-head"><span class="tab">Cameras</span><h2>{title} <span class="unit">Caltrans</span></h2></div>
      <ul class="cams">{"".join(card(c, "h3") for c in pick)}</ul>
      <p class="cam-src">{order} Pictures: Caltrans, with its own time along the bottom of each.
      <a href="{rel}traffic-cameras/">{anchor}</a> ({total} on one page).</p>
    </section>"""


SCRIPTS = '<script src="{rel}assets/js/cameras.js?v={v}" defer></script>'


def scripts(rel: str) -> str:
    return SCRIPTS.format(rel=rel, v=page_mod._asset_ver("assets/js/cameras.js"))


# ---------------------------------------------------------------- road status
def _route_row(slug: str, r: dict | None, rel: str) -> str:
    prose = roads_b._ROUTE_PROSE[slug]
    href, anchor = _ROUTE_LINK[slug]
    link = f' <a href="{rel}{href}">{anchor}</a>.'
    if not r:
        return (f'<li><span class="tag">No report</span> <strong>{prose}:</strong> '
                f'Caltrans conditions for this route were unavailable this build.{link}</li>')
    scope = r.get("scope")
    spoken = roads_b.spoken_status(r)
    if scope is None:
        status = roads_b._kern_status(r)
        word, cls = _STATUS_COPY.get(status, _STATUS_COPY["OPEN"])[0], _TAG_CLS.get(status, "amber")
        detail = " That is Caltrans' area-wide text, which covers more than this corridor."
    elif scope.get("on_pass_reported"):
        status = scope.get("on_pass", roads_b._kern_status(r))
        word, cls = _STATUS_COPY.get(status, _STATUS_COPY["OPEN"])[0], _TAG_CLS.get(status, "amber")
        said = [i.get("text", "") for i in scope.get("on_pass_items") or [] if i.get("text")][:2]
        detail = (" Caltrans: " + " ".join(f"&ldquo;{_e(t)}&rdquo;" for t in said)) if said else ""
    else:
        word, cls, detail = NO_PROBLEM_LABEL, "green", ""
    elsewhere = (scope or {}).get("elsewhere") or []
    if elsewhere:
        number = prose.split()[0]
        detail += (f" Elsewhere on {number}, Caltrans reports "
                   + " and ".join(_e(_elsewhere_phrase(i)) for i in elsewhere[:2])
                   + f", not on {_STRETCH[slug]}.")
    return (f'<li><span class="tag {cls}">{word}</span> <strong>{prose} is {spoken}.</strong>'
            f'{detail}{link}</li>')


def _chain_line(routes: dict) -> str:
    """Chain control, only from Caltrans items that sit on the three corridors."""
    if any(routes.get(s) is None or routes[s].get("scope") is None for s in _ROUTE_LINK):
        return ""
    named = []
    for slug in _ROUTE_LINK:
        for item in routes[slug]["scope"].get("on_pass_items") or []:
            if re.search(r"\bchains?\b", item.get("text", ""), re.I):
                named.append(f'{roads_b._ROUTE_PROSE[slug]}: &ldquo;{_e(item["text"])}&rdquo;')
    if named:
        return ("<li><strong>Chain control:</strong> Caltrans names chains on "
                + "; ".join(named) + "</li>")
    return ("<li><strong>Chain control:</strong> none is named on these three corridors in the "
            "Caltrans report.</li>")


def _fog_line(weather: dict, rel: str) -> str:
    link = f'<a href="{rel}fog-delays/">School fog delays today</a>.'
    if not (weather or {}).get("ok"):
        return ("<li><strong>Fog:</strong> National Weather Service alerts were unavailable this "
                f"build. {link}</li>")
    fog = _fog_advisories(weather)
    if not fog:
        return ("<li><strong>Fog:</strong> the National Weather Service had no dense fog advisory "
                f"posted for Kern County at the last check. {link}</li>")
    items = "; ".join(_e(a.get("headline") or a.get("event") or "") for a in fog)
    return f"<li><strong>Fog:</strong> the National Weather Service has posted: {items}. {link}</li>"


def _road_status(sources: dict, rel: str) -> tuple[str, str, str]:
    """(answer paragraph, detail card, Caltrans report time) from the same data /roads/ reads."""
    data = sources.get("roads") or {}
    route_list = data.get("routes", []) if (data.get("ok") or data.get("last_good")) else []
    routes = {r["slug"]: r for r in route_list}
    if not route_list:
        answer = (f'<div class="errorbox" id="road-answer">Caltrans road conditions could not be '
                  f'read when this page was built, so no road status is shown. The cameras below '
                  f'are not affected. Check <a href="https://roads.dot.ca.gov/" target="_blank" '
                  f'rel="noopener">roads.dot.ca.gov</a> or call {_PHONE}.</div>')
        return answer, "", ""
    ts = next((r.get("reported_as_of") for r in route_list if r.get("reported_as_of")), "")
    said = "; ".join(roads_b.spoken_parts(route_list))
    stale = (" Caltrans could not be reached on the latest check, so this is the most recent "
             "report and may be out of date." if data.get("stale") else "")
    lead = f"As of {_e(ts)}, Caltrans reports: " if ts else "Caltrans reports: "
    answer = (f'<p class="answer" id="road-answer" data-asof="{_e(ts)}"><strong>{lead}{said}.'
              f'</strong>{stale} The camera pictures below are the newest Caltrans has.</p>')
    rows = "".join(_route_row(slug, routes.get(slug), rel) for slug in _ROUTE_LINK)
    detail = (f'<div class="card road-now"><ul class="hl">{rows}'
              f'{_chain_line(routes)}{_fog_line(sources.get("weather") or {}, rel)}</ul></div>')
    return answer, detail, ts


# ---------------------------------------------------------------- page copy
def _places(rows: list) -> str:
    seen = []
    for c in rows:
        if c.get("near") and c["near"] not in seen:
            seen.append(c["near"])
    if not seen:
        return ""
    return seen[0] if len(seen) == 1 else f"{seen[0]} to {seen[-1]}"


def _district_line(cams: list, district: str) -> str:
    rows = [c for c in cams if c.get("district") == district]
    if not rows:
        return ""
    routes = [r for r, _ in by_route(rows)]
    listed = routes[0] if len(routes) == 1 else ", ".join(routes[:-1]) + " and " + routes[-1]
    return f"{_n(len(rows), 'camera', 'cameras')} on {listed}"


def _grade(cams: list, route: str, lo: float, hi: float) -> list:
    rows = [c for c in cams if c["route"] == route and c.get("postmile") is not None
            and lo <= c["postmile"] <= hi and c.get("elevation_ft") is not None]
    return sorted(rows, key=lambda c: c["elevation_ft"])


def _climb(rows: list) -> str:
    return ", ".join(f"{_e(c['name'])} ({_feet(c['elevation_ft'])})" for c in rows)


def _explainer(cams: list) -> tuple[str, list]:
    """The original copy, with every number read from the camera list. -> (html, FAQ pairs)."""
    total, live, out = counts(cams)
    d6, d9 = _district_line(cams, "6"), _district_line(cams, "9")
    freq = frequency_sentence(cams)
    i5 = _grade(cams, "I-5", 0, _GRAPEVINE_MAX_PM)
    sr58 = _grade(cams, "SR-58", _TEHACHAPI_MIN_PM, 9999)
    valley = [c for c in cams if c.get("near") == "Bakersfield" and c.get("elevation_ft") is not None]
    floor = (f"about {round(sorted(c['elevation_ft'] for c in valley)[len(valley) // 2], -1):,.0f} feet"
             if valley else "a few hundred feet")
    top58 = sr58[-1] if sr58 else None
    out_names = ", ".join(_e(c["label"]) for c in cams if not c.get("in_service"))

    who = (f"<p>Every camera on this page belongs to Caltrans, the California Department of "
           f"Transportation. Kern County is split between two Caltrans districts, and each "
           f"publishes its own list.</p><ul class=\"hl\">"
           + (f"<li><strong>District 6</strong>, run from Fresno, covers the valley floor and "
              f"the Kern County side of the Grapevine: {d6}.</li>" if d6 else "")
           + (f"<li><strong>District 9</strong>, run from Bishop, covers the Tehachapi "
              f"Mountains and the desert to the east: {d9}.</li>" if d9 else "")
           + "</ul><p>Both lists are open public data and the pictures are in the public "
             "domain. Bakersfield Daily Brief runs none of these cameras and does not edit the "
             "pictures. Each one is fetched from Caltrans and passed along as it is, with "
             "Caltrans' own date and time printed along the bottom.</p>")

    how = (f"<p>{freq} Those intervals are the ones Caltrans lists for each camera. " if freq else "<p>")
    how += ("This page asks for a new picture on the same schedule while a camera is on your "
            "screen, and the line under each picture says when Caltrans last replaced it.</p>"
            "<p>Read that line before you trust a clear road. When a camera stops sending, "
            "Caltrans keeps serving the last picture it received, so an old picture can look "
            "perfectly normal. A picture more than half an hour old is marked as old here.</p>"
            "<p>Caltrans sometimes sends a card reading Temporarily Unavailable in place of the "
            "picture for a camera it still lists as in service. That card is Caltrans' own. It is "
            "shown here as it arrives, and the line under it says a notice is up.</p>"
            f"<p>The pictures are stills, {_W} by {_H} pixels. This page does not carry live "
            f"video. Caltrans offers its own streams for some cameras on "
            f"<a href=\"{_QUICKMAP}\" target=\"_blank\" rel=\"noopener\">QuickMap</a>.</p>")

    cloud = (f"<p>Both passes are high enough to sit inside the weather. Tejon Pass, the top of "
             f"the Grapevine, is 4,144 feet. Tehachapi Summit is about 4,067 feet. The valley "
             f"cameras around Bakersfield sit at {floor}. When a storm crosses the mountains "
             f"the base of the cloud is often lower than the summits, so the road at the top is "
             f"inside the cloud: fog to a driver, and snow when it is cold enough. The same "
             f"storm can leave Bakersfield wet and clear, which is why a clean picture on "
             f"Highway 99 tells you nothing about the top of either pass.</p>")
    if i5:
        cloud += (f"<p>On the Grapevine, read the cameras from the bottom up: {_climb(i5)}. The "
                  f"highest of them is still far below the 4,144 foot summit, which is south of "
                  f"the Kern County line and is not on this list. A clear picture at "
                  f"{_feet(i5[-1]['elevation_ft'])} is not a clear summit.</p>")
    if top58:
        cloud += (f"<p>On Highway 58 the climb reads {_climb(sr58)}. "
                  f"{_e(top58['name'])} is the one to watch"
                  + ("." if top58.get("in_service") else
                     ", though Caltrans lists it as out of service right now.") + "</p>")
    cloud += ("<p>Valley fog is the opposite case. Tule fog forms on the valley floor on calm, "
              "clear winter nights, most often from November through February, and is thickest "
              "around sunrise. On those mornings the Highway 99 and I-5 valley cameras go grey "
              "while the passes above the fog are in sunshine. High wind closes both passes to "
              "trucks and trailers as well, and no camera can show you wind: that comes from "
              "the Caltrans report at the top of this page.</p>")

    chains = ("<p>Chain control is an order, posted by Caltrans and enforced at checkpoints at "
              "the foot of the grade. It has three levels.</p><ul class=\"hl\">"
              "<li><strong>R1:</strong> chains are required on every vehicle except passenger "
              "vehicles and light trucks under 6,000 pounds that have snow tires on at least "
              "two drive wheels.</li>"
              "<li><strong>R2:</strong> chains are required on every vehicle except four-wheel "
              "and all-wheel drive vehicles with snow tires on all four wheels.</li>"
              "<li><strong>R3:</strong> chains are required on every vehicle, with no "
              "exceptions. Caltrans usually closes a highway before it reaches R3.</li></ul>"
              "<p>A camera can show you that the pavement is white. It cannot show you that a "
              "chain control is posted or where the checkpoint is. For that, read the Caltrans "
              f"report at the top of this page or call {_PHONE}. Drivers without chains are "
              "turned around at the checkpoint.</p>")

    notrec = (f"<p>These are traffic cameras, and what they publish is not a surveillance "
              f"record. Each picture is a small still, {_W} by {_H} pixels. At that size you "
              f"can tell snow from wet pavement and stopped traffic from moving traffic. You "
              f"cannot read a license plate or recognize a driver.</p>"
              f"<p>Nothing is archived here. Each new picture replaces the last one. This site "
              f"holds a picture for about a minute, so that many readers do not each load "
              f"Caltrans' server, and then discards it. If you need footage of a crash, this "
              f"page does not have it and never did. What Caltrans keeps on its own systems is "
              f"a question for Caltrans.</p>"
              f"<p>They are also not police license plate readers. Those are separate "
              f"equipment, run by other agencies for a different purpose, and none of them "
              f"appears on this page.</p>")

    sections = "".join(f"""
    <section class="block">
      <div class="sign-head"><span class="tab">{tab}</span><h2>{h2}</h2></div>
      <div class="card">{body}</div>
    </section>""" for tab, h2, body in (
        ("Who", "Who runs these cameras", who),
        ("Timing", "How often the pictures update", how),
        ("Weather", "Why Tehachapi and the Grapevine disappear into cloud", cloud),
        ("Chains", "What chain control means here", chains),
        ("Limits", "What these cameras are not", notrec)))

    bako = [c for c in cams if c.get("near") == "Bakersfield"]
    bako_routes = [r for r, _ in by_route(bako)]
    near_bako = ""
    if bako:
        on = (bako_routes[0] if len(bako_routes) == 1
              else ", ".join(bako_routes[:-1]) + " and " + bako_routes[-1])
        near_bako = f" {_n(len(bako), 'is', 'are')} listed near Bakersfield, on {on}."
    faq = [
        ("Where can I see live traffic cameras in Bakersfield?",
         f"On this page, which shows every Caltrans traffic camera in Kern County. "
         f"{html.escape(count_sentence(cams))}{near_bako} The pictures come straight from "
         f"Caltrans and are not edited."),
        ("How often do the traffic camera pictures update?",
         (freq + " " if freq else "")
         + "The line under each picture gives the time Caltrans last replaced it."),
    ]
    if i5:
        faq.append((
            "Is there a traffic camera on the Grapevine?",
            f"Caltrans lists {_n(len(i5), 'camera', 'cameras')} on the Kern County side of the "
            f"I-5 grade: {_climb(i5)}. None is at the 4,144 foot summit of Tejon Pass, which is "
            f"south of the Kern County line."))
    if sr58:
        faq.append((
            "Is there a camera at Tehachapi Summit on Highway 58?",
            f"Caltrans lists {_n(len(sr58), 'camera', 'cameras')} on the Highway 58 climb: "
            f"{_climb(sr58)}."
            + (f" Out of service on Caltrans' list right now: {out_names}." if out_names else "")))
    faq.append((
        "Do these cameras record video or read license plates?",
        f"What Caltrans publishes is a still picture, {_W} by {_H} pixels, too small to read a "
        f"license plate. This page keeps no archive of the pictures. They are traffic cameras "
        f"and are not police license plate readers."))
    return sections, faq


def _log_html(data: dict) -> str:
    log = data.get("log") or []
    if log:
        rows = "".join(
            f'<tr><td class="num">{_e((e.get("date", "") + " " + e.get("time", "")).strip())}</td>'
            f'<td>{_e(e.get("label", ""))}</td><td>{_e(e.get("change", ""))}</td></tr>'
            for e in log[:12])
        return (f'<div class="table-wrap"><table class="data"><thead><tr><th class="num">When</th>'
                f'<th>Camera</th><th>Change</th></tr></thead><tbody>{rows}</tbody></table></div>')
    started = data.get("log_started")
    since = f" since this log started on {_e(started)}" if started else ""
    return (f'<p class="note">No camera has gone out of service, come back, or been added to '
            f'or dropped from the Caltrans list{since}.</p>')


def _jsonld(cams_in_order: list, faq: list, built_iso: str, title: str, desc: str) -> list:
    def plain(s: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

    blocks = [page_mod.org_jsonld(), page_mod.website_jsonld(),
              page_mod.webpage_jsonld("/traffic-cameras/", built_iso, title, desc)]
    blocks.append({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": plain(a)}} for q, a in faq]})
    if cams_in_order:
        blocks.append({
            "@context": "https://schema.org", "@type": "ItemList",
            "name": "Caltrans traffic cameras in Kern County",
            "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "numberOfItems": len(cams_in_order),
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": _plain(c["label"]),
                 "url": f"https://bakersfieldbrief.com/traffic-cameras/#cam-{c['id']}"}
                for i, c in enumerate(cams_in_order, 1)]})
    return blocks


def build(ctx, sources: dict) -> list[str]:
    built_iso = common.iso_today()
    rel = "../"
    data = sources.get("cameras") or {}
    cams = data.get("cameras") or []
    answer, road_detail, ts = _road_status(sources, rel)

    asof = (f'Caltrans road report: <span class="updated">{_e(ts)}</span>.' if ts else
            'Caltrans road report time unavailable this build.')
    freq = frequency_sentence(cams)
    groups = by_route(cams)
    ordered = [c for _, rows in groups for c in rows]

    if cams:
        jump = "".join(
            f'<a href="#cams-{common.safe_filename(route)}">{_e(route)} '
            f'<span>{len(rows)}</span></a>' for route, rows in groups)
        grid = "".join(f"""
      <h3 class="sec-head" id="cams-{common.safe_filename(route)}">{_e(route)} cameras
      <span class="unit">{_n(len(rows), 'camera', 'cameras')}{' · ' + _e(_places(rows)) if _places(rows) else ''}</span></h3>
      <ul class="cams dense">{"".join(card(c) for c in rows)}</ul>""" for route, rows in groups)
        stale = ('<p class="note">Caltrans\' camera list could not be read on the latest check. '
                 'The cameras below are from the last list this page read'
                 + (f', on {_e(data.get("asof"))}' if data.get("asof") else '')
                 + '. The pictures themselves still come live from Caltrans.</p>'
                 if (data.get("stale") or data.get("stale_districts")) else "")
        same_pole = {}
        for c in cams:
            if c.get("lat") is not None:
                same_pole.setdefault((c["lat"], c["lon"]), []).append(c)
        shared = [v for v in same_pole.values() if len(v) > 1]
        pole_note = " ".join(
            f"Caltrans lists {len(v)} cameras at one spot on {_e(v[0]['route'])} near "
            f"{_e(v[0]['near'])}; each is named here by the way it looks." for v in shared)
        cam_section = f"""
    <section class="block cam-block" id="cameras" data-cams>
      <div class="sign-head"><span class="tab">Live</span><h2>Kern County traffic cameras <span class="unit">Caltrans</span></h2></div>
      {stale}
      <div class="cam-bar"><p class="cam-sum">{html.escape(count_sentence(cams))}</p>
      <button type="button" class="cam-refresh" hidden>Refresh pictures</button></div>
      <nav class="cam-jump" aria-label="Jump to a highway">{jump}</nav>
      {grid}
      <p class="cam-src">Within each highway the cameras run in Caltrans postmile order, south to
      north or west to east. The direction after each route number is Caltrans' label for the
      camera, a compass word that is not always the way the traffic in the picture is moving.
      {pole_note} Tap a camera for the larger picture. Pictures: Caltrans.</p>
    </section>"""
    else:
        cam_section = f"""
    <section class="block cam-block" id="cameras">
      <div class="sign-head"><span class="tab">Live</span><h2>Kern County traffic cameras <span class="unit">Caltrans</span></h2></div>
      <div class="errorbox">Caltrans' camera list could not be read when this page was built, so
      no cameras are shown. See the cameras on
      <a href="{_QUICKMAP}" target="_blank" rel="noopener">Caltrans QuickMap</a>.</div>
    </section>"""

    explainer, faq = _explainer(cams) if cams else ("", [])
    faq_html = "".join(
        f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq)
    faq_section = f"""
    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Traffic camera questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>""" if faq else ""
    log_section = f"""
    <section class="block">
      <div class="sign-head"><span class="tab">Log</span><h2>Camera changes</h2></div>
      {_log_html(data)}
    </section>""" if cams else ""

    island = (f'<script type="application/json" id="cam-data">'
              f'{common.script_json([{k: c.get(k) for k in ("id", "label", "route", "direction", "near", "elevation_ft", "in_service", "update_min", "district")} for c in ordered], separators=(",", ":"))}'
              f'</script>' if cams else "")

    body = f"""
    <div class="pagehead">
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        <a href="/">Daily Brief</a> &rsaquo;
        <a href="{rel}trackers/">Trackers</a> &rsaquo; Traffic cameras
      </nav>
      <div class="hero"><p class="kicker">Traffic cameras · Caltrans</p>
      <h1>Bakersfield traffic cameras and Kern County road status</h1></div>
    </div>

    {answer}

    <p class="cam-asof">{asof} {html.escape(freq)}</p>
    <p class="note" id="road-newer" hidden></p>

    {road_detail}
    {cam_section}
    {explainer}
    {log_section}
    {faq_section}

    <p class="note">Road status is Caltrans' report, lightly cleaned for typos and spacing, with
    the agency's own time. Camera pictures are Caltrans' and are not edited. For the full report
    on each highway see <a href="{rel}grapevine/">Is the Grapevine open right now?</a>,
    <a href="{rel}tehachapi-pass/">Tehachapi Pass on SR-58</a> and
    <a href="{rel}roads/">Kern County road conditions</a>. Always confirm with Caltrans at
    {_PHONE} before you drive a pass in bad weather.</p>
    {island}"""

    title = "Bakersfield Traffic Cameras: Live Kern County Highway Cams | Bakersfield Daily Brief"
    desc = ("Live Caltrans traffic cameras for Bakersfield and Kern County: I-5 on the Grapevine, "
            "SR-58 over Tehachapi Pass and SR-99, with the current Caltrans road status for "
            "each highway and the time of every picture.")
    page = page_mod.render(
        title=title, desc=desc, canonical="/traffic-cameras/", content=body,
        current="trackers", rel=rel, built=built_iso,
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=_jsonld(ordered, faq, built_iso, title.split(" | ")[0], desc),
        extra_head='<meta name="color-scheme" content="light only">',
        extra_scripts=scripts(rel) + '\n  <script src="{rel}assets/js/webmcp-cameras.js" defer></script>'.format(rel=rel))
    common.write(common.SITE / "traffic-cameras" / "index.html", page)

    total, live, out = counts(cams)
    ctx.build_report["traffic_cameras"] = {
        "ok": bool(data.get("ok")), "cameras": total, "in_service": live,
        "stale": bool(data.get("stale") or data.get("stale_districts")),
    }
    return ["traffic-cameras/index.html"]
