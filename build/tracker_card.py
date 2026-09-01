#!/usr/bin/env python3
"""Regenerate the Flock/ALPR email card image from live camera data.

The email's "Flock & ALPR Tracker" card used to reference a STATIC committed
JPEG (assets/img/tracker-map-card.jpg) that never refreshed — the 2026-08-22
image was still shipping on 2026-09-01. This module redraws the card from the
same `alpr` source payload the surveillance page and email text use, so the
image is always fresh and always shows real camera positions + real stats.

Rendered with Pillow + the committed Lora font (assets/fonts/ttf/Lora-Variable.ttf)
so it is deterministic and identical on the host and in CI — no browser, no map
tiles, no network. Dark theme matches the site's surveillance page (deflock).

The emailer calls render_tracker_card() every build; the send gate verifies the
card is fresh by requiring the ALPR `asof` date embedded in the email text to
be recent (see build/email_gate.py).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import common

# ------------------------------------------------------------------ palette
BG = (20, 23, 26)          # #14171A  dark canvas
PANEL = (26, 33, 38)       # #1A2126  header/footer panels
GRID = (35, 43, 48)        # #232B30  subtle grid
TEXT = (232, 228, 216)     # #E8E4D8  primary text
MUTED = (138, 133, 120)    # #8A8578  secondary text
AMBER = (220, 154, 31)     # #DC9A1F  Flock dots / accents
AMBER_SOFT = (243, 199, 110)  # #F3C76E
RED = (179, 71, 47)        # #B3472F
DOT_OTHER = (120, 128, 138)  # non-Flock ALPR dots
RING = (243, 199, 110)     # newest-camera halo

W, H = 1048, 706
FONT = common.ROOT / "assets" / "fonts" / "ttf" / "Lora-Variable.ttf"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def _project(cameras: list[dict]) -> tuple[list[tuple[float, float]], float]:
    """Project camera lat/lon to normalized (x, y) in [0,1] with aspect fix.

    The bbox is cropped to the 5th-95th percentile of points so the dense
    Bakersfield metro fills the card instead of leaving large empty edges
    (east Kern has no cameras). Returns (points, aspect) where aspect is the
    width/height of the projected bbox (latitude-corrected).
    """
    import math
    pts = [(c["lat"], c["lon"]) for c in cameras if c.get("lat") is not None and c.get("lon") is not None]
    if not pts:
        return [], 1.0
    lats = sorted(p[0] for p in pts)
    lons = sorted(p[1] for p in pts)
    n = len(lats)
    if n >= 10:
        lo_i, hi_i = int(n * 0.05), int(n * 0.95) - 1
        lat0, lat1 = lats[lo_i], lats[hi_i]
        lon0, lon1 = lons[lo_i], lons[hi_i]
    else:
        lat0, lat1, lon0, lon1 = lats[0], lats[-1], lons[0], lons[-1]
    if lat1 == lat0:
        lat1 = lat0 + 0.01
    if lon1 == lon0:
        lon1 = lon0 + 0.01
    mid = (lat0 + lat1) / 2
    cos = max(0.5, math.cos(math.radians(mid)))
    lon_span = (lon1 - lon0) * cos
    lat_span = lat1 - lat0
    aspect = (lon_span / lat_span) if lat_span else 1.0
    out = []
    for la, lo in pts:
        x = (lo - lon0) / (lon1 - lon0)
        y = (lat1 - la) / (lat1 - lat0)
        # Clamp: cameras outside the percentile crop would project to <0 or >1
        # and render on top of the header/footer text. Pin them to the map edge.
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
        out.append((x, y))
    return out, aspect


def render_tracker_card(alpr: dict, out_path: Path | None = None) -> Path:
    """Draw the card from the alpr source payload. Returns the written path.

    Raises ValueError if there is no usable camera data (caller should then
    keep the previous image; the send gate will block on the stale asof).
    """
    cameras = alpr.get("cameras") or []
    stats = alpr.get("stats") or {}
    if not cameras:
        raise ValueError("no alpr cameras to render")
    asof = alpr.get("asof") or common.iso_today()

    total = stats.get("total", len(cameras))
    flock = stats.get("flock", 0)
    newest = stats.get("newest_mapped", "")
    # new cameras mapped in the last 7 days (same logic as the email text)
    today = dt.date.today().isoformat()
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    new_week = sum(1 for c in cameras if week_ago <= (c.get("mapped") or "") < today)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ------------------------------------------------------------ header
    HEADER_H = 164
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, 0, W, 4], fill=AMBER)  # amber top rule
    d.text((28, 24), "FLOCK & ALPR  ·  KERN COUNTY", font=_font(20), fill=AMBER)
    d.text((28, 52), "Live Camera Tracker", font=_font(40), fill=TEXT)
    d.text((28, 98), "License plate readers mapped in OpenStreetMap", font=_font(20), fill=MUTED)

    # stat row
    stats_def = [
        (f"{total}", "CAMERAS MAPPED"),
        (f"{flock}", "FLOCK SAFETY UNITS"),
        (f"{newest}", "NEWEST MAPPED"),
        (f"+{new_week}", "NEW THIS WEEK"),
    ]
    x = 28
    for val, lab in stats_def:
        d.text((x, 116), val, font=_font(26, bold=True), fill=TEXT)
        d.text((x, 146), lab, font=_font(14), fill=MUTED)
        x += 250

    # ------------------------------------------------------------ map
    top, bottom = HEADER_H, 600
    map_h = bottom - top
    points, aspect = _project(cameras)
    # fit the projected bbox into the map rect preserving aspect
    avail_w = W - 40
    avail_h = map_h - 36
    if aspect >= avail_w / avail_h:
        mw = avail_w
        mh = int(avail_w / aspect)
    else:
        mh = avail_h
        mw = int(avail_h * aspect)
    mx0 = (W - mw) // 2
    my0 = top + (map_h - mh) // 2

    # subtle grid (dimmer, thinner so it doesn't compete with the dots)
    for gx in range(mx0, mx0 + mw + 1, 60):
        d.line([gx, my0, gx, my0 + mh], fill=GRID, width=1)
    for gy in range(my0, my0 + mh + 1, 60):
        d.line([mx0, gy, mx0 + mw, gy], fill=GRID, width=1)
    d.rectangle([mx0, my0, mx0 + mw, my0 + mh], outline=GRID, width=2)

    # newest cameras (last 28 days) get a halo ring
    newest_28 = {c["id"] for c in cameras if (c.get("mapped") or "") >= (dt.date.today() - dt.timedelta(days=28)).isoformat()}

    for (nx, ny), cam in zip(points, cameras):
        px = mx0 + nx * mw
        py = my0 + ny * mh
        is_flock = "flock" in (cam.get("manufacturer") or "").lower()
        color = AMBER if is_flock else DOT_OTHER
        r = 6 if is_flock else 5
        if cam.get("id") in newest_28:
            d.ellipse([px - 13, py - 13, px + 13, py + 13], outline=RING, width=2)
        # dark outline lifts every dot off the grid
        d.ellipse([px - r - 1, py - r - 1, px + r + 1, py + r + 1], fill=(10, 12, 14))
        d.ellipse([px - r, py - r, px + r + r, py + r], fill=color)

    # ------------------------------------------------------------ footer
    d.rectangle([0, bottom, W, H], fill=PANEL)
    d.rectangle([0, bottom, W, bottom + 3], fill=AMBER)
    d.text((28, bottom + 22), "View the Live Camera Tracker", font=_font(24, bold=True), fill=TEXT)
    d.text((28, bottom + 56), "bakersfieldbrief.com/surveillance", font=_font(18), fill=AMBER_SOFT)
    d.text((W - 28, bottom + 56), f"Data as of {asof}", font=_font(16), fill=MUTED, anchor="ra")

    out = Path(out_path) if out_path else common.ROOT / "assets" / "img" / "tracker-map-card.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=88)
    common.log(f"tracker card rendered: {out} ({total} cams, {flock} flock, asof {asof})")
    return out

