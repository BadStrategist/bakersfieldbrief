#!/usr/bin/env python3
"""The tracker card badge and the email sentence must show ONE number.

Regression guard for 2026-09-14: the baked tracker card read "+0 NEW THIS WEEK"
while the sentence under it said "5 new cameras mapped this week". Cause: the
badge used ``stats['new_this_week']`` = the snapshot diff, and the snapshot
advances on the weekly change-log run, so the diff reads 0 for every build after
Monday. The count now comes from each camera's live OSM ``mapped`` date, which
recomputes every build.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _Resp:
    def __init__(self, elements):
        self._e = elements

    def json(self):
        return {"elements": self._e}


def _node(nid, mapped_days_ago, manufacturer="Flock Safety"):
    # Use the SAME clock the source uses (common.iso_today() = Pacific), not
    # dt.date.today() (the runner's local date = UTC in CI). Otherwise the
    # runner's UTC date rolls over ~7 hours before the Pacific date and this
    # test fails for any build pushed between 5pm and midnight Pacific.
    from build import common
    stamp = (dt.date.fromisoformat(common.iso_today())
             - dt.timedelta(days=mapped_days_ago)).isoformat()
    return {"id": nid, "lat": 35.37, "lon": -119.02,
            "timestamp": f"{stamp}T00:00:00Z",
            "tags": {"manufacturer": manufacturer, "surveillance": "ALPR"}}


def _run_alpr(monkeypatch, elements, snapshot_ids=()):
    """Run the source offline against a fake Overpass reply.

    The fakes go through ``monkeypatch`` so they are undone at teardown and
    never leak into tests that run later in the same session.
    """
    from build.sources import alpr
    from build import common
    monkeypatch.setattr(common, "fetch", lambda *a, **k: _Resp(elements))                # noqa: ARG005
    monkeypatch.setattr(common, "load_snapshot", lambda *a, **k: list(snapshot_ids))    # noqa: ARG005
    monkeypatch.setattr(common, "save_snapshot", lambda *a, **k: None)                  # noqa: ARG005
    return alpr.run(None, record_change=False)


class TestNewThisWeek:
    def test_counts_rolling_7_days_not_the_snapshot_diff(self, monkeypatch):
        """2 cameras inside 7 days, 1 outside -> 2 (even with an empty snapshot)."""
        data = _run_alpr(monkeypatch, [_node(1, 0), _node(2, 5), _node(3, 10)])
        assert data["ok"], data
        assert data["stats"]["new_this_week"] == 2
        # the snapshot diff would have said 3 — the exact bug that shipped "+0"
        assert data["stats"]["new_this_week_snapshot_diff"] == 3

    def test_does_not_go_to_zero_after_the_snapshot_advances(self, monkeypatch):
        """The weekly job's ids are already in the snapshot: the badge must hold."""
        ids = [1, 2, 3]
        data = _run_alpr(monkeypatch, [_node(1, 1), _node(2, 2), _node(3, 3)], snapshot_ids=ids)
        assert data["stats"]["new_this_week_snapshot_diff"] == 0
        assert data["stats"]["new_this_week"] == 3

    def test_eight_day_old_camera_is_out(self, monkeypatch):
        data = _run_alpr(monkeypatch, [_node(1, 7), _node(2, 8)])
        assert data["stats"]["new_this_week"] == 1


class TestEmailSentenceAgrees:
    def _payload(self, monkeypatch, elements):
        data = _run_alpr(monkeypatch, elements)
        return data

    def test_sentence_number_equals_the_badge_number(self, monkeypatch):
        from build.emailer import _flock_update_html
        data = self._payload(monkeypatch, [_node(1, 1), _node(2, 3), _node(3, 20)])
        html = _flock_update_html(data)
        badge = data["stats"]["new_this_week"]
        assert badge == 2
        assert f"<strong>{badge} new cameras mapped this week</strong>" in html

    def test_today_and_week_parts_sum_to_the_badge(self, monkeypatch):
        from build.emailer import _flock_update_html
        data = self._payload(monkeypatch, [_node(1, 0), _node(2, 0), _node(3, 4), _node(4, 6)])
        html = _flock_update_html(data)
        assert data["stats"]["new_this_week"] == 4
        assert "2 new cameras mapped today" in html
        assert "2 more this week" in html

    def test_empty_week_says_so(self, monkeypatch):
        from build.emailer import _flock_update_html
        html = _flock_update_html(self._payload(monkeypatch, [_node(1, 30)]))
        assert "No new cameras mapped in the last 7 days" in html

    def test_badge_reads_the_same_stat_field(self):
        """Guard the wiring: the card badge must read stats['new_this_week']."""
        src = (ROOT / "build" / "tracker_card.py").read_text(encoding="utf-8")
        assert re.search(r"new_this_week", src), \
            "tracker card no longer reads stats['new_this_week']"