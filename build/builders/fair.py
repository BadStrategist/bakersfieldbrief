#!/usr/bin/env python3
"""Kern County Fair page — /fair/ — dates, concert lineup, tickets.

Real, verified data pulled from kerncountyfair.com (the official fair site)
on 2026-08-30. Static page rebuilt every build; the year's content changes
when the fair announces updates. Concert lineup + ticket prices are displayed
verbatim from the official site — we never invent prices or acts.

Ranking target: "kern county fair 2026", "kern county fair dates",
"kern county fair concerts / concert lineup", "kern county fair tickets".
"""
from __future__ import annotations

from .. import common
from . import page as page_mod

# Dates & facts (verified from kerncountyfair.com, 2026-08-30)
FAIR_START = "2026-09-23"
FAIR_END = "2026-10-04"
FAIR_YEAR = "2026"
FAIR_ADDRESS = "1142 South P Street, Bakersfield, CA 93307"
# Fairgrounds geo (real coords from OSM Nominatim geocode of the address)
FAIR_LAT = 35.3443522
FAIR_LON = -119.0117664

# Concert series: Hard Rock Hotel & Casino Tejon Concert Series at the
# Budweiser Pavilion, 8:00 PM nightly, FREE with fair admission.
# (Verified from the official Budweiser Pavilion event schedule.)
CONCERTS = [
    ("2026-09-23", "ERNEST"),
    ("2026-09-24", "Collective Soul"),
    ("2026-09-25", "Barenaked Ladies"),
    ("2026-09-26", "Mario"),
    ("2026-09-27", "Ezequiel Peña"),
    ("2026-09-28", "Gretchen Wilson"),
    ("2026-09-29", "Chandler Moore"),
    ("2026-09-30", "Carly Pearce"),
    ("2026-10-01", "Daughtry"),
    ("2026-10-02", "90's Rewind"),
    ("2026-10-03", "Joe Nichols"),
    ("2026-10-04", "Industria del Amor"),
]

# Grandstand + special events (official fair site)
GRANDSTAND = [
    ("PRCA Rodeo", "Professional Rodeo Cowboys Association rodeo at the grandstand."),
    ("Fiesta Del Charro Rodeo", "Mexican-style rodeo at the grandstand."),
    ("Monster Trucks", "Monster truck show at the grandstand."),
    ("Scottish Games & Gathering", "Highland games and Scottish cultural gathering."),
    ("26th Annual Latino Food Festival — Menudo & Pozole Cook-Off",
     "Annual food festival and cook-off."),
]

# Ticket prices (verified from the official Tickets & Deals page)
TICKETS = [
    ("Adult admission", "$15 at the gate", "$11 online discount"),
    ("Senior (62+)", "$10 at the gate", ""),
    ("Child (6–12)", "$6 at the gate", "$5 online discount"),
    ("Child (5 & under)", "FREE", ""),
    ("Military (with ID)", "FREE", ""),
    ("Parking", "$10 per day", ""),
    ("Carnival wristband (Mon–Thu)", "$43", "$38 online discount"),
    ("Carnival wristband (Fri–Sun)", "$48", "$38 online discount"),
    ("Family 4-Pack", "$80", "4 adult admissions + 2 parking passes"),
]


def _fmt_date(d: str) -> str:
    import datetime as dt
    day = dt.date.fromisoformat(d)
    # %-d is not portable (fails on Windows); strip the leading zero instead.
    return day.strftime("%A, %B %d").replace(" 0", " ")


def _concert_rows() -> str:
    rows = []
    for d, act in CONCERTS:
        rows.append(
            f'<tr><td class="num">{_fmt_date(d)}</td>'
            f"<td><strong>{common.esc(act)}</strong></td>"
            f'<td class="num">8:00 PM</td></tr>')
    return "\n".join(rows)


def _ticket_rows() -> str:
    rows = []
    for label, gate, note in TICKETS:
        note_html = f'<span class="note">({note})</span>' if note else ""
        rows.append(
            f'<tr><td>{common.esc(label)}</td>'
            f'<td class="num">{common.esc(gate)}</td>'
            f"<td>{note_html}</td></tr>")
    return "\n".join(rows)


def _grandstand_list() -> str:
    return "\n".join(
        f"<li><strong>{common.esc(name)}</strong> — {common.esc(desc)}</li>"
        for name, desc in GRANDSTAND)


def _faq_jsonld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "What are the 2026 Kern County Fair dates?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "The 2026 Kern County Fair runs September 23 through October 4, 2026 at the Kern County Fairgrounds, 1142 South P Street, Bakersfield, CA 93307.",
                },
            },
            {
                "@type": "Question",
                "name": "Who is playing the Kern County Fair in 2026?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("The 2026 Kern County Fair concert series at the Budweiser Pavilion "
                             "includes ERNEST (Sept 23), Collective Soul (Sept 24), Barenaked Ladies "
                             "(Sept 25), Mario (Sept 26), Ezequiel Peña (Sept 27), Gretchen Wilson "
                             "(Sept 28), Chandler Moore (Sept 29), Carly Pearce (Sept 30), Daughtry "
                             "(Oct 1), 90's Rewind (Oct 2), Joe Nichols (Oct 3), and Industria del Amor "
                             "(Oct 4). Concerts start at 8:00 PM and are free with fair admission."),
                },
            },
            {
                "@type": "Question",
                "name": "How much are Kern County Fair tickets 2026?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": ("2026 Kern County Fair admission is $15 for adults at the gate (or $11 "
                             "online), $10 for seniors 62+, $6 for children 6-12 (or $5 online), and "
                             "free for children 5 and under and military with ID. Parking is $10. "
                             "Carnival wristbands are $43 Monday-Thursday and $48 Friday-Sunday "
                             "(or $38 online)."),
                },
            },
            {
                "@type": "Question",
                "name": "Where is the Kern County Fair held?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "The Kern County Fair is held at the Kern County Fairgrounds, 1142 South P Street, Bakersfield, CA 93307.",
                },
            },
        ],
    }


def _events_jsonld() -> list[dict]:
    """One MusicEvent block per concert — strong for concert-lineup rich results."""
    evs = []
    for d, act in CONCERTS:
        evs.append({
            "@context": "https://schema.org",
            "@type": "MusicEvent",
            "name": f"{act} — Kern County Fair 2026",
            "startDate": f"{d}T20:00:00-07:00",
            "location": {
                "@type": "Place",
                "name": "Budweiser Pavilion, Kern County Fairgrounds",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "1142 South P Street",
                    "addressLocality": "Bakersfield",
                    "addressRegion": "CA",
                    "postalCode": "93307",
                },
            },
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "isAccessibleForFree": True,
            "description": f"{act} performs at the Budweiser Pavilion during the 2026 Kern County Fair — free with fair admission.",
            "url": "https://www.kerncountyfair.com/p/things-to-do/concerts",
        })
    return evs


def _fairgrounds_jsonld() -> dict:
    """Local SEO geo markup for the fairgrounds (EventVenue + GeoCoordinates)."""
    return {
        "@context": "https://schema.org",
        "@type": "EventVenue",
        "name": "Kern County Fairgrounds",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "1142 South P Street",
            "addressLocality": "Bakersfield",
            "addressRegion": "CA",
            "postalCode": "93307",
        },
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": FAIR_LAT,
            "longitude": FAIR_LON,
        },
        "url": "https://www.kerncountyfair.com/",
    }


def _breadcrumb_jsonld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home",
             "item": "https://bakersfieldbrief.com/"},
            {"@type": "ListItem", "position": 2, "name": "Kern County Fair 2026",
             "item": "https://bakersfieldbrief.com/fair/"},
        ],
    }


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"

    body = f"""
    <div class="pagehead"><div class="hero">
      <p class="kicker">Kern County Fair 2026</p>
      <h1>Kern County Fair 2026 — Dates, Concerts &amp; Tickets</h1>
      <p class="lede">The 2026 Kern County Fair runs <strong>September 23 &ndash; October 4</strong> at
      the Kern County Fairgrounds in Bakersfield. Twelve nights of headline concerts at the Budweiser
      Pavilion, PRCA rodeo, monster trucks, carnival, and the county&rsquo;s biggest food lineup
      &mdash; all here in one place.</p>
      <div class="meta"><span>Updated <span class="updated">{built_iso}</span></span>
      <span class="dot">&bull;</span><span>Source: kerncountyfair.com</span></div>
    </div></div>

    <div class="stats">
      <div class="stat"><div class="n">Sept 23</div><div class="l">fair opens</div></div>
      <div class="stat amber"><div class="n">Oct 4</div><div class="l">final day</div></div>
      <div class="stat"><div class="n">12</div><div class="l">concert nights</div></div>
      <div class="stat amber"><div class="n">$11</div><div class="l">adult online</div></div>
    </div>

    <div class="card">
      <span class="tag amber">Dates</span>
      <h3>When is the Kern County Fair?</h3>
      <p><strong>September 23 &ndash; October 4, 2026</strong> &mdash; twelve days at the Kern County
      Fairgrounds, <strong>{common.esc(FAIR_ADDRESS)}</strong>.</p>
      <p>Concerts start at <strong>8:00 PM nightly</strong> at the Budweiser Pavilion and are
      <strong>free with fair admission</strong>. See the full lineup below.</p>
    </div>

    <p class="sec-head">2026 Concert lineup <span class="unit">Budweiser Pavilion &middot; 8:00 PM &middot; free with admission</span></p>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Date</th><th>Artist</th><th class="num">Show time</th></tr></thead>
      <tbody>{_concert_rows()}</tbody>
    </table></div>

    <p class="sec-head" style="margin-top:26px">Tickets &amp; admission <span class="unit">from the official fair site</span></p>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Item</th><th class="num">At the gate</th><th>Deal</th></tr></thead>
      <tbody>{_ticket_rows()}</tbody>
    </table></div>
    <p class="note">Buy early online at <a href="https://www.kerncountyfair.com/p/ticketsanddeals" rel="noopener" target="_blank">kerncountyfair.com</a> for the best prices. All prices as published by the fair; no refunds or exchanges.</p>

    <p class="sec-head" style="margin-top:26px">Grandstand &amp; special events</p>
    <div class="card"><ul class="guide-list">{_grandstand_list()}</ul></div>

    <div class="card">
      <span class="tag amber">Plan your visit</span>
      <h3>Fair tips</h3>
      <p>General parking is $10 per day (cash and card accepted). Discounted admission and carnival
      wristbands are available online. The fair is at 1142 South P Street in Bakersfield.</p>
      <p>Official sources: <a href="https://www.kerncountyfair.com/" rel="noopener" target="_blank">kerncountyfair.com</a> &middot;
      <a href="https://www.kerncountyfair.com/events" rel="noopener" target="_blank">events &amp; schedule</a> &middot;
      <a href="https://www.kerncountyfair.com/p/ticketsanddeals" rel="noopener" target="_blank">tickets</a>.</p>
    </div>

    <p class="note">This page is compiled from the official Kern County Fair website and is updated when the fair
    announces changes. Always confirm on kerncountyfair.com before making plans. The Kern County Fair is
    operated by the Kern County Fair Association, not by Bakersfield Daily Brief.</p>"""

    page = page_mod.render(
        title="Kern County Fair 2026 — Dates, Concert Lineup & Tickets | Bakersfield Daily Brief",
        desc="2026 Kern County Fair: Sept 23 – Oct 4 in Bakersfield. Full concert lineup at the Budweiser Pavilion, ticket prices, grandstand events, and FAQ — from the official fair site.",
        canonical="/fair/",
        content=body, current="other", rel=rel, built=built_iso,
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        og_image="https://bakersfieldbrief.com/assets/img/fair.jpg",
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                _breadcrumb_jsonld(),
                _faq_jsonld(), _fairgrounds_jsonld()] + _events_jsonld())
    common.write(common.SITE / "fair" / "index.html", page)
    built.append("fair/index.html")

    ctx.build_report["fair"] = {
        "year": FAIR_YEAR,
        "start": FAIR_START,
        "end": FAIR_END,
        "concerts": len(CONCERTS),
    }
    return built
