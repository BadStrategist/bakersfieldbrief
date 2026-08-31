#!/usr/bin/env python3
"""Compose the BakersfieldBrief launch ad: 5 photoreal shots, slide-in text
(matching the daily reels' Lora/cream/gold look, but snappier), slow zoom
motion, hard cuts. 1080x1920 @ 24fps, 20s. Frames -> pipe to ffmpeg."""
from __future__ import annotations

import subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
FPS = 24
DUR = 20.0
TOTAL = int(DUR * FPS)

CREAM = (250, 246, 236)
INK = (38, 43, 48)
GOLD = (214, 158, 30)
GREY = (110, 112, 115)
DARK_SCRIM = (10, 12, 18)

FONT_PATH = r"C:\Users\tscac\Projects\BakersfieldBrief.com\scripts\brief_reel\fonts\Lora-Variable.ttf"
AD_DIR = Path(r"C:\Users\tscac\Projects\BakersfieldBrief.com\data\ad_kit")

SHOTS = [
    {"file": "shot1_heli.png", "dur": 3.6, "zoom": "in",
     "lines": [("Ever wondered", 92, 600), ("what that boom was?", 92, 600)]},
    {"file": "shot2_boom.png", "dur": 3.6, "zoom": "out",
     "lines": [("Why is the helicopter", 88, 600), ("circling your street?", 88, 600)]},
    {"file": "shot3_skyline.png", "dur": 3.6, "zoom": "in",
     "lines": [("We're listening", 92, 600), ("while you're sleeping.", 92, 600)]},
    {"file": "shot4_sunrise.png", "dur": 3.6, "zoom": "out",
     "lines": [("The Kern County news", 86, 600), ("you'd otherwise miss.", 86, 600)]},
    {"file": "shot5_brand.png", "dur": 5.6, "zoom": "in",
     "lines": [("The Kern Overnight", 66, 500), ("BakersfieldBrief.com", 104, 700)],
     "tag": ["Every morning.", "The Kern County news you'd otherwise miss."]},
]

# Pre-load + pre-scale (shots are 1152x2048; center-crop to 1080x1920)
imgs = {}
for s in SHOTS:
    im = Image.open(AD_DIR / s["file"]).convert("RGB")
    # center crop to 9:16 then resize
    iw, ih = im.size
    target = 1080 / 1920
    if iw / ih > target:  # too wide
        nw = int(ih * target); x0 = (iw - nw) // 2
        im = im.crop((x0, 0, x0 + nw, ih))
    else:
        nh = int(iw / target); y0 = (ih - nh) // 2
        im = im.crop((0, y0, iw, y0 + nh))
    imgs[s["file"]] = im.resize((W, H), Image.LANCZOS)


def font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def ease(x):
    x = max(0.0, min(1.0, x)); return x * x * (3 - 2 * x)


def draw_centered_lines(base, lines, y0, line_gap, scrim=True):
    """Slide-in lines (alpha + y-rise), centered, with a bottom scrim."""
    im = base.copy()
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    if scrim:
        # bottom gradient scrim for legibility
        sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sc)
        top = H - 700
        for i in range(H - top):
            a = int(210 * (i / (H - top)) ** 1.4)
            sd.line([(0, top + i), (W, top + i)], fill=DARK_SCRIM + (a,))
        sc = sc.filter(ImageFilter.GaussianBlur(24))
        overlay.alpha_composite(sc)
    y = y0
    for (txt, size, weight) in lines:
        f = font(size, weight)
        w = od.textlength(txt, font=f)
        od.text(((W - w) / 2, y), txt, font=f, fill=CREAM + (255,))
        y += line_gap
    return overlay


def draw_tag(im_draw, txt, y, size=42, weight=600, fill=GOLD):
    f = font(size, weight)
    w = im_draw.textlength(txt, font=f)
    im_draw.text(((W - w) / 2, y), txt, font=f, fill=fill + (255,))


def make_frame(t):
    # which shot
    acc = 0.0
    for idx, s in enumerate(SHOTS):
        d = s["dur"]
        if t < acc + d:
            break
        acc += d
    else:
        idx, d, acc = len(SHOTS) - 1, SHOTS[-1]["dur"], sum(x["dur"] for x in SHOTS[:-1])
    s = SHOTS[idx]
    local = t - acc
    im = imgs[s["file"]]

    # slow zoom: crop window shrinks/grows over the shot
    zoom_in = s["zoom"] == "in"
    z0, z1 = (1.0, 1.12) if zoom_in else (1.12, 1.0)
    z = z0 + (z1 - z0) * ease(local / s["dur"])
    cw, ch = int(W / z), int(H / z)
    # drift slightly upward over time for a cinematic feel
    drift = int(60 * (local / s["dur"]))
    y0 = min(max(0, drift), H - ch)
    x0 = (W - cw) // 2
    frame = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS)

    # text slide-in: appears in first 0.45s of the shot, snappy
    prog_ = min(1.0, local / 0.45)
    e = ease(prog_)
    base = frame.convert("RGBA")
    ov = draw_centered_lines(base, s["lines"], 1180, 120)
    # move the whole overlay up as it fades in
    shift = int((1 - e) * 60)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    out.alpha_composite(base)
    ov2 = ov.crop((0, max(0, shift), W, H - max(0, shift)))
    out.alpha_composite(ov2, (0, shift))
    if s.get("tag"):
        od = ImageDraw.Draw(out)
        ta = int(255 * e)
        lines = s["tag"] if isinstance(s["tag"], list) else [s["tag"]]
        y = 1500
        for ln in lines:
            f = font(42, 600)
            w = od.textlength(ln, font=f)
            od.text(((W - w) / 2, y), ln, font=f, fill=GOLD + (ta,))
            y += 56
    return out.convert("RGB")


def main():
    cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(AD_DIR / "ad_music.wav"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(AD_DIR / "bakersfieldbrief_ad.mp4"),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(TOTAL):
        t = fi / FPS
        frame = make_frame(t)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    rc = proc.wait()
    print("ffmpeg exit:", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
