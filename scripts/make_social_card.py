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

    Prefer the brief body's own framing ('The night's most serious call came
    just before 1 a.m., when a wrong-way driver...'), which the editorial
    writer chose as the lead. Fall back to the overnight report's 'big one'.
    """
    m = re.search(r"The night[’']s most serious (?:call|incident)", brief)
    if m:
        start = m.start()
        # walk to the first real sentence end, skipping a.m./p.m. abbreviations
        i = start
        while i < len(brief):
            c = brief[i]
            if c in ".!?":
                prev = brief[i - 1] if i > 0 else ""
                nxt = brief[i + 1:i + 2]
                is_abbrev = (c == "." and prev.isalpha() and nxt.isalpha())
                if not is_abbrev:
                    return brief[start:i + 1].strip()
            i += 1
        return brief[start:start + 240].strip()
    m = re.search(r"##\s*The big one\s*\n+(.+?)(?=\n##|\Z)", overnight, re.S)
    if m:
        first = re.split(r"(?<=[.!?])\s+", m.group(1).strip())[0].strip()
        if len(first) > 30:
            return first
    return overnight.strip()[:220]


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


def main() -> int:
    date = (sys.argv[sys.argv.index("--date") + 1]
            if "--date" in sys.argv
            else datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"))
    out_p = (Path(sys.argv[sys.argv.index("--out") + 1])
             if "--out" in sys.argv
             else ROOT / "site" / "assets" / "img" / "social" / f"{date}.png")

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

    dt = datetime.now(ZoneInfo("America/Los_Angeles"))
    headline = headline_for(date)
    serious = most_serious_incident(brief, overnight)
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
