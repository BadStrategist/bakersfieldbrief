#!/usr/bin/env python3
"""The Grapevine page — /grapevine/ — SEO/GEO flagship for LA↔Bakersfield.

Big plain answer at the top (OPEN / RESTRICTIONS / CLOSED for I-5 Tejon
Pass), SR-58 and SR-99 status alongside, the Caltrans "latest reported as
of" timestamp displayed verbatim, a recent-changes log, and original
explainer copy (why the Grapevine closes, alternates, Caltrans phone).
"""
from __future__ import annotations

import html
import json

from .. import common
from . import page as page_mod

_PHONE = "1-800-427-7623"

_STATUS_COPY = {
    "OPEN": ("Open", "big-open", "No closures or restrictions are currently reported on this route."),
    "RESTRICTIONS": ("Restrictions", "big-restrict", "The route is open with restrictions — see the details below."),
    "CLOSED": ("Closed", "big-closed", "The route is reported closed — see the details below."),
}


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    data = sources.get("roads", {})
    routes = data.get("routes", []) if data.get("ok") else []
    log = data.get("log", [])
    rel = "../"

    i5 = next((r for r in routes if r["slug"] == "i5"), None)
    others = [r for r in routes if r["slug"] != "i5"]

    # ---- big answer (headlines the pass itself; notes other I-5 sections)
    if i5:
        pass_status = i5.get("pass_status") or i5["status"]
        label, cls, note = _STATUS_COPY.get(pass_status, _STATUS_COPY["OPEN"])
        if i5["status"] != pass_status:
            note += (f" Note: other I-5 sections report "
                     f"{i5['status'].lower()} — see the details below.")
        big = f"""
      <div class="big-status {cls}">
        <p class="big-label">I-5 · Grapevine (Tejon Pass)</p>
        <p class="big-word">{label}</p>
        <p class="big-note">{note}</p>
      </div>"""
    else:
        big = '<div class="errorbox">Caltrans conditions unavailable this build.</div>'

    ts = i5.get("reported_as_of", "") if i5 else ""
    ts_html = (f'<span class="updated">{html.escape(ts)}</span>' if ts
               else '<span class="updated">timestamp unavailable this build</span>')

    # ---- all-route details
    cards = ""
    no_text = '<li class="note">No conditions text parsed.</li>'
    for r in [i5] + others:
        if not r:
            continue
        secs = "".join(f"""
        <li><strong>{html.escape(s['region'])}:</strong> {html.escape(s['text'])}</li>"""
                       for s in r.get("sections", []))
        cards += f"""
        <div class="card">
          <span class="tag {'amber' if r['status'] != 'OPEN' else 'green'}">{r['status']}</span>
          <h3>{html.escape(r['name'])}</h3>
          <ul class="hl">{secs or no_text}</ul>
        </div>"""

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

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Highway conditions · Caltrans</p>
      <h1>Is the Grapevine closed right now?</h1>
      <p class="lede">Live I-5 conditions over Tejon Pass — the 40-mile climb that connects
      Los Angeles and Bakersfield — plus SR-58 over Tehachapi and SR-99 up the valley.</p>
      <div class="meta"><span>Caltrans report: {ts_html}</span>
      <span class="dot">&bull;</span><span>refreshes 3× daily</span></div></div>
    </div>

    {big}

    <div class="grid cols-2">{cards}</div>

    <section class="block">
      <div class="sign-head"><span class="tab">Why</span><h2>Why the Grapevine closes</h2></div>
      <div class="card"><p>The Grapevine is the I-5 crossing of Tejon Pass (elevation 4,144
      feet), the highest point on the route between Los Angeles and the Central Valley. It
      closes for three reasons, in rough order of frequency: <strong>snow and ice</strong>
      (a few inches is enough to force chain controls or a full closure), <strong>dense
      fog</strong> that can drop visibility to near zero for miles, and <strong>high
      winds</strong> that tip trucks — the pass has a history of overturns that shut both
      directions for hours. Caltrans also schedules maintenance closures overnight, which
      appear on this page as restrictions with times.</p>
      <p>Chain requirements are posted at the bottom of the grade. When R2 or R3 chain
      controls are in effect, traction devices are mandatory — Caltrans officers turn
      vehicles around at the chain-installation points.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Alternates</span><h2>If it's closed: alternate routes</h2></div>
      <div class="card"><ul class="hl">
        <li><strong>SR-58 over Tehachapi Pass</strong> — the usual detour, but it's a mountain
        pass itself: check its status above before committing.</li>
        <li><strong>SR-14 / US-395 loop</strong> — east around the mountains via Mojave and
        the Owens Valley; long, but it stays open when both passes close.</li>
        <li><strong>US-101 coast route</strong> — the long way around; only worth it for
        multi-day closures.</li>
        <li><strong>Amtrak San Joaquins</strong> — the train doesn't care about chain
        controls; Bakersfield is a main-line stop.</li>
      </ul>
      <p class="note" style="margin-top:8px">Live conditions and closure updates, 24/7:
      <a href="https://roads.dot.ca.gov/" target="_blank" rel="noopener">roads.dot.ca.gov</a>
      or Caltrans at <strong>{_PHONE}</strong>.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Log</span><h2>Recent changes</h2></div>
      {log_html}
    </section>

    <p class="note">Conditions are as reported by Caltrans District 7/6; we display the agency's
    own timestamp verbatim. Our status words (OPEN / RESTRICTIONS / CLOSED) are a plain-text
    classification of that report — always confirm on the official source before driving.</p>"""

    page = page_mod.render(
        title="Is the Grapevine (I-5 Tejon Pass) closed right now? | Bakersfield Daily Brief",
        desc="Live Caltrans conditions for the I-5 Grapevine over Tejon Pass — the LA to Bakersfield route — plus SR-58 Tehachapi and SR-99. Closed or restricted? Updated 3x daily.",
        canonical="/grapevine/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq_jsonld()])
    common.write(common.SITE / "grapevine" / "index.html", page)
    built.append("grapevine/index.html")

    ctx.build_report["grapevine"] = {
        "i5": i5["status"] if i5 else None,
        "i5_pass": i5.get("pass_status") if i5 else None,
        "log_entries": len(log),
    }
    return built


def _faq_jsonld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": "Is the Grapevine closed right now?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Check this page: we show the current Caltrans-reported status of I-5 over Tejon Pass — OPEN, RESTRICTIONS, or CLOSED — with the agency's own timestamp."}},
            {"@type": "Question", "name": "Why does the Grapevine close?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Snow and ice, dense fog, and high winds. Caltrans also schedules overnight maintenance closures. Chain controls (R2/R3) are posted at the bottom of the grade."}},
            {"@type": "Question", "name": "What is the best alternate route if the Grapevine is closed?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "SR-58 over Tehachapi Pass is the usual detour; SR-14/US-395 around the east side stays open when both passes close. Amtrak San Joaquins also serves Bakersfield."}},
            {"@type": "Question", "name": "How do I get current California highway conditions?",
             "acceptedAnswer": {"@type": "Answer", "text":
                "Call Caltrans at 1-800-427-7623 or visit roads.dot.ca.gov. This page refreshes 3 times daily."}},
        ],
    }
