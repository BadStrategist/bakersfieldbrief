#!/usr/bin/env python3
"""Regenerate the Flock/ALPR email card image from live camera data.

A light street-map card (Esri World Street Map basemap — clean, keyless, no
watermark), amber Flock / muted-green other camera markers, amber ring on
newest (last 28 days), and numbered clusters. CARTO Voyager now requires an
API key and returns a watermark without it, so the card uses Esri tiles
instead — same light-road-map character, always clean. Tiles are fetched from
the Esri World Street Map service at build time, so the email card is fresh
every build and faithfully shows real camera positions.

Rendered with Pillow. Deterministic given the camera payload. The live page
uses Leaflet+markerClusterGroup; this module reproduces the same visual with
pure PIL so the email can bake a single PNG (no browser in CI).

The emailer calls render_tracker_card() every build; the send gate verifies
the card is fresh via the ALPR asof date (see build/email_gate.py).
"""
from __future__ import annotations

import datetime as dt
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import requests

from . import common

# ------------------------------------------------------------- live-page colors
FLOCK = (220, 154, 31)        # #DC9A1F amber
FLOCK_LENS = (122, 90, 14)    # #7A5A0E
OTHER = (143, 160, 153)       # #8FA099 muted green-gray
OTHER_LENS = (78, 91, 87)     # #4E5B57
CLUSTER = (38, 42, 47)        # dark navy cluster dot
RING = (243, 199, 110)        # #F3C76E newest halo

TEXT = (32, 38, 44)
MUTED = (87, 80, 74)
PAPER = (250, 246, 236)       # #FAF6EC site paper
CARD = (255, 253, 247)        # #FFFDF7
LINE = (227, 219, 200)        # #E3DBC8
AMBER_RULE = (220, 154, 31)

VOYAGER = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
SUBDOMAINS = [""]  # Esri is single-host; no subdomain needed

# Card dimensions (kept like the old screenshot: 1048 wide)
W, H = 1048, 786
HEADER_H = 176
MAP_BOTTOM = H - 70  # leave room for attribution strip


def _font(size, bold=False):
    try:
        if bold:
            return ImageFont.truetype(common.ROOT / "assets" / "fonts" / "ttf" / "Lora-Variable.ttf", size)
        return ImageFont.truetype(common.ROOT / "assets" / "fonts" / "ttf" / "Lora-Variable.ttf", size)
    except Exception:
        return ImageFont.load_default()


# ----------------------------------------------------------------- Web Mercator
def _ll_to_wm(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n * 256.0
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n * 256.0
    return x, y


def _tile_range(center_lat, center_lon, zoom, half_px_w, half_px_h):
    """Return the inclusive tile XY range covering a half-extent box around center."""
    cx, cy = _ll_to_wm(center_lat, center_lon, zoom)
    min_px_x = cx - half_px_w
    max_px_x = cx + half_px_w
    min_px_y = cy - half_px_h
    max_px_y = cy + half_px_h
    x0 = int(min_px_x // 256); x1 = int(max_px_x // 256)
    y0 = int(min_px_y // 256); y1 = int(max_px_y // 256)
    return x0, x1, y0, y1


def _fetch_tile(z, x, y, timeout=20):
    url = VOYAGER.format(z=z, x=x, y=y)
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (BakersfieldBrief)"})
        if r.status_code == 200:
            return io.BytesIO(r.content)
        raise RuntimeError(f"tile fetch failed z{z}/{x}/{y}: {r.status_code}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"tile fetch failed z{z}/{x}/{y}: {e}") from e


def _render_map(cameras, center_lat, center_lon, zoom, mw, mh):
    """Return a PIL Image of the Voyager map covering (mw, mh) around the center."""
    half_w = mw / 2.0
    half_h = mh / 2.0
    x0, x1, y0, y1 = _tile_range(center_lat, center_lon, zoom, half_w, half_h)
    canvas = Image.new("RGB", (mw, mh), (240, 240, 240))
    cx, cy = _ll_to_wm(center_lat, center_lon, zoom)
    # pixel offset of the map's top-left from world origin
    top_px_x = cx - half_w
    top_px_y = cy - half_h
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            try:
                tile = Image.open(_fetch_tile(zoom, tx, ty)).convert("RGB")
            except Exception:
                continue
            # tile's top-left in world pixels
            tt_x = tx * 256
            tt_y = ty * 256
            # where it lands on canvas
            dx = tt_x - top_px_x
            dy = tt_y - top_px_y
            if dx > mw or dy > mh or dx + 256 < 0 or dy + 256 < 0:
                continue
            canvas.paste(tile, (int(round(dx)), int(round(dy))))
    return canvas, cx, cy


def render_tracker_card(alpr: dict, out_path=None):
    """Redraw the Flock/ALPR card image (Voyager light map) from live data.

    Writes to common.ROOT/assets/img/tracker-map-card.jpg by default.
    """
    cameras = [c for c in alpr.get("cameras", []) if c.get("lat") is not None and c.get("lon") is not None]
    total = (alpr.get("stats") or {}).get("total", len(cameras))
    flock = (alpr.get("stats") or {}).get("flock", 0)
    asof = alpr.get("asof", "")

    if not cameras:
        raise ValueError("no camera data to render tracker card")

    # center on the mean of camera positions (dense metro)
    center_lat = sum(c["lat"] for c in cameras) / len(cameras)
    center_lon = sum(c["lon"] for c in cameras) / len(cameras)
    # choose zoom so the camera cloud fills ~80% of the map rect
    zoom = 11
    mw, mh = W, H - HEADER_H - 70
    for z in range(10, 14):
        pts = [_ll_to_wm(c["lat"], c["lon"], z) for c in cameras]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        cx, cy = _ll_to_wm(center_lat, center_lon, z)
        span_w = (max(xs) - min(xs)) / mw
        span_h = (max(ys) - min(ys)) / mh
        if max(span_w, span_h) <= 0.72:
            zoom = z
        else:
            break
    else:
        zoom = 13

    map_img, cx, cy = _render_map(cameras, center_lat, center_lon, zoom, mw, mh)

    # ---------------------------------------------------------------- overlay
    img = Image.new("RGB", (W, H), PAPER)
    img.paste(map_img, (0, HEADER_H))
    d = ImageDraw.Draw(img)

    # header panel
    d.rectangle([0, 0, W, HEADER_H], fill=CARD)
    d.rectangle([0, 0, W, 4], fill=AMBER_RULE)
    d.text((28, 22), "FLOCK & ALPR  ·  KERN COUNTY", font=_font(20), fill=(179, 71, 47))
    d.text((28, 50), "Live Camera Tracker", font=_font(40), fill=TEXT)
    d.text((28, 98), "License plate readers mapped in OpenStreetMap", font=_font(20), fill=MUTED)

    stats_def = [
        (f"{total}", "CAMERAS MAPPED"),
        (f"{flock}", "FLOCK SAFETY UNITS"),
        (f"{asof}", "DATA AS OF"),
        (f"+{(alpr.get('stats') or {}).get('new_this_week',0)}", "NEW THIS WEEK"),
    ]
    x = 28
    for val, lab in stats_def:
        d.text((x, 116), val, font=_font(26, bold=True), fill=TEXT)
        d.text((x, 146), lab, font=_font(13), fill=MUTED)
        x += 250

    # newest cameras (last 28 days) ring highlight (matches trackers.js)
    cutoff = (dt.date.today() - dt.timedelta(days=28)).isoformat()
    newest_set = {c["id"] for c in cameras if (c.get("mapped") or "") >= cutoff}

    # cluster + draw markers
    cluster_cell = 40  # px — merge markers closer than this into a cluster
    grid = {}
    unclustered = []
    # map marker offset relative to map top-left
    top_px_x = cx - mw / 2.0
    top_px_y = cy - mh / 2.0
    placed = []
    for c in cameras:
        px, py = _ll_to_wm(c["lat"], c["lon"], zoom)
        gx = int(px // cluster_cell); gy = int(py // cluster_cell)
        key = (gx, gy)
        if key in grid:
            grid[key].append(c)
        else:
            grid[key] = [c]
    for key, group in grid.items():
        if len(group) == 1:
            c = group[0]
            px, py = _ll_to_wm(c["lat"], c["lon"], zoom)
            placed.append((px - top_px_x, py - top_px_y, c))
        else:
            # cluster centroid
            clat = sum(x["lat"] for x in group) / len(group)
            clon = sum(x["lon"] for x in group) / len(group)
            px, py = _ll_to_wm(clat, clon, zoom)
            placed.append((px - top_px_x, py - top_px_y, None, len(group)))

    for item in placed:
        px, py = item[0], item[1]
        mx, my = int(round(px)), int(round(py)) + HEADER_H
        if len(item) == 4:  # cluster
            n = item[3]
            size = 26 + min(18, n // 3)
            d.ellipse([mx - size // 2, my - size // 2, mx + size // 2, my + size // 2], fill=CLUSTER)
            d.text((mx, my), str(n), font=_font(int(size * 0.5), bold=True), fill=(255, 255, 255), anchor="mm")
        else:
            c = item[2]
            is_flock = "flock" in (c.get("manufacturer") or "").lower()
            col = FLOCK if is_flock else OTHER
            lens = FLOCK_LENS if is_flock else OTHER_LENS
            is_new = c.get("id") in newest_set
            if is_new:
                d.ellipse([mx - 15, my - 15, mx + 15, my + 15], outline=RING, width=2)
            # camera glyph (body + lens)
            d.rounded_rectangle([mx - 9, my - 7, mx + 11, my + 7], radius=2, fill=col)
            d.ellipse([mx + 1, my - 3, mx + 8, my + 3], fill=lens)
            d.rectangle([mx - 11, my - 5, mx - 9, my + 5], fill=col)

    # attribution + freshness footer strip
    d.rectangle([0, MAP_BOTTOM, W, H], fill=CARD)
    d.rectangle([0, MAP_BOTTOM, W, MAP_BOTTOM + 3], fill=AMBER_RULE)
    d.text((28, MAP_BOTTOM + 20), "View the Live Camera Tracker", font=_font(22, bold=True), fill=TEXT)
    d.text((28, MAP_BOTTOM + 48), "bakersfieldbrief.com/surveillance", font=_font(17), fill=(110, 100, 92))
    d.text((W - 28, MAP_BOTTOM + 48), f"Data as of {asof}", font=_font(15), fill=MUTED, anchor="ra")
    d.text((W - 28, MAP_BOTTOM + 12), "Map: Esri · © OpenStreetMap contributors", font=_font(12), fill=MUTED, anchor="ra")

    out = Path(out_path) if out_path else common.ROOT / "assets" / "img" / "tracker-map-card.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=88)
    common.log(f"tracker card rendered: {out} ({total} cams, {flock} flock, asof {asof})")
    return out
