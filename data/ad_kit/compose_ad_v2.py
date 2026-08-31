#!/usr/bin/env python3
"""BakersfieldBrief launch ad v2 — motion-design driven.

Research-backed rules applied (top reel ads 2026):
  * hook in first 1.5s (pattern interrupt)          -> BOOM + static + giant type
  * jump cuts, no dead air                          -> 2-4s shots, punch zooms
  * kinetic typography, beat-synced                 -> type slams & pulses to 128bpm
  * works on mute                                   -> text carries the message
  * motion, not pans                                -> punch-in zooms, shakes, flashes
  * audio-reactive brand motif                      -> live waveform = "we're listening"
"""
from __future__ import annotations

import json, math, random, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
FPS = 24
CREAM = (250, 246, 236)
INK = (16, 18, 24)
GOLD = (232, 176, 46)
NAVY = (10, 14, 26)
GREY = (150, 152, 158)

AD_DIR = Path(r"C:\Users\tscac\Projects\BakersfieldBrief.com\data\ad_kit")
FONT_SANS = r"C:\Windows\Fonts\bahnschrift.ttf"       # punchy headline sans
FONT_SERIF = r"C:\Users\tscac\Projects\BakersfieldBrief.com\scripts\brief_reel\fonts\Lora-Variable.ttf"

hitmap = json.loads((AD_DIR / "hitmap.json").read_text())
DUR = hitmap["duration"]
BEATS = hitmap["beats"]
ENV = hitmap["env"]                      # per-frame audio envelope 0..1
TOTAL = int(DUR * FPS)
N_BEATS = len(BEATS)

SHOTS = [
    # (image, t_start, t_end, zoom_dir, headline lines [(text, size, font)], kicker)
    {"img": None, "t0": 0.00, "t1": 1.90, "zoom": "in", "kicker": "BAKERSFIELD · OVERNIGHT",
     "lines": [("EVER WONDERED", 128, "sans"), ("WHAT THAT", 128, "sans")]},
    {"img": None, "t0": 1.90, "t1": 3.75, "zoom": "in", "kicker": None,
     "lines": [("BOOM WAS?", 150, "sans")]},
    {"img": "shot1_heli.png", "t0": 3.75, "t1": 7.10, "zoom": "out", "kicker": "03:47 AM",
     "lines": [("WHY IS THE HELICOPTER", 76, "sans"), ("CIRCLING YOUR", 76, "sans"), ("NEIGHBORHOOD?", 92, "sans")]},
    {"img": "shot2_boom.png", "t0": 7.10, "t1": 9.85, "zoom": "in", "kicker": "02:12 AM",
     "lines": [("THAT BOOM", 100, "sans"), ("YOU HEARD?", 100, "sans")]},
    {"img": "shot3_skyline.png", "t0": 9.85, "t1": 12.60, "zoom": "out", "kicker": "LIVE · SCANNER",
     "lines": [("WE'RE LISTENING", 100, "sans"), ("WHILE YOU", 100, "sans"), ("SLEEP", 128, "sans")]},
    {"img": "shot4_sunrise.png", "t0": 12.60, "t1": 15.00, "zoom": "in", "kicker": "06:00 AM",
     "lines": [("EVERY MORNING", 110, "sans"), ("THE KERN COUNTY NEWS", 66, "sans"), ("YOU'D OTHERWISE MISS", 66, "sans")]},
    {"img": "shot5_brand.png", "t0": 15.00, "t1": DUR, "zoom": "in", "kicker": "THE KERN OVERNIGHT",
     "lines": [("BakersfieldBrief.com", 104, "serif")],
     "tag": "The Kern County news you'd otherwise miss."},
]

# Preload images
imgs = {}
for s in SHOTS:
    if s["img"]:
        im = Image.open(AD_DIR / s["img"]).convert("RGB")
        iw, ih = im.size
        target = W / H
        if iw / ih > target:
            nw = int(ih * target); x0 = (iw - nw) // 2
            im = im.crop((x0, 0, x0 + nw, ih))
        else:
            nh = int(iw / target); y0 = (ih - nh) // 2
            im = im.crop((0, y0, iw, y0 + nh))
        imgs[s["img"]] = im.resize((W, H), Image.LANCZOS)


def font_sans(size, weight="bold"):
    try:
        return ImageFont.truetype(FONT_SANS, size)
    except Exception:
        return ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", size)


def font_serif(size, weight=600):
    f = ImageFont.truetype(FONT_SERIF, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def punch_zoom(t, t0, t1, direction):
    """Fast punch-in/out with settle — reads as motion, not a pan."""
    d = t1 - t0
    p = (t - t0) / d
    if direction == "in":
        # start zoomed OUT, punch IN quickly, hold
        z = 1.18 - 0.16 * ease_out(min(1.0, p * 2.2))
    else:
        # start zoomed IN, punch OUT, hold
        z = 1.02 + 0.16 * ease_out(min(1.0, p * 2.2))
    # slow drift after settle
    drift = 0.02 * ease_in_out(min(1.0, max(0.0, p * 1.2)))
    return z + (drift if direction == "in" else -drift)


def shot_for(t):
    for s in SHOTS:
        if t >= s["t0"] and t < s["t1"]:
            return s
    return SHOTS[-1]


def draw_waveform(base, t, big=False):
    """Audio-reactive bar waveform — the 'we're listening' motif."""
    fi = min(len(ENV) - 1, int(t * FPS))
    wav = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(wav)
    nb = 44
    gap = 6
    bw = (W - gap * (nb + 1)) / nb
    maxh = 240 if big else 120
    base_y = H - (110 if big else 70)
    # window of env around fi for motion
    for i in range(nb):
        k = fi - nb + i
        if k < 0 or k >= len(ENV):
            v = 0.0
        else:
            v = ENV[k]
        # moving-window smoothing
        v = max(v, 0.05)
        h = max(6.0, v * maxh * (1.0 + 0.15 * math.sin(t * 12 + i * 0.55)))
        x = gap + i * (bw + gap)
        gold = (232, 176, 46, 220)
        cream = (250, 246, 236, 160)
        col = gold if i % 4 == 0 else cream
        d.rounded_rectangle([x, base_y - h, x + bw, base_y], radius=3, fill=col)
    # scanning line
    sy = (int(t * 220) % (H - 400)) + 150
    d.line([(60, sy), (W - 60, sy)], fill=(232, 176, 46, 90), width=2)
    return wav


def add_grain(base, seed):
    """Film grain — kills the AI-clean look."""
    rnd = random.Random(seed)
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = g.load()
    for _ in range(12000):
        x = rnd.randrange(W); y = rnd.randrange(H)
        v = rnd.randint(18, 42)
        px[x, y] = (v, v, v, 70)
    return Image.alpha_composite(base, g)


def make_frame(t):
    fi = int(t * FPS)
    s = shot_for(t)
    local = t - s["t0"]
    d = s["t1"] - s["t0"]

    # --- background plate with punch zoom ---
    if s["img"]:
        im = imgs[s["img"]]
        z = punch_zoom(t, s["t0"], s["t1"], s["zoom"])
        cw, ch = int(W / z), int(H / z)
        # slow vertical drift for parallax feel
        drift_y = int((H - ch) * ease_in_out(min(1.0, local / d)) * 0.5)
        x0 = (W - cw) // 2
        y0 = (H - ch) // 2 - drift_y // 2 + drift_y
        y0 = max(0, min(H - ch, y0))
        frame = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS).convert("RGBA")
    else:
        frame = Image.new("RGBA", (W, H), NAVY + (255,))

    # --- text: beat-synced slams ---
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    n_lines = len(s["lines"])
    # each line slams in staggered 0.22s apart, pulse on beats
    block_y = 1180 if s["img"] else 1180
    line_h = 150 if s["img"] else 165
    start_y = block_y - (n_lines - 1) * line_h // 2
    for li, (txt, size, fnt) in enumerate(s["lines"]):
        appear = 0.0 + li * 0.22
        if local < appear:
            continue
        p = min(1.0, (local - appear) / 0.30)
        e = ease_out(p)
        scale = 0.72 + 0.28 * e            # slam in
        # beat pulse
        beat_idx = int((t) / (60 / 128.0))
        bp = max(0.0, 1.0 - ((t - BEATS[min(beat_idx, N_BEATS - 1)]) / 0.47))
        pulse = 1.0 + 0.025 * bp
        size_f = int(size * scale * pulse)
        f = font_sans(size_f) if fnt == "sans" else font_serif(size_f)
        alpha = int(255 * e)
        y = start_y + li * line_h + int((1 - e) * 60)
        # shadow for legibility
        for dx, dy, col, a in [(-3, 3, (0, 0, 0), int(alpha * 0.75)), (3, -3, (0, 0, 0), int(alpha * 0.5))]:
            w = od.textlength(txt, font=f)
            od.text(((W - w) / 2 + dx, y + dy), txt, font=f, fill=col + (a,))
        w = od.textlength(txt, font=f)
        od.text(((W - w) / 2, y), txt, font=f, fill=CREAM + (alpha,))

    # kicker (small gold label above lines)
    if s.get("kicker"):
        kp = min(1.0, local / 0.25)
        kf = font_sans(34)
        kw = od.textlength(s["kicker"], font=kf)
        ky = start_y - 120
        od.text(((W - kw) / 2, ky), s["kicker"], font=kf, fill=GOLD + (int(255 * kp),))

    # tagline (brand card)
    if s.get("tag"):
        tp = min(1.0, max(0.0, (local - 0.6) / 0.4))
        if tp > 0:
            tf = font_serif(44, 500)
            tw = od.textlength(s["tag"], font=tf)
            od.text(((W - tw) / 2, 1560), s["tag"], font=tf, fill=GOLD + (int(255 * ease_out(tp)),))

    out = Image.alpha_composite(frame, ov)

    # --- brand motif: waveform + scrim ---
    big_wave = s["img"] is None
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    top = 1000
    for i in range(H - top):
        a = int(150 * (i / (H - top)) ** 1.3)
        sd.line([(0, top + i), (W, top + i)], fill=(5, 8, 16, a))
    scrim = scrim.filter(ImageFilter.GaussianBlur(20))
    out = Image.alpha_composite(out, scrim)
    out = Image.alpha_composite(out, draw_waveform(out, t, big=big_wave))

    # --- flash cuts on beats ---
    beat_times = [b for b in BEATS if t - 0.02 <= b < t + 0.10]
    if beat_times and s["img"]:
        fl = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        fd = ImageDraw.Draw(fl)
        fd.rectangle([0, 0, W, H], fill=(255, 255, 255, 90))
        out = Image.alpha_composite(out, fl)

    # --- static burst at the very top (radio tune-in) ---
    if t < 0.55:
        st = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd2 = ImageDraw.Draw(st)
        rnd = random.Random(fi)
        for _ in range(8000):
            x = rnd.randrange(W); y = rnd.randrange(H)
            v = rnd.randint(40, 160)
            sd2.point((x, y), fill=(v, v, v, 120))
        out = Image.alpha_composite(out, st)

    # --- boom flash at 0.0 ---
    if t < 0.12:
        fl = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        ImageDraw.Draw(fl).rectangle([0, 0, W, H], fill=(255, 255, 255, int(200 * (1 - t / 0.12))))
        out = Image.alpha_composite(out, fl)

    out = add_grain(out.convert("RGBA"), fi)
    return out.convert("RGB")


def main():
    cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(AD_DIR / "ad_music_v2.wav"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(AD_DIR / "bakersfieldbrief_ad_v2.mp4"),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(TOTAL):
        t = fi / FPS
        if t > DUR:
            break
        proc.stdin.write(make_frame(t).tobytes())
    proc.stdin.close()
    rc = proc.wait()
    print("ffmpeg exit:", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
