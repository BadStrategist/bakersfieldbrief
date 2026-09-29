#!/usr/bin/env python3
"""Letters to the editor — an index of published letters, one page per
letter, and a submission form.

Submissions POST to FormSubmit (free, keyless) which forwards to
editor@bakersfieldbrief.com; published letters are curated into
data/letters.json. A letter with a "slug" gets its own page at
/letters/<slug>/ (headline, dek, byline, body, sources, OpinionNewsArticle
JSON-LD). A letter without one is a short reader note shown on the index.

Letter body format (plain text, escaped on render): paragraphs separated by
a blank line, "## " for a subhead, "> " for a pull quote, [text](https://…)
for a link."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from urllib.parse import quote

from .. import common
from . import page as page_mod

FORM_EMAIL = "editor@bakersfieldbrief.com"
BASE = "https://bakersfieldbrief.com"
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_MONTHS = ("Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.",
           "Sept.", "Oct.", "Nov.", "Dec.")


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _ap_date(iso: str) -> str:
    """2026-09-28 -> Sept. 28, 2026 (AP style)."""
    try:
        d = dt.date.fromisoformat(iso)
    except (TypeError, ValueError):
        return _esc(iso)
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def _inline(text: str) -> str:
    return _LINK.sub(lambda m: f'<a href="{m.group(2)}" rel="noopener">{m.group(1)}</a>', _esc(text))


def _plain(text: str) -> str:
    return _LINK.sub(r"\1", text or "")


def _words(text: str) -> int:
    return len(_plain(text).split())


def _read_min(text: str) -> int:
    return max(1, round(_words(text) / 230))


def _body_html(body: str) -> str:
    out, first = [], True
    for block in re.split(r"\n\s*\n", (body or "").strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            out.append(f"<h2>{_inline(block[3:])}</h2>")
        elif block.startswith("> "):
            out.append(f'<blockquote class="op-pull"><p>{_inline(block[2:])}</p></blockquote>')
        else:
            cls = ' class="op-first"' if first else ""
            out.append(f"<p{cls}>{_inline(block)}</p>".replace("\n", "<br/>"))
            first = False
    return "\n".join(out)


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name or "") if p and p[0].isalpha() and not p.endswith(".")]
    return "".join(p[0] for p in (parts[:1] + parts[-1:])).upper() or "BB"


def _load() -> list[dict]:
    try:
        letters = json.loads((common.DATA / "letters.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        letters = []
    letters = [l for l in letters if isinstance(l, dict)]
    return sorted(letters, key=lambda l: l.get("date", ""), reverse=True)


# ------------------------------------------------------------------ one letter
def _article_jsonld(l: dict, url: str) -> dict:
    try:
        stamp = dt.datetime.combine(dt.date.fromisoformat(l["date"]), dt.time(9, 0),
                                    tzinfo=common.PACIFIC).isoformat()
    except (KeyError, ValueError):
        stamp = l.get("date", "")
    author = {"@type": "Person", "name": l.get("name", "")}
    if l.get("author_title"):
        author["jobTitle"] = l["author_title"].split(",")[0].strip()
        if "," in l["author_title"]:
            org = {"@type": "Organization", "name": l["author_title"].split(",", 1)[1].strip()}
            if l.get("author_url"):
                org["url"] = l["author_url"]
            author["worksFor"] = org
    if l.get("author_bio"):
        author["description"] = l["author_bio"]
    block = {
        "@context": "https://schema.org",
        "@type": "OpinionNewsArticle",
        "headline": l.get("headline", ""),
        "description": l.get("description") or l.get("dek", ""),
        "image": [f"{BASE}/assets/img/bakersfield.jpg"],
        "datePublished": stamp,
        "dateModified": stamp,
        "author": author,
        "publisher": {"@type": "NewsMediaOrganization", "name": page_mod.SITE_NAME,
                      "url": f"{BASE}/", "logo": page_mod.publisher_logo()},
        "mainEntityOfPage": url,
        "articleSection": "Letters to the editor",
        "wordCount": _words(l.get("body", "")),
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "contentLocation": {"@type": "Place", "name": "Bakersfield, California"},
    }
    if l.get("topic"):
        block["about"] = l["topic"]
    if l.get("sources"):
        block["citation"] = [{"@type": "CreativeWork", "name": s.get("title", ""),
                              "url": s.get("url", ""),
                              "publisher": {"@type": "Organization", "name": s.get("outlet", "")}}
                             for s in l["sources"] if s.get("url")]
    return block


def _share(url: str, headline: str) -> str:
    u, t = quote(url, safe=""), quote(headline, safe="")
    return f"""
      <div class="op-share" aria-label="Share this letter">
        <span class="op-label">Share</span>
        <button type="button" class="op-share-btn" data-copy="{url}">Copy link</button>
        <a class="op-share-btn" href="https://www.facebook.com/sharer/sharer.php?u={u}" rel="noopener" target="_blank">Facebook</a>
        <a class="op-share-btn" href="https://twitter.com/intent/tweet?url={u}&amp;text={t}" rel="noopener" target="_blank">X</a>
        <a class="op-share-btn" href="mailto:?subject={t}&amp;body={u}">Email</a>
      </div>"""


_COPY_JS = """<script>
document.querySelectorAll('[data-copy]').forEach(function (b) {
  b.addEventListener('click', function () {
    var done = function () { var t = b.textContent; b.textContent = 'Copied'; setTimeout(function () { b.textContent = t; }, 1600); };
    if (navigator.clipboard) { navigator.clipboard.writeText(b.dataset.copy).then(done, function () {}); }
  });
});
</script>"""


def _build_one(ctx, l: dict, built_iso: str) -> str:
    slug = l["slug"]
    rel = "../../"
    canonical = f"/letters/{slug}/"
    url = BASE + canonical
    headline = l.get("headline") or l.get("topic") or "Letter to the editor"
    name = l.get("name", "A reader")
    role = ", ".join(x for x in (l.get("author_title"), l.get("author_place")) if x)
    mins = _read_min(l.get("body", ""))

    summary = ""
    if l.get("summary"):
        items = "".join(f"<li>{_inline(s)}</li>" for s in l["summary"])
        summary = f'<aside class="op-brief"><p class="op-label">The argument in brief</p><ul>{items}</ul></aside>'

    sources = ""
    if l.get("sources"):
        items = "".join(
            f'<li><span class="op-src-outlet">{_esc(s.get("outlet"))}</span>'
            f'<a href="{_esc(s.get("url"))}" rel="noopener">{_esc(s.get("title"))}</a></li>'
            for s in l["sources"] if s.get("url"))
        sources = f'<section class="op-sources"><p class="op-label">Reporting cited in this letter</p><ul>{items}</ul></section>'

    author_link = (f' <a href="{_esc(l["author_url"])}" rel="noopener">{_esc(l["author_url"].split("//")[-1].strip("/"))}</a>'
                   if l.get("author_url") else "")
    about = ""
    if l.get("author_bio"):
        about = f"""
      <section class="op-author">
        <div class="op-avatar" aria-hidden="true">{_initials(name)}</div>
        <div><p class="op-label">About the author</p><p>{_esc(l['author_bio'])}{author_link}</p></div>
      </section>"""

    disclosure = (f'<p class="op-note"><strong>Opinion.</strong> Views are the author&rsquo;s own, not the Brief&rsquo;s. '
                  f'{_esc(l["disclosure"])}</p>') if l.get("disclosure") else (
        '<p class="op-note"><strong>Opinion.</strong> Views are the author&rsquo;s own, not the Brief&rsquo;s.</p>')

    body = f"""
    <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="{rel}">Home</a> &rsaquo; <a href="../">Letters</a> &rsaquo; {_esc(headline)}</nav>
    <article class="op">
      <header class="op-head">
        <p class="op-kicker">{_esc(l.get('kind') or 'Letter to the editor')}{(' &middot; ' + _esc(l['topic'])) if l.get('topic') else ''}</p>
        <h1>{_esc(headline)}</h1>
        {f'<p class="op-dek">{_esc(l["dek"])}</p>' if l.get('dek') else ''}
        <div class="op-byline">
          <div class="op-avatar" aria-hidden="true">{_initials(name)}</div>
          <div class="op-who"><strong>By {_esc(name)}</strong>{f'<span>{_esc(role)}</span>' if role else ''}</div>
        </div>
        <p class="op-meta"><time datetime="{_esc(l.get('date'))}">{_ap_date(l.get('date', ''))}</time> <span aria-hidden="true">&middot;</span> {mins} min read</p>
      </header>
      {disclosure}
      {summary}
      <div class="op-body">
{_body_html(l.get('body', ''))}
      </div>
      <p class="op-end">&mdash; {_esc(name)}{(', ' + _esc(role)) if role else ''}</p>
      {_share(url, headline)}
      {about}
      {sources}
      <section class="op-reply">
        <div><p class="op-label">Your turn</p>
        <h2>Agree? Disagree? Write a letter.</h2>
        <p>The Brief publishes signed, civil letters from Kern County readers. Responses to this piece are welcome.</p></div>
        <a class="op-btn" href="../#write">Write to the editor</a>
      </section>
    </article>"""

    title = l.get("title_tag") or headline
    page = page_mod.render(
        title=f"{title} | Bakersfield Daily Brief",
        desc=l.get("description") or l.get("dek", ""),
        og_title=headline, og_desc=l.get("dek") or l.get("description", ""),
        og_type="article", canonical=canonical, content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, extra_scripts=_COPY_JS,
        extra_head=(f'<meta property="article:published_time" content="{_esc(l.get("date"))}"/>'
                    f'<meta property="article:section" content="Opinion"/>'
                    f'<meta name="author" content="{_esc(name)}"/>'),
        jsonld=[_article_jsonld(l, url)])
    out = f"letters/{slug}/index.html"
    common.write(common.SITE / "letters" / slug / "index.html", page)
    return out


# ------------------------------------------------------------------ index
def _card(l: dict, featured: bool) -> str:
    name = l.get("name", "A reader")
    role = ", ".join(x for x in (l.get("author_title"), l.get("author_place")) if x)
    headline = l.get("headline") or l.get("topic") or "Letter"
    href = f'{l["slug"]}/'
    meta = f'<time datetime="{_esc(l.get("date"))}">{_ap_date(l.get("date", ""))}</time> &middot; {_read_min(l.get("body", ""))} min read'
    if featured:
        return f"""
      <article class="lt-feature">
        <p class="op-kicker">Latest &middot; {_esc(l.get('kind') or 'Letter')}{(' &middot; ' + _esc(l['topic'])) if l.get('topic') else ''}</p>
        <h2><a href="{href}">{_esc(headline)}</a></h2>
        {f'<p class="lt-dek">{_esc(l["dek"])}</p>' if l.get('dek') else ''}
        <div class="op-byline">
          <div class="op-avatar" aria-hidden="true">{_initials(name)}</div>
          <div class="op-who"><strong>{_esc(name)}</strong>{f'<span>{_esc(role)}</span>' if role else ''}</div>
        </div>
        <p class="op-meta">{meta}</p>
        <a class="op-btn" href="{href}">Read the letter</a>
      </article>"""
    return f"""
      <article class="lt-item">
        <p class="op-meta">{meta}</p>
        <h3><a href="{href}">{_esc(headline)}</a></h3>
        <p class="lt-by">{_esc(name)}{(' &middot; ' + _esc(role)) if role else ''}</p>
      </article>"""


def _note(l: dict) -> str:
    """A short reader letter with no page of its own."""
    return f"""
      <article class="lt-item lt-note">
        <p class="op-meta">{_ap_date(l.get('date', ''))}{(' &middot; ' + _esc(l['topic'])) if l.get('topic') else ''}</p>
        <div class="lt-note-body"><p>{_inline(l.get('body', '')).replace(chr(10), '<br/>')}</p></div>
        <p class="lt-by">&mdash; {_esc(l.get('name', 'A reader'))}</p>
      </article>"""


def build(ctx, sources: dict) -> list[str]:
    built = []
    built_iso = common.iso_today()
    rel = "../"
    letters = _load()

    for l in letters:
        if l.get("slug"):
            built.append(_build_one(ctx, l, built_iso))

    if letters:
        first, rest = letters[0], letters[1:]
        lead = _card(first, True) if first.get("slug") else _note(first)
        more = "".join(_card(l, False) if l.get("slug") else _note(l) for l in rest)
        published = lead + (f'<p class="sec-head">More letters</p><div class="lt-list">{more}</div>' if more else "")
    else:
        published = ('<div class="lt-empty"><p>No letters published yet. Be the first: '
                     'every submission is read by the editor.</p></div>')

    form = f"""
    <section class="lt-write" id="write">
      <div class="lt-write-intro">
        <p class="op-kicker">Write to the editor</p>
        <h2>Have something to say about Kern County?</h2>
        <p>Respond to something in the Brief, or raise an issue your neighbors should know about. Every letter goes to the editor&rsquo;s inbox and gets read.</p>
        <ol class="lt-steps">
          <li><strong>Keep it tight.</strong> About 250 words for a letter. Guest opinion pieces can run longer; email us first.</li>
          <li><strong>Stay factual and civil.</strong> No personal attacks. Link or name your sources.</li>
          <li><strong>Sign it.</strong> Your real name and neighborhood or city. We never publish your email.</li>
          <li><strong>We may edit</strong> for length and clarity, never for meaning.</li>
        </ol>
        <p class="lt-alt">Prefer email? <a href="mailto:{FORM_EMAIL}">{FORM_EMAIL}</a></p>
      </div>
      <form action="https://formsubmit.co/{FORM_EMAIL}" method="POST" class="letter-form lt-form">
        <input type="hidden" name="_subject" value="Letter to the editor — bakersfieldbrief.com"/>
        <input type="hidden" name="_template" value="table"/>
        <input type="text" name="_honey" style="display:none" tabindex="-1" autocomplete="off"/>
        <label>Your name <input type="text" name="name" required autocomplete="name" placeholder="First Last, neighborhood"/></label>
        <label>Email <span class="lt-hint">(never published)</span> <input type="email" name="email" required autocomplete="email"/></label>
        <label>Topic <input type="text" name="topic" placeholder="e.g. Flock cameras on Chester Ave"/></label>
        <label>Your letter <textarea name="letter" rows="8" required placeholder="About 250 words. Factual, civil, signed."></textarea></label>
        <button type="submit" class="btn">Send to the editor</button>
      </form>
    </section>"""

    body = f"""
    <div class="pagehead lt-head"><div class="hero"><p class="kicker">Opinion</p>
    <h1>Letters to the editor</h1>
    <p class="lede">Kern County readers and local voices, on the record. Read the latest, then add yours.</p>
    <a class="lt-jump" href="#write">Write a letter &darr;</a></div></div>
    {published}
    {form}
    <p class="note" style="margin-top:24px">Letters and guest opinions reflect their authors&rsquo; views, not this publication&rsquo;s. We publish civil, signed letters and note corrections to the record per our <a href="{rel}corrections/">corrections policy</a>.</p>"""

    blog = {"@context": "https://schema.org", "@type": "CollectionPage",
            "name": "Letters to the editor", "url": f"{BASE}/letters/",
            "isPartOf": {"@type": "WebSite", "name": page_mod.SITE_NAME, "url": f"{BASE}/"},
            "hasPart": [{"@type": "OpinionNewsArticle", "headline": l.get("headline", ""),
                         "url": f"{BASE}/letters/{l['slug']}/", "datePublished": l.get("date", ""),
                         "author": {"@type": "Person", "name": l.get("name", "")}}
                        for l in letters if l.get("slug")]}
    page = page_mod.render(
        title="Letters to the editor | Bakersfield Daily Brief",
        desc="Letters to the editor and guest opinion from Kern County readers in Bakersfield Daily Brief. Read the latest and write in.",
        canonical="/letters/", content=body, current="other", rel=rel,
        built=built_iso, statusbar=ctx.statusbar, jsonld=[page_mod.org_jsonld(), blog])
    common.write(common.SITE / "letters" / "index.html", page)
    built.append("letters/index.html")

    ctx.build_report["letters"] = {"published": len(letters)}
    return built
