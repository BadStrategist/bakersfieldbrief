#!/usr/bin/env python3
"""
render_reel.py — turn brief.json into a 30-second 1080x1920 reel (MP4, music mixed in)
and a 1080x1350 still card (PNG) for feed/carousel posts.

Usage:
    python render_reel.py brief.json                 # -> out/reel.mp4, out/card.png
    python render_reel.py brief.json --out out/mon   # -> out/mon.mp4, out/mon.png
    python render_reel.py brief.json --no-card
    python render_reel.py brief.json --duration 30 --fps 24

Requires: Python 3.9+, Pillow, numpy, ffmpeg on PATH. Nothing else. No network.
Backgrounds: set "backgrounds": "auto" | "none" | "<scene>" in brief.json; per-story "scene" or "image" override.
See README.md for the JSON schema and how to drive it from cron / another LLM.
"""
import argparse, json, os, re, subprocess, sys, shutil

from PIL import Image, ImageDraw, ImageFont
import backgrounds as BG

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(HERE, "fonts", "Lora-Variable.ttf")

W, H = 1080, 1920
# A scene shorter than this cannot be read: the headline lands at 0.5 s,
# the subhead at 1.5 s and the place box at 2.1 s, so the reader needs the
# card to hold well past 2.1 s. Operator rule 2026-09-20: reels run about
# 30 s, never under 25, and scenes never flip faster than a reader reads.
MIN_CARD = 6.0
CREAM = (250, 246, 236)
INK = (38, 43, 48)
GOLD = (214, 158, 30)
RED = (170, 66, 44)
GREY = (110, 112, 115)


# ---------- helpers ----------
def font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f

F = dict(
    mast=font(84, 500), date=font(40, 500), head=font(78, 600), kick=font(36, 600),
    sub=font(42, 400), meta=font(46, 600), meta2=font(36, 500), tag=font(50, 500),
    url=font(44, 600), num=font(30, 600), brand_sm=font(38, 500),
)

def ease(x):
    x = max(0.0, min(1.0, x)); return x * x * (3 - 2 * x)

def prog(t, a, b):
    return ease((t - a) / (b - a)) if b > a else 1.0

def wrap(d, txt, f, maxw):
    words, lines, cur = txt.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= maxw:
            cur = test
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    return lines

def text_c(im, d, y, txt, f, fill, alpha=1.0, dy=0):
    if alpha <= 0:
        return
    if alpha >= 1:
        w = d.textlength(txt, font=f); d.text(((W - w) / 2, y + dy), txt, font=f, fill=fill); return
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    w = od.textlength(txt, font=f)
    od.text(((W - w) / 2, y + dy), txt, font=f, fill=fill + (int(255 * alpha),))
    im.alpha_composite(ov)

def draw_logo(im, cx, cy, r, alpha=1.0):
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=INK)
    s = r / 135.0
    top = (cx, cy - 92 * s); bl = (cx - 52 * s, cy + 78 * s); br = (cx + 52 * s, cy + 78 * s)
    d.line([bl, top], fill="white", width=int(10 * s)); d.line([br, top], fill="white", width=int(10 * s))
    for k, yy in enumerate([-30, 12, 50]):
        y = cy + yy * s; hw = (26 + k * 13) * s
        d.line([(cx - hw, y), (cx + hw, y)], fill="white", width=int(7 * s))
    d.line([(cx - 40 * s, cy + 40 * s), (cx + 40 * s, cy - 10 * s)], fill="white", width=int(6 * s))
    d.line([(cx + 40 * s, cy + 40 * s), (cx - 40 * s, cy - 10 * s)], fill="white", width=int(6 * s))
    d.rectangle([cx - 70 * s, cy + 78 * s, cx + 70 * s, cy + 94 * s], fill=GOLD)
    d.rectangle([cx - 9 * s, cy - 104 * s, cx + 9 * s, cy - 88 * s], fill="white")
    d.ellipse([cx - 11 * s, cy - 124 * s, cx + 11 * s, cy - 102 * s], fill=GOLD)
    if alpha < 1:
        ov.putalpha(ov.getchannel("A").point(lambda p: int(p * alpha)))
    im.alpha_composite(ov)

def fade_over(im, color, a):
    if a > 0:
        im.alpha_composite(Image.new("RGBA", im.size, color + (int(255 * a),)))


# ---------- scenes ----------
def lead_card(im, d, cfg, s, total, tl, card_len, fade_out=True, idx=0, sub_lines=4):
    """The night card. Story 1 is the cold opener, and with "style": "night" every
    story uses it. Time, event and place are COMPLETE FROM FRAME 0 (frame 0 is
    the thumbnail), all of it above the bottom 35 percent that the caption bar
    covers. What moves in the first second is the live dot, the rule and the
    subhead, which arrives a word at a time. With read-along captions the
    subhead is held to two lines so the caption panel has room above that 35%."""
    C_HEAD, C_SUB = CREAM, (235, 230, 220)
    text_c(im, d, 150, cfg["kicker"], F["kick"], (196, 90, 66))
    text_c(im, d, 205, f"{idx + 1} / {total}", F["num"], (200, 195, 185))

    y = 300
    when = s.get("time", "")
    if when:
        fw = font(64, 600)
        tw = d.textlength(when, font=fw)
        x0 = (W - tw) / 2 + 26
        d.text((x0, y), when, font=fw, fill=GOLD)
        # Live dot: pulses about once a second so the frame is never still.
        r = 13 + 4 * abs(((tl * 1.1) % 1.0) * 2 - 1)
        d.ellipse([x0 - 52 - r, y + 44 - r, x0 - 52 + r, y + 44 + r], fill=(214, 72, 48))
        y += 104

    label = s.get("label") or s["headline"]
    size = 124
    while size > 72 and len(wrap(d, label, font(size, 700), 960)) > 2:
        size -= 8
    fl = font(size, 700)
    for ln in wrap(d, label, fl, 960):
        text_c(im, d, y, ln, fl, C_HEAD)
        y += int(size * 1.12)
    where = s.get("where", "") if s.get("label") else ""
    if where:
        y += 14
        fw2 = font(58, 500)
        for ln in wrap(d, where, fw2, 940):
            text_c(im, d, y, ln, fw2, GOLD)
            y += 72

    rw = int(300 * prog(tl, 0.0, 0.5))
    if rw > 0:
        d.line([(W / 2 - rw / 2, y + 30), (W / 2 + rw / 2, y + 30)], fill=GOLD, width=5)

    # Subhead: one word every 1/14 s from 0.25 s, each line laid out at its
    # full width so no word moves once it is drawn.
    # Fit the subhead WHOLE into the room it has: above the caption panel when
    # there are captions, above the bottom 35% otherwise. Try smaller sizes, then
    # drop trailing sentences; never cut a sentence partway ("...and was gone
    # when", 2026-10-20) and never draw under the panel.
    yy = y + 78
    limit = (CAP_Y - 28) if cfg.get("captions") else H * 0.65
    sentences = re.split(r"(?<=[.!?])\s+", (s.get("subhead") or "").strip())
    fs, lines, lh = None, [], 0
    while sentences and fs is None:
        text = " ".join(sentences)
        for size in (50, 46, 42):
            f_try = font(size, 400)
            ls = wrap(d, text, f_try, 900)
            step = int(size * 1.28)
            if len(ls) <= sub_lines and yy + len(ls) * step <= limit:
                fs, lines, lh = f_try, ls, step
                break
        if fs is None:
            sentences = sentences[:-1]
    shown = int(max(0.0, tl - 0.25) * 14)
    for ln in lines:
        words = ln.split()
        if shown <= 0:
            break
        x = (W - d.textlength(ln, font=fs)) / 2
        d.text((x, yy), " ".join(words[:shown]), font=fs, fill=C_SUB)
        shown -= len(words)
        yy += lh
    if fade_out:
        fade_over(im, (0, 0, 0), prog(tl, card_len - 0.5, card_len))


def story_card(im, d, cfg, s, idx, total, tl, card_len, dark=False, fade_out=True):
    C_HEAD = CREAM if dark else INK
    C_SUB = (215, 210, 200) if dark else GREY
    C_KICK = (196, 90, 66) if dark else RED
    C_NUM = (200, 195, 185) if dark else GREY
    a = prog(tl, 0.0, 0.5)
    text_c(im, d, 150, cfg["kicker"], F["kick"], C_KICK, a)
    text_c(im, d, 205, f"{idx + 1} / {total}", F["num"], C_NUM, a)
    lines = wrap(d, s["headline"], F["head"], 900)
    y = 330
    for i, ln in enumerate(lines):
        la = prog(tl, 0.15 + i * 0.18, 0.5 + i * 0.18)
        text_c(im, d, y, ln, F["head"], C_HEAD, la, dy=int((1 - la) * 24))
        y += 96
    n = len(lines)
    ra = prog(tl, 0.7, 1.0)
    if ra > 0:
        rw = int(300 * ra); d.line([(W / 2 - rw / 2, y + 30), (W / 2 + rw / 2, y + 30)], fill=GOLD, width=5)
    sa = prog(tl, 0.95, 1.5)
    for j, ln in enumerate(wrap(d, s.get("subhead", ""), F["sub"], 880)):
        text_c(im, d, y + 80 + j * 56, ln, F["sub"], C_SUB, sa)
    if s.get("time") or s.get("place"):
        ma = prog(tl, 1.6, 2.1)
        if ma > 0:
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
            by = 1180 + int((1 - ma) * 40)
            if dark:
                od.rounded_rectangle([140, by, W - 140, by + 220], radius=22, fill=(20, 22, 26, int(215 * ma)), outline=(255, 255, 255, int(40 * ma)), width=2)
            else:
                od.rounded_rectangle([140, by, W - 140, by + 220], radius=22, fill=INK + (int(235 * ma),))
            od.text((190, by + 42), s.get("time", ""), font=F["meta"], fill=(255, 255, 255, int(255 * ma)))
            # Place label: shrink to fit, then wrap. It must never run off the
            # frame edge or collide with the marker icon at x ~ 850.
            pl = s.get("place", "")
            pf, maxw = 36, 600
            while pf > 22 and od.textlength(pl, font=font(pf, 500)) > maxw:
                pf -= 2
            fpl = font(pf, 500)
            if od.textlength(pl, font=fpl) <= maxw:
                od.text((190, by + 120), pl, font=fpl, fill=GOLD + (int(255 * ma),))
            else:
                ws = pl.split()
                mid = (len(ws) + 1) // 2
                l1, l2 = " ".join(ws[:mid]), " ".join(ws[mid:])
                while mid > 1 and (od.textlength(l1, font=fpl) > maxw or od.textlength(l2, font=fpl) > maxw):
                    mid -= 1
                    l1, l2 = " ".join(ws[:mid]), " ".join(ws[mid:])
                od.text((190, by + 96), l1, font=fpl, fill=GOLD + (int(255 * ma),))
                od.text((190, by + 100 + pf), l2, font=fpl, fill=GOLD + (int(255 * ma),))
            px, py = W - 230, by + 110
            od.ellipse([px - 26, py - 46, px + 26, py + 6], outline=GOLD + (int(255 * ma),), width=6)
            od.polygon([(px - 24, py - 10), (px + 24, py - 10), (px, py + 40)], fill=GOLD + (int(255 * ma),))
            od.ellipse([px - 10, py - 30, px + 10, py - 10], fill=INK + (int(255 * ma),))
            im.alpha_composite(ov)
    if fade_out:
        fade_over(im, (0, 0, 0) if dark else CREAM, prog(tl, card_len - 0.5, card_len))


CAP_FONT_PATH = os.path.join(HERE, "fonts", "Inter-Variable.ttf")


def cap_font(size, weight=600):
    f = ImageFont.truetype(CAP_FONT_PATH, size)
    try:
        f.set_variation_by_axes([min(32, size), weight])
    except Exception:
        pass
    return f


CAP_Y, CAP_H = 1000, 236          # panel ends at 1236, above the bottom 35% (1248)
CAP_LABEL = cap_font(26, 700)
CAP_TEXT = cap_font(46, 640)
CAP_LINES, CAP_MAXW = 2, W - 2 * 130
_CAP_MEASURE = ImageDraw.Draw(Image.new("RGBA", (8, 8)))


def caption_lines(texts, f=CAP_TEXT):
    """The panel's line layout for one cue: [[(index, width), ...], ...]. build_captions
    cuts its cues with this same measure, so a cue always fits in CAP_LINES lines."""
    sp = _CAP_MEASURE.textlength(" ", font=f)
    lines, cur, cw = [], [], 0.0
    for k, txt in enumerate(texts):
        ww = _CAP_MEASURE.textlength(txt, font=f)
        if cur and cw + sp + ww > CAP_MAXW:
            lines.append(cur); cur, cw = [], 0.0
        cur.append((k, ww)); cw += (sp if cw else 0) + ww
    if cur:
        lines.append(cur)
    return lines


def caption_panel(im, cfg, t):
    """Read-along captions for the scanner audio: the words of the clip under
    this scene, a phrase at a time, karaoke style. Spoken words are white, the
    word being said is gold, words still to come are dim, so a viewer with the
    sound off can follow the radio. Cues come from build_captions.py, which
    times them to the mixed soundtrack and blanks anything the report's privacy
    rules forbid (house numbers, plates, phone numbers) before they get here."""
    cues = cfg.get("captions") or []
    cue = next((c for c in cues if c["s"] - 0.15 <= t <= c["e"] + 0.45), None)
    if cue is None:
        return
    a = min(prog(t, cue["s"] - 0.15, cue["s"] + 0.1), 1.0 - prog(t, cue["e"] + 0.2, cue["e"] + 0.45))
    if a <= 0:
        return
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    od.rounded_rectangle([90, CAP_Y, W - 90, CAP_Y + CAP_H], radius=26,
                         fill=(10, 12, 15, int(215 * a)), outline=GOLD + (int(90 * a),), width=2)
    # Label: a red "on air" dot and SCANNER AUDIO, so nobody reads the radio as our words.
    od.ellipse([130, CAP_Y + 34, 146, CAP_Y + 50], fill=(214, 72, 48, int(255 * a)))
    od.text((160, CAP_Y + 26), "SCANNER AUDIO", font=CAP_LABEL, fill=(214, 180, 120, int(255 * a)))
    # Lay the words out once (no word moves while it is on screen), two lines max.
    # A cue that needs a third line (one not cut by build_captions) is drawn
    # smaller, never cut: lines[:2] used to drop its last words without a trace.
    words, x0, y = cue["words"], 130, CAP_Y + 82
    f, size = CAP_TEXT, 46
    lines = caption_lines([wd["w"] for wd in words], f)
    while len(lines) > CAP_LINES and size > 34:
        size -= 2
        f = cap_font(size, 640)
        lines = caption_lines([wd["w"] for wd in words], f)
    sp = od.textlength(" ", font=f)
    for ln in lines:
        x = x0
        for k, ww in ln:
            wd = words[k]
            if t >= wd["e"]:
                col = (248, 245, 238)
            elif t >= wd["s"]:
                col = GOLD
            else:
                col = (130, 134, 138)
            if wd.get("redacted"):
                col = (150, 120, 70)
            od.text((x, y), wd["w"], font=f, fill=col + (int(255 * a),))
            x += ww + sp
        y += 64 if len(lines) <= CAP_LINES else int(128 / len(lines))
    im.alpha_composite(ov)


_BG_CACHE = {}


def scene_of(cfg, s):
    """Scene name for a story: the brief's scene when it carries one, otherwise
    picked from the headline words. An unmapped incident type leaves the scene
    empty (make_brief_json no longer writes the default), which is what stopped
    every unmapped story showing the same library image."""
    mode = cfg.get("backgrounds", "auto")   # "auto" | "none" | a scene name
    scene = (s.get("scene") or "").strip()
    if not scene:
        scene = BG.pick_scene(s["headline"] + " " + s.get("subhead", "")) if mode == "auto" else mode
    return scene or "city"


def story_bg(cfg, s, k):
    """Return treated background for story s (or None for the flat cream card)."""
    mode = cfg.get("backgrounds", "auto")   # "auto" | "none" | a scene name
    if mode == "none" and not s.get("image") and not s.get("scene"):
        return None
    scene = scene_of(cfg, s)
    key = (k, s.get("image"), scene, mode)
    if key not in _BG_CACHE:
        _BG_CACHE[key] = BG.load_or_make(scene, s.get("image"), seed=k)
    return _BG_CACHE[key]


def bg_variant(bg, k):
    """Per-story treatment. Adjacent stories can share a scene (two fire
    stories) and the library holds ONE image per scene, so without this the
    same picture shows twice running and reads as a flash. Alternate stories
    get a mirror and a slightly different crop scale."""
    im = bg
    if k % 2:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    z = 1.12 if k % 2 == 0 else 1.20
    return im.resize((int(im.width * z), int(im.height * z)), Image.LANCZOS)


def bg_at(bg, tl, card_len):
    """Ken Burns window: a slow drift across the card so the background is
    never a frozen image that pops on and off."""
    if bg.width <= W or bg.height <= H:
        return bg
    p = 0.0 if card_len <= 0 else max(0.0, min(1.0, tl / card_len))
    x0 = int((bg.width - W) * p)
    # A diagonal move: a horizontal-only pan is invisible on a scene whose
    # bright detail sits low (the fire glow), so the window also travels up.
    y0 = int((bg.height - H) * (0.18 + 0.64 * p))
    return bg.crop((x0, y0, x0 + W, y0 + H))



def frame(t, cfg, dur):
    stories = cfg["stories"]
    intro, outro = 1.0, 4.0
    card_len = (dur - intro - outro) / max(1, len(stories))
    if card_len < MIN_CARD:
        raise SystemExit(
            f"FATAL {len(stories)} stories in {dur:.0f}s leaves {card_len:.1f}s per "
            f"scene; the floor is {MIN_CARD:.1f}s (all text is on screen by "
            f"2.1s). Drop a story or lengthen the soundtrack.")

    scenes = [scene_of(cfg, s) for s in stories]
    first = {}
    for i, sc in enumerate(scenes):
        first.setdefault(sc, i)

    im = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=(232, 224, 205))
    d.rectangle([0, 0, int(W * t / dur), 14], fill=GOLD)
    # No bottom URL band: the bottom 35% of a 9:16 surface is covered by the
    # caption bar, the audio chip and the story reply box. The URL ships once,
    # in the outro, and lives in the caption every time.

    # "hook": "cold" in brief.json: no title card. Story 1 opens the reel on its
    # own background and keeps the intro second, so every later card and the
    # soundtrack stay exactly where they were.
    cold = cfg.get("hook") == "cold"

    def start(n):
        return 0.0 if (cold and n == 0) else intro + card_len * n

    if t < intro and not cold:
        # 1 second title flash, COMPLETE FROM FRAME 0. The first frame of a video
        # is its thumbnail in every preview surface (chat, file browser, social),
        # and the original fade-in drew frame 0 at alpha 0: bare cream with a top
        # bar, which is the "blank card" bug. So the card is drawn at full alpha
        # from t=0 and held for the whole intro, then fades to story 1 as before.
        # Duration is unchanged, so the soundtrack stays in sync.
        draw_logo(im, W / 2, 660, 150)
        text_c(im, d, 880, cfg["date_label"], F["date"], INK)
        d.line([(W / 2 - 110, 944), (W / 2 + 110, 944)], fill=GOLD, width=5)
        text_c(im, d, 990, cfg["brand"], F["mast"], INK)
        text_c(im, d, 1120, cfg["kicker"], F["kick"], RED)
        y = 1240
        for ln in wrap(d, stories[0]["headline"], font(66, 600), 900):
            text_c(im, d, y, ln, font(66, 600), INK)
            y += 84
        fade_over(im, CREAM, prog(t, 0.72, 1.0))
    elif t < dur - outro:
        k = max(0, min(len(stories) - 1, int((t - intro) // card_len)))
        tl = t - start(k); this_len = start(k + 1) - start(k)
        # Two stories in a row with the same scene are ONE continuous shot: same
        # variant, the drift keeps running and there is no fade to black between
        # them. Fading between two copies of the same picture is what read as
        # "flashing the same image".
        kk = first[scenes[k]]
        same_next = k + 1 < len(stories) and scenes[k + 1] == scenes[k]
        # One continuous shot: the drift spans the whole run of same-scene cards,
        # so the picture keeps moving instead of freezing at the panned edge.
        group = 1
        while kk + group < len(stories) and scenes[kk + group] == scenes[kk]:
            group += 1
        bg = story_bg(cfg, stories[k], kk)
        dark = bg is not None
        if dark:
            im.paste(bg_at(bg_variant(bg, kk), t - start(kk),
                           start(kk + group) - start(kk)), (0, 0))
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, W, 14], fill=(60, 55, 45)); d.rectangle([0, 0, int(W * t / dur), 14], fill=GOLD)
            # (bottom URL band removed: unusable on every 9:16 surface)
        draw_logo(im, 92, 90, 46)
        d.text((155, 66), cfg["brand"], font=F["brand_sm"], fill=CREAM if dark else INK)
        night = cfg.get("style") == "night"
        if dark and ((cold and k == 0) or night):
            lead_card(im, d, cfg, stories[k], len(stories), tl, this_len,
                      fade_out=not same_next, idx=k,
                      sub_lines=2 if cfg.get("captions") else 4)
        else:
            story_card(im, d, cfg, stories[k], k, len(stories), tl, this_len, dark=dark,
                       fade_out=not same_next)
        caption_panel(im, cfg, t)
    else:
        tl = t - (dur - outro)
        draw_logo(im, W / 2, 700, 170, prog(tl, 0.0, 0.8))
        text_c(im, d, 950, cfg["tagline"], F["tag"], INK, prog(tl, 0.5, 1.2))
        text_c(im, d, 1040, "Full brief every morning at", F["sub"], GREY, prog(tl, 1.0, 1.7))
        text_c(im, d, 1100, cfg["url"], F["url"], GOLD, prog(tl, 1.0, 1.7))
        text_c(im, d, 1230, cfg.get("cta", ""), F["kick"], RED, prog(tl, 1.8, 2.4))
        fade_over(im, (0, 0, 0), prog(tl, outro - 0.8, outro))
    return im.convert("RGB")


def still_card(cfg):
    """1080x1350 static card matching the original design (headline first, then brand)."""
    CW, CH = 1080, 1350
    im = Image.new("RGBA", (CW, CH), CREAM + (255,)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, CW, 12], fill=GOLD)
    d.rectangle([0, CH - 150, CW, CH], fill=INK)
    def tc(y, txt, f, fill):
        w = d.textlength(txt, font=f); d.text(((CW - w) / 2, y), txt, font=f, fill=fill)
    draw_logo(im, CW / 2, 200, 120)
    tc(345, cfg["date_label"], F["date"], INK)
    d.line([(CW / 2 - 120, 405), (CW / 2 + 120, 405)], fill=GOLD, width=4)
    tc(430, cfg["brand"], font(70, 500), INK)
    s = cfg["stories"][0]
    y = 570
    for ln in wrap(d, s["headline"], font(66, 600), 900):
        tc(y, ln, font(66, 600), INK); y += 82
    tc(y + 20, cfg["kicker"], F["kick"], RED)
    yy = y + 90
    for ln in wrap(d, s.get("subhead", ""), font(40, 400), 900):
        tc(yy, ln, font(40, 400), GREY); yy += 52
    tc(CH - 118, cfg["tagline"], font(40, 500), (255, 255, 255))
    tc(CH - 62, cfg["url"], font(34, 600), GOLD)
    return im.convert("RGB")


# ---------- main ----------
def probe_duration(path):
    """Length in seconds via ffprobe, or None when it cannot be read. Never raises."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip()) if r.returncode == 0 else None
    except Exception:
        return None


def resolve_music(src, explicit):
    """Find the music file without guessing silently.

    An explicit --music is CWD-relative first (what a shell user means) and
    script-relative second. The brief json's own "music" is script-relative,
    which is how it has always been written. If neither exists, name BOTH paths
    that were tried instead of printing one misleading one.
    """
    cwd_path = os.path.abspath(src)
    here_path = os.path.join(HERE, src)
    if os.path.exists(cwd_path):
        return cwd_path
    if explicit and os.path.exists(here_path):
        return here_path
    sys.exit(f"music file not found; tried:\n  {cwd_path}\n  {here_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default=None,
                    help="output path stem, no extension (CWD-relative; "
                         "default: <script>/out/reel)")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--no-card", action="store_true")
    ap.add_argument("--music", help="override music path from json")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")
    cfg = json.load(open(args.config, encoding="utf-8"))
    for k in ("brand", "date_label", "kicker", "tagline", "url", "stories"):
        if k not in cfg:
            sys.exit(f"brief.json missing required key: {k}")
    if not (1 <= len(cfg["stories"]) <= 4):
        sys.exit("stories must have 1-4 items")

    music = resolve_music(args.music or cfg.get("music", "music/bed_dark.mp3"),
                          bool(args.music))
    music_dur = probe_duration(music)

    # ffmpeg runs -shortest, so it ends the mux at the end of the audio and
    # closes the pipe while frames are still being written. That surfaced as a
    # raw "OSError: [Errno 22] Invalid argument" traceback about 20 s in, with
    # no explanation. Clamp to the audio and say so instead.
    if music_dur and args.duration > music_dur + 0.05:
        print(f"[reel] soundtrack is {music_dur:.2f}s but --duration was "
              f"{args.duration:.2f}s; rendering {music_dur:.2f}s instead "
              f"(-shortest stops at the audio and breaks the pipe).",
              file=sys.stderr)
        args.duration = round(music_dur, 3)

    # Pacing gate, up front: never spawn the encoder (and never leave a stub mp4
    # behind) for a reel whose scenes are too short to read. Text is fully on
    # screen by 2.1 s, so a card under MIN_CARD seconds cannot be read. Runs
    # AFTER the clamp so it judges the duration actually rendered.
    _card = (args.duration - 1.0 - 4.0) / max(1, len(cfg["stories"]))
    if _card < MIN_CARD:
        sys.exit(
            f"FATAL {len(cfg['stories'])} stories in {args.duration:.0f}s leaves "
            f"{_card:.1f}s per scene; the floor is {MIN_CARD:.1f}s. Drop a story or "
            f"lengthen the soundtrack.")

    # An explicit --out is CWD-relative. It used to resolve against the script
    # directory, so a repo-relative path silently wrote into scripts/brief_reel/
    # and the caller looked in the wrong place.
    stem = (os.path.join(HERE, "out/reel") if args.out is None
            else os.path.abspath(args.out))
    _d = os.path.dirname(stem)
    if _d:
        os.makedirs(_d, exist_ok=True)
    mp4 = stem + ".mp4"; png = stem + ".png"

    if not args.no_card:
        still_card(cfg).save(png); print("card:", png)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
           "-i", music,
           "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-threads", "2", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(args.fps * args.duration)
    for i in range(n):
        try:
            p.stdin.write(frame(i / args.fps, cfg, args.duration).tobytes())
        except (BrokenPipeError, OSError) as exc:
            p.stdin.close(); p.wait()
            sys.exit(f"[reel] the encoder closed the pipe at {i / args.fps:.1f}s of "
                     f"{args.duration:.1f}s ({exc}). It stopped early; check the "
                     f"soundtrack length against --duration.")
        if i % (args.fps * 5) == 0:
            print(f"  {i / args.fps:4.0f}s / {args.duration:.0f}s", flush=True)
    p.stdin.close(); p.wait()
    if p.returncode != 0:
        sys.exit("ffmpeg failed")
    print("reel:", mp4)


if __name__ == "__main__":
    main()
