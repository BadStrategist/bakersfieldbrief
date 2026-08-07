#!/usr/bin/env python3
"""Openings & Closings — merged feed of new liquor license applications (CA ABC,
filtered to Bakersfield) and food-facility closures (Kern County Environmental
Health), tagged by type. DBA filings and building permits are stubs.
"""
from __future__ import annotations

import html

from .. import common
from . import images
from . import page as page_mod


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"
    abc = sources.get("abc", {})
    food = sources.get("food", {})

    # ---- openings: liquor license applications ----
    if abc.get("ok"):
        rows = abc.get("items", [])
        if rows:
            items = "".join(f"""
        <li>
          <span class="src">Liquor license · {html.escape(r.get('type', 'application'))} · expires {html.escape(r.get('expires', '—'))}</span><br>
          <a href="{html.escape(r.get('url') or 'https://www.abc.ca.gov/licensing/license-lookup/')}">{html.escape(r.get('dba') or 'Unnamed applicant')}</a>
          <span class="when">{html.escape(r.get('address', ''))}</span>
        </li>""" for r in rows[:20])
            openings = f'<ul class="hl">{items}</ul>'
        else:
            openings = ('<p class="note">No pending Bakersfield liquor license applications are '
                        'listed by the CA Department of Alcoholic Beverage Control right now. '
                        'The statewide list is checked daily.</p>')
    else:
        openings = (f'<div class="errorbox">ABC data unavailable this build '
                    f'({html.escape(abc.get("error", "unknown"))}).</div>')

    # ---- closings: food facility closures ----
    if food.get("ok"):
        frows = food.get("items", [])
        if frows:
            rows = "".join(f"""
            <tr>
              <td><strong>{html.escape(f.get('facility', ''))}</strong></td>
              <td>{html.escape(f.get('address', ''))}</td>
              <td>{html.escape(str(f.get('closed_date', ''))[:10])}</td>
              <td class="num">{html.escape(f.get('score', ''))}</td>
            </tr>""" for f in frows)
            closings = f"""
            <div class="table-wrap"><table class="data">
              <thead><tr><th>Facility</th><th>Address</th><th>Closed</th><th class="num">Score</th></tr></thead>
              <tbody>{rows}</tbody>
            </table></div>"""
        else:
            closings = '<p class="note">No food facilities are currently listed as closed by Kern County Environmental Health.</p>'
    else:
        closings = (f'<div class="errorbox">Kern EH data unavailable this build '
                    f'({html.escape(food.get("error", "unknown"))}).</div>')

    body = f"""
    <div class="pagehead">
      <div class="hero"><p class="kicker">Openings &amp; Closings</p>
      <h1>New licenses &amp; facility closures</h1>
      <p class="lede">A daily merged feed of business openings and closures in Bakersfield:
      pending liquor license applications filed with the state, and food facilities closed by
      county environmental health inspectors. Each item links to the official record.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>CA ABC · Kern County Environmental Health</span></div></div>
    </div>

    {images.figure("almonds", rel)}

    <section class="block">
      <div class="sign-head"><span class="tab amber">Open</span><h2>Liquor license applications</h2></div>
      <div class="card">{openings}
      <p class="note">Source: California Department of Alcoholic Beverage Control &mdash; new
      applications list. A pending application is not an approval; the public can protest
      applications at the district office within the protest window.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab red">Close</span><h2>Food facility closures</h2></div>
      <div class="card">{closings}
      <p class="note">Source: Kern County Public Health / Environmental Health &mdash; closed food
      facility list. The closure score is the inspection score at closure. Facilities may reopen
      after passing re-inspection.</p></div>
    </section>

    <section class="block">
      <div class="sign-head"><span class="tab">Later</span><h2>Coming to this section</h2></div>
      <div class="grid cols-2">
        <div class="card"><span class="tag">Stub</span><h3>DBA filings</h3>
        <p>Kern County Clerk fictitious business name filings are on the roadmap; the clerk&rsquo;s
        portal needs a self-hosted runner for automated access.</p></div>
        <div class="card"><span class="tag">Stub</span><h3>Building permits</h3>
        <p>Kern Development Services permit data is a planned tracker; blocked from datacenter
        IPs for now.</p></div>
      </div>
    </section>"""

    page = page_mod.render(
        title="Openings & Closings — new liquor licenses & food closures | Bakersfield Daily Brief",
        desc="Daily merged feed of Bakersfield business openings (CA ABC liquor license applications) and closings (Kern County food facility closures), each linked to the official record.",
        canonical="/openings/",
        content=body, current="openings", rel=rel, built=built_iso, statusbar=ctx.statusbar,
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()])
    common.write(common.SITE / "openings" / "index.html", page)
    built.append("openings/index.html")

    ctx.build_report["openings"] = {
        "liquor_apps": len(abc.get("items", [])),
        "food_closures": len(food.get("items", [])),
    }
    return built
