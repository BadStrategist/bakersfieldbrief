#!/usr/bin/env python3
"""Regression tests for the CrimeRadar emulator bridge.

Covers the faults found in the 2026-10-03 audit, each of which either stopped
the pipeline or could have published something wrong:

  * every scheduled run failed because child processes inherited the cron
    runner's invalid stdin;
  * the 07:15 emit required incidents/<date>.json, which the 07:30 publish
    creates;
  * the emit wrote into incidents/ and a second run emptied the staging file;
  * a failed UI dump silently re-read the previous screen;
  * pre-midnight polls never reached the reel or the street lookup;
  * the reel matcher accepted a clip on time alone and misread AM/PM times;
  * a failed clip capture was never retried.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar.py -q
Fully offline: no emulator, no adb, no network.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "brief_reel"))
sys.path.insert(0, str(ROOT / "kern_overnight"))
import crimeradar_monitor as cr  # noqa: E402
import merge_crimeradar as mc  # noqa: E402
import make_dispatch_audio as mda  # noqa: E402

DATE = "2026-10-04"

TRANSCRIPT = [
    {"type": "pursuit and crash", "time": "00:04", "agency": "CHP",
     "area": "South Union Avenue area", "notability": 5, "disposition": "",
     "summary": "A chase ended when the driver crashed into the median."},
    {"type": "structure fire", "time": "02:10", "agency": "KCFD",
     "area": "Oakley Street", "notability": 3, "disposition": "",
     "summary": "Crews knocked down a garage fire on Oakley Street."},
]


def staged(time, summary, **kw):
    return {"type": "Incident", "time": time, "agency": cr.FEED_NAME, "area": "",
            "notability": 3, "disposition": "", "summary": summary,
            "source": "crimeradar", **kw}


@pytest.fixture
def dirs(tmp_path):
    inc, stage = tmp_path / "incidents", tmp_path / "work"
    inc.mkdir(); stage.mkdir()
    return inc, stage


def put_stage(stage, rows):
    (stage / f"emulator_incidents_{DATE}.json").write_text(
        json.dumps({"date": DATE, "incidents": rows}), encoding="utf-8")


def put_inc(inc, rows):
    (inc / f"{DATE}.json").write_text(json.dumps(rows), encoding="utf-8")


def read_inc(inc):
    return json.loads((inc / f"{DATE}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------- merge
def test_merge_adds_uncovered_and_is_idempotent(dirs):
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("05:00", "Fight at Marriott."),
                      staged("02:14", "Garage fire on Oakley St.")])
    r1 = mc.merge(DATE, inc, stage)
    assert (r1["merged"], r1["covered"], r1["changed"]) == (1, 1, True)
    after = read_inc(inc)
    assert [i["summary"] for i in after if i.get("source") == "crimeradar"] == \
        ["Fight at Marriott."]
    for _ in range(3):
        r = mc.merge(DATE, inc, stage)
        assert r["changed"] is False
    assert read_inc(inc) == after


def test_merge_survives_reextraction(dirs):
    """The watchdog re-extracts the transcript: the rows must come back."""
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("05:00", "Fight at Marriott.")])
    mc.merge(DATE, inc, stage)
    put_inc(inc, TRANSCRIPT)                     # rewrite, emulator rows lost
    assert mc.merge(DATE, inc, stage)["merged"] == 1
    assert len(read_inc(inc)) == len(TRANSCRIPT) + 1


def test_merge_never_builds_a_report_from_emulator_rows_alone(dirs):
    inc, stage = dirs
    put_stage(stage, [staged("05:00", "Fight at Marriott.")])
    assert mc.merge(DATE, inc, stage)["merged"] == 0
    assert not (inc / f"{DATE}.json").exists()   # must not create the file
    put_inc(inc, [])                             # the publish's empty skeleton
    assert mc.merge(DATE, inc, stage)["merged"] == 0
    assert read_inc(inc) == []


def test_merge_withholds_private_rows_and_house_numbers(dirs):
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("03:00", "Patient evaluation at Mercy Southwest."),
                      staged("03:20", "Juvenile reported self-harm at home."),
                      staged("04:00", "Burglary alarm at 1234 Main St.")])
    r = mc.merge(DATE, inc, stage)
    assert (r["merged"], r["private"]) == (1, 2)
    kept = [i for i in read_inc(inc) if i.get("source") == "crimeradar"]
    assert kept[0]["summary"] == "Burglary alarm at Main St."


def test_merge_skips_routine_rows_by_default(dirs):
    """Only serious app rows are merged; traffic stops stay out of the report."""
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("03:14", "Traffic stop near Real Road.", notability=2),
                      staged("04:24", "Report of armed man banging on door.")])
    assert mc.merge(DATE, inc, stage)["merged"] == 1
    kept = [i for i in read_inc(inc) if i.get("source") == "crimeradar"]
    assert [i["time"] for i in kept] == ["04:24"]


@pytest.mark.parametrize("bad", ["{not json", '{"incidents": 7}', "[]", ""])
def test_merge_never_raises_on_bad_staging(dirs, bad):
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    (stage / f"emulator_incidents_{DATE}.json").write_text(bad, encoding="utf-8")
    assert mc.merge(DATE, inc, stage)["merged"] == 0
    assert read_inc(inc) == TRANSCRIPT


def test_merge_never_raises_on_bad_incidents(dirs):
    inc, stage = dirs
    put_stage(stage, [staged("05:00", "Fight at Marriott.")])
    (inc / f"{DATE}.json").write_text("{broken", encoding="utf-8")
    assert mc.merge(DATE, inc, stage)["merged"] == 0
    assert (inc / f"{DATE}.json").read_text(encoding="utf-8") == "{broken"


def test_coverage_is_per_incident_not_whole_night():
    # shares "fire" + "oakley" with the 02:10 incident, but six hours away
    assert mc.covered_by("08:30", "Garage fire on Oakley St", TRANSCRIPT) is None
    assert mc.covered_by("02:30", "Garage fire on Oakley St", TRANSCRIPT) is not None
    # across midnight
    assert mc.covered_by("23:50", "Chase ends in crash on Union", TRANSCRIPT) is not None


# -------------------------------------------------------------------- emit
@pytest.fixture
def monitor(tmp_path, monkeypatch):
    """The monitor pointed at temp dirs, with the History sweep stubbed."""
    out, inc = tmp_path / "work", tmp_path / "incidents"
    out.mkdir(); inc.mkdir()
    monkeypatch.setattr(cr, "OUT", out)
    monkeypatch.setattr(cr, "INCIDENTS", inc)
    monkeypatch.setattr(cr, "_area_for", lambda title, places: places.get(title, ""))
    rows = [{"when": "Oct 4, 2026 5:00 AM", "title": "Fight at Marriott", "cy": 1},
            {"when": "Oct 4, 2026 2:14 AM", "title": "Garage fire on Oakley St", "cy": 2},
            {"when": "Oct 3, 2026 9:30 PM", "title": "Shots fired near park", "cy": 3},
            {"when": "Oct 3, 2026 6:00 PM", "title": "Out of window row", "cy": 4}]
    monkeypatch.setattr(cr, "history_sweep", lambda *a, **k: [dict(r) for r in rows])
    return out, inc


def test_emit_works_before_the_incidents_file_exists(monitor):
    out, inc = monitor
    e = cr.emit_incidents(DATE)
    assert "error" not in e and e["staged"] == 3 and e["have_incidents"] is False
    doc = json.loads((out / f"emulator_incidents_{DATE}.json").read_text(encoding="utf-8"))
    assert [i["time"] for i in doc["incidents"]] == ["21:30", "02:14", "05:00"]
    assert not (inc / f"{DATE}.json").exists()    # staging only


def test_emit_never_writes_incidents_and_second_run_keeps_staging(monitor):
    out, inc = monitor
    put_inc(inc, TRANSCRIPT)
    before = (inc / f"{DATE}.json").read_bytes()
    cr.emit_incidents(DATE)
    assert (inc / f"{DATE}.json").read_bytes() == before
    mc.merge(DATE, inc, out)                      # publish merges...
    e2 = cr.emit_incidents(DATE)                  # ...then the emit runs again
    assert e2["staged"] == 3                      # staging is NOT emptied
    assert mc.merge(DATE, inc, out)["changed"] is False


def test_emit_refuses_an_empty_window(monitor, monkeypatch):
    out, _ = monitor
    good = out / f"emulator_incidents_{DATE}.json"
    cr.emit_incidents(DATE)
    kept = good.read_bytes()
    monkeypatch.setattr(cr, "history_sweep", lambda *a, **k: [
        {"when": "Oct 3, 2026 6:00 PM", "title": "Out of window row", "cy": 4}])
    e = cr.emit_incidents(DATE)
    assert e.get("alarm") and good.read_bytes() == kept


def test_emulator_rows_can_never_be_the_lead_story(monitor):
    out, _ = monitor
    cr.emit_incidents(DATE)
    doc = json.loads((out / f"emulator_incidents_{DATE}.json").read_text(encoding="utf-8"))
    assert max(i["notability"] for i in doc["incidents"]) <= 3


# ------------------------------------------------------------ process / UI
def test_children_never_inherit_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "emulator-5554\tdevice\n", "")
    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    assert cr.device_online() is True
    assert seen["stdin"] is subprocess.DEVNULL


@pytest.mark.parametrize("line,ok", [("emulator-5554\tdevice", True),
                                     ("emulator-5554\toffline", False),
                                     ("emulator-5554\tunauthorized", False),
                                     ("emulator-5556\tdevice", False)])
def test_device_online_parses_state(monkeypatch, line, ok):
    monkeypatch.setattr(cr, "_run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, f"List of devices attached\n{line}\n", ""))
    assert cr.device_online() is ok


def test_dump_ui_never_returns_a_stale_screen(tmp_path, monkeypatch):
    """A failed dump must raise, not hand back the previous dump's XML."""
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    (tmp_path / "cr.xml").write_text("<hierarchy>OLD SCREEN</hierarchy>", encoding="utf-8")
    monkeypatch.setattr(cr, "adb", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "ERROR: could not get idle state."))
    with pytest.raises(RuntimeError):
        cr.dump_ui("cr")


def test_lock_excludes_a_second_run_and_goes_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr, "LOCK", tmp_path / "emulator.lock")
    monkeypatch.setattr(cr, "_HAVE_LOCK", False)
    assert cr.acquire_lock(0) is True
    monkeypatch.setattr(cr, "_HAVE_LOCK", False)          # a different process
    assert cr.acquire_lock(0) is False
    monkeypatch.setattr(cr, "LOCK_STALE", -1)             # holder went silent
    assert cr.acquire_lock(0) is True
    cr.release_lock()
    assert not (tmp_path / "emulator.lock").exists()


def test_seen_expires_and_reads_the_legacy_list(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "OUT", tmp_path)
    (tmp_path / "seen.json").write_text('["aaa", "bbb"]', encoding="utf-8")
    assert cr.load_seen()["aaa"]["done"] is True
    old = (dt.datetime.now() - dt.timedelta(hours=cr.SEEN_TTL_H + 1)).isoformat()
    cr.save_seen({"old": {"first": old, "tries": 3, "done": False},
                  "new": {"first": dt.datetime.now().isoformat(), "tries": 1, "done": False}})
    assert set(cr.load_seen()) == {"new"}


# -------------------------------------------------------------------- reel
def test_night_polls_span_both_calendar_days(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "OUT", tmp_path)
    card = {"title": "Vehicle fire near Winchester", "place": "Winchester St"}
    (tmp_path / "polls_2026-10-03.jsonl").write_text(
        json.dumps({"ts": "20261003-181500", "cards": [{"title": "afternoon", "place": "X"}]}) + "\n" +
        json.dumps({"ts": "20261003-221500", "cards": [card]}) + "\n", encoding="utf-8")
    (tmp_path / "polls_2026-10-04.jsonl").write_text(
        json.dumps({"ts": "20261004-031500", "cards": [{"title": "late", "place": "Y St"}]}) + "\n",
        encoding="utf-8")
    assert [p["ts"] for p in cr._night_polls(DATE)] == ["20261003-221500", "20261004-031500"]
    assert cr._poll_places(DATE) == {"Vehicle fire near Winchester": "Winchester St",
                                     "late": "Y St"}


CLIPS = [{"file": "01.mp3", "title": "Vehicle fire in parking lot near Winchester",
          "approx_time": "2026-10-03 23:20:00"},
         {"file": "02.mp3", "title": "Toddler missing near kids carnival carousel",
          "approx_time": "2026-10-04 00:40:00"}]


def test_reel_matcher_reads_am_pm_and_needs_shared_words():
    fire = {"headline": "Car fire in a parking lot", "time": "11:30 PM"}
    assert mda.match_emulator_clip(fire, CLIPS, set())["file"] == "01.mp3"
    child = {"headline": "Missing toddler found at carnival", "time": "12:45 AM"}
    assert mda.match_emulator_clip(child, CLIPS, set())["file"] == "02.mp3"
    # right time, unrelated story: time alone must never attach a clip
    other = {"headline": "Burglary suspect arrested downtown", "time": "11:25 PM"}
    assert mda.match_emulator_clip(other, CLIPS, set()) is None
    # right words, wrong hour
    assert mda.match_emulator_clip({"headline": "Car fire in a parking lot",
                                    "time": "3:30 AM"}, CLIPS, set()) is None
    # never reused
    assert mda.match_emulator_clip(fire, CLIPS, {"01.mp3"}) is None


# ------------------------------------------------- editorial rules (owner)
def _notability(title):
    tier = 3
    for t, pat in cr.ESCALATE:
        if t < tier and pat.search(title):
            tier = t
            break
    return cr.TIER_NOTABILITY[tier]


@pytest.mark.parametrize("title,published", [
    # big fires and police chases stay
    ("Apartment fire response near West Plymouth", True),
    ("Structure fire with flames through the roof", True),
    ("Brush fire spreading near Highway 58", True),
    ("High-speed BMW chase ends in crash", True),
    ("Pursuit of stolen truck on Highway 99", True),
    # small fires are routine
    ("Small vegetation fire damages power pole", False),
    ("Illegal trash fire in backyard", False),
    ("Fire alarm at middle school", False),
    # most medical calls are out
    ("Fall patient reported at Plaza Towers", False),
    ("Medical aid requested near Bernard Street", False),
    ("Person with chest pain at main gate", False),
    ("ill patient reported at racina and a street", False),
    ("Person with difficulty breathing at MacArthur Drive", False),
    ("Seizure reported at bus stop", False),
    # ...unless severe
    ("Unconscious woman receiving CPR at Kern River Campground", True),
    ("Possible drowning at Lake Ming", True),
    ("Unresponsive man found in vehicle", True),
    # never, however serious
    ("Juvenile reported self-harm at home", False),
    ("Person with psychiatric issue near Montclair Street", False),
    ("Maternity patient unresponsive in street", False),
    # routine police traffic is out
    ("Traffic stop on East Tehachapi Boulevard", False),
])
def test_what_reaches_the_report(title, published):
    ok = not mc.is_private(title) and _notability(title) >= mc.MIN_NOTABILITY
    assert ok is published


# ------------------------------------------- 7 PM - 7 AM window + gap filling
def test_report_window_is_seven_pm_to_seven_am():
    lo, hi = cr.report_window("2026-10-04")
    assert (lo.year, lo.month, lo.day, lo.hour) == (2026, 10, 3, 19)
    assert (hi.year, hi.month, hi.day, hi.hour) == (2026, 10, 4, 7)


@pytest.mark.parametrize("hhmm,radio", [
    # the radio feed's own hours
    ("21:00", True), ("23:59", True), ("00:00", True), ("05:29", True),
    # the hours only the emulator covers
    ("19:00", False), ("20:59", False), ("05:30", False), ("06:59", False),
    # unreadable times take the stricter rule
    ("", True), ("nonsense", True), ("25:00", True),
])
def test_in_radio_hours(hhmm, radio):
    assert mc.in_radio_hours(hhmm) is radio


def test_gap_hours_merge_routine_rows_and_radio_hours_do_not(dirs):
    """7-9 PM and 5:30-7 AM have no radio audio, so every app row fills them.

    Inside the feed's own hours the serious-only floor still applies, so the
    emulator cannot pad the part of the night the transcript already covers.
    """
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("19:12", "Traffic stop on Rosedale Highway.", notability=2),
                      staged("20:30", "Welfare check on Chester Avenue.", notability=2),
                      staged("06:15", "Vandalism report at a park.", notability=2),
                      staged("22:40", "Traffic stop on Ming Avenue.", notability=2),
                      staged("03:14", "Traffic stop near Real Road.", notability=2),
                      staged("23:20", "House fire reported on Wilson Road.", notability=3)])
    r = mc.merge(DATE, inc, stage)
    kept = [i for i in read_inc(inc) if i.get("source") == "crimeradar"]
    # the three gap rows plus the serious radio-hour one; the two routine
    # radio-hour rows stay out (the merge preserves the staged order, and the
    # monitor stages chronologically)
    assert sorted(i["time"] for i in kept) == sorted(["19:12", "20:30", "23:20", "06:15"])
    assert {i["time"] for i in kept} == {"19:12", "20:30", "23:20", "06:15"}
    assert r["gap"] == 3
    assert r["merged"] == 4


def test_every_gap_row_in_the_report_came_from_the_emulator(dirs):
    """The gap hours have no other source: nothing is invented to fill them."""
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("19:05", "Traffic stop on Coffee Road.", notability=2)])
    mc.merge(DATE, inc, stage)
    after = read_inc(inc)
    gap_rows = [i for i in after if not mc.in_radio_hours(i["time"])]
    assert gap_rows
    assert all(i.get("source") == "crimeradar" for i in gap_rows)
    # and the radio hours are untouched by the gap rule
    assert all(i.get("source") != "crimeradar"
               for i in after if i.get("time") in ("00:04", "02:10"))
