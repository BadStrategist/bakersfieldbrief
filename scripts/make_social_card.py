#!/usr/bin/env python3
"""Generate the daily social card for The Bakersfield Brief (IG + FB).

Deterministic brand card in the site's exact visual language:
cream #FAF6EC, charcoal #232B30, amber #DC9A1F, red #B3472F, Lora serif,
derrick route-shield badge. Rendered fresh each morning with the date,
the top-story headline, and the night's MOST SERIOUS incident.

Usage: python scripts/make_social_card.py [--date YYYY-MM-DD] [--out PATH]
  default out: site/assets/img/social/<date>.png  (deployed with the site)

Never AI-rendered — a template, so it always looks like the brief.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PAPER = (250, 246, 236)      # #FAF6EC
CHARCOAL = (35, 43, 48)      # #232B30
AMBER = (220, 154, 31)       # #DC9A1F
INK_SOFT = (87, 80, 74)      # #57504A
RED = (179, 71, 47)          # #B3472F
WHITE = (255, 255, 255)

W, H = 1080, 1350
FONT = ROOT / "assets" / "fonts" / "ttf" / "Lora-Variable.ttf"


def font(sz: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), sz)


def draw_shield(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Derrick route-shield (the site's masthead mark), radius r at (cx, cy)."""
    s = r / 46.0
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CHARCOAL)

    def X(x: float) -> float:
        return cx + (x - 50) * s * 0.86

    def Y(y: float) -> float:
        return cy + (y - 50) * s * 0.86

    lw = lambda v: max(1, int(v * s * 0.86))  # noqa: E731
    d.line([X(18), Y(89), X(82), Y(89)], fill=AMBER, width=lw(5.5))
    for x1, y1, x2, y2 in [(31, 86, 50, 21), (69, 86, 50, 21)]:
        d.line([X(x1), Y(y1), X(x2), Y(y2)], fill=WHITE, width=lw(4))
    d.rounded_rectangle([X(44.5), Y(15), X(55.5), Y(22)],
                        radius=max(1, int(2 * s * 0.86)), fill=WHITE)
    d.ellipse([X(46.5), Y(7), X(53.5), Y(14)], fill=AMBER)
    for x1, y1, x2, y2 in [(35.7, 70, 59.9, 55), (64.3, 70, 40.1, 55),
                           (44.4, 40, 51.7, 27), (55.6, 40, 48.3, 27)]:
        d.line([X(x1), Y(y1), X(x2), Y(y2)], fill=WHITE, width=lw(3))


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
         max_w: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def most_serious_incident(brief: str, overnight: str) -> str:
    """The night's most serious incident.

    Priority:
    1. The brief's editorial framing ('The night's most serious ...') —
       the writer's own lead, when present.
    2. A wrong-way crash paragraph from the brief's Top stories section
       (fatal crashes are the most serious incident by definition; the
       brief is regenerated daily so the phrasing varies).
    3. The overnight report's '## The big one' section.
    """
    m = re.search(r"The night[’']s most serious (?:call|incident)", brief)
    if m:
        return _walk_to_sentence_end(brief, m.start())
    m = re.search(r"\*\*[^*]*wrong-way[^*]*\*\*[^\n]*", brief)
    if m:
        # Fatal crash: take the whole Top-stories paragraph (bold lead +
        # detail sentences — that's where the vehicles/times/deaths live),
        # stripped of markdown.
        end = brief.find("\n\n", m.start())
        if end == -1:
            end = len(brief)
        return re.sub(r"[*#_]", "", brief[m.start():end]).strip()
    m = re.search(r"##\s*The big one\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    if m:
        first = re.split(r"(?<=[.!?])\s+", m.group(1).strip())[0].strip()
        if len(first) > 30:
            return first
    return overnight.strip()[:220]


def _walk_to_sentence_end(text: str, start: int) -> str:
    """Text from start to the first real sentence end, skipping a.m./p.m."""
    i = start
    while i < len(text):
        c = text[i]
        if c in ".!?":
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1:i + 2]
            is_abbrev = (c == "." and prev.isalpha() and nxt.isalpha())
            if not is_abbrev:
                return text[start:i + 1].strip()
        i += 1
    return text[start:start + 300].strip()


def headline_for(date: str) -> str:
    try:
        entries = json.loads((ROOT / "data" / "briefs_archive.json")
                             .read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "The Bakersfield Brief"
    for e in entries:
        if e.get("date") == date:
            return (e.get("headline") or "").strip() or "The Bakersfield Brief"
    return "The Bakersfield Brief"


# ---------------------------------------------------------------------------
# Reel panels (1080x1920, 9:16) — multi-screen so the 30s reel keeps moving.
# ---------------------------------------------------------------------------

def overnight_full(brief: str) -> str:
    """The full Kern Overnight section paragraph (the night's story in prose)."""
    m = re.search(r"##\s*The Kern Overnight\s*\n+(.+?)(?=\n##|\Z)", brief, re.S)
    if m:
        return re.sub(r"[*#_]", "", m.group(1)).strip()
    return brief.strip()[:400]


def county_bullets(overnight: str, skip: tuple[str, ...] = ("pinned",)) -> list[str]:
    """3-4 scannable bullets from the report's 'Around the county' section,
    skipping anything that duplicates the serious incident (e.g. 'pinned')."""
    m = re.search(r"##\s*Around the county\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    if not m:
        return []
    items = []
    for lead, text in re.findall(r"\*\*(.+?)\*\*\s*([^\n]+)", m.group(1)):
        lead = lead.strip().rstrip(".")
        line = (lead + ". " + text).strip()
        if any(x in line.lower() for x in skip):
            continue
        items.append(line)
    return items[:4]


def weather_line(brief: str) -> str:
    m = re.search(r"##\s*Today's weather\s*\n+(.+?)(?=\n##|\Z)", brief, re.S)
    if m:
        return re.sub(r"[*#_]", "", m.group(1)).strip()
    return ""


def _panel_base(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 14], fill=AMBER)
    return img, d


def _panel_footer(d: ImageDraw.ImageDraw, w: int, h: int,
                  tag: str = "The city talks. We listen.", url: str = "bakersfieldbrief.com") -> None:
    d.rectangle([0, h - 150, w, h], fill=CHARCOAL)
    f = font(32)
    tw = d.textlength(tag, font=f)
    d.text(((w - tw) / 2, h - 118), tag, font=f, fill=PAPER)
    f2 = font(28)
    tw = d.textlength(url, font=f2)
    d.text(((w - tw) / 2, h - 62), url, font=f2, fill=AMBER)


def render_reel_panels(date: str, brief: str, overnight: str,
                       headline: str, serious: str,
                       out_dir: Path) -> list[Path]:
    """Render the 4 reel panels (1080x1920) to out_dir, return their paths."""
    W, H = 1080, 1920
    dt = datetime.now(ZoneInfo("America/Los_Angeles"))
    dateline = dt.strftime("%A, %B %d").upper()
    paths: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Panel 1: front page (shield + dateline + headline) ---
    img, d = _panel_base(W, H)
    draw_shield(d, W // 2, 300, 130)
    f_dl = font(34)
    tw = d.textlength(dateline, font=f_dl)
    d.text(((W - tw) / 2, 520), dateline, font=f_dl, fill=CHARCOAL)
    d.rectangle([W // 2 - 120, 576, W // 2 + 120, 580], fill=AMBER)
    f_t = font(64)
    title = "The Bakersfield Brief"
    tw = d.textlength(title, font=f_t)
    d.text(((W - tw) / 2, 600), title, font=f_t, fill=CHARCOAL)
    f_h = font(52)
    y = 780
    for ln in wrap(d, headline, f_h, W - 140, 6):
        tw = d.textlength(ln, font=f_h)
        d.text(((W - tw) / 2, y), ln, font=f_h, fill=CHARCOAL)
        y += 64
    _panel_footer(d, W, H)
    p1 = out_dir / f"{date}-p1.png"
    img.save(p1)
    paths.append(p1)

    # --- Panel 2: the night's most serious incident (full paragraph) ---
    img, d = _panel_base(W, H)
    label = "THE KERN OVERNIGHT · WHILE YOU SLEPT"
    f_lab = font(34)
    tw = d.textlength(label, font=f_lab)
    d.text(((W - tw) / 2, 130), label, font=f_lab, fill=RED)
    d.rectangle([W // 2 - 120, 186, W // 2 + 120, 190], fill=AMBER)
    f_o = font(40)
    y = 240
    for ln in wrap(d, serious, f_o, W - 150, 16):
        tw = d.textlength(ln, font=f_o)
        d.text(((W - tw) / 2, y), ln, font=f_o, fill=INK_SOFT)
        y += 52
    _panel_footer(d, W, H)
    p2 = out_dir / f"{date}-p2.png"
    img.save(p2)
    paths.append(p2)

    # --- Panel 3: also overnight (scannable county bullets) ---
    img, d = _panel_base(W, H)
    label = "ALSO OVERNIGHT"
    f_lab = font(34)
    tw = d.textlength(label, font=f_lab)
    d.text(((W - tw) / 2, 120), label, font=f_lab, fill=RED)
    d.rectangle([W // 2 - 120, 176, W // 2 + 120, 180], fill=AMBER)
    f_b = font(36)
    y = 230
    for item in county_bullets(overnight):
        for ln in wrap(d, item, f_b, W - 160, 4):
            tw = d.textlength(ln, font=f_b)
            d.text(((W - tw) / 2, y), ln, font=f_b, fill=CHARCOAL)
            y += 44
        y += 30
    _panel_footer(d, W, H)
    p3 = out_dir / f"{date}-p3.png"
    img.save(p3)
    paths.append(p3)

    # --- Panel 4: today's weather + link ---
    img, d = _panel_base(W, H)
    label = "TODAY IN BAKERSFIELD"
    f_lab = font(34)
    tw = d.textlength(label, font=f_lab)
    d.text(((W - tw) / 2, 300), label, font=f_lab, fill=RED)
    d.rectangle([W // 2 - 120, 356, W // 2 + 120, 360], fill=AMBER)
    f_w = font(42)
    y = 440
    for ln in wrap(d, weather_line(brief), f_w, W - 150, 8):
        tw = d.textlength(ln, font=f_w)
        d.text(((W - tw) / 2, y), ln, font=f_w, fill=INK_SOFT)
        y += 56
    f_link = font(40)
    link = "Full brief at bakersfieldbrief.com"
    tw = d.textlength(link, font=f_link)
    d.text(((W - tw) / 2, 1080), link, font=f_link, fill=CHARCOAL)
    _panel_footer(d, W, H)
    p4 = out_dir / f"{date}-p4.png"
    img.save(p4)
    paths.append(p4)

    return paths


def main() -> int:
    date = (sys.argv[sys.argv.index("--date") + 1]
            if "--date" in sys.argv
            else datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"))
    out_p = (Path(sys.argv[sys.argv.index("--out") + 1])
             if "--out" in sys.argv
             else ROOT / "site" / "assets" / "img" / "social" / f"{date}.png")
    reel_dir = (Path(sys.argv[sys.argv.index("--reel-dir") + 1])
                if "--reel-dir" in sys.argv
                else out_p.parent / "reel")

    bp = ROOT / "data" / "briefs" / f"{date}.json"
    op = ROOT / "data" / "overnight_reports" / f"{date}.md"
    if not bp.exists() or not op.exists():
        print(f"SKIP {date}: missing brief body or overnight report — no card")
        return 0
    brief = json.loads(bp.read_text(encoding="utf-8")).get("body", "")
    overnight = op.read_text(encoding="utf-8")
    if len(brief) < 200 or len(overnight) < 300:
        print(f"SKIP {date}: brief/overnight too short — no card")
        return 0

    headline = headline_for(date)
    serious = most_serious_incident(brief, overnight)

    if "--reel-dir" in sys.argv:
        paths = render_reel_panels(date, brief, overnight, headline, serious, reel_dir)
        for p in paths:
            print(f"panel saved: {p}")
        return 0

    dt = datetime.now(ZoneInfo("America/Los_Angeles"))
    dateline = dt.strftime("%A, %B %d").upper()

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=AMBER)

    draw_shield(d, W // 2, 210, 135)
    f_dl = font(34)
    tw = d.textlength(dateline, font=f_dl)
    d.text(((W - tw) / 2, 395), dateline, font=f_dl, fill=CHARCOAL)
    d.rectangle([W // 2 - 120, 448, W // 2 + 120, 452], fill=AMBER)

    f_t = font(62)
    title = "The Bakersfield Brief"
    tw = d.textlength(title, font=f_t)
    d.text(((W - tw) / 2, 470), title, font=f_t, fill=CHARCOAL)

    f_h = font(50)
    y = 620
    for ln in wrap(d, headline, f_h, W - 160, 4):
        tw = d.textlength(ln, font=f_h)
        d.text(((W - tw) / 2, y), ln, font=f_h, fill=CHARCOAL)
        y += 60

    f_lab = font(30)
    label = "THE KERN OVERNIGHT · WHILE YOU SLEPT"
    tw = d.textlength(label, font=f_lab)
    d.text(((W - tw) / 2, y + 20), label, font=f_lab, fill=RED)

    f_o = font(31)
    y += 78
    for ln in wrap(d, serious, f_o, W - 200, 5):
        tw = d.textlength(ln, font=f_o)
        d.text(((W - tw) / 2, y), ln, font=f_o, fill=INK_SOFT)
        y += 42

    d.rectangle([0, H - 150, W, H], fill=CHARCOAL)
    f_f = font(32)
    tag = "The city talks. We listen."
    tw = d.textlength(tag, font=f_f)
    d.text(((W - tw) / 2, H - 118), tag, font=f_f, fill=PAPER)
    f_url = font(28)
    url = "bakersfieldbrief.com"
    tw = d.textlength(url, font=f_url)
    d.text(((W - tw) / 2, H - 62), url, font=f_url, fill=AMBER)

    out_p.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_p)
    print(f"card saved: {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
