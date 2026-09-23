"""Regression tests for the 2026-09-22 pipeline review fixes.

Each test pins one bug that shipped or could ship: a failed source printed as an all-clear, an
OSM tag breaking out of a <script> block, twin change-log entries, a Caltrans error page read as
"OPEN", Overpass errors read as "0 cameras", and the CHP "overnight" count.
"""
import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build.common as common  # noqa: E402


# ---------------------------------------------------------------- script safety
def test_script_json_cannot_close_the_script_element():
    raw = common.script_json({"operator": "</script><script>alert(1)</script>"})
    assert "</script" not in raw and "<" not in raw
    assert json.loads(raw)["operator"] == "</script><script>alert(1)</script>"


def test_inline_placeholder_is_script_safe():
    html = '<script type="application/json" id="d">/*__DATA__*/null</script>'
    out = common.inline_placeholder(html, {"x": "</script><b>"})
    assert out.count("</script>") == 1


def test_jsonld_is_script_safe():
    from build.builders import page as page_mod
    out = page_mod.render(title="t", desc="d", canonical="/x/", content="", current="", rel="",
                          built="2026-09-22", jsonld=[{"@type": "Thing", "name": "</script><i>"}])
    assert "</script><i>" not in out


# ---------------------------------------------------------------- change log
def test_change_log_one_entry_per_date(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "LOGS", tmp_path)
    assert common.append_change_log("t", {"date": "2026-09-21", "new_count": 3}) is not False
    assert common.append_change_log("t", {"date": "2026-09-21", "new_count": 0}) is False
    log = common.load_change_log("t")
    assert [e["new_count"] for e in log] == [3]


def test_committed_alpr_log_has_no_duplicate_dates():
    log = json.loads((common.DATA / "change_logs" / "alpr.json").read_text(encoding="utf-8"))
    dates = [e["date"] for e in log]
    assert len(dates) == len(set(dates))


# ---------------------------------------------------------------- roads
def test_caltrans_error_page_is_not_open():
    from build.sources import roads
    r = roads._parse("<html><body>Service temporarily unavailable</body></html>", roads.ROUTES[0])
    assert r.get("_no_report")


# ---------------------------------------------------------------- ALPR / Overpass
class _Resp:
    def __init__(self, j):
        self._j = j

    def json(self):
        return self._j


def test_overpass_error_remark_is_a_failure(monkeypatch):
    from build.sources import alpr
    monkeypatch.setattr(common, "fetch", lambda *a, **k: _Resp(
        {"elements": [], "remark": "runtime error: Query timed out in \"query\" at line 1"}))
    r = alpr.run(types.SimpleNamespace(today=dt.date.today()))
    assert r["ok"] is False


def test_overpass_collapse_is_a_failure(monkeypatch):
    from build.sources import alpr
    monkeypatch.setattr(common, "load_snapshot",
                        lambda name, default=None: list(range(200)) if name == "alpr_nodes" else default)
    monkeypatch.setattr(common, "fetch", lambda *a, **k: _Resp({"elements": [
        {"id": 1, "lat": 35.4, "lon": -119.0, "timestamp": "2026-09-01T00:00:00Z", "version": 1, "tags": {}}]}))
    r = alpr.run(types.SimpleNamespace(today=dt.date.today()))
    assert r["ok"] is False


def test_first_mapped_ignores_later_edits(monkeypatch):
    from build.sources import alpr
    saved = {}
    monkeypatch.setattr(common, "load_snapshot", lambda name, default=None: {} if name == "alpr_created" else default)
    monkeypatch.setattr(common, "save_snapshot", lambda name, obj: saved.setdefault(name, obj))
    monkeypatch.setattr(common, "load_change_log", lambda t: [])
    monkeypatch.setattr(common, "fetch", lambda url, **k: _Resp(
        {"elements": [{"id": 7, "version": 1, "timestamp": "2025-01-11T10:00:00Z"}]}))
    out = alpr._first_mapped([
        {"id": 5, "version": 1, "timestamp": "2026-09-20T00:00:00Z"},
        {"id": 7, "version": 3, "timestamp": "2026-09-17T00:00:00Z"},   # old camera, edited
    ])
    assert out == {"5": "2026-09-20", "7": "2025-01-11"}


# ---------------------------------------------------------------- CHP overnight
def test_chp_overnight_is_a_time_window(monkeypatch):
    from build.sources import chp
    fixed = dt.datetime(2026, 9, 22, 9, 0, tzinfo=common.PACIFIC)
    monkeypatch.setattr(common, "now_pacific", lambda: fixed)
    arch = [{"log_id": "a", "time": "Sep 21 2026  8:30PM"},   # before 9 PM: not overnight
            {"log_id": "b", "time": "Sep 21 2026 11:15PM"},
            {"log_id": "c", "time": "Sep 22 2026  3:05AM"},
            {"log_id": "d", "time": "Sep 22 2026  8:00AM"}]   # after 7 AM: not overnight
    assert [a["log_id"] for a in chp._overnight(arch)] == ["b", "c"]


# ---------------------------------------------------------------- honest failure states
def test_statusbar_never_claims_all_clear_when_nws_failed():
    from build.builders import page as page_mod
    bar = page_mod.build_statusbar({"ok": False, "error": "timeout"}, {"ok": False})
    assert "No active weather alerts" not in bar
    assert "No upcoming meetings posted" not in bar
    ok_bar = page_mod.build_statusbar({"ok": True, "alerts": [], "forecast": {}}, {"ok": True, "upcoming": []})
    assert "No active weather alerts" in ok_bar


@pytest.mark.parametrize("mod_path", ["build/emailer.py", "build/builders/daily.py"])
def test_no_unconditional_all_clear_strings(mod_path):
    """The all-clear sentences must each sit behind an ok-check branch."""
    src = (common.ROOT / mod_path).read_text(encoding="utf-8")
    for s in ('"No active weather alerts for Kern County."',):
        i = src.find(s)
        assert i > 0
        assert '.get("ok")' in src[max(0, i - 200):i], f"{mod_path}: {s} is not gated on ok"


# ---------------------------------------------------------------- AI output
class _LLMResp:
    status_code = 200

    def __init__(self, content, reasoning=""):
        self._j = {"choices": [{"message": {"content": content, "reasoning": reasoning},
                                "finish_reason": "length"}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self._j


@pytest.mark.parametrize("content,reasoning", [
    ("", "We need to write a digest of 3-5 short paragraphs grouping related items."),
    ("We need to write a digest. Let's outline: Paragraph 1: crime.", ""),
])
def test_model_planning_never_becomes_page_copy(monkeypatch, content, reasoning):
    """2026-09-22: the model's reasoning went live on the home page under The News."""
    from build import llm
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _LLMResp(content, reasoning))
    assert llm._chat("prompt") is None


def test_real_answer_passes(monkeypatch):
    from build import llm
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: _LLMResp("Bakersfield police are searching for two burglary suspects."))
    assert llm._chat("prompt").startswith("Bakersfield police")


def test_no_control_characters_in_source():
    """An editing slip once turned regex word boundaries into literal backspace characters in
    build/sources/roads.py, and the "closed"/"wind"/"fog" patterns silently never matched."""
    bad = []
    for ext in ("*.py", "*.js", "*.html", "*.css", "*.yml"):
        for p in common.ROOT.glob(f"**/{ext}"):
            if any(part in {"site", "work", ".venv", "node_modules", "__pycache__"} for part in p.parts):
                continue
            try:
                s = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(ch in s for ch in "\x00\x07\x08\x0b\x0c"):
                bad.append(str(p.relative_to(common.ROOT)))
    assert not bad, bad


# ---------------------------------------------------------------- venues
def test_utc_show_time_is_local_day():
    from build.sources.venues_extra import local_when
    # a 7:30 PM Pacific show stored as 02:30 UTC the next day
    assert local_when("2026-10-10T02:30:00+00:00") == "2026-10-09 19:30"
    assert local_when("2026-10-03") == "2026-10-03"


def test_ics_home_games_only(monkeypatch):
    from build.sources import venues_extra as X
    soon = (common.now_pacific() + dt.timedelta(days=3)).strftime("%Y%m%d")
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:(Football) Pasadena City vs. Bakersfield\r\n"
           f"DTSTART:{soon}T010000Z\r\nURL:/links/abc\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:(Football) Bakersfield vs. Fresno City\r\n"
           f"DTSTART:{soon}T010000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    class R:
        text = ics
    monkeypatch.setattr(common, "fetch", lambda *a, **k: R())
    out = X.ics({"url": "https://www.gogades.com/x.ics", "home_rule": "vs_bakersfield",
                 "prefix": "Bakersfield College "})
    assert [e["name"] for e in out] == ["Bakersfield College Football vs. Pasadena City"]
    assert out[0]["url"] == "https://www.gogades.com/links/abc"


def test_guide_never_lists_past_events():
    from build.builders import guide
    today = dt.date(2026, 9, 22)
    evs = [{"name": "Old show", "when": "Sep 18, 2026", "venue_slug": "fox"},
           {"name": "Friday show", "when": "Sep 25, 2026", "venue_slug": "temblor"}]
    assert [e["name"] for e in guide._pick(evs, today)] == ["Friday show"]
