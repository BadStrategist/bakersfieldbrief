#!/usr/bin/env python3
"""Render the daily-weather graphic card for the Brief email + homepage.

A single baked PNG (no browser in CI), drawn with Pillow in the same visual
language as the Flock tracker card (build/tracker_card.py): cream paper, amber
accents, Lora type. Pure NWS + EPA data — current observation, today's
high/low from the gridpoint forecast, wind/humidity from the KBFL station, AQI
from AirNow, and any active Kern alerts. Real numbers only, never placeholder.

Deterministic given the weather dict. The emailer calls render_weather_card()
every build and embeds the live /assets/img/weather-card.jpg; the send gate
fails closed if the redraw throws (it must never ship a stale image).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import common

# ---- brand palette (mirrors tracker_card.py / emailer) ------------------
AMBER = (220, 154, 31)        # #DC9A1F
AMBER_SOFT = (243, 199, 110)  # #F3C76E
AMBER_LIGHT = (250, 233, 190)
RED = (179, 71, 47)           # #B3472F kicker
TEXT = (32, 38, 44)           # #20262C
MUTED = (100, 93, 84)         # readable secondary
INK_SOFT = (140, 132, 122)    # tiny attribution only
PAPER = (250, 246, 236)       # #FAF6EC
CARD = (255, 253, 247)        # #FFFDF7
LINE = (225, 217, 198)        # #E1D9C6
WHITE = (255, 255, 255)

# AQI category colour (EPA 1-6)
AQI_COL = {1: (68, 153, 71), 2: (219, 198, 0), 3: (232, 133, 32),
           4: (210, 40, 36), 5: (126, 23, 79), 6: (94, 10, 36)}

W, H = 1048, 640
PAD = 44

_font_cache = {}


def _font(size: int, weight: int = 400):
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    try:
        f = ImageFont.truetype(str(common.ROOT / "assets" / "fonts" / "ttf" / "Lora-Variable.ttf"), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def _cardinal(deg):
    if deg is None:
        return ""
    try:
        return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(int(float(deg)) % 360 / 45) % 8]
    except (TypeError, ValueError):
        return ""


def _tracked(d, text, x, y, font, fill, spacing=3):
    """Uppercase label with even letter-spacing (no stray trailing gap)."""
    gaps = spacing if text else 0
    s = text
    # wide variant without last-letter gap: build manually
    t = ""
    for i, ch in enumerate(s):
        t += ch
        if i < len(s) - 1:
            t += " " * gaps
    d.text((x, y), t, font=font, fill=fill)


def _sun(d, cx, cy, r):
    # soft halo rings, then filled amber disc with a glare dot — clean, no fake art
    halo = AMBER_SOFT
    for rr, w in ((int(r * 1.85), 14), (int(r * 1.55), 22), (int(r * 1.3), 30)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=halo, width=w)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBER)
    d.ellipse([cx - int(r * .72), cy - int(r * .72), cx + int(r * .72), cy + int(r * .72)], fill=(247, 198, 92))
    d.ellipse([cx - int(r * .28), cy - int(r * .38), cx + int(r * .1), cy], fill=(253, 228, 160))


def render_weather_card(wx: dict, out_path=None):
    """wx keys: current, high, low, condition, wind_mph, wind_dir(deg),
    humidity(%), aqi, aqi_category, alerts(list[str]), observed(str),
    day_label(str). Missing stats render as honest '—', never fabricated."""
    cur = wx.get("current")
    hi = wx.get("high")
    lo = wx.get("low")
    cond = (wx.get("condition") or "").strip()
    aqi = wx.get("aqi")
    aqi_cat = wx.get("aqi_category")
    alerts = wx.get("alerts") or []
    observed = wx.get("observed") or ""
    day_label = wx.get("day_label") or (dt.date.today().strftime("%A, %B") + " " + str(dt.date.today().day))

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 5], fill=AMBER)

    # ---------------- header ----------------
    _tracked(d, "TODAY'S WEATHER", PAD, 44, _font(22, 700), RED, spacing=3)
    _tracked(d, "BAKERSFIELD · KERN COUNTY", PAD, 72, _font(14, 600), MUTED, spacing=2)
    d.text((W - PAD, 70), day_label, font=_font(18, 500), fill=TEXT, anchor="ra")
    d.rectangle([PAD, 106, W - PAD, 108], fill=LINE)

    # ---------------- current temp (left) ----------------
    now = "—" if cur is None else f"{cur}°"
    d.text((PAD + 4, 168), now, font=_font(200, 700), fill=TEXT)
    # baseline rule under the big number
    d.rectangle([PAD + 8, 396, PAD + 360, 398], fill=AMBER)
    # a sun fills the empty space right of the current temp (left zone)
    _sun(d, 502, 286, 54)
    d.text((PAD + 6, 416), (cond.upper() or "CONDITIONS UNAVAILABLE"), font=_font(24, 700), fill=TEXT)
    obs = f"Observed {observed} · KBFL airport" if observed else "KBFL airport observation"
    d.text((PAD + 6, 452), obs, font=_font(15, 500), fill=MUTED)

    # ---------------- forecast (right) ----------------
    DIVX = 620
    d.rectangle([DIVX, 150, DIVX + 2, 388], fill=LINE)  # thin vertical divider
    right_x = DIVX + 58
    _tracked(d, "FORECAST FOR TODAY", right_x, 172, _font(15, 700), INK_SOFT, spacing=2)
    hi_v = "—" if hi is None else f"{hi}°"
    lo_v = "—" if lo is None else f"{lo}°"
    for yy, lab, val, coldark in ((232, "High", hi_v, TEXT), (330, "Low", lo_v, MUTED)):
        d.text((right_x, yy), val, font=_font(82, 700), fill=coldark)
        d.text((right_x + 150, yy + 8), lab.upper(), font=_font(15, 700), fill=INK_SOFT)

    # ---------------- metrics band ----------------
    band_y = 448
    d.rounded_rectangle([PAD, band_y, W - PAD, H - 84], radius=14, fill=CARD,
                        outline=LINE, width=1)
    d.rectangle([PAD, band_y, PAD + 6, H - 84], fill=AMBER)  # left accent
    wind_dir_txt = _cardinal(wx.get("wind_dir"))
    wind_v = "—"
    if wx.get("wind_mph") is not None:
        wind_v = f"{round(wx['wind_mph'])} mph" + (f" {wind_dir_txt}" if wind_dir_txt else "")
    hum_v = "—" if wx.get("humidity") is None else f"{round(wx['humidity'])}%"
    aq_v = "—" if aqi is None else f"AQI {aqi}"
    alert_v = (f"{len(alerts)} active" if alerts else "None active")
    segs = [
        ("WIND", wind_v, TEXT, None),
        ("HUMIDITY", hum_v, TEXT, None),
        ("AIR QUALITY", aq_v, TEXT, aqi),
        ("ALERTS", alert_v, (RED if alerts else TEXT), None),
    ]
    inner_x0 = PAD + 34
    inner_x1 = W - PAD - 20
    seg_w = (inner_x1 - inner_x0) / len(segs)
    for i, (lab, val, col, aq) in enumerate(segs):
        x0 = int(inner_x0 + i * seg_w)
        if aq is not None:
            num = 3
            for k, lim in enumerate((50, 100, 150, 200, 300, 500)):
                if aq <= lim:
                    num = k + 1
                    break
            aqcol = AQI_COL.get(num, AMBER)
            d.ellipse([x0 + 2, band_y + 40, x0 + 22, band_y + 60], fill=aqcol)
            d.text((x0 + 30, band_y + 40), val, font=_font(26, 700), fill=TEXT)
        else:
            d.text((x0, band_y + 40), val, font=_font(26, 700), fill=col)
        _tracked(d, lab, x0, band_y + 82, _font(12, 700), MUTED, spacing=2)
        if i < len(segs) - 1:
            d.rectangle([int(x0 + seg_w) - 2, band_y + 30, int(x0 + seg_w), band_y + 80], fill=LINE)

    # ---------------- footer ----------------
    if alerts:
        d.text((PAD, H - 52), "⚠  " + alerts[0], font=_font(16, 600), fill=RED)
    d.text((W - PAD, H - 52), "National Weather Service · api.weather.gov · EPA AirNow",
           font=_font(13, 500), fill=INK_SOFT, anchor="ra")

    out = Path(out_path) if out_path else common.ROOT / "assets" / "img" / "weather-card.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90)
    common.log(f"weather card rendered: {out} (cur {cur} hi {hi} lo {lo} aqi {aqi})")
    return out


if __name__ == "__main__":
    import json
    import sys
    import urllib.request
    HDR = {"User-Agent": "BakersfieldBrief (bakersfieldbrief.com)", "Accept": "application/geo+json"}
    def get(u):
        with urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=25) as r:
            return json.loads(r.read())
    def _observed_local(obs):
        """Observation time in Pacific, from the station's OWN timestamp.
        Mirrors build/sources/weather.py so the harness and the real render path
        cannot disagree about what "observed" means."""
        ts = (obs or {}).get("timestamp") or ""
        if not ts:
            return ""
        try:
            return (dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    .astimezone(dt.timezone(dt.timedelta(hours=-7)))
                    .strftime("%I:%M %p").lstrip("0"))
        except Exception:  # noqa: BLE001
            return ""

    o = get("https://api.weather.gov/stations/KBFL/observations/latest")["properties"]
    def f(c):
        return None if c is None else round(c * 9 / 5 + 32)
    today = dt.date.today().isoformat()
    periods = get(get("https://api.weather.gov/points/35.3733,-119.0187")["properties"]["forecast"])["properties"]["periods"]
    hi = lo = None
    cond = ""
    for p in periods:
        if (p.get("startTime") or "")[:10] == today:
            if p.get("isDaytime"):
                hi = p["temperature"] if hi is None else max(hi, p["temperature"])
                if not cond:
                    cond = p.get("shortForecast", "")
            else:
                lo = p["temperature"] if lo is None else min(lo, p["temperature"])
    wd = (o.get("windDirection") or {}).get("value")
    wx = {
        "current": f((o.get("temperature") or {}).get("value")),
        "high": hi, "low": lo, "condition": cond,
        "wind_mph": common.wind_mph(o.get("windSpeed")),
        "wind_dir": wd,
        "humidity": (o.get("relativeHumidity") or {}).get("value"),
        "aqi": int(sys.argv[1]) if len(sys.argv) > 1 else None,
        "aqi_category": sys.argv[2] if len(sys.argv) > 2 else "",
        "alerts": [],
        # Use the OBSERVATION's own timestamp, not the clock. dt.datetime.now()
        # here mislabelled the card with the time the harness ran (and printed a
        # UTC time as if it were local on a UTC runner), unlike the real render
        # path in build/sources/weather.py which reads o["timestamp"].
        "observed": _observed_local(o),
    }
    p = render_weather_card(wx, Path(sys.argv[0]).resolve().parent / ".." / "assets" / "img" / "_weather_draft.jpg")
    print(p)
