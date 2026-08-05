#!/usr/bin/env python3
"""Static pages: about, privacy, contact, stub sections (work-money,
sunday-read), 404. Substantial original copy — AdSense compliance requires
every template to carry real editorial content, never thin/scraped pages.
"""
from __future__ import annotations

import html

from .. import common
from . import page as page_mod


def build(ctx, sources: dict) -> list[str]:
    built_iso = common.iso_today()
    built = []

    # ---------------------------------------------------------- about
    body = """
    <div class="pagehead"><div class="hero"><p class="kicker">About</p>
    <h1>About Bakersfield Daily Brief</h1>
    <p class="lede">A free, automated civic news brief for Bakersfield and Kern County — built
    from public records every morning, edited by software, reviewed by a human.</p></div></div>
    <div class="prose">
      <h2>What this is</h2>
      <p>Bakersfield Daily Brief is a daily digest of local civic information: the morning&rsquo;s
      conditions, the day&rsquo;s local news headlines, and the most notable item on the public
      meeting calendar. It covers the City of Bakersfield, Kern County, and the surrounding
      valley &mdash; the communities along State Route 99 from Wheeler Ridge to the Kern River
      Canyon.</p>
      <h2>How it works</h2>
      <p>Every morning at 6:00 AM Pacific, a build pipeline fetches data from the agencies that
      publish it: the City of Bakersfield&rsquo;s meeting system (eSCRIBE), the Kern County Board
      of Supervisors&rsquo; official agenda, the California Department of Alcoholic Beverage
      Control, Kern County Environmental Health, the California Highway Patrol, the National
      Weather Service, the EPA (AirNow), the California Data Exchange Center, and
      OpenStreetMap. The data is checked, summarized, and baked into static pages &mdash; there
      is no database and no live data connection on this site.</p>
      <h2>What we publish &mdash; and what we don&rsquo;t</h2>
      <p>We publish <strong>headlines with links</strong> to the original reporting (we never
      republish article text), <strong>factual summaries</strong> of public agendas and records,
      and <strong>data trackers</strong> with clear sourcing. We deliberately do not cover crime
      bookings or sports, and we do not take positions on ballot measures, candidates, or policy.
      When we make a mistake, we correct it openly &mdash; email the contact address below.</p>
      <h2>Independence &amp; funding</h2>
      <p>This site is independent and reader-funded by display advertising. Ads are clearly
      labeled, shown only with your consent, and never placed inside content in a way that
      could be mistaken for reporting. No agency, advertiser, or official controls the content
      of the brief.</p>
      <h2>Who runs it</h2>
      <p>Bakersfield Daily Brief is an automated publication with human editorial review.
      Automation drafts; a human reviews meeting recaps before they publish and stands behind
      the corrections policy.</p>
    </div>"""
    common.write(common.SITE / "about" / "index.html", page_mod.render(
        title="About — how the Brief works, what we publish | Bakersfield Daily Brief",
        desc="How Bakersfield Daily Brief works: an independent, automated civic news brief for Bakersfield and Kern County, built from public records, funded by labeled, consent-based ads.",
        canonical="/about/", content=body, current="other", rel="../",
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld()]))
    built.append("about/index.html")

    # ---------------------------------------------------------- privacy
    body = """
    <div class="pagehead"><div class="hero"><p class="kicker">Privacy</p>
    <h1>Privacy Policy</h1>
    <p class="lede">Short version: this site is static, stores nothing about you on its own
    servers, and shows ads only with your consent.</p></div></div>
    <div class="prose">
      <h2>What this site collects</h2>
      <p>Bakersfield Daily Brief is a static website hosted on GitHub Pages. It has no accounts,
      no comments, no login, and no server-side tracking of its own. We do not collect names,
      email addresses, or any personal information through this site.</p>
      <h2>Advertising</h2>
      <p>This site is funded by display advertising served by Google AdSense. Ads render only
      after you accept the consent prompt, which we show because Google&rsquo;s advertising
      partners may use cookies or device identifiers to serve and measure ads. If you decline,
      no ad scripts load at all. You can change your choice at any time by clearing this site&rsquo;s
      local storage in your browser.</p>
      <p>Google&rsquo;s use of advertising cookies is described in Google&rsquo;s Privacy &amp;
      Terms and the <a href="https://policies.google.com/technologies/partner-sites">Advertising
      cookies policy</a>. You can opt out of personalized advertising at
      <a href="https://adssettings.google.com">Google Ad Settings</a>.</p>
      <h2>Third-party data we display</h2>
      <p>Everything we display comes from public agencies. When you follow a link to a source
      (a news outlet, an agency, a map), that site&rsquo;s own privacy policy applies. The
      interactive map loads tiles from CARTO and OpenStreetMap; their privacy practices are
      governed by their policies. We do not receive any data back from those services through
      this site.</p>
      <h2>Analytics</h2>
      <p>We may add privacy-respecting, cookieless analytics in the future. If we do, this
      policy will be updated and the tool will be disclosed here.</p>
      <h2>Children</h2>
      <p>This site does not target children under 13 and does not knowingly collect any
      information from them.</p>
      <h2>Contact</h2>
      <p>Privacy questions: use the <a href="../contact/">contact page</a>. We respond to
      privacy inquiries within 30 days.</p>
      <p class="note">Last updated: <strong>August 4, 2026</strong>.</p>
    </div>"""
    common.write(common.SITE / "privacy" / "index.html", page_mod.render(
        title="Privacy Policy | Bakersfield Daily Brief",
        desc="Privacy policy for Bakersfield Daily Brief: a static site with no accounts or server-side tracking; consent-based ads; disclosures for third-party data we display.",
        canonical="/privacy/", content=body, current="other", rel="../",
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()]))
    built.append("privacy/index.html")

    # ---------------------------------------------------------- contact
    body = """
    <div class="pagehead"><div class="hero"><p class="kicker">Contact</p>
    <h1>Contact the Brief</h1>
    <p class="lede">Corrections, questions about a source, or feedback on the site.</p></div></div>
    <div class="prose">
      <h2>Email</h2>
      <p>Write to <a href="mailto:editor@bakersfieldbrief.com">editor@bakersfieldbrief.com</a>.
      We read everything; automation drafts, a human replies.</p>
      <h2>Corrections</h2>
      <p>If a headline, agenda item, or data point looks wrong, tell us what you saw and what
      you expected. Corrections are posted on the affected page and noted in the next daily brief.</p>
      <h2>Source tips</h2>
      <p>Know a public dataset that belongs in the brief? We&rsquo;re especially interested in
      anything the county and city publish as open data.</p>
      <h2>Business</h2>
      <p>Advertising and partnership inquiries: same address, subject line &ldquo;Advertising&rdquo;.
      Ad placements are labeled and never influence editorial content.</p>
    </div>"""
    common.write(common.SITE / "contact" / "index.html", page_mod.render(
        title="Contact | Bakersfield Daily Brief",
        desc="Contact Bakersfield Daily Brief: corrections, source tips, and questions about the automated civic brief for Bakersfield and Kern County.",
        canonical="/contact/", content=body, current="other", rel="../",
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()]))
    built.append("contact/index.html")

    # ---------------------------------------------------------- stub sections
    for slug, name, lede, copy in [
        ("work-money", "Work & Money",
         "Kern County jobs, wages, and the local economy.",
         "<p>This section is on the roadmap. Planned coverage: Kern County unemployment and "
         "labor-market data from EDD, local minimum-wage and cost-of-living notes, and major "
         "employer news with links to original reporting.</p>"),
        ("sunday-read", "The Sunday Read",
         "A weekly newsletter-length look at one Kern County story.",
         "<p>The Sunday Read is a planned weekly newsletter-format piece: one long, sourced "
         "look at a Kern County topic, assembled from public records and linked reporting. "
         "Until it launches, the daily brief is the place to be.</p>"),
    ]:
        body = f"""
        <div class="pagehead"><div class="hero"><p class="kicker">Coming soon</p>
        <h1>{html.escape(name)}</h1>
        <p class="lede">{html.escape(lede)}</p></div></div>
        <div class="card">{copy}</div>"""
        common.write(common.SITE / slug / "index.html", page_mod.render(
            title=f"{name} — coming soon | Bakersfield Daily Brief",
            desc=f"{lede} Coming soon on Bakersfield Daily Brief.",
            canonical=f"/{slug}/", content=body, current=slug.replace("-", ""), rel="../",
            built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()]))
        built.append(f"{slug}/index.html")

    # ---------------------------------------------------------- 404
    body = """
    <div class="hero"><p class="kicker">404</p>
    <h1>Off-ramp not found</h1>
    <p class="lede">That page doesn&rsquo;t exist &mdash; maybe it moved, or the brief rebuilt
    and the URL changed.</p></div>
    <div class="card"><p>Try the <a href="index.html">Daily Brief</a>, the
    <a href="city-hall/">City Hall &amp; County</a> section, or the
    <a href="trackers/">trackers</a>.</p></div>"""
    common.write(common.SITE / "404.html", page_mod.render(
        title="Page not found | Bakersfield Daily Brief",
        desc="404 — this page does not exist on Bakersfield Daily Brief.",
        canonical="/404.html", content=body, current="other", rel="",
        built=built_iso, statusbar=ctx.statusbar, jsonld=[]))
    built.append("404.html")

    # ---------------------------------------------------------- ads.txt
    # Placeholder until AdSense approval — replace with the real pub ID.
    (common.SITE / "ads.txt").write_text(
        "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0\n",
        encoding="utf-8")
    built.append("ads.txt")

    ctx.build_report["static"] = {"pages": built}
    return built
