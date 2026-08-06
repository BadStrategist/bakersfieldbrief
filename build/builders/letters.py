#!/usr/bin/env python3
"""Letters to the editor — published letters + a submission form.

Submissions POST to FormSubmit (free, keyless) which forwards to
editor@bakersfieldbrief.com; published letters are curated into
data/letters.json and rendered here as the 'letter to the editor' blog."""
from __future__ import annotations

import html
import json

from .. import common
from . import page as page_mod

FORM_EMAIL = "editor@bakersfieldbrief.com"


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"

    letters = []
    try:
        letters = json.loads((common.DATA / "letters.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        letters = []
    letters = [l for l in letters if isinstance(l, dict)]

    if letters:
        items = "".join(f"""
        <article class="letter">
          <p class="letter-meta">{html.escape(l.get('date', ''))} &middot; {html.escape(l.get('name', 'A reader'))}{(' &middot; ' + html.escape(l['topic'])) if l.get('topic') else ''}</p>
          <h2>{html.escape(l.get('topic') or 'Letter')}</h2>
          <p>{html.escape(l.get('body', '')).replace(chr(10), '<br/>')}</p>
        </article>""" for l in letters)
        published = f'<p class="sec-head">Published letters</p><div class="letters">{items}</div>'
    else:
        published = ('<p class="note">No letters published yet — be the first. '
                     'Submissions are read by the editor and the best are published here.</p>')

    form = f"""
    <div class="card">
      <p class="sec-head">Write in</p>
      <form action="https://formsubmit.co/{FORM_EMAIL}" method="POST" class="nl-form letter-form">
        <input type="hidden" name="_subject" value="Letter to the editor — bakersfieldbrief.com"/>
        <input type="hidden" name="_template" value="table"/>
        <input type="text" name="_honey" style="display:none" tabindex="-1" autocomplete="off"/>
        <label>Your name <input type="text" name="name" required placeholder="First Last, neighborhood"/></label>
        <label>Your email (never published) <input type="email" name="email" required/></label>
        <label>Topic <input type="text" name="topic" placeholder="e.g. Flock cameras on Chester Ave"/></label>
        <label>Your letter <textarea name="letter" rows="6" required placeholder="Keep it to about 250 words. Factual, civil, signed — letters may be edited for length and clarity."></textarea></label>
        <button type="submit" class="btn">Send the letter</button>
      </form>
      <p class="note" style="margin-top:8px">Letters go straight to the editor&rsquo;s inbox. Publication is at our discretion; we never publish your email. You can also write to {FORM_EMAIL} directly.</p>
    </div>"""

    body = f"""
    <div class="pagehead"><div class="hero"><p class="kicker">Reader forum</p>
    <h1>Letters to the editor</h1>
    <p class="lede">Kern County readers, on the record. Write in about anything in the brief — the best letters get published here.</p></div></div>
    {published}
    {form}
    <p class="note" style="margin-top:14px">Letters reflect the author&rsquo;s views, not this publication&rsquo;s. We publish civil, signed letters and note corrections to the record per our <a href="{rel}corrections/">corrections policy</a>.</p>"""

    page = page_mod.render(
        title="Letters to the editor | Bakersfield Daily Brief",
        desc="Letters to the editor of Bakersfield Daily Brief: write in about anything in the brief, and read published letters from Kern County readers.",
        canonical="/letters/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld()])
    common.write(common.SITE / "letters" / "index.html", page)
    built.append("letters/index.html")

    ctx.build_report["letters"] = {"published": len(letters)}
    return built
