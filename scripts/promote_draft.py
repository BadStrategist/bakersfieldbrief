#!/usr/bin/env python3
"""Promote a reviewed recap draft into the live site.

  python scripts/promote_draft.py drafts/recap-<slug>.md

Reads the front-matter (title/meeting/date), renders the markdown body into a
static page at site/city-hall/recaps/<slug>/index.html, and appends the recap
to the City Hall hub. Run it AFTER reviewing the draft.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import common  # noqa: E402
from build.builders import page as page_mod  # noqa: E402

try:
    import markdown as md
except ImportError:
    md = None


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/promote_draft.py drafts/recap-<slug>.md")
        sys.exit(1)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"not found: {src}")
        sys.exit(1)

    raw = src.read_text(encoding="utf-8")
    fm, body = _front_matter(raw)
    title = fm.get("title", src.stem.replace("recap-", "What They Decided — "))
    slug = src.stem.replace("recap-", "")

    if md:
        body_html = md.markdown(body, extensions=["extra"])
    else:
        body_html = "<p>" + "\n".join(body.splitlines()) + "</p>"

    content = f"""
    <div class="pagehead">
      <nav class="breadcrumbs"><a href="../index.html">Daily Brief</a> &rsaquo;
      <a href="../city-hall/">City Hall &amp; County</a> &rsaquo; {title}</nav>
      <div class="hero"><p class="kicker">What They Decided</p>
      <h1>{title}</h1>
      <p class="lede">Post-meeting recap &mdash; reviewed and published from a draft.</p></div>
    </div>
    <div class="prose card">{body_html}</div>"""

    page = page_mod.render(
        title=f"{title} | Bakersfield Daily Brief",
        desc=f"Post-meeting recap: {title}.",
        canonical=f"/city-hall/recaps/{slug}/",
        content=content, current="cityhall", rel="../../",
        built=common.iso_today(),
        jsonld=[page_mod.org_jsonld()])
    out = common.SITE / "city-hall" / "recaps" / slug / "index.html"
    common.write(out, page)
    print(f"published: {out}")
    print("review the page, then commit + push (the deploy workflow publishes it).")


def _front_matter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    if not m:
        return {}, raw
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, m.group(2)


if __name__ == "__main__":
    main()
