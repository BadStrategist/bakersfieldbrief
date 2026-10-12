#!/usr/bin/env python3
"""The ALPR camera data must be provably today's, every day, and an outage must never be silent.

Before 2026-10-07 a failed Overpass fetch returned the last good camera list with ok=True. The
build stayed green, nobody was told, and the only symptom was an older "Data as of" date until
the Monday verify step. These tests pin the four states the source can be in and what each one
does to the run (scripts/check_alpr_fresh.py, the step every building workflow runs) and to
the page:

  fetched today                      -> fresh, run passes
  fetch failed, last good list       -> page keeps the list under ITS date, run FAILS
  fetch failed, no list at all       -> page says unavailable, run FAILS
  stale-but-serving, any date        -> run FAILS (a fallback never reads as green)

The stale flag is for CI only. It never reaches a page, a card or an email: the answer to an
outage is a red run and an ops alert, and the page stays honest through its date alone.

Nothing here touches the network: common.fetch is replaced and refuses any URL but Overpass,
and the snapshots and the change log live in tmp_path. The clock is pinned too.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build import common  # noqa: E402
from build.sources import alpr  # noqa: E402
import check_alpr_fresh as chk  # noqa: E402

# tests/test_alpr_new_week.py assigns its own common.fetch / load_snapshot / save_snapshot and
# never puts them back. Hold the real ones from import time (collection, before any test body
# runs) so these tests exercise the real snapshot code whatever order the suite runs in.
_REAL = {n: getattr(common, n) for n in
         ("load_snapshot", "save_snapshot", "load_change_log", "append_change_log")}

TODAY = "2026-10-07"          # a Wednesday: not the Monday change-log day
YESTERDAY = "2026-10-06"
NOW = dt.datetime(2026, 10, 7, 6, 12, tzinfo=chk.PACIFIC)


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _node(nid, stamp="2026-09-01", version=1):
    return {"id": nid, "lat": 35.37, "lon": -119.02, "timestamp": f"{stamp}T00:00:00Z",
            "version": version,
            "tags": {"manufacturer": "Flock Safety", "surveillance:type": "ALPR"}}


def _camera(nid, mapped="2026-09-01"):
    return {"id": nid, "lat": 35.37, "lon": -119.02, "manufacturer": "Flock Safety",
            "operator": "", "direction": "", "mapped": mapped, "edited": mapped,
            "start_date": "", "camera_type": ""}


@pytest.fixture
def box(tmp_path, monkeypatch):
    """An offline sandbox: tmp snapshots and change log, a pinned Pacific date, a scripted
    Overpass. box.reply is what the next fetch returns; an Exception instance is raised."""
    snap, logs = tmp_path / "snapshots", tmp_path / "change_logs"
    snap.mkdir()
    logs.mkdir()
    monkeypatch.setattr(common, "SNAP", snap)
    monkeypatch.setattr(common, "LOGS", logs)
    for name, fn in _REAL.items():
        monkeypatch.setattr(common, name, fn)
    state = types.SimpleNamespace(today=TODAY, reply={"elements": []}, calls=[],
                                  snap=snap, logs=logs, by_url={}, v1={})
    monkeypatch.setattr(common, "today_pacific", lambda: dt.date.fromisoformat(state.today))

    def fake_fetch(url, **kw):
        """box.reply answers every Overpass server; box.by_url[url] overrides one of them.
        box.v1[node id] is the creation date the OSM history API gives (absent: it fails)."""
        state.calls.append(url)
        prefix = alpr.OSM_V1.split("{id}")[0]
        if url.startswith(prefix):
            nid = int(url[len(prefix):].split("/")[0])
            if nid not in state.v1:
                raise ConnectionError("api.openstreetmap.org down")
            return _Resp({"elements": [{"id": nid, "version": 1,
                                        "timestamp": f"{state.v1[nid]}T00:00:00Z"}]})
        assert url in (alpr.OVERPASS, *alpr.BACKENDS), f"a test reached for the network: {url}"
        reply = state.by_url.get(url, state.reply)
        if isinstance(reply, Exception):
            raise reply
        return _Resp(reply)

    monkeypatch.setattr(common, "fetch", fake_fetch)
    return state


def _seed_last(box, asof=YESTERDAY, n=3):
    cams = [_camera(100 + i) for i in range(n)]
    common.save_snapshot("alpr_last", {"cameras": cams, "asof": asof,
                                       "stats": {"total": n, "flock": n, "new_this_week": 0,
                                                 "newest_mapped": "2026-09-01"}})
    return cams


# ---------------------------------------------------------------- the source: four states
class TestSource:
    def test_successful_fetch_is_fresh_and_dated_today(self, box):
        box.reply = {"elements": [_node(1), _node(2)]}
        data = alpr.run(None)
        assert data["ok"] is True
        assert data["stale"] is False            # explicit, not merely absent
        assert data["asof"] == TODAY
        assert data["stats"]["total"] == 2
        assert "error" not in data
        last = common.load_snapshot("alpr_last")
        assert last["asof"] == TODAY and len(last["cameras"]) == 2

    def test_failed_fetch_serves_the_last_good_list_and_says_so(self, box):
        cams = _seed_last(box, asof=YESTERDAY)
        box.reply = ConnectionError("overpass-api.de timed out")
        data = alpr.run(None)
        # the 2026-09-22 fix stands: the page still has its cameras
        assert data["ok"] is True and data["cameras"] == cams
        # ...but the outage is on the record, with the date of the list actually served
        assert data["stale"] is True
        assert data["asof"] == YESTERDAY
        assert "timed out" in data["error"]

    def test_failed_fetch_never_restamps_the_last_good_list(self, box):
        """The fallback must not advance its own date: that is what would turn a week-long
        outage into a page that says "Data as of today"."""
        _seed_last(box, asof="2026-10-01")
        box.reply = ConnectionError("down")
        for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
            box.today = day
            assert alpr.run(None)["asof"] == "2026-10-01"
        assert common.load_snapshot("alpr_last")["asof"] == "2026-10-01"

    def test_failed_fetch_with_no_snapshot_is_not_ok(self, box):
        box.reply = ConnectionError("down")
        data = alpr.run(None)
        assert data["ok"] is False
        assert "down" in data["error"]
        assert not data.get("cameras")

    def test_overpass_error_remark_is_a_failed_fetch(self, box):
        """HTTP 200 with a timeout remark and no elements is an outage, not "0 cameras"."""
        _seed_last(box)
        box.reply = {"elements": [], "remark": "runtime error: Query timed out in \"query\""}
        data = alpr.run(None)
        assert data["stale"] is True and data["asof"] == YESTERDAY and len(data["cameras"]) == 3

    def test_truncated_reply_is_a_failed_fetch(self, box):
        _seed_last(box)
        common.save_snapshot("alpr_nodes", list(range(100)))
        box.reply = {"elements": [_node(i) for i in range(40)]}      # under 60% of 100
        data = alpr.run(None)
        assert data["stale"] is True and data["asof"] == YESTERDAY


# ---------------------------------------------------------------- the fetch itself
class TestFetch:
    """2026-10-10 to 2026-10-12: a query with no declared budget asked a busy Overpass for the
    defaults (180 s, 512 MB) and was refused at the door with a 504, run after run."""

    def test_query_declares_a_small_budget_and_keeps_the_node_metadata(self):
        assert alpr.QUERY.startswith("[out:json][timeout:25][maxsize:33554432];")
        # the first-mapped logic reads version and timestamp from `out meta`
        assert alpr.QUERY.endswith("out meta;")

    def test_a_refusing_front_door_fails_over_to_its_backends_in_order(self, box):
        box.by_url[alpr.OVERPASS] = ConnectionError("504 Gateway Timeout")
        box.by_url[alpr.BACKENDS[0]] = ConnectionError("429 Too Many Requests")
        box.reply = {"elements": [_node(1), _node(2)]}
        data = alpr.run(None)
        assert data["stale"] is False and data["asof"] == TODAY and data["stats"]["total"] == 2
        assert box.calls == [alpr.OVERPASS, *alpr.BACKENDS]

    def test_a_healthy_front_door_is_the_only_server_asked(self, box):
        box.reply = {"elements": [_node(1)]}
        alpr.run(None)
        assert box.calls == [alpr.OVERPASS]

    def test_a_timeout_remark_fails_over_too(self, box):
        box.by_url[alpr.OVERPASS] = {"elements": [], "remark": "runtime error: Query timed out"}
        box.reply = {"elements": [_node(1)]}
        data = alpr.run(None)
        assert data["stale"] is False and data["stats"]["total"] == 1

    def test_every_server_down_names_each_one_in_the_error(self, box):
        _seed_last(box)
        box.reply = ConnectionError("down")
        data = alpr.run(None)
        assert data["stale"] is True
        for url in (alpr.OVERPASS, *alpr.BACKENDS):
            assert url.split("/")[2] in data["error"]


# ---------------------------------------------------------------- a camera with no date
class TestUndated:
    """An edited node's first-mapped date comes from the OSM history API. When that lookup
    fails: a warning on a daily run (the list is the day's), a red run on the weekly one (the
    row would otherwise lend the camera its own date)."""

    def test_daily_run_keeps_the_camera_and_leaves_its_date_blank(self, box):
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2, "2026-10-06", version=2)]}
        data = alpr.run(None)
        assert data["stale"] is False and data["asof"] == TODAY
        assert {c["id"]: c["mapped"] for c in data["cameras"]} == {1: "2026-09-01", 2: ""}
        assert data["stats"]["new_this_week"] == 0       # never the edit date

    def test_weekly_run_refuses_the_row_for_an_undated_new_camera(self, box):
        box.today = "2026-10-12"
        _seed_last(box, asof="2026-10-11")
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2, "2026-10-06", version=2)]}
        data = alpr.run(None, record_change=True)
        assert data["stale"] is True and data["asof"] == "2026-10-11"
        assert "could not be dated" in data["error"] and "nodes 2" in data["error"]
        assert common.load_change_log("alpr") == []
        assert common.load_snapshot("alpr_nodes") == [1]
        # the re-run, with the history API back, logs it under its real date
        box.v1[2] = "2026-10-05"
        data = alpr.run(None, record_change=True)
        assert data["stale"] is False
        assert [e["new_ids"] for e in common.load_change_log("alpr")] == [[2]]
        assert {c["id"]: c["mapped"] for c in data["cameras"]}[2] == "2026-10-05"

    def test_weekly_run_is_not_stopped_by_an_undated_camera_that_is_not_new(self, box):
        """An old gap is the daily warning's business; the row only vouches for its new ids."""
        box.today = "2026-10-12"
        common.save_snapshot("alpr_nodes", [1, 2])
        box.reply = {"elements": [_node(1), _node(2, "2026-10-06", version=2), _node(3)]}
        data = alpr.run(None, record_change=True)
        assert data["stale"] is False
        assert [e["new_ids"] for e in common.load_change_log("alpr")] == [[3]]

    def test_gate_warns_and_passes(self, box, tmp_path, capsys):
        box.reply = {"elements": [_node(1), _node(2, "2026-10-06", version=2)]}
        args = _write_run(tmp_path, alpr.run(None))
        assert chk.main(args, now=NOW) == 0
        out = capsys.readouterr().out
        warns = [ln for ln in out.splitlines() if ln.startswith("::warning")]
        assert len(warns) == 1 and "nodes 2" in warns[0] and "1 camera(s)" in warns[0]
        assert "::error" not in out
        assert not (tmp_path / "alert.txt").exists()

    def test_gate_is_silent_when_every_camera_is_dated(self, box, tmp_path, capsys):
        box.reply = {"elements": [_node(1), _node(2)]}
        assert chk.main(_write_run(tmp_path, alpr.run(None)), now=NOW) == 0
        assert "::warning" not in capsys.readouterr().out


# ---------------------------------------------------------------- one writer for the change log
class TestSingleWriter:
    """The daily run proves freshness; the Monday run alone writes the change log and advances
    the node snapshot. A daily writer would log every camera on the day it was mapped and leave
    the Monday row reading +0, and two writers on one date is the twin-row bug."""

    def test_daily_run_does_not_touch_the_log_or_the_node_snapshot(self, box):
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2)]}
        data = alpr.run(None)                       # record_change defaults to False
        assert data["ok"] and data["stale"] is False
        assert common.load_snapshot("alpr_nodes") == [1]
        assert not (box.logs / "alpr.json").exists()
        assert common.load_change_log("alpr") == []

    def test_monday_run_logs_the_diff_and_advances_once(self, box):
        box.today = "2026-10-12"                    # a Monday
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2)]}
        alpr.run(None, record_change=True)
        log = common.load_change_log("alpr")
        assert [(e["date"], e["new_ids"], e["new_count"]) for e in log] == [("2026-10-12", [2], 1)]
        assert common.load_snapshot("alpr_nodes") == [1, 2]

    def test_a_week_of_daily_runs_leaves_the_monday_diff_whole(self, box):
        """Camera 2 is mapped on Tuesday. Daily runs see it all week; Monday still reports it."""
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2, "2026-10-06")]}
        for day in ("2026-10-06", "2026-10-07", "2026-10-08", "2026-10-11"):
            box.today = day
            alpr.run(None)
        box.today = "2026-10-12"
        alpr.run(None, record_change=True)
        log = common.load_change_log("alpr")
        assert len(log) == 1 and log[0]["new_ids"] == [2]

    def test_second_writer_on_the_same_date_cannot_double_log(self, box):
        box.today = "2026-10-12"
        common.save_snapshot("alpr_nodes", [1])
        box.reply = {"elements": [_node(1), _node(2)]}
        alpr.run(None, record_change=True)
        box.reply = {"elements": [_node(1), _node(2), _node(3)]}
        alpr.run(None, record_change=True)          # a manual dispatch after the cron
        log = common.load_change_log("alpr")
        assert [e["date"] for e in log] == ["2026-10-12"]
        # camera 3 was not logged, so the snapshot must not swallow it: next Monday reports it
        assert common.load_snapshot("alpr_nodes") == [1, 2]

    def test_monday_outage_writes_no_row_and_keeps_the_snapshot(self, box):
        box.today = "2026-10-12"
        _seed_last(box, asof="2026-10-11")
        common.save_snapshot("alpr_nodes", [100, 101, 102])
        box.reply = ConnectionError("down")
        data = alpr.run(None, record_change=True)
        assert data["stale"] is True
        assert common.load_change_log("alpr") == []
        assert common.load_snapshot("alpr_nodes") == [100, 101, 102]


# ---------------------------------------------------------------- the daily gate
def _fresh(asof=TODAY, **over):
    p = {"ok": True, "stale": False, "asof": asof, "cameras": [_camera(1)], "stats": {"total": 1}}
    p.update(over)
    return p


class TestVerdict:
    def test_fresh_payload_passes(self):
        assert chk.problems(_fresh(), [TODAY]) == []

    def test_stale_fallback_fails_even_when_its_date_is_today(self):
        """08:00 fetch good, 11:00 fetch down: the list is today's, the check still failed.
        A fallback is never green."""
        found = chk.problems(_fresh(stale=True, error="ConnectionError: down"), [TODAY])
        assert len(found) == 1 and "last good list" in found[0] and "down" in found[0]

    def test_stale_fallback_from_an_older_day_reports_both(self):
        found = chk.problems(_fresh(asof=YESTERDAY, stale=True, error="Timeout"), [TODAY])
        assert len(found) == 2
        assert any(YESTERDAY in f and "not the Pacific date" in f for f in found)

    def test_failed_fetch_with_no_snapshot_fails(self):
        found = chk.problems({"ok": False, "error": "ConnectionError: down"}, [TODAY])
        assert len(found) == 1 and "no last good list" in found[0]

    def test_old_date_fails_without_any_stale_flag_set(self):
        """A cache left over from yesterday's run, marked as a clean fetch."""
        found = chk.problems(_fresh(asof=YESTERDAY), [TODAY])
        assert len(found) == 1 and "not the Pacific date" in found[0]

    def test_missing_stale_flag_is_not_a_pass(self):
        p = _fresh()
        del p["stale"]
        assert any("no explicit stale flag" in f for f in chk.problems(p, [TODAY]))

    @pytest.mark.parametrize("payload", [None, {}, [], "ok"])
    def test_no_payload_fails(self, payload):
        assert chk.problems(payload, [TODAY])

    def test_ok_with_zero_cameras_fails(self):
        assert any("zero cameras" in f for f in chk.problems(_fresh(cameras=[]), [TODAY]))

    def test_truthy_but_not_true_ok_fails(self):
        assert chk.problems(_fresh(ok="yes"), [TODAY])


class TestRunDate:
    def test_run_date_is_the_pacific_date_not_utc(self):
        # 17:30 PT on the 6th is already the 7th in UTC
        now = dt.datetime(2026, 10, 7, 0, 30, tzinfo=dt.timezone.utc)
        assert chk.run_dates(now, None) == [YESTERDAY]

    def test_build_just_before_midnight_counts_for_a_check_just_after(self):
        now = dt.datetime(2026, 10, 7, 0, 3, tzinfo=chk.PACIFIC)
        assert chk.run_dates(now, "2026-10-06T23:58:10-07:00") == [TODAY, YESTERDAY]

    def test_an_old_build_report_cannot_vouch_for_old_data(self):
        now = dt.datetime(2026, 10, 7, 3, 9, tzinfo=chk.PACIFIC)
        assert chk.run_dates(now, "2026-10-06T23:58:10-07:00") == [TODAY]

    @pytest.mark.parametrize("built", [None, "", "not a date", 5, "2026-10-08T00:10:00-07:00"])
    def test_unreadable_or_future_build_time_adds_nothing(self, built):
        assert chk.run_dates(NOW, built) == [TODAY]


def _write_run(tmp_path, alpr_payload, built_at="2026-10-07T06:09:00-07:00"):
    """The two files a build leaves behind, written the way build_all.py writes them."""
    cache, report = tmp_path / "source_cache.json", tmp_path / "build_report.json"
    cache.write_text(json.dumps({"weather": {"ok": True}, "alpr": alpr_payload},
                                indent=1, default=str), encoding="utf-8")
    report.write_text(json.dumps({"built_at": built_at}), encoding="utf-8")
    return ["--cache", str(cache), "--report", str(report),
            "--alert-file", str(tmp_path / "alert.txt")]


class TestGateEndToEnd:
    """Source -> the cache file -> the step's exit code, the annotation and the alert text."""

    def test_successful_fetch_passes_and_writes_no_alert(self, box, tmp_path, capsys):
        box.reply = {"elements": [_node(1), _node(2)]}
        args = _write_run(tmp_path, alpr.run(None))
        assert chk.main(args, now=NOW) == 0
        out = capsys.readouterr().out
        assert "::error" not in out and "OK" in out
        assert not (tmp_path / "alert.txt").exists()

    def test_failed_fetch_with_a_good_snapshot_fails_the_run(self, box, tmp_path, capsys):
        _seed_last(box, asof=YESTERDAY)
        box.reply = ConnectionError("overpass-api.de timed out")
        payload = alpr.run(None)
        assert payload["ok"] is True                  # the page is fine; the run is not
        args = _write_run(tmp_path, payload)
        assert chk.main(args, now=NOW) == 1
        out = capsys.readouterr().out
        assert out.count("::error title=ALPR tracker is not fresh::") == 2
        alert = (tmp_path / "alert.txt").read_text(encoding="utf-8")
        assert "NOT today's" in alert and YESTERDAY in alert and "timed out" in alert

    def test_failed_fetch_after_a_good_one_the_same_day_still_fails(self, box, tmp_path, capsys):
        box.reply = {"elements": [_node(1)]}
        alpr.run(None)                                # the 05:00 build
        box.reply = ConnectionError("down")
        payload = alpr.run(None)                      # the 08:00 build
        assert payload["asof"] == TODAY and payload["stale"] is True
        assert chk.main(_write_run(tmp_path, payload), now=NOW) == 1
        assert capsys.readouterr().out.count("::error") == 1

    def test_failed_fetch_with_no_snapshot_fails_the_run(self, box, tmp_path, capsys):
        box.reply = ConnectionError("down")
        args = _write_run(tmp_path, alpr.run(None))
        assert chk.main(args, now=NOW) == 1
        assert "no last good list" in capsys.readouterr().out
        assert (tmp_path / "alert.txt").exists()

    def test_missing_cache_file_fails_the_run(self, tmp_path, capsys):
        args = ["--cache", str(tmp_path / "nope.json"), "--report", str(tmp_path / "nope2.json")]
        assert chk.main(args, now=NOW) == 1
        assert "no alpr payload" in capsys.readouterr().out

    def test_every_annotation_is_one_line(self, tmp_path, capsys):
        """GitHub cuts an ::error at the first newline; a multi-line error loses its reason."""
        args = _write_run(tmp_path, {"ok": False, "error": "HTTPError: 504\nGateway\r\nTimeout"})
        assert chk.main(args, now=NOW) == 1
        errs = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("::error")]
        assert len(errs) == 1 and "504 Gateway Timeout" in errs[0]


# ---------------------------------------------------------------- the workflows
def _steps(name):
    """The job's steps as dicts of id / name / if / text.

    Read as text on purpose: PyYAML is not in requirements.txt, and a guard that skips itself
    on the CI runner guards nothing. Every step in these files starts at "      - ".
    """
    import re
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text[text.index("    steps:\n") + len("    steps:\n"):]
    out = []
    for block in re.split(r"(?m)^(?= {6}- )", body):
        # comment lines belong to the file, not to the step: drop them before matching
        code = "\n".join(ln for ln in block.split("\n") if not ln.lstrip().startswith("#"))
        if not code.strip():
            continue

        def key(k, code=code):
            m = re.search(rf"(?m)^ {{6}}(?:- | {{2}}){k}:[ ]*(.*)$", code)
            return m.group(1).split("   #")[0].strip() if m else None
        out.append({"id": key("id"), "name": key("name") or "", "if": key("if") or "", "text": code})
    return out


class TestWorkflowWiring:
    def test_daily_runs_the_gate_after_the_deploy_and_cannot_mask_it(self):
        steps = _steps("daily.yml")
        ids = [s.get("id") for s in steps]
        gate = steps[ids.index("alpr_fresh")]
        assert "python scripts/check_alpr_fresh.py" in gate["text"]
        assert "continue-on-error" not in gate["text"]
        assert "|| true" not in gate["text"]
        assert ids.index("build") < ids.index("deploy") < ids.index("alpr_fresh")
        # it must not sit in front of the artifact push: a red gate there drops the day's data
        assert ids.index("push") < ids.index("alpr_fresh")
        assert "steps.build.outcome == 'success'" in gate["if"] and "!cancelled()" in gate["if"]

    def test_no_step_in_either_workflow_is_allowed_to_fail_quietly(self):
        for name in ("daily.yml", "weekly.yml"):
            steps = _steps(name)
            assert len(steps) >= 8, name          # the reader found the steps at all
            assert all("continue-on-error" not in s["text"] for s in steps), name

    def test_daily_failure_alert_goes_through_notify_discord(self):
        notify = _steps("daily.yml")[-1]
        assert notify["if"] == "failure()"
        assert "ALPR_OUTCOME: ${{ steps.alpr_fresh.outcome }}" in notify["text"]
        assert "--file /tmp/bb_alpr.txt" in notify["text"]
        assert "python scripts/notify_discord.py" in notify["text"]
        # the gate writes the alert text where the notify step reads it
        gate = next(s for s in _steps("daily.yml") if s["id"] == "alpr_fresh")
        assert "--alert-file /tmp/bb_alpr.txt" in gate["text"]

    def test_heartbeat_fires_only_on_a_passed_gate(self):
        ping = next(s for s in _steps("daily.yml") if "secrets.UP_ALPR_PING_URL" in s["text"])
        assert "steps.alpr_fresh.outcome == 'success'" in ping["if"]

    def test_a_red_gate_does_not_withhold_the_newsletter(self):
        send = next(s for s in _steps("daily.yml") if s["id"] == "send")
        assert "!cancelled()" in send["if"]
        assert "alpr_fresh" not in send["if"]

    def test_only_the_weekly_job_writes_the_change_log(self):
        """A second --alpr-change writer is the twin-row bug. The daily build must not pass it."""
        daily = "\n".join(s["text"] for s in _steps("daily.yml"))
        weekly = "\n".join(s["text"] for s in _steps("weekly.yml"))
        assert "--alpr-change" not in daily
        assert weekly.count("--alpr-change") == 1
        others = []
        for p in (ROOT / ".github" / "workflows").glob("*.yml"):
            code = "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines()
                             if not ln.lstrip().startswith("#"))
            if p.name != "weekly.yml" and "--alpr-change" in code:
                others.append(p.name)
        assert others == []

    def test_weekly_keeps_its_change_log_verify_before_the_push(self):
        names = [s["name"] for s in _steps("weekly.yml")]
        assert names.index("Verify the ALPR change-log row") < names.index("Commit generated artifacts")
        assert names[-1] == "Remind ops when the land ownership join is due"


# ---------------------------------------------------------------- the page
def _render_surveillance(payload, tmp_path, monkeypatch):
    from build.builders import trackers
    site = tmp_path / "site"
    (site / "surveillance").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(common, "SITE", site)
    monkeypatch.setattr(common, "today_pacific", lambda: dt.date.fromisoformat(TODAY))
    ctx = types.SimpleNamespace(today=dt.date.fromisoformat(TODAY), statusbar="", build_report={})
    trackers.build_alpr(ctx, {"alpr": payload})
    return (site / "surveillance" / "index.html").read_text(encoding="utf-8")


def _page_payload(**over):
    cams = [_camera(1, "2026-09-26"), _camera(2, "2026-05-01")]
    p = {"ok": True, "stale": False, "asof": TODAY, "cameras": cams, "change_log": [],
         "stats": {"total": 2, "flock": 2, "new_this_week": 0, "newest_mapped": "2026-09-26"}}
    p.update(over)
    return p


def _tracker_json(raw):
    import re
    return json.loads(re.search(
        r'<script type="application/json" id="tracker-data">(.*?)</script>', raw, re.S).group(1))


class TestPageDisclosure:
    """What a reader sees. The rule (AGENTS.md): the page always prints the date of the list it
    is showing, and the stale flag is for CI only. An outage is answered with a red run and an
    alert, never with page copy, so a fallback build renders exactly like a fresh build of that
    older date and can never claim today's."""

    STALE = dict(stale=True, asof="2026-10-04", error="ConnectionError: secret-host")

    def test_fresh_page_has_todays_date(self, tmp_path, monkeypatch):
        raw = _render_surveillance(_page_payload(), tmp_path, monkeypatch)
        assert f'data-asof>{TODAY}</span>' in raw
        assert _tracker_json(raw)["asof"] == TODAY

    def test_stale_page_keeps_the_cameras_under_the_date_they_are_from(self, tmp_path, monkeypatch):
        raw = _render_surveillance(_page_payload(**self.STALE), tmp_path, monkeypatch)
        # the fallback list is still the page (the 2026-09-22 fix)
        assert raw.count('<li class="ax-item" data-id="') == 2
        assert "Overpass/OSM data unavailable this build." not in raw
        # every date on it is the last good list's; none is the day of the failed build
        assert 'data-asof>2026-10-04</span>' in raw
        assert "as of 2026-10-04" in raw
        assert f"as of {TODAY}" not in raw
        # (the footer's "Updated <build date>" is the site build, and stays today's)
        assert f'class="updated" data-asof>{TODAY}' not in raw
        assert _tracker_json(raw)["asof"] == "2026-10-04"

    def test_stale_flag_and_error_never_reach_the_page(self, tmp_path, monkeypatch):
        stale = _render_surveillance(_page_payload(**self.STALE), tmp_path, monkeypatch)
        payload = _tracker_json(stale)
        assert "stale" not in payload and "error" not in payload
        assert "secret-host" not in stale and "ConnectionError" not in stale
        # same list, same date, clean fetch: the same page, byte for byte
        fresh = _render_surveillance(_page_payload(asof="2026-10-04"), tmp_path, monkeypatch)
        assert stale == fresh

    def test_no_snapshot_page_says_unavailable_and_never_zero(self, tmp_path, monkeypatch):
        raw = _render_surveillance({"ok": False, "error": "down"}, tmp_path, monkeypatch)
        assert "Overpass/OSM data unavailable this build." in raw
        assert "0 total license-plate readers" not in raw

    def test_home_card_is_the_same_for_a_stale_list(self):
        from build.builders import home
        stale = home._trackers("", _page_payload(**self.STALE))
        assert "2 cameras mapped." in stale
        assert stale == home._trackers("", _page_payload(asof="2026-10-04"))

    def test_email_card_carries_the_date_of_the_list_it_shows(self):
        from build.emailer import _flock_update_html
        stale = _flock_update_html(_page_payload(**self.STALE))
        # build/email_gate.py reads the card's age from this line and blocks the send past 3 days
        assert "Data as of 2026-10-04" in stale
        assert f"Data as of {TODAY}" not in stale
        assert "secret-host" not in stale
        assert stale == _flock_update_html(_page_payload(asof="2026-10-04"))

    def test_no_builder_reads_the_ci_flag(self):
        """The flag has one reader outside the source: CI. A builder that branches on it is how
        page copy comes back, on a surface the byte-for-byte tests above do not render."""
        import re
        pat = re.compile(r"""get\(\s*["']stale["']|\[\s*["']stale["']\s*\]""")
        # the surfaces that render the camera list (other trackers keep flags of their own)
        files = [ROOT / "build" / "emailer.py"] + [
            ROOT / "build" / "builders" / n
            for n in ("trackers.py", "home.py", "alpr_page.py", "alpr_explorer.py", "numbers.py")]
        hits = {f.name: [m.group(0) for m in pat.finditer(f.read_text(encoding="utf-8"))] for f in files}
        # trackers.py also builds the fire and reservoir pages; none of them reads a "stale" key
        assert {k: v for k, v in hits.items() if v} == {}


# ---------------------------------------------------------------- ownership (manual local join)
def _own(built, ids):
    return {"cams": [{"id": str(i)} for i in ids], "owners": [], "parcels": [],
            "meta": {"built": built}}


class TestOwnership:
    CAMS = {"cameras": [_camera(1), _camera(2), _camera(3)]}

    def test_complete_and_recent_join_is_not_due(self):
        st = chk.ownership_status(self.CAMS, _own("2026-09-30", [1, 2, 3]), TODAY)
        assert st["due"] is False and st["unjoined"] == [] and st["age_days"] == 7

    def test_new_camera_inside_the_grace_period_is_not_due(self):
        st = chk.ownership_status(self.CAMS, _own("2026-09-30", [1, 2]), TODAY)
        assert st["due"] is False and st["unjoined"] == ["3"]

    def test_camera_left_unjoined_past_the_grace_period_is_due(self):
        st = chk.ownership_status(self.CAMS, _own("2026-09-22", [1, 2]), TODAY)
        assert st["due"] is True and st["age_days"] == 15
        assert "1 mapped camera has no owner record" in st["reasons"][0]

    def test_an_old_roll_is_due_even_with_every_camera_joined(self):
        st = chk.ownership_status(self.CAMS, _own("2026-06-01", [1, 2, 3]), TODAY)
        assert st["due"] is True and "tax-roll copy" in st["reasons"][0]

    @pytest.mark.parametrize("own", [None, {}, {"cams": []}])
    def test_missing_ownership_data_is_due(self, own):
        assert chk.ownership_status(self.CAMS, own, TODAY)["due"] is True

    def test_undated_ownership_data_is_due(self):
        assert chk.ownership_status(self.CAMS, _own("", [1, 2, 3]), TODAY)["due"] is True

    def test_reminder_mode_never_fails_the_run_and_alerts_only_when_due(self, tmp_path, capsys):
        cache = tmp_path / "source_cache.json"
        cache.write_text(json.dumps({"alpr": self.CAMS}), encoding="utf-8")
        own = tmp_path / "own.json"
        alert = tmp_path / "own.txt"
        base = ["--ownership", "--cache", str(cache), "--own", str(own), "--alert-file", str(alert)]

        own.write_text(json.dumps(_own("2026-09-30", [1, 2, 3])), encoding="utf-8")
        assert chk.main(base, now=NOW) == 0
        assert not alert.exists()

        own.write_text(json.dumps(_own("2026-09-22", [1, 2])), encoding="utf-8")
        assert chk.main(base, now=NOW) == 0
        assert "due for a refresh" in alert.read_text(encoding="utf-8")
        assert "::error" not in capsys.readouterr().out


def test_every_workflow_that_builds_the_site_proves_the_camera_data():
    """Each content workflow runs build_all.py, so each one fetches the camera list and deploys
    /surveillance/. A gate on daily.yml alone leaves the others free to ship a fallback green.
    weekly.yml is the exception by design: its change-log verify step fails on a stale payload
    and on a missing row for the Pacific date, which is the stricter check."""
    seen = []
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        steps = _steps(p.name)
        if not any("build/build_all.py" in s["text"] for s in steps):
            continue
        seen.append(p.name)
        if p.name == "weekly.yml":
            verify = next(s for s in steps if s["name"] == "Verify the ALPR change-log row")
            assert "if stale:" in verify["text"] and "if last != today:" in verify["text"]
            continue
        gate = [s for s in steps if s["id"] == "alpr_fresh"]
        assert len(gate) == 1, p.name
        assert "python scripts/check_alpr_fresh.py" in gate[0]["text"], p.name
        assert "continue-on-error" not in gate[0]["text"], p.name
        assert any("ALPR_OUTCOME: ${{ steps.alpr_fresh.outcome }}" in s["text"]
                   and "scripts/notify_discord.py" in s["text"] for s in steps), p.name
    assert "daily.yml" in seen and "weekly.yml" in seen
