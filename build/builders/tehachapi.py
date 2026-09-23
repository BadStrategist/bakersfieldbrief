#!/usr/bin/env python3
"""Tehachapi Pass live tracker — SR-58 road status + live wind/forecast.

Mirrors the grapevine page's proven ranking formula for a second high-value
pass: direct quotable answer, honest status word scoped to "SR-58 reported X
(Central California area)" (SR-58 Caltrans text is area-wide, NOT pass-specific),
live KTSP/TSP wind + NWS forecast + CAZ334 alerts, FAQPage JSON-LD with the live
status in Q1, report-age hint, and a last-known stale fallback.

Honesty rules (non-negotiable, per project): never say "Tehachapi Pass is OPEN"
as a bare claim (SR-58 text is area-wide); never invent wind/temp (KTSP or a
labeled fallback only); timestamps are Caltrans'/KTSP's own verbatim; any
missing source renders "unavailable this build", never an empty card as live.
"""
from __future__ import annotations

import html
import re

from .. import common
from . import images
from . import page as page_mod
from .grapevine import (_report_age_hint, _scope_note,
                        NO_PROBLEM_LABEL, NO_PROBLEM_SPOKEN)

_PHONE = "1-800-427-7623"
_TAG_CLS = {"OPEN": "green", "RESTRICTIONS": "amber", "CLOSED": "red"}

# Status copy map mirrors grapevine's (same labels/logic).
_STATUS_COPY = {
    # (badge label, css class, plain note, spoken form for sentences) — the spoken
    # form keeps the quotable answer grammatical: "is reported Restrictions" is not.
    "OPEN": ("Open", "big-open", "No closures or restrictions are currently reported on this route.",
             "open"),
    "RESTRICTIONS": ("Restrictions", "big-restrict", "The route is open with restrictions — see the details below.",
                     "open with restrictions"),
    "CLOSED": ("Closed", "big-closed", "The route is reported closed — see the details below.",
               "closed"),
}


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    roads = sources.get("roads", {})
    tw = sources.get("tehachapi_weather", {})
    rte = next((r for r in roads.get("routes", []) if r.get("slug") == "sr58"), None)
    others = [r for r in roads.get("routes", []) if r.get("slug") != "sr58"]
    log = roads.get("log", [])
    is_stale = bool(roads.get("stale"))
    routes_present = bool(roads.get("routes"))  # last-known fallback counts
    cur = tw.get("current", {})
    forecast = tw.get("forecast", [])
    alerts = tw.get("alerts", [])
    rel = "../"

    # ---- big status (honest, area-scoped wording)
    if rte and routes_present:
        scope = rte.get("scope")
        area_note = "(Caltrans Central California area)"
        scope_legend = ""
        if scope is None:
            # Snapshot predates corridor scoping: keep the area-scoped claim.
            status = rte.get("pass_status") or rte.get("status", "OPEN")
            label, cls, note, spoken = _STATUS_COPY.get(status, _STATUS_COPY["OPEN"])
            scope = {}
        elif scope.get("on_pass_reported"):
            status = scope.get("on_pass", rte.get("pass_status") or rte.get("status", "OPEN"))
            label, cls, note, spoken = _STATUS_COPY.get(status, _STATUS_COPY["OPEN"])
        else:
            # SR-58 ships ONE Caltrans section for the whole route, so a collision
            # in Bakersfield was headlined as "Tehachapi Pass: CLOSED". Only claim
            # a pass status when a Caltrans item names the corridor.
            label, cls, spoken = NO_PROBLEM_LABEL, "big-open", NO_PROBLEM_SPOKEN
            note = "Caltrans reports no closures or restrictions on Tehachapi Pass itself."
            area_note = "(Caltrans condition text below)"

        if rte.get("scope") is None:
            scope_legend = ("SR-58&rsquo;s Caltrans report is area-wide (Central California), so "
                            "the status word means &ldquo;SR-58 reported " + str(label) +
                            " (Central California area)&rdquo;, not a pass-specific claim.")
        elif scope.get("on_pass_reported"):
            scope_legend = ("A Caltrans item names the pass corridor, so this is a pass-specific "
                            "claim; other SR-58 items are listed separately with their location.")
        else:
            scope_legend = ("Caltrans names no problem on the pass corridor; any SR-58 problem "
                            "elsewhere is listed with its location, not as a claim about the pass.")
        note += _scope_note(scope, "SR-58")
        verbatim = " ".join(s.get("text", "") for s in (rte.get("sections") or []))
        big = f"""
      <div class="big-status {cls}">
        <p class="big-label">SR-58 · Tehachapi Pass</p>
        <p class="big-word">{label}</p>
        <p class="big-note">{note} <span class="subtle">{area_note}</span></p>
      </div>"""
        # direct quotable answer (first text after H1 for crawlers/AI) — honest scoping
        ts = rte.get("reported_as_of", "")
        if rte.get("scope") is None:
            # legacy snapshot wording, unchanged: it never claimed the pass itself
            direct_answer = (
                f'<p class="answer"><strong>As of {html.escape(ts or "the latest Caltrans report")}, '
                f'SR-58 is reported <span class="{cls}">{label}</span> by Caltrans '
                f'(Central California area).</strong> {note}</p>')
        else:
            _verdict = (f'<span class="{cls}">{spoken}</span>, as reported by Caltrans'
                        if scope.get("on_pass_reported") else
                        f'<span class="{cls}">{spoken}</span>')
            direct_answer = (
                f'<p class="answer"><strong>As of {html.escape(ts or "the latest Caltrans report")}, '
                f'SR-58 through Tehachapi Pass is {_verdict}.</strong> {note}</p>')
        if verbatim:
            direct_answer += (f'<p class="note">Showing Caltrans&rsquo; condition text: '
                              f'<em>{html.escape(verbatim)}</em></p>')
    else:
        big = '<div class="errorbox">Caltrans SR-58 conditions unavailable this build.</div>'
        direct_answer = (
            '<p class="answer">Caltrans SR-58 conditions are unavailable this build. '
            f'Check <a href="https://roads.dot.ca.gov/">roads.dot.ca.gov</a> or call {_PHONE}.</p>')
        label, cls, note, spoken, ts = "—", "", "", "unavailable", ""
        scope_legend = "Caltrans SR-58 conditions are unavailable this build."


    _age = _report_age_hint(rte.get("reported_as_of", "")) if rte else ""
    ts_html = (f'<span class="updated">{html.escape(rte["reported_as_of"])}{html.escape(_age)}</span>'
               if rte and rte.get("reported_as_of")
               else '<span class="updated">timestamp unavailable this build</span>')

    # stale banner
    staledom = ('<div class="errorbox">Caltrans is unreachable right now. The conditions '
                'below are from <strong>the most recent report</strong> and may be out of date. '
                'Confirm live status before driving: '
                '<a href="https://roads.dot.ca.gov/" target="_blank" rel="noopener">roads.dot.ca.gov</a> '
                f'or {_PHONE}.</div>' if is_stale else '')

    # ---- live wind & temp card (tehachapi wind answer)
    wind_card = '<div class="errorbox">Current pass weather unavailable this build.</div>'
    if cur.get("ok"):
        parts = []
        if cur.get("temperature") is not None:
            parts.append(f'<span class="n">{cur["temperature"]}°F</span> temp')
        if cur.get("wind_mph") is not None:
            gust = f", gusts to <strong>{cur['gust_mph']} mph</strong>" if cur.get("gust_mph") else ""
            parts.append(f'<span class="n">{cur["wind_mph"]} mph</span> wind{gust} '
                         f'from <strong>{cur.get("wind_dir") or "?"}</strong>')
        cond = cur.get("condition") or ""
        # observed is already "Sep 05, 07:35 PM"
        obs = cur.get("observed", "")
        station = cur.get("station", "?")
        stat_text = ", ".join(parts) or "no readings"
        wind_card = (
            '<div class="card"><h3>Current conditions at the pass</h3>'
            f'<p class="big-word" style="font-size:1.6rem">{stat_text}'
            + (f' &middot; {cond}' if cond else '')
            + f'</p>'
            f'<p class="note">Source: NWS station <strong>{html.escape(station)}</strong> '
            f'(Tehachapi), observed {html.escape(obs)}.</p></div>')
    elif cur:
        wind_card = ('<div class="errorbox">Live weather is unavailable this build — '
                     'the NWS station did not return a current reading.</div>')

    # ---- NWS forecast block
    fc_html = '<p class="note">Forecast unavailable this build.</p>'
    if forecast:
        rows = "".join(
            f'<tr><td>{html.escape(p.get("name", ""))}</td>'
            f'<td>{p.get("temp_f", "—")}°</td>'
            f'<td>{html.escape(p.get("wind_speed", ""))} {html.escape(p.get("wind_dir", ""))}</td>'
            f'<td>{html.escape(p.get("short", ""))}</td></tr>'
            for p in forecast[:5])
        fc_html = (f'<div class="table-wrap"><table class="data wide">'
                   f'<thead><tr><th>Period</th><th>Hi/Lo</th><th>Wind</th><th>Forecast</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>'
                   f'<p class="note">Source: National Weather Service.</p>')

    # ---- alerts block
    al_html = ('<p>No active NWS advisories for the Tehachapi area (CAZ334).</p>'
               f'<p class="note">Source: National Weather Service. Zone CAZ334 · '
               f'<a href="https://www.weather.gov/hnx/" target="_blank" rel="noopener">weather.gov/hnx</a></p>')
    if alerts:
        items = "".join(
            f'<li><span class="tag {_sev_cls(a.get("severity"))}">{html.escape(a.get("severity", ""))}</span> '
            f'<strong>{html.escape(a.get("event", ""))}</strong> {html.escape(a.get("headline", ""))}</li>'
            for a in alerts)
        al_html = f'<ul class="hl">{items}</ul><p class="note">Source: NWS. Confirm at weather.gov.</p>'

    # ---- route cards (SR-58 focus + I-5 + SR-99 compare)
    _TRACKER_LINKS = {"i5": "../grapevine/", "sr58": "", "sr99": ""}
    route_cards = []
    for r in ([rte] if rte else []) + others:
        if not r:
            continue
        st = r.get("pass_status") or r.get("status")
        # dedupe identical Caltrans section text (I-5 sometimes returns the same
        # "No traffic restrictions reported." line three times) and truncate on
        # a word boundary so no dangling fragment ("…permit loads N") ships.
        seen, txts = set(), []
        for s in (r.get("sections") or []):
            t = (s.get("text") or "").strip()
            if t and t not in seen:
                seen.add(t)
                txts.append(t)
        vtext = " ".join(txts) or "No detail text from Caltrans."
        if len(vtext) > 180:
            cut = vtext[:180].rsplit(" ", 1)[0].rstrip(",;:.")
            vtext = cut + "…"
        link = _TRACKER_LINKS.get(r.get("slug", ""))
        h3 = (f'<h3><a href="{link}">{html.escape(r.get("name", r.get("slug", "")))}</a></h3>'
              if link else f'<h3>{html.escape(r.get("name", r.get("slug", "")))}</h3>')
        route_cards.append(f"""
        <div class="card"><span class="tag {_TAG_CLS.get(st, 'amber')}">{st}</span>
        {h3}
        <p class="note">{html.escape(vtext)}</p></div>""")
    cards_html = "".join(route_cards)

    # ---- recent changes log
    if log:
        rows = "".join(f"""
        <tr><td class="num">{html.escape(e.get('ts', ''))}</td>
        <td>{html.escape(e.get('route_name', e.get('route', '')))}</td>
        <td>{html.escape(e.get('from', ''))} → <strong>{html.escape(e.get('to', ''))}</strong></td></tr>"""
                       for e in log[:12])
        log_html = f"""<div class="table-wrap"><table class="data">
          <thead><tr><th class="num">When</th><th>Route</th><th>Change</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""
    else:
        log_html = '<p class="note">No status changes since tracking started.</p>'

    # ---- FAQ (visible + schema). Q1 carries the live status.
    stale_sfx = (" — Caltrans is unreachable right now, so this is the most recent report and may "
                 "be out of date. Confirm live status before driving." if is_stale else "")
    # Only claim "as reported by Caltrans" when Caltrans names the pass corridor.
    _asof = html.escape(ts or "the latest update")
    if rte and rte.get("scope") is None:
        faq_lead = (f'SR-58 over Tehachapi Pass is reported <strong>{label}</strong> by Caltrans '
                    f'as of {_asof}{stale_sfx}.')
    elif rte and (rte.get("scope") or {}).get("on_pass_reported"):
        faq_lead = (f'SR-58 through Tehachapi Pass is <strong>{spoken}</strong>, as reported by '
                    f'Caltrans as of {_asof}{stale_sfx}.')
    elif rte:
        faq_lead = (f'SR-58 through Tehachapi Pass is clear of reported problems as of '
                    f'{_asof}{stale_sfx}.')
    else:
        faq_lead = "Caltrans SR-58 conditions are unavailable this build."
    faq_qa = [
        ("Is Tehachapi Pass open right now?",
         (f"{faq_lead} {note}" if rte else
          "Caltrans SR-58 conditions are unavailable this build — see roads.dot.ca.gov or call 1-800-427-7623.")),
        ("What are the road conditions on Highway 58 through Tehachapi Pass?",
         (f"{faq_lead} Confirm on roads.dot.ca.gov before driving." if rte else
          "Caltrans conditions are unavailable this build.")),
        ("How windy is Tehachapi Pass right now?",
         (_wind_answer(cur) if cur.get("ok") else
          "A current wind reading is unavailable this build — the NWS station did not report.")),
        ("How do I check SR-58 Tehachapi Pass conditions?",
         f"Call Caltrans at {_PHONE} or visit roads.dot.ca.gov. This page also checks Caltrans "
         f"in real time when you load it and refreshes every 60 seconds while it's open."),
        ("Why does Tehachapi Pass close?",
         "Snow and ice in winter storms, and high winds that tip high-profile vehicles. Caltrans posts "
         "chain controls (R2/R3) at the base of the grade."),
        ("What is the best alternate route if Tehachapi Pass is closed?",
         "The Grapevine (I-5 / Tejon Pass) is the usual detour — check its status here — or SR-14/US-395 "
         "around the east side, which stays open when both passes close."),
    ]
    faq_html = "".join(
        f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)
    live_answer = re.sub(r"<[^>]+>", "", faq_qa[0][1]) if rte else None

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Highway conditions · Caltrans + NWS</p>
      <h1>Is Tehachapi Pass (SR-58) open right now?</h1>
      <p class="lede">Live SR-58 conditions over Tehachapi Pass (elevation 4,067 ft) — the mountain
      alternative to the Grapevine — plus live wind, the NWS forecast, and Kern alerts.</p>
      <div class="meta"><span>Caltrans report: {ts_html}</span>
      <span class="dot">&bull;</span><span>live &middot; checks SR-58 &amp; wind in real time</span></div></div>
    </div>

    {direct_answer}

    {staledom}

    {big}

        {images.figure("tehachapi", rel)}

        <div class="grid cols-2">
          {wind_card}
      <div class="card"><h3>Forecast</h3>{fc_html}</div>
    </div>

    <section class="block">
      <div class="sign-head"><span class="tab">Alerts</span><h2>NWS alerts for the pass</h2></div>
      <div class="card">{al_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Compare</span><h2>Corridor routes</h2></div>
      <div class="grid cols-2">{cards_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Alternates</span><h2>If it's closed</h2></div>
      <div class="card"><ul class="hl">
        <li><strong>The Grapevine (I-5 / Tejon Pass)</strong> — the usual detour; check its live status on
        <a href="/grapevine/">the Grapevine page</a>.</li>
        <li><strong>SR-14 / US-395 loop</strong> — east around the mountains via Mojave and the Owens
        Valley; stays open when both passes close.</li>
        <li><strong>Amtrak San Joaquins</strong> — the train doesn't care about chain controls;
        Tehachapi and Bakersfield are on the line.</li>
      </ul>
      <p class="note" style="margin-top:8px">Live conditions and closures, 24/7:
      <a href="https://roads.dot.ca.gov/" target="_blank" rel="noopener">roads.dot.ca.gov</a>
      or Caltrans at <strong>{_PHONE}</strong>.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Why</span><h2>Why Tehachapi Pass closes</h2></div>
      <div class="card"><p>Tehachapi Pass is the SR-58 crossing of the Tehachapi Mountains
      (summit about <strong>4,067 feet</strong>), the key east-side mountain pass on the Los
      Angeles–San Joaquin Valley corridor. It closes for two main reasons: <strong>snow and ice</strong>
      in winter storms (a few inches can force chain controls or a closure), and <strong>high
      winds</strong> that flip high-profile trucks — wind advisories are common here and are a frequent
      cause of restrictions even when there's no precipitation.</p>
      <p>Chain requirements are posted at the base of the grade. When R2 or R3 chain controls are in
      effect, traction devices are mandatory.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Before you drive</span><h2>Know before you go</h2></div>
      <div class="card"><ul class="hl">
        <li><strong>Elevation:</strong> the pass crest is about <strong>4,067 ft</strong> — snow at
        the summit is common even when the valley is dry.</li>
        <li><strong>Chain controls:</strong> R2 (chains or traction devices on all vehicles except
        4WD/AWD with snow tires) and R3 (chains required on all vehicles) are posted at the base of
        the grade when winter storms hit.</li>
        <li><strong>See it live:</strong> view current Caltrans cameras and traffic on
        <a href="https://quickmap.dot.ca.gov/" target="_blank" rel="noopener">QuickMap</a> — the
        official free live map of highway conditions, closures, and road cams for SR-58.</li>
      </ul></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Log</span><h2>Recent changes</h2></div>
      {log_html}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Tehachapi Pass questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>

    <p class="note">Road conditions are Caltrans&rsquo; text, lightly cleaned for typos and spacing
    (facts and the agency&rsquo;s timestamp are unchanged). {scope_legend}
    Wind/weather are from the NWS station and forecast; each shows its own timestamp.
    Always confirm on the official source before driving.</p>"""

    page = page_mod.render(
        title="Is Tehachapi Pass (SR-58) open right now? | Bakersfield Daily Brief",
        desc="Live SR-58 conditions over Tehachapi Pass — the LA-to-Bakersfield alternative to the Grapevine — plus Tehachapi wind, weather, and NWS alerts. Live: checks Caltrans & NWS in real time on every load.",
        canonical="/tehachapi-pass/", content=body, current="trackers", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq(live_answer, faq_qa)],
        extra_scripts='<script src="{rel}assets/js/live-pass.js" defer></script>'.format(rel=rel))
    common.write(common.SITE / "tehachapi-pass" / "index.html", page)
    built.append("tehachapi-pass/index.html")

    ctx.build_report["tehachapi"] = {
        "sr58": rte.get("status") if rte else None,
        "wind_mph": cur.get("wind_mph"),
        "alerts": len(alerts),
        "stale": is_stale,
    }
    return built


def _sev_cls(sev: str) -> str:
    return {"Extreme": "red", "Severe": "red", "Moderate": "amber"}.get(sev, "green")


def _wind_answer(cur: dict) -> str:
    """Honest wind sentence for the FAQ/schema. Omits the gust clause entirely
    when no gust reading is present, instead of leaving a blank 'gusts to — mph'."""
    mph = cur.get("wind_mph")
    gust = cur.get("gust_mph")
    wdir = cur.get("wind_dir") or "—"
    obs = cur.get("observed", "the latest observation")
    station = cur.get("station", "NWS")
    if mph is None:
        return f"As of {obs}, the {station} station did not report a wind speed."
    base = f"As of {obs}, the {station} station reports {mph} mph"
    if gust is not None:
        base += f" with gusts to {gust} mph"
    return f"{base} from {wdir}."


def _faq(live_answer: str | None, faq_qa) -> dict:
    """FAQPage schema. Q1's answer carries the live status for AI/featured-snippet."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer",
                                "text": (live_answer if (i == 0 and live_answer) else a)}}
            for i, (q, a) in enumerate(faq_qa)
        ],
    }

