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
import argparse, json, os, subprocess, sys, shutil

from PIL import Image, ImageDraw, ImageFont
import backgrounds as BG

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(HERE, "fonts", "Lora-Variable.ttf")

W, H = 1080, 1920
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
def story_card(im, d, cfg, s, idx, total, tl, card_len, dark=False):
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
    fade_over(im, (0, 0, 0) if dark else CREAM, prog(tl, card_len - 0.5, card_len))


_BG_CACHE = {}
def story_bg(cfg, s, k):
    """Return treated background for story s (or None for the flat cream card)."""
    mode = cfg.get("backgrounds", "auto")   # "auto" | "none" | a scene name
    if mode == "none" and not s.get("image") and not s.get("scene"):
        return None
    key = (k, s.get("image"), s.get("scene"), mode)
    if key not in _BG_CACHE:
        scene = s.get("scene") or (BG.pick_scene(s["headline"] + " " + s.get("subhead", "")) if mode == "auto" else mode)
        _BG_CACHE[key] = BG.load_or_make(scene, s.get("image"), seed=k)
    return _BG_CACHE[key]


def frame(t, cfg, dur):
    stories = cfg["stories"]
    intro, outro = 1.0, 4.0
    card_len = (dur - intro - outro) / max(1, len(stories))

    im = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=(232, 224, 205))
    d.rectangle([0, 0, int(W * t / dur), 14], fill=GOLD)
    # No bottom URL band: the bottom 35% of a 9:16 surface is covered by the
    # caption bar, the audio chip and the story reply box. The URL ships once,
    # in the outro, and lives in the caption every time.

    if t < intro:
        # 1 second title flash. The reel must open on story 1 inside the first
        # second, so the masthead is a bug here, not a 4 second curtain.
        a = prog(t, 0.0, 0.28)
        draw_logo(im, W / 2, 660, 150 * (0.88 + 0.12 * a), a)
        text_c(im, d, 880, cfg["date_label"], F["date"], INK, prog(t, 0.10, 0.42))
        rw = int(220 * prog(t, 0.16, 0.46)); d.line([(W / 2 - rw / 2, 944), (W / 2 + rw / 2, 944)], fill=GOLD, width=5)
        text_c(im, d, 990, cfg["brand"], F["mast"], INK, prog(t, 0.22, 0.54))
        text_c(im, d, 1120, cfg["kicker"], F["kick"], RED, prog(t, 0.32, 0.64))
        fade_over(im, CREAM, prog(t, 0.72, 1.0))
    elif t < dur - outro:
        k = min(len(stories) - 1, int((t - intro) // card_len)); tl = (t - intro) - card_len * k
        bg = story_bg(cfg, stories[k], k)
        dark = bg is not None
        if dark:
            im.paste(bg, (0, 0)); d = ImageDraw.Draw(im)
            d.rectangle([0, 0, W, 14], fill=(60, 55, 45)); d.rectangle([0, 0, int(W * t / dur), 14], fill=GOLD)
            # (bottom URL band removed: unusable on every 9:16 surface)
        draw_logo(im, 92, 90, 46)
        d.text((155, 66), cfg["brand"], font=F["brand_sm"], fill=CREAM if dark else INK)
        story_card(im, d, cfg, stories[k], k, len(stories), tl, card_len, dark=dark)
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
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default="out/reel", help="output path stem (no extension)")
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
    music = args.music or cfg.get("music", "music/bed_dark.mp3")
    if not os.path.isabs(music):
        music = os.path.join(HERE, music)
    if not os.path.exists(music):
        sys.exit(f"music file not found: {music}")

    stem = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)
    os.makedirs(os.path.dirname(stem), exist_ok=True)
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
        p.stdin.write(frame(i / args.fps, cfg, args.duration).tobytes())
        if i % (args.fps * 5) == 0:
            print(f"  {i / args.fps:4.0f}s / {args.duration:.0f}s", flush=True)
    p.stdin.close(); p.wait()
    if p.returncode != 0:
        sys.exit("ffmpeg failed")
    print("reel:", mp4)


if __name__ == "__main__":
    main()
