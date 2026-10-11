#!/usr/bin/env python3
"""The owner's 2026-10-11 rule for the CrimeRadar leg: Discord and Claude Desktop
are closed while the emulator leg runs, and reopened when it ends.

What has to hold:
  * only what the leg closed is reopened: an app that was not open at the close
    is never opened, and a leg that closed nothing opens nothing;
  * it never fails the leg: a close that fails, a refusal, a reopen that fails
    are each a line in the log, and the scripts keep their own exit codes;
  * the reopen is reached on every way out of the stop script, and after a
    preflight that failed, but not on the preflight's mid-leg wedge recycle;
  * the memguard is a separate rule and keeps its own apps and its own floor.

These run the real scripts against a scripted process driver and a scripted adb:
nothing on this machine is closed or opened, and there is no emulator.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_apps.py -q
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_crimeradar_preflight import LEG, _bash, _stub, run_preflight

APPS = ("discord", "claude-desktop")

# An app is "running" while $FAKE_APPS/<app> exists. FAKE_STOP_<APP> and
# FAKE_START_<APP> (dash as underscore) force that verb's exit code.
FAKE_DRIVER = r"""#!/usr/bin/env bash
echo "$*" >>"$FAKE_APPS/calls"
verb="$1"; app="$2"; key="$(echo "$app" | tr 'a-z-' 'A-Z_')"
forced="FAKE_$(echo "$verb" | tr 'a-z' 'A-Z')_$key"
if [ -n "${!forced:-}" ]; then echo "forced ${!forced}"; exit "${!forced}"; fi
case "$verb" in
  stop)  [ -f "$FAKE_APPS/$app" ] || { echo "not running"; exit 1; }
         rm -f "$FAKE_APPS/$app"; echo "6 process(es), 1255 MB private"; exit 0 ;;
  start) [ -f "$FAKE_APPS/$app" ] && { echo "already running: 6 process(es), 1255 MB private"; exit 0; }
         : >"$FAKE_APPS/$app"; echo "6 process(es), 300 MB private"; exit 0 ;;
esac
exit 9
"""


class Box:
    """A scratch repo, a scripted driver, and which apps are 'running'."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.work = tmp_path / "work" / "crimeradar"
        self.work.mkdir(parents=True, exist_ok=True)
        self.apps = tmp_path / "apps"
        self.apps.mkdir(exist_ok=True)
        self.driver = _stub(tmp_path / "driver", FAKE_DRIVER)

    def env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ, CR_REPO=self.root.as_posix(),
                   CR_APPS_DRIVER=self.driver.as_posix(), FAKE_APPS=self.apps.as_posix())
        for knob in ("CR_LEG_APPS", "CR_SCRIPTS", "CR_WEDGE_RETRY"):
            env.pop(knob, None)
        env.update(extra)
        return env

    def open(self, *apps: str) -> None:
        for app in apps:
            (self.apps / app).write_text("")

    def running(self) -> set[str]:
        return {a for a in APPS if (self.apps / a).exists()}

    def recorded(self) -> list[str]:
        p = self.work / "leg_apps.state"
        return p.read_text().split() if p.exists() else []

    def calls(self) -> list[str]:
        p = self.apps / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def run(self, verb: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([_bash(), (LEG / "crimeradar_apps.sh").as_posix(), verb],
                              env=self.env(**extra), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)


@pytest.fixture
def box(tmp_path):
    if not _bash():
        pytest.skip("no bash on this machine (Git Bash on Windows)")
    return Box(tmp_path)


def test_the_leg_closes_both_and_the_stop_reopens_both(box):
    box.open(*APPS)
    r = box.run("close")
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.running() == set()
    assert box.recorded() == list(APPS)
    assert "closed discord (6 process(es), 1255 MB private)" in r.stdout
    r = box.run("reopen")
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.running() == set(APPS)
    assert "reopened discord" in r.stdout and "reopened claude-desktop" in r.stdout
    assert box.recorded() == []            # a second stop job has nothing left to open
    log = (box.work / "leg_apps.log").read_text()
    assert "close discord" in log and "reopen claude-desktop" in log


def test_an_app_that_was_not_open_is_never_opened(box):
    box.open("discord")                    # the owner had quit Claude Desktop himself
    r = box.run("close")
    assert "claude-desktop already closed" in r.stdout
    assert box.recorded() == ["discord"]
    box.run("reopen")
    assert box.running() == {"discord"}
    assert "start claude-desktop" not in box.calls()


def test_a_leg_that_closed_nothing_opens_nothing(box):
    r = box.run("reopen")
    assert r.returncode == 0 and "nothing to reopen" in r.stdout
    assert box.calls() == []               # the driver is not even asked
    r = box.run("close")                   # and a close with both already shut
    assert r.returncode == 0 and box.recorded() == []
    box.run("reopen")
    assert box.running() == set()


def test_a_close_on_every_poll_keeps_the_first_record(box):
    """The preflight runs every 15 minutes: polls two to eight find them shut."""
    box.open(*APPS)
    box.run("close")
    r = box.run("close")
    assert "discord already closed" in r.stdout
    assert box.recorded() == list(APPS)
    box.run("reopen")
    assert box.running() == set(APPS)


def test_a_close_that_fails_is_logged_and_the_next_app_still_closes(box):
    box.open(*APPS)
    r = box.run("close", FAKE_STOP_DISCORD="5")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "could not close discord (driver code 5" in r.stdout
    assert box.running() == {"discord"}    # untouched, so not recorded
    assert box.recorded() == ["claude-desktop"]
    assert "close discord FAILED" in (box.work / "leg_apps.log").read_text()


def test_a_half_closed_app_is_recorded_so_it_comes_back(box):
    box.open(*APPS)
    r = box.run("close", FAKE_STOP_DISCORD="2")
    assert r.returncode == 0 and "did not close cleanly" in r.stdout
    assert "discord" in box.recorded()


def test_a_refused_close_is_not_recorded(box):
    """Exit 3: this run is inside the app's own process tree."""
    box.open(*APPS)
    r = box.run("close", FAKE_STOP_CLAUDE_DESKTOP="3")
    assert r.returncode == 0 and "claude-desktop left open" in r.stdout
    assert box.recorded() == ["discord"]


def test_a_reopen_that_fails_is_tried_again_by_the_next_stop(box):
    box.open(*APPS)
    box.run("close")
    r = box.run("reopen", FAKE_START_DISCORD="2")
    assert r.returncode == 0 and "could not reopen discord" in r.stdout
    assert box.recorded() == ["discord"] and box.running() == {"claude-desktop"}
    box.run("reopen")
    assert box.running() == set(APPS) and box.recorded() == []


def test_an_app_the_owner_reopened_himself_is_left_as_it_is(box):
    box.open("discord")
    box.run("close")
    box.open("discord")                    # he opened it again before the stop
    r = box.run("reopen")
    assert "discord is already open again" in r.stdout
    assert box.recorded() == []


def test_the_off_switch_and_a_missing_work_directory_touch_nothing(box):
    box.open(*APPS)
    r = box.run("close", CR_LEG_APPS="0")
    assert r.returncode == 0 and "off" in r.stdout
    shutil.rmtree(box.work)                # nowhere to keep the record: do not close
    r = box.run("close")
    assert r.returncode == 0 and "nothing touched" in r.stdout
    assert box.running() == set(APPS) and box.calls() == []


def _preflight(box: Box, dumps: str, **extra: str) -> subprocess.CompletedProcess:
    shutil.rmtree(box.root / "work")       # run_preflight builds its own scratch repo here
    return run_preflight(box.root, dumps, CR_LEG_APPS="1", CR_APPS_DRIVER=box.driver.as_posix(),
                         FAKE_APPS=box.apps.as_posix(), **extra)


def test_the_preflight_closes_them_before_it_touches_the_emulator(box):
    box.open(*APPS)
    r = _preflight(box, "ok")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "closed discord" in r.stdout and "closed claude-desktop" in r.stdout
    assert box.running() == set() and box.recorded() == list(APPS)


def test_a_preflight_that_dies_leaves_the_record_for_the_stop_job(box):
    box.open("discord")
    r = _preflight(box, "fail")
    assert r.returncode == 5, r.stdout + r.stderr      # the leg's own code, unchanged
    assert box.recorded() == ["discord"]


def test_the_preflight_runs_without_the_apps_script(box):
    """The leg does not depend on it: a missing script is a line, not exit 13."""
    scripts = box.root / "scripts_copy"
    scripts.mkdir()
    for name in ("crimeradar_preflight.sh", "crimeradar_emu_stop.sh", "adb_bounded.sh"):
        shutil.copy(LEG / name, scripts / name)
    r = _preflight(box, "ok", CR_SCRIPTS=scripts.as_posix())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "crimeradar_apps.sh is missing" in r.stdout


def _stop(box: Box, devices: str, **extra: str) -> subprocess.CompletedProcess:
    bindir = box.root / "stopbin"
    bindir.mkdir(exist_ok=True)
    adb = _stub(bindir / "adb", "#!/usr/bin/env bash\n"
                '[ "$1" = "devices" ] && printf \'List of devices attached\\n%s\' "$FAKE_DEVICES"\n'
                "exit 0\n")
    _stub(bindir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _stub(bindir / "powershell", "#!/usr/bin/env bash\nexit 0\n")   # the kill-by-name fallback
    env = box.env(ADB_BIN=adb.as_posix(), FAKE_DEVICES=devices,
                  PATH=str(bindir) + os.pathsep + os.environ["PATH"], **extra)
    return subprocess.run([_bash(), (LEG / "crimeradar_emu_stop.sh").as_posix()], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


def test_the_stop_reopens_them_when_the_emulator_was_already_gone(box):
    """A leg that died early: nothing to stop, and the reopen is still reached."""
    box.open(*APPS)
    box.run("close")
    r = _stop(box, "")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "emulator already stopped" in r.stdout
    assert box.running() == set(APPS) and box.recorded() == []


def test_the_stop_reopens_them_even_when_the_emulator_will_not_stop(box):
    box.open("discord")
    box.run("close")
    r = _stop(box, "emulator-5554\tdevice\n")
    assert r.returncode == 1, r.stdout + r.stderr      # the stop's own failure, unchanged
    assert "still up" in r.stdout and "reopened discord" in r.stdout
    assert box.running() == {"discord"}


def test_the_wedge_recycle_is_not_the_end_of_the_leg(box):
    """The preflight stops the emulator mid-leg to recycle it; nothing reopens."""
    box.open(*APPS)
    box.run("close")
    r = _stop(box, "", CR_WEDGE_RETRY="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert box.running() == set() and box.recorded() == list(APPS)


def test_the_driver_finds_apps_by_path_and_guards_its_caller():
    """claude.exe is also Claude Code: an image name alone must never be the test."""
    text = (LEG / "crimeradar_apps.ps1").read_text(encoding="utf-8")
    assert r"*\WindowsApps\Claude_*\app\claude.exe" in text
    assert r"Discord\app-*\Discord.exe" in text
    assert "refused: this run is inside" in text and "refused: a hermes process" in text
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "Get-Process" not in code and "taskkill" not in code     # both match by name


def test_the_real_driver_answers_running_without_touching_anything():
    ps = shutil.which("powershell")
    if os.name != "nt" or not ps:
        pytest.skip("the process driver is Windows PowerShell")
    for app in APPS:
        r = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            str(LEG / "crimeradar_apps.ps1"), "running", app],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
        assert r.returncode in (0, 1), r.stdout + r.stderr
        assert ("process(es)" in r.stdout) == (r.returncode == 0), r.stdout


def test_the_memguard_keeps_its_own_apps_and_its_own_floor():
    text = (LEG / "crimeradar_memguard.sh").read_text(encoding="utf-8")
    assert "for NAME in RuneLite chrome; do" in text
    assert 'FLOOR_MB="${CR_MEM_FLOOR_MB:-1500}"' in text
    assert "crimeradar_apps" not in text
