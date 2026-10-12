"""The email's overnight card must print the same rows as the home band.

All three surfaces (the home band, /overnight/ and the email) read night_counts.MAP, so
one night cannot show two sets of numbers. The card is drawn from the published report
and its call file only; with neither, it draws nothing and invents nothing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import emailer  # noqa: E402
from build.builders import night_counts, overnight  # noqa: E402

ROWS = {"weapons call": 1, "fight": 1, "crash": 6, "campfire": 1, "medical aid": 2}


def _incs():
    return [{"type": t, "summary": "on a street"} for t, n in ROWS.items() for _ in range(n)]


def _report(monkeypatch, date_iso="2026-10-12"):
    monkeypatch.setattr(overnight, "_published_reports", lambda: [{"date": date_iso}])
    monkeypatch.setattr(overnight, "_incidents", lambda _d: _incs())


def test_the_card_prints_the_home_band_rows(monkeypatch):
    _report(monkeypatch)
    html, txt = emailer._overnight_card({})
    rows = night_counts.chips(_incs())[0]
    assert sum(n for _, n in rows) == len(_incs()) == 11
    for label, n in rows:
        assert f">{n}</td>" in html and label in html, label
        assert f"\n  {n} {label}" in txt, label
    # the html splits the number and the words across tags, the text version does not
    assert "<strong>11</strong>" in html and "calls while Kern slept" in html
    assert "11 calls while Kern slept" in txt
    # 2026-10-12 is a Monday, so the window opens on Sunday.
    assert "7 PM Sunday to 7 AM Monday, Oct 12" in html
    assert "Calls by type, most serious first" in html
    assert f"{emailer.BASE_URL}/overnight/" in html


def test_no_report_or_no_call_file_means_no_card(monkeypatch):
    monkeypatch.setattr(overnight, "_published_reports", lambda: [])
    assert emailer._overnight_card({}) == ("", "")
    monkeypatch.setattr(overnight, "_published_reports", lambda: [{"date": "2026-10-12"}])
    monkeypatch.setattr(overnight, "_incidents", lambda _d: [])
    assert emailer._overnight_card({}) == ("", "")


def test_the_chp_line_needs_its_own_reading_of_the_same_morning(monkeypatch):
    _report(monkeypatch)
    stale = emailer._overnight_card(
        {"ok": True, "asof": "2026-10-11T07:00", "overnight": [1, 2]})[0]
    same = emailer._overnight_card(
        {"ok": True, "asof": "2026-10-12T07:00", "overnight": [1, 2]})[0]
    assert "CHP logged" not in stale
    assert "CHP logged 2 road incidents overnight" in same
