#!/usr/bin/env python3
"""Kern County highway conditions hub — /roads/.

The year-round traffic play: one stable page that answers 'what are road
conditions in Bakersfield / Kern right now' across the three highways people
actually drive — I-5 (Grapevine/Tejon Pass), SR-58 (Tehachapi), and SR-99
(up the valley) — with the Caltrans status for each, the agency's verbatim
timestamp, a change log, and a live-status hydration widget.

Reuses the SAME Caltrans data the /grapevine/ page already pulls (roads source),
so this costs zero new plumbing. SEO/AI-forward: direct quotable answer in the
first 40 words, on-page FAQ matching the schema, honest staleness fallback.
"""
from __future__ import annotations

import html
import re

from .. import common
from . import images
from . import page as page_mod
from ..sources import roads as roads_src
from .grapevine import (_STATUS_COPY, _TAG_CLS, _report_age_hint, _scope_note,
                        _elsewhere_phrase, NO_PROBLEM_LABEL, NO_PROBLEM_SPOKEN)

_PHONE = "1-800-427-7623"

_ROUTE_META = {
    "i5": ("I-5 · Grapevine (Tejon Pass)", "the LA-to-Bakersfield pass", "../grapevine/"),
    "sr58": ("SR-58 · Tehachapi Pass", "the east–west pass to the desert", "../tehachapi-pass/"),
    "sr99": ("SR-99 · Central Valley", "the valley route north through Bakersfield", ""),
}

# Prose names for the direct answer, so it never renders "I-5 (Grapevine (Tejon Pass))".
_ROUTE_PROSE = {
    "i5": "I-5 over Tejon Pass",
    "sr58": "SR-58 over Tehachapi Pass",
    "sr99": "SR-99 through the Central Valley",
}


def _kern_status(r: dict) -> str:
    """The status word this page should report for a route, in Kern County terms.

    A route's `status` rolls up EVERY Caltrans region, so a closed connector in
    Orange County was headlined as "I5 CLOSED" on this Kern County page while
    Tejon Pass itself was open. `pass_status` is the Central California / pass
    section, which is what grapevine.py, tehachapi.py and the status bar already
    report, so use the same field here and the whole site agrees.
    """
    return r.get("pass_status") or r.get("status", "OPEN")


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    data = sources.get("roads", {})
    routes = data.get("routes", []) if (data.get("ok") or data.get("last_good")) else []
    log = data.get("log", [])
    is_stale = bool(data.get("stale"))
    rel = "../"

    # ---- direct quotable answer (first text after H1, for crawlers/AI)
    if routes:
        # Spoken form, not raw status words: "I5 RESTRICTIONS" is unquotable,
        # "I-5 (Tejon Pass) is open with restrictions" is what an answer engine repeats.
        _numbers = {"i5": "I-5", "sr58": "SR-58", "sr99": "SR-99"}
        parts = []
        for r in routes:
            meta = _ROUTE_META.get(r["slug"])
            if not meta:
                continue
            sc = r.get("scope")
            if sc is None:
                spoken = _STATUS_COPY.get(_kern_status(r), _STATUS_COPY["OPEN"])[3]
            elif sc.get("on_pass_reported"):
                spoken = _STATUS_COPY.get(sc.get("on_pass", _kern_status(r)),
                                          _STATUS_COPY["OPEN"])[3]
            else:
                # No Caltrans item names this corridor: say that, never a bare OPEN/CLOSED
                spoken = NO_PROBLEM_SPOKEN
            parts.append(f"{_ROUTE_PROSE.get(r['slug'], meta[0])} is {spoken}")
        statuses = "; ".join(parts)
        asof = next((r.get("reported_as_of") for r in routes if r.get("reported_as_of")), data.get("asof", "the latest Caltrans report"))
        direct = (f'<p class="answer"><strong>As of {html.escape(asof)}, Caltrans reports: '
                  f'{statuses}.</strong> '
                  f'Check each route below for the latest Caltrans-reported conditions '
                  f'before you drive.</p>')
    else:
        direct = '<div class="errorbox">Caltrans conditions unavailable this build.</div>'

    # ---- big summary cards per route
    cards = ""
    for slug, (label, blurb, tracker_link) in _ROUTE_META.items():
        r = next((x for x in routes if x["slug"] == slug), None)
        if not r:
            cards += f"""<div class="card"><h3>{html.escape(label)}</h3>
            <p class="note">Conditions unavailable this build.</p></div>"""
            continue
        status = _kern_status(r)
        wlabel, wcls, note, _wspoken = _STATUS_COPY.get(status, _STATUS_COPY["OPEN"])
        if r.get("status") != status:
            note += " Note: other sections of this route report differently — see details below."
        secs = "".join(
            f"""<li><span class="tag {_TAG_CLS.get(s['status'],'amber')}">{s['status']}</span>
            <strong>{html.escape(s['region'])}:</strong> {html.escape(s['text'])}</li>"""
            for s in r.get("sections", []))
        ts = r.get("reported_as_of", "")
        age = _report_age_hint(ts)
        link_html = (f'<p class="note"><a href="{tracker_link}">Detailed {html.escape(label.split(" · ")[0])} conditions →</a></p>'
                     if tracker_link else "")
        cards += f"""<div class="card" data-route="{html.escape(r['slug'])}">
          <span class="tag {_TAG_CLS.get(status,'amber')}">{status}</span>
          <h3>{html.escape(label)}</h3>
          <p class="note">{blurb}.</p>
          <ul class="hl">{secs or '<li class="note">No conditions text parsed.</li>'}</ul>
          <p class="note"><span class="updated">{html.escape(ts)}{html.escape(age)}</span></p>
          {link_html}
        </div>"""
    ts_any = next((r.get("reported_as_of") for r in routes if r.get("reported_as_of")), "")
    _age_all = _report_age_hint(ts_any)
    ts_html = (f'<span class="updated">{html.escape(ts_any)}{html.escape(_age_all)}</span>' if ts_any
               else '<span class="updated">timestamp unavailable this build</span>')
    staledom = ('<div class="errorbox">Caltrans is unreachable right now. The conditions '
                'below are from <strong>the most recent report</strong> and may be out of date. '
                'Confirm live status before driving: '
                '<a href="https://roads.dot.ca.gov/" target="_blank" rel="noopener">roads.dot.ca.gov</a> '
                f'or {_PHONE}.</div>' if is_stale else '')

    # ---- change log
    if log:
        rows = "".join(f"""<tr><td class="num">{html.escape(roads_src.log_when(e))}</td>
        <td>{html.escape(e.get('route_name', e.get('route','')))}</td>
        <td>{html.escape(e.get('from',''))} → <strong>{html.escape(e.get('to',''))}</strong></td></tr>"""
                       for e in log[:12])
        log_html = f"""<div class="table-wrap"><table class="data">
          <thead><tr><th class="num">When</th><th>Route</th><th>Change</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""
    else:
        log_html = '<p class="note">No status changes since tracking started.</p>'

    # ---- FAQ (on-page + schema, with live status injected into Q1)
    stale_suffix = (" — Caltrans is unreachable right now, so this is the most recent report "
                    "and may be out of date. Confirm live status before driving." if is_stale else "")

    def _route_status(slug: str) -> str:
        r = next((x for x in routes if x["slug"] == slug), None)
        if not r:
            return "unavailable this build"
        return _kern_status(r)

    def _route_scope(slug: str) -> dict | None:
        """None means 'no route'; {} means 'route present, snapshot has no scope'."""
        r = next((x for x in routes if x["slug"] == slug), None)
        return None if r is None else (r.get("scope") or {})

    def _route_spoken(slug: str) -> str:
        sc = _route_scope(slug)
        if sc is None:
            return "unavailable this build"
        if not sc:                       # pre-scope snapshot: report the rollup word
            return _STATUS_COPY.get(_kern_status(next(x for x in routes if x["slug"] == slug)),
                                    _STATUS_COPY["OPEN"])[3]
        if sc.get("on_pass_reported"):
            return _STATUS_COPY.get(sc.get("on_pass", "OPEN"), _STATUS_COPY["OPEN"])[3]
        return NO_PROBLEM_SPOKEN

    def _route_clause(slug: str, name: str) -> str:
        """Full honest sentence about a pass, plus where the real problem is."""
        sc = _route_scope(slug)
        if sc is None:
            return f"Caltrans {name} conditions are unavailable this build."
        if not sc:
            return (f"{name} is {_route_spoken(slug)}, as reported by Caltrans "
                    f"(Caltrans reports this area-wide, which covers more than the pass).")
        note = _scope_note(sc, name.split()[0])
        if sc.get("on_pass_reported"):
            return f"{name} is {_route_spoken(slug)}, as reported by Caltrans.{note}"
        return (f"Caltrans reports no closure or restriction on {name} itself."
                f"{note}")

    live_status = statuses if routes else "unavailable this build"
    faq_qa = [
        ("What are the road conditions in Bakersfield and Kern County right now?",
         f"As of {html.escape(asof)}, Caltrans reports: {html.escape(live_status)}.{stale_suffix} "
         f"See each route above for details, or call Caltrans at {_PHONE}."),
        ("Is SR-58 / Tehachapi Pass open?",
         f"{_route_clause('sr58', 'SR-58 through Tehachapi Pass')} "
         f"It is a mountain pass and can close for snow, wind, and chain controls in winter."),
        ("Is the Grapevine (I-5) open?",
         f"{_route_clause('i5', 'I-5 over Tejon Pass')} "
         f"It is the highest point on I-5 between LA and the Central Valley."),
        ("Is SR-99 open through Bakersfield?",
         f"SR-99 is {_route_spoken('sr99')}, as reported by Caltrans."),
        ("Is SR-99 closed in Bakersfield?",
         (f"{_route_clause('sr99', 'SR-99 through Bakersfield')} Caltrans posts closures of "
          f"SR-99 anywhere along the route, so read the location before you change plans.")),
        ("Is the Grapevine or Tehachapi Pass closed right now?",
         (f"Caltrans reports no closure on the pass corridors. "
          f"{_scope_note(_route_scope('i5'), 'I-5').strip()} "
          f"{_scope_note(_route_scope('sr58'), 'SR-58').strip()}").replace("  ", " ")),
        ("How do I get current California highway conditions?",
         f"Call Caltrans at {_PHONE} or visit roads.dot.ca.gov. This page also checks Caltrans "
         f"in real time when you load it and refreshes every 60 seconds while it's open."),
    ]
    faq_html = "".join(
        f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)
    live_answer = re.sub(r"<[^>]+>", "", faq_qa[0][1])

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Highway conditions · Caltrans</p>
      <h1>Bakersfield &amp; Kern County road conditions right now</h1>
      <p class="lede">Live conditions for the three highways that move Kern County —
      I-5 over the Grapevine, SR-58 over Tehachapi Pass, and SR-99 up the valley —
      straight from Caltrans.</p>
      <div class="meta"><span>Caltrans report: {ts_html}</span>
      <span class="dot">&bull;</span><span>live &middot; checks Caltrans in real time</span></div></div>
    </div>

    {direct}

    {staledom}

    {images.figure("wind", rel)}

    <div class="grid cols-2">{cards}</div>

    <section class="block">
      <div class="sign-head"><span class="tab">Log</span><h2>Recent changes</h2></div>
      {log_html}
      {roads_src.log_note(log)}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Road conditions questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Live</span><h2>Check current conditions</h2></div>
      <div class="card"><p>Conditions are Caltrans&rsquo; text, lightly cleaned for typos and spacing
      (facts and the agency&rsquo;s timestamp are unchanged). Status words are per Caltrans area section.
      For current conditions on demand, use the official
      <a href="https://quickmap.dot.ca.gov/" target="_blank" rel="noopener">Caltrans QuickMap</a>
      or call <strong>{_PHONE}</strong>.</p></div>
    </section>

    <p class="note">Always confirm on the official source before driving.</p>"""

    page = page_mod.render(
        title="Bakersfield & Kern County Road Conditions Today | Live Caltrans",
        desc="Live Caltrans conditions for I-5 (Grapevine), SR-58 (Tehachapi Pass), and SR-99 through "
             "Bakersfield — closed, restricted, or open. Live: checks Caltrans in real time on every load.",
        canonical="/roads/", content=body, current="trackers", rel=rel,
        built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq_jsonld(faq_qa, live_answer)],
        extra_scripts='<script src="{rel}assets/js/live-roads.js" defer></script>'.format(rel=rel))
    common.write(common.SITE / "roads" / "index.html", page)
    built.append("roads/index.html")

    ctx.build_report["roads"] = {
        "routes": [f"{r['slug']}:{_kern_status(r)}" for r in routes],
        "log_entries": len(log),
    }
    return built


def _faq_jsonld(faq_qa, live_answer: str) -> dict:
    """FAQPage schema built from the SAME faq_qa list rendered on-page, so the
    schema answers can never drift from the visible text (Q1 gets the live
    status, Q2-Q4 carry their real reported statuses)."""
    main = []
    for i, (q, a) in enumerate(faq_qa):
        text = live_answer if (i == 0 and live_answer) else re.sub(r"<[^>]+>", "", a)
        main.append({"@type": "Question", "name": q,
                     "acceptedAnswer": {"@type": "Answer", "text": text}})
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": main}
