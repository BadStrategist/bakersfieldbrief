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

And the guard set added after the 2026-10-06..09 outage, when the second source
was down for three nights and then came back serving Mendocino County:

  * a system ANR dialog and a keyguard were both reported as "the app UI has
    likely changed";
  * every staged row was stamped with the Bakersfield feed whatever the screen
    showed, so a Mendocino state would have staged Willits rows as Kern;
  * a failed emit left nothing behind, so it looked like "nothing to do";
  * the publish pushed the report with no second source and nobody was told.

The XML under tests/fixtures/crimeradar/ is captured from the emulator, not
written by hand: anr_system_ui / anr_app (the two ANR dialogs), home_kern,
replay_kern / history_kern, replay_mendocino / history_mendocino (2026-10-09,
the wrong-region state).

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar.py -q
Fully offline: no emulator, no adb, no network.
"""
from __future__ import annotations

import datetime as dt
import json
import os
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
FIX = ROOT / "tests" / "fixtures" / "crimeradar"
KERN = {"name": mc.FEED_NAME, "location": mc.FEED_LOCATION}
MENDOCINO = {"name": "Mendocino County Sheriff, Fire, EMS, Cal Fire and CHP",
             "location": "Mendocino, California"}


def fx(name):
    return (FIX / f"{name}.xml").read_text(encoding="utf-8")

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


def put_stage(stage, rows, **doc):
    # the header a real 07:15 emit wrote for this date (Oct 4), plus the feed
    doc = {"date": DATE, "generated": f"{DATE}T07:16:46", "feed": KERN,
           "history_newest": f"{DATE} 05:24", "history_oldest": "2026-10-03 10:27",
           "history_complete": True, "incidents": rows, **doc}
    (stage / f"emulator_incidents_{DATE}.json").write_text(
        json.dumps(doc), encoding="utf-8")


def put_inc(inc, rows):
    (inc / f"{DATE}.json").write_text(json.dumps(rows), encoding="utf-8")


def read_inc(inc):
    return json.loads((inc / f"{DATE}.json").read_text(encoding="utf-8"))


def _night_epoch(date_iso: str, hhmm: str) -> int:
    """The epoch of a clock time in the night of report <date_iso>.

    The night opens at 19:00 and closes at 07:00, so every evening hour (and a
    block that starts early, like 18:47) is on the opening day, and only the
    small hours are on the report's own date.
    """
    d = dt.date.fromisoformat(date_iso) - dt.timedelta(days=1)
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    day = d if h >= 12 else d + dt.timedelta(days=1)
    return int(dt.datetime.combine(day, dt.time(h, m), mc.PACIFIC).timestamp())


def write_transcript(tdir, date_iso: str, block_starts):
    """A transcript whose rows name `block_starts` as the blocks they came from."""
    tdir.mkdir(parents=True, exist_ok=True)
    rows = [{"time_local": s, "text": "copy", "duration": 2.0, "confidence": 0.9,
             "engine": "faster-whisper:large-v3",
             "source_file": f"14029-{_night_epoch(date_iso, s)}.mp3"}
            for s in block_starts]
    (tdir / f"{date_iso}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return tdir


def feed_hour_blocks(date_iso: str):
    """Block starts that tile 21:00 -> 05:30, the hours the feed carries."""
    return [f"{(21 * 60 + 30 * step) // 60 % 24:02d}:{30 * step % 60:02d}"
            for step in range(0, 17)]


@pytest.fixture(autouse=True)
def night_transcript(tmp_path_factory, monkeypatch):
    """Every test runs with the transcript a real night would have.

    The spans are read from it, so without one there are no radio hours at all.
    A test that needs that case passes a directory with no file for the date.
    """
    tdir = write_transcript(tmp_path_factory.mktemp("transcripts"), DATE,
                            feed_hour_blocks(DATE))
    monkeypatch.setattr(mc, "TRANSCRIPTS", tdir)
    return tdir


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
    monkeypatch.setattr(cr, "SWEPT_FEED", dict(KERN))   # what a Kern sweep leaves
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
    # the hours the night's blocks cover
    ("21:00", True), ("23:59", True), ("00:00", True), ("05:29", True),
    # the 05:00 block runs to 05:30:29, so 05:30 is a covered minute
    ("05:30", True),
    # the hours only the emulator covers
    ("19:00", False), ("20:59", False), ("06:15", False), ("06:59", False),
    # unreadable times take the stricter rule
    ("", True), ("nonsense", True), ("25:00", True),
])
def test_in_radio_follows_the_night_transcript(hhmm, radio, night_transcript):
    """The spans are the transcript's own blocks; no constant decides this."""
    spans = mc.radio_spans(DATE, night_transcript)
    assert mc.in_radio(hhmm, spans, DATE) is radio


def test_the_shoulders_become_radio_hours_when_their_blocks_arrive(tmp_path):
    """A transcript that reaches back to 19:00 makes the evening a radio hour."""
    tdir = write_transcript(tmp_path / "t", DATE, ["19:05", "19:35", "20:05"])
    spans = mc.radio_spans(DATE, tdir)
    assert mc.in_radio("19:20", spans, DATE) is True
    assert mc.in_radio("20:15", spans, DATE) is True
    assert mc.in_radio("03:00", spans, DATE) is False


def test_no_transcript_means_no_radio_hours(tmp_path):
    """No readable transcript: no radio hours, every hour is a gap hour."""
    assert mc.radio_spans(DATE, tmp_path / "empty") == []
    assert mc.in_radio("23:00", [], DATE) is False


def test_radio_spans_ignores_rows_that_name_no_block(tmp_path):
    """A row that names no archive block tells us nothing about coverage."""
    tdir = tmp_path / "t"
    tdir.mkdir()
    (tdir / f"{DATE}.jsonl").write_text(
        '{"text": "copy", "source_file": "live-stream"}\n', encoding="utf-8")
    assert mc.radio_spans(DATE, tdir) == []


def test_a_straddling_18_47_block_makes_19_05_a_radio_hour(dirs, tmp_path):
    """The block that starts at 18:47 carries 19:00-19:17, so 19:05 is covered."""
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("19:05", "Traffic stop on Rosedale Highway.",
                             notability=2)])
    # with no transcript on disk every hour is a gap hour: the routine row stays
    assert mc.merge(DATE, inc, stage, tmp_path / "nothing")["merged"] == 1
    put_inc(inc, TRANSCRIPT)                    # back to the transcript alone
    tdir = write_transcript(tmp_path / "t", DATE, ["18:47"])
    r = mc.merge(DATE, inc, stage, tdir)
    assert (r["merged"], r["gap"]) == (0, 0)    # inside the span: serious only


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


def test_every_gap_row_in_the_report_came_from_the_emulator(dirs,
                                                             night_transcript):
    """The gap hours have no other source: nothing is invented to fill them."""
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    put_stage(stage, [staged("19:05", "Traffic stop on Coffee Road.", notability=2)])
    mc.merge(DATE, inc, stage, night_transcript)
    after = read_inc(inc)
    spans = mc.radio_spans(DATE, night_transcript)
    gap_rows = [i for i in after if not mc.in_radio(i["time"], spans, DATE)]
    assert gap_rows
    assert all(i.get("source") == "crimeradar" for i in gap_rows)
    # and the radio hours are untouched by the gap rule
    assert all(i.get("source") != "crimeradar"
               for i in after if i.get("time") in ("00:04", "02:10"))


# ------------------------------------------------ what was actually on screen
def fake_adb(xml=None, fail="", activity="", window=""):
    """An adb whose `pull` delivers this dump (or whose dump fails with `fail`)."""
    def adb(*args, **kw):
        out = ""
        if args[0] == "pull" and xml is not None:
            Path(args[2]).write_text(xml, encoding="utf-8")
        elif args[:3] == ("shell", "dumpsys", "activity"):
            out = activity
        elif args[:3] == ("shell", "dumpsys", "window"):
            out = window
        return subprocess.CompletedProcess(args, 1 if fail else 0, out, fail)
    return adb


@pytest.mark.parametrize("dump,title", [
    ("anr_system_ui", "System UI isn't responding"),
    ("anr_app", "CrimeRadar isn't responding"),
])
def test_a_system_dialog_is_named_with_its_own_exit_code(tmp_path, monkeypatch, dump, title):
    assert cr.system_dialog(fx(dump)) == title
    assert cr.system_dialog(fx("home_kern")) is None
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "adb", fake_adb(fx(dump)))
    with pytest.raises(cr.SystemDialog) as ei:
        cr.dump_ui("cr")
    assert ei.value.code == 7
    text = cr.alarm_text(ei.value)
    assert title in text and "package android" in text
    assert "likely changed" not in text and "Play Store" not in text


def test_a_locked_screen_is_reported_as_a_keyguard(tmp_path, monkeypatch):
    """2026-10-09: a keyguard gave "null root node", reported as a UI change."""
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "adb", fake_adb(
        fail="ERROR: null root node returned by UiTestAutomationBridge.",
        activity="  topResumedActivity=ActivityRecord{5804e16 u0 "
                 "com.newsbreak.crimeradar/com.particlemedia.feature.home.RadarHomeActivity t25}",
        window="    isKeyguardShowing=true\n"))
    with pytest.raises(cr.Unreadable) as ei:
        cr.dump_ui("cr")
    assert ei.value.code == 8
    text = cr.alarm_text(ei.value)
    assert "null root node" in text and "keyguard showing" in text
    assert "foreground package com.newsbreak.crimeradar" in text
    assert "likely changed" not in text


@pytest.fixture
def poller(tmp_path, monkeypatch):
    """poll() against one fixed screen, no emulator."""
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "normalise_feed", lambda: None)
    monkeypatch.setattr(cr, "dismiss_overlays", lambda *a, **k: [])

    def show(xml):
        monkeypatch.setattr(cr, "dump_ui", lambda *a, **k: xml)
    return tmp_path, show


def app_screen(*texts, package=cr.PKG):
    nodes = "".join(f'<node index="0" text="{t}" resource-id="" package="{package}" '
                    f'bounds="[0,{i * 40}][700,{i * 40 + 40}]" />'
                    for i, t in enumerate(texts))
    return f"<hierarchy rotation=\"0\">{nodes}</hierarchy>"


def test_zero_cards_alarm_says_what_was_on_screen(poller, capsys):
    """2026-10-09: the app showed "Couldn't load updates"; the alarm blamed a UI change."""
    _, show = poller
    show(app_screen("Bakersfield", "Couldn't load updates", "Retry"))
    assert cr.poll() == 4
    err = capsys.readouterr().err
    assert "Couldn't load updates" in err and f"package {cr.PKG}" in err
    assert "likely changed" not in err and "Play Store" not in err


def test_zero_cards_under_another_app_is_unreadable_not_a_ui_change(poller):
    _, show = poller
    show(app_screen("Phone", "Messages", package="com.google.android.apps.nexuslauncher"))
    with pytest.raises(cr.Unreadable) as ei:
        cr.poll()
    assert ei.value.code == 8 and "nexuslauncher" in str(ei.value)


# ------------------------------------------------------------- the wrong feed
def test_feed_identity_is_read_off_the_screen():
    assert cr.home_feed(fx("home_kern")) == ("Bakersfield", True)
    assert cr.replay_feeds(fx("replay_kern")) == [KERN]
    assert cr.replay_feeds(fx("replay_mendocino")) == [MENDOCINO]
    assert cr.history_feed(fx("history_kern"), []) == KERN
    # scrolled: the name is the toolbar title, the location comes from Replay
    assert cr.history_feed(fx("history_mendocino"),
                           cr.replay_feeds(fx("replay_mendocino"))) == MENDOCINO
    assert mc.is_kern_feed(KERN) and not mc.is_kern_feed(MENDOCINO)
    # a name with no location on screen is not verified
    assert not mc.is_kern_feed(cr.history_feed(fx("history_mendocino"), []))
    assert not mc.is_kern_feed({"name": mc.FEED_NAME, "location": ""})
    assert not mc.is_kern_feed(None)


def test_poll_record_carries_the_feed_the_screen_showed(poller):
    out, show = poller
    show(fx("home_kern"))
    assert cr.poll() == 0
    recs = [json.loads(line) for f in out.glob("polls_*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["feed"] == "Bakersfield" and recs[0]["n_cards"] > 0


CHIP = 'text="Bakersfield" resource-id="com.newsbreak.crimeradar:id/txt_location_feed_tab"'


@pytest.mark.parametrize("old,new,says", [
    # the 2026-10-09 state: the app's picker sat on a Mendocino County address
    (CHIP, CHIP.replace("Bakersfield", "5000 Vista Del Lago Rd"), "5000 Vista Del Lago Rd"),
    # the chip is a tab: with Nationwide selected it no longer names the feed
    ('selected="true" bounds="[83,169][248,241]"',
     'selected="false" bounds="[83,169][248,241]"', "not the selected tab"),
])
def test_poll_refuses_a_feed_that_is_not_kern(poller, old, new, says):
    out, show = poller
    xml = fx("home_kern")
    assert xml.count(old) == 1
    show(xml.replace(old, new))
    with pytest.raises(cr.WrongFeed) as ei:
        cr.poll()
    assert ei.value.code == 9 and says in str(ei.value)
    assert not list(out.glob("polls_*.jsonl"))      # nothing recorded
    assert not (out / "seen.json").exists()


@pytest.fixture
def sweeper(tmp_path, monkeypatch):
    """The real History sweep and main(), driven by captured screens."""
    out, inc = tmp_path / "work", tmp_path / "incidents"
    out.mkdir(); inc.mkdir()
    monkeypatch.setattr(cr, "OUT", out)
    monkeypatch.setattr(cr, "INCIDENTS", inc)
    monkeypatch.setattr(cr, "LOCK", out / "emulator.lock")
    monkeypatch.setattr(cr, "_HAVE_LOCK", False)
    monkeypatch.setattr(cr, "SWEPT_FEED", {})
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "device_online", lambda: True)
    monkeypatch.setattr(cr, "adb", fake_adb())

    def show(region):
        monkeypatch.setattr(cr, "goto_history",
                            lambda: cr.replay_feeds(fx(f"replay_{region}")))
        monkeypatch.setattr(cr, "dump_ui", lambda *a, **k: fx(f"history_{region}"))
    return out, show


def run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["crimeradar_monitor.py", *argv])
    return cr.main()


def emit_status(out):
    return json.loads((out / f"emit_status_{DATE}.json").read_text(encoding="utf-8"))


def test_history_sweep_reads_kern_and_refuses_mendocino(sweeper):
    _, show = sweeper
    show("kern")
    rows = cr.history_sweep()
    assert rows and cr.SWEPT_FEED == KERN
    show("mendocino")
    with pytest.raises(cr.WrongFeed) as ei:
        cr.history_sweep()
    assert ei.value.code == 9 and "Mendocino" in str(ei.value)
    assert cr.SWEPT_FEED == MENDOCINO


def test_emit_on_the_wrong_feed_stages_nothing_and_says_why(sweeper, monkeypatch, capsys):
    """The Willits-rows-as-Bakersfield fault: exit 9, no staging file, a status file."""
    out, show = sweeper
    show("mendocino")
    assert run_main(monkeypatch, "--emit", DATE) == 9
    assert not (out / f"emulator_incidents_{DATE}.json").exists()
    st = emit_status(out)
    assert (st["rc"], st["ok"], st["outcome"]) == (9, False, "wrong_feed")
    assert st["feed"] == MENDOCINO and "Mendocino" in st["reason"]
    assert "Mendocino" in capsys.readouterr().err
    assert not (out / "emulator.lock").exists()


def test_emit_stamps_rows_and_status_with_the_verified_feed(monitor, monkeypatch):
    out, _ = monitor
    monkeypatch.setattr(cr, "LOCK", out / "emulator.lock")
    monkeypatch.setattr(cr, "_HAVE_LOCK", False)
    monkeypatch.setattr(cr, "device_online", lambda: True)
    assert run_main(monkeypatch, "--emit", DATE) == 0
    doc = json.loads((out / f"emulator_incidents_{DATE}.json").read_text(encoding="utf-8"))
    assert doc["feed"] == KERN
    assert {i["agency"] for i in doc["incidents"]} == {KERN["name"]}
    st = emit_status(out)
    assert (st["rc"], st["ok"], st["outcome"], st["staged"]) == (0, True, "staged", 3)
    assert st["feed"] == KERN and st["history_complete"] is True


@pytest.mark.parametrize("swept", [{}, MENDOCINO, {"name": mc.FEED_NAME, "location": ""}])
def test_emit_never_stages_an_unverified_feed(monitor, monkeypatch, swept):
    """Belt and braces: even a sweep that returned rows stages nothing unverified."""
    out, _ = monitor
    monkeypatch.setattr(cr, "SWEPT_FEED", dict(swept))
    e = cr.emit_incidents(DATE)
    assert e.get("wrong_feed") and e.get("alarm")
    assert not (out / f"emulator_incidents_{DATE}.json").exists()


def test_every_failed_emit_leaves_a_status_file(monitor, monkeypatch):
    out, _ = monitor
    monkeypatch.setattr(cr, "LOCK", out / "emulator.lock")
    monkeypatch.setattr(cr, "_HAVE_LOCK", False)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    # the device is offline
    monkeypatch.setattr(cr, "device_online", lambda: False)
    assert run_main(monkeypatch, "--emit", DATE) == 2
    assert emit_status(out)["outcome"] == "device_offline"
    # History has no row in the window
    monkeypatch.setattr(cr, "device_online", lambda: True)
    monkeypatch.setattr(cr, "history_sweep", lambda *a, **k: [
        {"when": "Oct 3, 2026 6:00 PM", "title": "Out of window row", "cy": 4}])
    assert run_main(monkeypatch, "--emit", DATE) == 4
    st = emit_status(out)
    assert st["outcome"] == "empty_window" and "no rows inside" in st["reason"]
    # a system dialog covers the screen

    def dialog(*a, **k):
        raise cr.SystemDialog('a system dialog covers the screen: "System UI isn\'t responding"')
    monkeypatch.setattr(cr, "history_sweep", dialog)
    assert run_main(monkeypatch, "--emit", DATE) == 7
    st = emit_status(out)
    assert st["outcome"] == "system_dialog" and "System UI" in st["reason"]
    # a bug nobody planned for still leaves a record
    monkeypatch.setattr(cr, "history_sweep", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        run_main(monkeypatch, "--emit", DATE)
    st = emit_status(out)
    assert st["ok"] is False and "ZeroDivisionError" in st["reason"]
    assert not (out / f"emulator_incidents_{DATE}.json").exists()


# ------------------------------------------------ readiness + the publish gate
def test_merge_refuses_rows_that_are_not_stamped_kern(dirs):
    inc, stage = dirs
    put_inc(inc, TRANSCRIPT)
    for feed in (None, MENDOCINO):
        put_stage(stage, [staged("05:00", "Fatality reported on Highway 20 in Willits.")],
                  feed=feed)
        r = mc.merge(DATE, inc, stage)
        assert r["merged"] == 0 and r["changed"] is False and "Kern feed" in r["note"]
        assert read_inc(inc) == TRANSCRIPT


def test_readiness_is_zero_only_for_a_verified_fresh_complete_kern_night(dirs):
    _, stage = dirs
    rows = [staged("05:00", "Fight at Marriott.")]
    put_stage(stage, rows)
    r = mc.readiness(DATE, stage)
    assert (r["code"], r["ok"]) == (mc.READY, True)
    for doc, code in [
        ({"feed": MENDOCINO}, mc.WRONG_FEED),
        ({"feed": None}, mc.WRONG_FEED),                 # staged before the stamp existed
        ({"generated": "2026-10-03T07:16:46"}, mc.STALE),        # another morning's run
        ({"generated": f"{DATE}T02:00:00"}, mc.STALE),           # before the night ended
        ({"date": "2026-10-03"}, mc.STALE),
        ({"history_newest": f"{DATE} 01:10"}, mc.STALE),         # the app had stopped updating
        ({"history_newest": ""}, mc.STALE),
        ({"history_complete": False}, mc.INCOMPLETE),
    ]:
        put_stage(stage, rows, **doc)
        r = mc.readiness(DATE, stage)
        assert (r["code"], r["ok"]) == (code, False), doc
        assert r["reason"]


def test_readiness_tells_a_failed_emit_from_one_that_never_ran(dirs):
    _, stage = dirs
    r = mc.readiness(DATE, stage)
    assert r["code"] == mc.ABSENT and "never reached the monitor" in r["reason"]
    (stage / f"emit_status_{DATE}.json").write_text(json.dumps(
        {"ran": f"{DATE}T07:19:02", "rc": 9, "outcome": "wrong_feed",
         "reason": "History is for Mendocino"}), encoding="utf-8")
    r = mc.readiness(DATE, stage)
    assert r["code"] == mc.ABSENT
    assert "exited 9" in r["reason"] and "History is for Mendocino" in r["reason"]


@pytest.mark.parametrize("bad", ["{not json", '{"incidents": 7}', "[]", "", "null"])
def test_readiness_never_raises(dirs, bad):
    _, stage = dirs
    (stage / f"emulator_incidents_{DATE}.json").write_text(bad, encoding="utf-8")
    assert mc.readiness(DATE, stage)["code"] == mc.ABSENT
    assert mc.readiness("not-a-date", stage)["code"] == mc.ABSENT
    assert mc.readiness(None, stage)["ok"] is False


def test_gate_holds_without_a_second_source_until_a_human_releases_that_date(dirs):
    _, stage = dirs
    g = mc.gate(DATE, stage)
    assert g["release"] is False and g["code"] == mc.ABSENT
    (stage / "release_2026-10-03.txt").write_text("owner: ship it", encoding="utf-8")
    assert mc.gate(DATE, stage)["release"] is False          # another day's release
    (stage / f"release_{DATE}.txt").write_text("  \n", encoding="utf-8")
    assert mc.gate(DATE, stage)["release"] is False          # an empty file says nothing
    (stage / f"release_{DATE}.txt").write_text("owner: radio-only is fine today",
                                               encoding="utf-8")
    g = mc.gate(DATE, stage)
    assert g["release"] is True and g["released_by"] == f"release_{DATE}.txt"
    assert g["ok"] is False                                  # released, still not ready


def test_gate_opens_on_its_own_when_the_second_source_is_ready(dirs):
    _, stage = dirs
    put_stage(stage, [staged("05:00", "Fight at Marriott.")])
    g = mc.gate(DATE, stage)
    assert g["release"] is True and g["released_by"] == "second source"


# ------------------------------------------- getting back to History from anywhere
# Verified 2026-10-09: the 07:15 emit failed four mornings in a row with
# "could not reach Replay > History" while a "System UI isn't responding" dialog
# sat over the app. The old nav sent one unconditional BACK and then tapped a
# literal 360,1430, so the dialog was unreadable and unrecoverable.


def test_the_tab_bar_and_the_replay_selection_are_read_from_the_dump():
    assert cr._tab_bar(fx("home_kern")) is True
    assert cr._tab_bar(fx("replay_kern")) is True
    assert cr._tab_bar(fx("anr_system_ui")) is False
    assert cr._replay_selected(fx("replay_kern")) is True
    assert cr._replay_selected(fx("home_kern")) is False


def test_goto_history_recovers_from_a_system_dialog(tmp_path, monkeypatch):
    """ANR dialog -> tap Wait -> Home -> Replay -> History, all offline."""
    seen = []

    def adb(*args, **kw):
        seen.append(args)
        if args[0] == "pull":
            Path(args[2]).write_text(dumps[min(n["i"], len(dumps) - 1)], encoding="utf-8")
            n["i"] += 1
        return subprocess.CompletedProcess(args, 0, "", "")

    n = {"i": 0}
    dumps = [fx("anr_system_ui"), fx("home_kern"), fx("replay_kern")]

    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr, "adb", adb)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "dismiss_overlays", lambda *a, **k: [])

    feeds = cr.goto_history()
    assert feeds, "the Replay page's feeds should have been read"

    taps = [a for a in seen if a[:2] == ("shell", "input") and a[2] == "tap"]
    wait = cr._center(cr._by_id(fx("anr_system_ui"), "aerr_wait"))
    assert (str(wait[0]), str(wait[1])) in [(t[3], t[4]) for t in taps], \
        "the ANR dialog must be cleared by tapping Wait"
    label = cr._center(cr._by_id(fx("replay_kern"), "history_label"))
    assert (str(label[0]), str(label[1])) == (taps[-1][3], taps[-1][4]), \
        "the last tap must land on history_label, not a fixed coordinate"


def test_goto_history_says_what_it_saw_when_the_tab_bar_never_appears(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "OUT", tmp_path)
    monkeypatch.setattr(cr.time, "sleep", lambda s: None)
    monkeypatch.setattr(cr, "dismiss_overlays", lambda *a, **k: [])
    monkeypatch.setattr(cr, "adb", fake_adb(fx("anr_system_ui")))
    with pytest.raises(cr.ScreenError) as ei:
        cr.goto_history()
    assert "no tab bar" in str(ei.value) or "system dialog" in str(ei.value)
    assert ei.value.code == 7


# ------------------------------------------------------------------- the lock
def _dead_pid():
    """A pid that has certainly exited."""
    p = subprocess.run([sys.executable, "-c", "pass"])
    return p.pid if hasattr(p, "pid") and p.pid else 999999


def test_the_lock_is_reclaimable_when_its_owner_is_gone(tmp_path, monkeypatch):
    lock = tmp_path / "emulator.lock"
    monkeypatch.setattr(cr, "LOCK", lock)
    monkeypatch.setattr(cr, "OUT", tmp_path)

    lock.write_text(f"{os.getpid()} 2026-10-09T16:11:00", encoding="utf-8")
    assert cr.lock_reclaimable() is False
    assert cr.reclaim_lock_cli() == 1
    assert lock.exists(), "a live owner's lock must survive"

    lock.write_text(f"{_dead_pid()} 2026-10-09T16:11:00", encoding="utf-8")
    assert cr.lock_reclaimable() is True
    assert cr.reclaim_lock_cli() == 0
    assert not lock.exists(), "a dead owner's lock must be reclaimed"

    lock.write_text("not-a-pid", encoding="utf-8")
    assert cr.lock_reclaimable() is False, "an unparseable fresh lock counts as held"

    lock.unlink()
    assert cr.reclaim_lock_cli() == 0