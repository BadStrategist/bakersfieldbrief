"""The app's own coach-mark blocked the location chip, and the morning went with it.

2026-10-20, 07:50 (the morning's second cold boot): the Home header was correct.
`location_feed_tab_container` was there, selected, reading "Bakersfield". On top of it
sat the app's new feature tour, `tip_card` ("Play Local Dispatch Feeds" / "Got it"),
inside a CLICKABLE scrim covering all 720x1560 pixels. Every tap on the chip landed on
the scrim, so the picker never opened; the monitor read the tour's own window as
History ("an unnamed feed") and exited 9. The same emulator, tip dismissed, passed
immediately.

The fix is in the dump, not in the callers: dump_ui clears the tip by resource-id and
re-dumps, so every screen read in the script (region, tabs, history, sweep) is immune.
The fixtures are the real nodes from that dump, cut to the ones that matter.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_tipcard.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "crimeradar"
TIP = (FIX / "home_tip_card_2026-10-20.xml").read_text(encoding="utf-8")
CLEAN = (FIX / "home_after_tip_2026-10-20.xml").read_text(encoding="utf-8")


def load_monitor():
    spec = importlib.util.spec_from_file_location("crmon", ROOT / "scripts"
                                                  / "crimeradar_monitor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def mon(tmp_path, monkeypatch):
    m = load_monitor()
    monkeypatch.setattr(m, "OUT", tmp_path)
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    return m


def fake_adb(mon, monkeypatch, screens, taps):
    """pull writes the next screen in *screens* (the last one repeats)."""
    state = {"i": 0}

    def adb(*args):
        cmd = [str(a) for a in args]
        if cmd[:2] == ["shell", "uiautomator"]:
            return ""
        if cmd and cmd[0] == "pull":
            dest = Path(cmd[2])
            dest.write_text(screens[min(state["i"], len(screens) - 1)], encoding="utf-8")
            state["i"] += 1
            return ""
        if cmd[:3] == ["shell", "input", "tap"]:
            taps.append((int(cmd[3]), int(cmd[4])))
            return ""
        return ""

    monkeypatch.setattr(mon, "adb", adb)


def test_the_tip_is_recognised_by_resource_id_not_by_its_text(mon):
    tip = mon._app_tip(TIP)
    assert tip is not None
    assert tip["resource-id"].endswith(":id/action_button")    # the button, not the card
    assert "Got it" in tip["text"]
    assert mon._app_tip(CLEAN) is None


def test_dump_ui_presses_got_it_and_returns_the_screen_underneath(mon, monkeypatch):
    taps: list = []
    fake_adb(mon, monkeypatch, [TIP, CLEAN], taps)
    xml = mon.dump_ui("tip", tries=3)
    assert taps == [(360, 847)]                                  # centre of [105,807][615,887]
    assert mon._by_id(xml, "tip_card") is None
    assert mon.home_feed(xml) == ("Bakersfield", True)           # the chip is readable again


def test_a_clean_screen_is_not_tapped(mon, monkeypatch):
    taps: list = []
    fake_adb(mon, monkeypatch, [CLEAN], taps)
    xml = mon.dump_ui("clean", tries=3)
    assert taps == []
    assert mon.home_feed(xml) == ("Bakersfield", True)


def test_a_tip_that_never_goes_away_costs_two_taps_and_still_returns(mon, monkeypatch):
    """A tour that reappears must not spin: two taps, then read what is there."""
    taps: list = []
    fake_adb(mon, monkeypatch, [TIP], taps)
    xml = mon.dump_ui("stuck", tries=3)
    assert taps == [(360, 847), (360, 847)]
    assert mon._by_id(xml, "tip_card") is not None              # caller sees the truth


# -- the night leg's repair: a wrong chip is not the end of the poll ----------

import os  # noqa: E402

CALLS: list = []


def fake_sh(mon, monkeypatch, results):
    """results maps SETREG_SH ('set_region') / --print ('ready') / runner to codes."""
    state = {"ready": results.get("ready", [1])}

    def _sh(args, timeout):
        args = [str(a) for a in args]
        if any(a.endswith("crimeradar_set_region.sh") for a in args):
            if "--print" in args:
                nxt = state["ready"].pop(0) if len(state["ready"]) > 1 else state["ready"][0]
                CALLS.append(("ready", nxt))
                return nxt, ""
            CALLS.append(("set_region", 0))
            return results.get("set_region", 0), "set_region: done"
        if any(a.endswith("runner.py") for a in args):
            CALLS.append(("runner", 0))
            return results.get("runner", 0), "region_claude: chip=Bakersfield"
        CALLS.append(("?", 127))
        return 127, ""

    CALLS.clear()
    monkeypatch.setattr(mon, "_sh", _sh)


@pytest.fixture
def runner_dir(tmp_path, monkeypatch, mon):
    (tmp_path / "runner.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(mon, "RUNNER_PY", tmp_path)
    return tmp_path


def test_selfheal_can_be_turned_off(mon, monkeypatch):
    monkeypatch.setenv("CR_SELFHEAL", "0")
    fake_sh(mon, monkeypatch, {})
    assert mon.region_selfheal("test") == (False, "self-heal disabled (CR_SELFHEAL=0)")
    assert CALLS == []


def test_selfheal_stops_after_set_region_works(mon, monkeypatch, runner_dir):
    fake_sh(mon, monkeypatch, {"set_region": 0, "ready": [0]})
    ready, how = mon.region_selfheal("chip was 'Nationwide'")
    assert ready and "set_region fixed it" in how
    assert [c[0] for c in CALLS] == ["set_region", "ready"]      # no Claude was spent


def test_selfheal_falls_to_the_boxed_claude_session(mon, monkeypatch, runner_dir):
    fake_sh(mon, monkeypatch, {"set_region": 11, "ready": [0], "runner": 0})
    ready, how = mon.region_selfheal("chip was 'unknown'")
    assert ready and "region_claude fixed it" in how
    assert [c[0] for c in CALLS] == ["set_region", "runner", "ready"]


def test_selfheal_reports_both_failures(mon, monkeypatch, runner_dir):
    fake_sh(mon, monkeypatch, {"set_region": 11, "ready": [1], "runner": 1})
    ready, how = mon.region_selfheal("chip was 'unknown'")
    assert not ready
    assert "set_region exit 11" in how and "region_claude exit 1" in how


def test_selfheal_can_skip_claude(mon, monkeypatch, runner_dir):
    monkeypatch.setenv("CR_SELFHEAL_CLAUDE", "0")
    fake_sh(mon, monkeypatch, {"set_region": 11, "ready": [1]})
    ready, how = mon.region_selfheal("chip was 'unknown'")
    assert not ready and "Claude disabled" in how
    assert [c[0] for c in CALLS] == ["set_region"]
