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
from . import images
from . import page as page_mod
from ..sources import roads as roads_src

_PHONE = "1-800-427-7623"

_STATUS_COPY = {
    # (badge label, css class, plain note, spoken form for sentences)
    # The spoken form exists because "the pass is Restrictions" is not a sentence:
    # answer engines quote the direct answer verbatim, so it has to read as English.
    "OPEN": ("Open", "big-open",
             "No closures or restrictions are currently reported on this route.",
             "open"),
    "RESTRICTIONS": ("Restrictions", "big-restrict",
                     "The route is open with restrictions — see the details below.",
                     "open with restrictions"),
    "CLOSED": ("Closed", "big-closed",
               "The route is reported closed — see the details below.",
               "closed"),
}

_TAG_CLS = {"OPEN": "green", "RESTRICTIONS": "amber", "CLOSED": "red"}


def _elsewhere_phrase(it: dict) -> str:
    """Plain-words phrase for a Caltrans problem that is NOT on the pass."""
    kind = {"CLOSED": "a closure", "RESTRICTIONS": "restrictions"}.get(it.get("status"), "an advisory")
    return f"{kind} at {it['where']}" if it.get("place") else f"{kind} in {it['where']}"


def _scope_note(scope: dict, route_word: str) -> str:
    """Sentence naming Caltrans problems that sit elsewhere on the route.

    The pass answer has to survive being quoted: a bare "other sections report
    closed" next to "is the pass open" is what makes an answer engine quote the
    wrong road, so name the place and say outright that it is not the pass.
    """
    items = (scope or {}).get("elsewhere") or []
    if not items:
        return ""
    bits = [_elsewhere_phrase(it) for it in items[:2]]
    tail = "none of them on the pass" if (scope or {}).get("on_pass_reported") else "not on the pass"
    return (f" Elsewhere on {route_word}, Caltrans reports "
            + " and ".join(bits) + f" — {tail}.")


NO_PROBLEM_LABEL = "No problems reported"
NO_PROBLEM_SPOKEN = "clear of reported problems"


def _first_sentence(text: str, limit: int = 190) -> str:
    """Caltrans' first sentence for a section, bounded, for the 'elsewhere' note."""
    t = " ".join((text or "").split())
    cut = t.find(". ")
    s = t[:cut + 1] if cut > 0 else t
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "..."


def _report_age_hint(reported_as_of: str) -> str:
    """Short human hint for how old the Caltrans report is, or '' if unparseable.
    Format: 'Saturday, September 5th, 2026 at 07:40 PM' (Pacific time)."""
    import datetime as _dt
    import zoneinfo as _zi
    if not reported_as_of:
        return ""
    try:
        s = reported_as_of.replace(" at ", ", ")
        # Caltrans writes ordinal day ("September 5th") — strip the ordinal suffix.
        s = __import__("re").sub(r"(\d+)(st|nd|rd|th)", r"\1", s)
        parsed = _dt.datetime.strptime(s, "%A, %B %d, %Y, %I:%M %p")
        pac = _zi.ZoneInfo("America/Los_Angeles")
        now = _dt.datetime.now(pac)
        parsed = parsed.replace(tzinfo=pac)
        mins = int((now - parsed).total_seconds() // 60)
        if mins < 0:
            mins = 0
        if mins < 1:
            return " (just now)"
        if mins < 60:
            return f" ({mins} min ago)"
        hrs = mins // 60
        if hrs < 24:
            return f" ({hrs} hr{'' if hrs == 1 else 's'} ago)"
        return f" ({hrs // 24} day{'' if hrs // 24 == 1 else 's'} ago)"
    except Exception:
        return ""


def build(ctx, sources: dict) -> list[str]:
    # imported here: traffic_cameras reads this package's road wording, so a top-level import is a cycle
    from . import traffic_cameras
    built = []
    built_iso = common.iso_today()
    data = sources.get("roads", {})
    # ok OR last_good: a failed live fetch may return last-known routes flagged
    # stale=True so we can render a graceful "may be out of date" fallback
    # instead of asserting "unavailable".
    routes = data.get("routes", []) if (data.get("ok") or data.get("last_good")) else []
    log = data.get("log", [])
    is_stale = bool(data.get("stale"))
    rel = "../"

    i5 = next((r for r in routes if r["slug"] == "i5"), None)
    others = [r for r in routes if r["slug"] != "i5"]

    # ---- big answer (headlines the pass itself; notes other I-5 sections)
    if i5:
        scope = i5.get("scope")
        _legacy = False
        if scope is None:
            # Snapshot predates corridor scoping (last-known fallback): keep the old
            # area-scoped claim rather than inventing "no problems reported".
            pass_status = i5.get("pass_status") or i5["status"]
            label, cls, note, spoken = _STATUS_COPY.get(pass_status, _STATUS_COPY["OPEN"])
            note += (" Note: that status is Caltrans' area-wide text, which covers more "
                     "than the pass.")
            scope = {}
            _legacy = True
        elif scope.get("on_pass_reported"):
            pass_status = scope.get("on_pass", i5.get("pass_status") or i5["status"])
            label, cls, note, spoken = _STATUS_COPY.get(pass_status, _STATUS_COPY["OPEN"])
        else:
            # Caltrans names no problem on the corridor, so claim no bare OPEN/CLOSED.
            label, cls, spoken = NO_PROBLEM_LABEL, "big-open", NO_PROBLEM_SPOKEN
            note = "Caltrans reports no closures or restrictions on Tejon Pass itself."
        note += _scope_note(scope, "I-5")
        big = f"""
      <div class="big-status {cls}">
        <p class="big-label">I-5 · Grapevine (Tejon Pass)</p>
        <p class="big-word">{label}</p>
        <p class="big-note">{note}</p>
      </div>"""
        # ---- direct quotable answer (first text after H1 for crawlers/AI)
        direct_answer = (f'<p class="answer"><strong>Is the Grapevine open right now? '
                         f'As of {html.escape(i5.get("reported_as_of", "the latest Caltrans report"))}, '
                         f'I-5 over Tejon Pass is <span class="{cls}">{spoken}</span>.</strong> '
                         f'{note}</p>')
    else:
        big = '<div class="errorbox">Caltrans conditions unavailable this build.</div>'
        direct_answer = ""

    ts = i5.get("reported_as_of", "") if i5 else ""
    _age = _report_age_hint(ts)
    ts_html = (f'<span class="updated">{html.escape(ts)}{html.escape(_age)}</span>' if ts
               else '<span class="updated">timestamp unavailable this build</span>')
    staledom = ('<div class="errorbox">Caltrans is unreachable right now. The conditions '
                'below are from <strong>the most recent report</strong> and may be out of date. '
                'Confirm live status before driving: '
                '<a href="https://roads.dot.ca.gov/" target="_blank" rel="noopener">roads.dot.ca.gov</a> '
                f'or {_PHONE}.</div>'
                if is_stale else '')

    # ---- live FAQ (visible on-page + injected into Q1 schema answer)
    # so the quotable answer IS the real current status, not "check this page".
    stale_suffix = (" — Caltrans is unreachable right now, so this is the most recent "
                    "report and may be out of date. Confirm live status before driving."
                    if is_stale else "")

    # FAQ lead: only say "as reported by Caltrans" when Caltrans actually names the
    # corridor. Otherwise it reads "clear of reported problems as reported by
    # Caltrans", which is the kind of sentence an answer engine drops.
    if i5:
        _asof = html.escape(ts or "the latest update")
        if (i5.get("scope") or {}).get("on_pass_reported") or i5.get("scope") is None:
            faq_lead = (f'The Grapevine (I-5 over Tejon Pass) is <strong>{spoken}</strong>, '
                        f'as reported by Caltrans at {_asof}{stale_suffix}.')
        else:
            faq_lead = (f'The Grapevine (I-5 over Tejon Pass) is clear of reported problems '
                        f'as of {_asof}{stale_suffix}.')
    else:
        faq_lead = "Caltrans conditions are unavailable this build."
    faq_qa = [
        ("Is the Grapevine open right now?",
                 (f'{faq_lead} {note}'
                  if i5 else
                  "Caltrans conditions are unavailable this build — see the official source below.")),
                ("Is the Grapevine closed right now?",
                 (f'{faq_lead} {note}'
                  if i5 else
                  "Caltrans conditions are unavailable this build — see the official source below.")),
        ("Why does the Grapevine close?",
         "Snow and ice, dense fog, and high winds. Caltrans also schedules overnight maintenance "
         "closures. Chain controls (R2/R3) are posted at the bottom of the grade."),
        ("What is the best alternate route if the Grapevine is closed?",
         "SR-58 over Tehachapi Pass is the usual detour; SR-14/US-395 around the east side stays "
         "open when both passes close. Amtrak San Joaquins also serves Bakersfield."),
        ("How do I get current California highway conditions?",
         "Call Caltrans at 1-800-427-7623 or visit roads.dot.ca.gov. This page also checks "
         "Caltrans in real time when you load it and refreshes every 60 seconds while it's open."),
    ]
    faq_html = "".join(
            f'<p class="pr-q"><strong>{html.escape(q)}</strong></p><p>{a}</p>' for q, a in faq_qa)

    # ---- all-route details (per-section status chips; no misleading
    #      route-wide tag — for I-5 the tag is the pass itself)
    cards = ""
    no_text = '<li class="note">No conditions text parsed.</li>'
    for r in [i5] + others:
        if not r:
            continue
        card_status = r.get("pass_status") if r["slug"] == "i5" else r["status"]
        secs_list = list(r.get("sections", []))
        if r["slug"] == "i5" and card_status:
            # Pass-scoped sections first: the Tejon Pass answer must not sit under
            # a closure 200 miles away (an Orange County connector) in visual order.
            secs_list.sort(key=lambda s: 0 if s.get("status") == card_status else 1)
        secs = "".join(f"""
        <li><span class="tag {_TAG_CLS.get(s['status'], 'amber')}">{s['status']}</span>
        <strong>{html.escape(s['region'])}:</strong> {html.escape(s['text'])}</li>"""
                       for s in secs_list)
        cards += f"""
        <div class="card">
          <span class="tag {_TAG_CLS.get(card_status, 'amber')}">{card_status}</span>
          <h3>{html.escape(r['name'])}</h3>
          <ul class="hl">{secs or no_text}</ul>
        </div>"""

    # ---- recent changes log
    if log:
        rows = "".join(f"""
        <tr><td class="num">{html.escape(roads_src.log_when(e))}</td>
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
      <h1>Is the Grapevine open right now?</h1>
      <p class="lede">I-5 over Tejon Pass, the climb between Los Angeles and Bakersfield,
      checked against Caltrans while this page is open.</p>
      <div class="meta"><span>Caltrans report: {ts_html}</span>
      <span class="dot">&bull;</span><span>live &middot; checks the Grapevine in real time</span></div></div>
    </div>

    {direct_answer}

        {staledom}

        <p class="note" style="margin-top:10px">Also see the <a href="../roads/">Kern County road conditions hub</a>
        — I-5, SR-58, and SR-99 status on one page.</p>

    {images.figure("wind", rel)}

    {big}

    {traffic_cameras.block(sources, rel, "grapevine")}

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
      <p>Chain requirements are posted at the bottom of the grade. Under R2 chain controls,
      every vehicle needs chains except four-wheel or all-wheel drive with snow tires on all four
      wheels; under R3, every vehicle needs chains. Drivers without them are turned back at the
      chain-control checkpoints.</p></div>
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
      {roads_src.log_note(log)}
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">FAQ</span><h2>Grapevine questions</h2></div>
      <div class="card">{faq_html}</div>
    </section>

    <p class="note">Conditions are Caltrans&rsquo; text, lightly cleaned for typos and spacing
    (facts and the agency&rsquo;s timestamp are unchanged). Status words are per Caltrans area
    section; for I-5 the big answer reflects the Tejon Pass (Central) section only. Always confirm
    on the official source before driving.</p>"""

    page = page_mod.render(
        title="Is the Grapevine Open Right Now? Live I-5 Tejon Pass Status | Bakersfield Daily Brief",
                desc="Is the Grapevine open or closed right now? Live Caltrans status for I-5 over Tejon Pass with the agency's own timestamp, chain controls, and the SR-58 and SR-99 alternates. Checks Caltrans on every load.",
                canonical="/grapevine/", content=body, current="trackers", rel=rel,
                built=built_iso, statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
                        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(), _faq_jsonld(faq_qa)],
                extra_scripts='<script src="{rel}assets/js/live-pass.js" defer></script>'.format(rel=rel)
                + traffic_cameras.scripts(rel))
    common.write(common.SITE / "grapevine" / "index.html", page)
    built.append("grapevine/index.html")

    ctx.build_report["grapevine"] = {
        "i5": i5["status"] if i5 else None,
        "i5_pass": i5.get("pass_status") if i5 else None,
        "log_entries": len(log),
    }
    return built


def _faq_jsonld(faq_qa: list) -> dict:
    """FAQPage schema built from the SAME on-page Q&A list, so the visible FAQ
    and the schema can never drift. Q1 carries the LIVE Caltrans status (so an
    AI/featured snippet citing this page quotes the real current state, not a
    circular 'check this page')."""
    import re as _re

    def _plain(s: str) -> str:
        return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", "", s)).strip()

    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": _plain(a)}}
            for q, a in faq_qa
        ],
    }
