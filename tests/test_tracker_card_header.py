"""Markers must stay inside the map rect of the tracker card.

Regression guard for 2026-10-13: the camera list is county-wide while the zoom frame is the
metro, so a marker north of the frame projects to a negative y. Drawn straight onto the card
those markers covered the heading, the standfirst and the "416" stat in the daily email.

These tests run the real render_tracker_card with the tile fetch replaced by a flat grey map,
so no network. Each off-frame camera is placed by inverting the card's own projection, so it
lands a known number of pixels past a known edge of the map rect.
"""
import datetime as dt
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import build.tracker_card as tc  # noqa: E402
from build.sources import alpr as alpr_source  # noqa: E402

MAP_GREY = (240, 240, 240)
STATS = {"total": 455, "flock": 416, "new_this_week": 2}
TODAY = dt.date(2026, 10, 14)
NEW = "2026-10-10"   # inside the 28-day window: drawn with the newest ring
OLD = "2026-01-01"
MH = tc.MAP_BOTTOM - tc.HEADER_H

# The frame: the corners and centre of the metro box, so the zoom and centre are fixed.
_B = alpr_source.METRO_BOX
FRAME = [{"id": f"f{i}", "lat": lat, "lon": lon, "manufacturer": "Flock Safety", "mapped": OLD}
         for i, (lat, lon) in enumerate([(_B[0] + .01, _B[1] + .01), (_B[0] + .01, _B[3] - .01),
                                         (_B[2] - .01, _B[1] + .01), (_B[2] - .01, _B[3] - .01),
                                         ((_B[0] + _B[2]) / 2, (_B[1] + _B[3]) / 2)])]


def _render(monkeypatch, tmp_path, cameras, name):
    seen = {}

    def flat_map(_cams, clat, clon, zoom, mw, mh):
        cx, cy = tc._ll_to_wm(clat, clon, zoom)
        seen.update(zoom=zoom, cx=cx, cy=cy, mw=mw, mh=mh)
        return Image.new("RGB", (mw, mh), MAP_GREY), cx, cy

    monkeypatch.setattr(tc, "_render_map", flat_map)
    monkeypatch.setattr(tc.common, "today_pacific", lambda: TODAY)
    out = tc.render_tracker_card({"cameras": cameras, "stats": STATS, "asof": TODAY.isoformat()},
                                 tmp_path / f"{name}.png")
    return Image.open(out).convert("RGB"), seen


def _cam(seen, cid, x, y, mapped=OLD, maker="Flock Safety"):
    """A camera that lands at (x, y) in map-rect pixels (y < 0 is north of the frame)."""
    n = 2 ** seen["zoom"] * 256.0
    wx = seen["cx"] - seen["mw"] / 2.0 + x
    wy = seen["cy"] - seen["mh"] / 2.0 + y
    lon = wx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * wy / n))))
    return {"id": cid, "lat": lat, "lon": lon, "manufacturer": maker, "mapped": mapped}


def _bands(card):
    return (card.crop((0, 0, tc.W, tc.HEADER_H)).tobytes(),
            card.crop((0, tc.MAP_BOTTOM, tc.W, tc.H)).tobytes())


def test_off_frame_markers_leave_the_header_and_footer_untouched(monkeypatch, tmp_path):
    base, seen = _render(monkeypatch, tmp_path, FRAME, "base")
    off = [
        _cam(seen, "north-ring", 300, -30, mapped=NEW),  # glyph and newest ring wholly north: the heading
        _cam(seen, "north-edge", 600, 4),                 # glyph straddles the top edge by 3 rows
        *[_cam(seen, f"north-cl{i}", 800, -10) for i in range(5)],  # a cluster of 5 across the top edge
        _cam(seen, "south-edge", 450, MH + 6),            # glyph straddles the bottom edge
        _cam(seen, "east-edge", tc.W + 6, 300),           # glyph straddles the right edge
        _cam(seen, "west-edge", -6, 300),                 # glyph straddles the left edge
    ]
    assert not any(alpr_source.in_metro(c) for c in off), "test setup: an off-frame camera moved the frame"
    card, seen2 = _render(monkeypatch, tmp_path, FRAME + off, "off")
    assert seen2 == seen, "test setup: the off-frame cameras changed the zoom or the centre"

    # The header panel must end where the marker layer begins. When it ran one row long, onto
    # row HEADER_H, a glyph on the top edge painted into the header's last row.
    assert base.getpixel((tc.W // 2, tc.HEADER_H)) == MAP_GREY, "the header panel overlaps the map's first row"
    assert base.getpixel((tc.W // 2, tc.HEADER_H - 1)) == tc.CARD

    head, foot = _bands(card)
    base_head, base_foot = _bands(base)
    assert head == base_head, "a marker reached the header band (rows 0 to HEADER_H - 1)"
    assert foot == base_foot, "a marker reached the footer strip"


def test_a_marker_on_an_edge_keeps_its_in_frame_part(monkeypatch, tmp_path):
    _, seen = _render(monkeypatch, tmp_path, FRAME, "base")
    edge = [_cam(seen, "n", 600, 4), _cam(seen, "s", 450, MH + 4),
            _cam(seen, "e", tc.W + 6, 300), _cam(seen, "w", -6, 300)]
    card, _ = _render(monkeypatch, tmp_path, FRAME + edge, "edge")
    px = card.load()
    assert px[595, tc.HEADER_H] == tc.FLOCK, "the top-edge glyph lost its in-frame rows"
    assert px[445, tc.MAP_BOTTOM - 1] == tc.FLOCK, "the bottom-edge glyph lost its in-frame rows"
    assert px[tc.W - 1, tc.HEADER_H + 300] == tc.FLOCK, "the right-edge glyph lost its in-frame columns"
    assert px[0, tc.HEADER_H + 305] == tc.FLOCK, "the left-edge glyph lost its in-frame columns"  # 305: below the lens


def test_the_amber_badge_and_its_ring_sit_on_the_camera(monkeypatch, tmp_path):
    _, seen = _render(monkeypatch, tmp_path, FRAME, "base")
    x, y = 200, 470  # clear of every frame camera
    card, _ = _render(monkeypatch, tmp_path, FRAME + [_cam(seen, "new", x, y, mapped=NEW)], "badge")
    px = card.load()
    top = tc.HEADER_H + y
    assert px[x - 5, top] == tc.FLOCK, "the amber body is not at the camera's point"
    assert px[x + 4, top] == tc.FLOCK_LENS, "the lens is not at the camera's point"
    assert px[x, top - 15] == tc.RING, "the newest ring is not centred on the camera"
    assert px[x - 5, y] != tc.FLOCK, "the marker layer was pasted at the card's top, not the map's"


def test_markers_wholly_past_any_edge_draw_nothing():
    placed = [(tc.W / 2, -16.0, {"id": "n"}), (tc.W / 2, MH + 16.0, {"id": "s"}),
              (tc.W + 16.0, MH / 2, {"id": "e"}), (-16.0, MH / 2, {"id": "w"}),
              (tc.W / 2, -23.0, None, 60)]  # the largest cluster (radius 22) north of the frame
    layer = tc._marker_layer(placed, {"n", "s", "e", "w"}, tc.W, MH)
    assert layer.size == (tc.W, MH)
    assert layer.getchannel("A").getbbox() is None, "a marker past an edge left pixels on the layer"
