#!/usr/bin/env python3
"""What the CrimeRadar leg leaves behind when it fails (2026-10-11).

Two of that day's failures (06:55, 07:54) had no RAM reading, because only the
night script called the memguard, and none had the emulator's own output or the
host GPU's state, so "is the GPU path the cause?" was answered on indirect
evidence. What has to hold now:

  * every leg step records free host RAM, and recording changes nothing about
    what the memguard closes: its hours, its floor and its two apps are its own;
  * the emulator's output is kept, and a log that outgrows its cap is cut and
    says so;
  * a snapshot is written on the preflight's exits 3, 5 and 12, on monitor exits
    4, 5, 7 and 8, and before a stop, and on nothing else;
  * none of it changes an exit code or fails a run.

These run the real scripts against a scripted adb, powershell and monitor: no
emulator, nothing closed, nothing measured on this machine.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_leg.py -q
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_crimeradar_preflight import LEG, _bash, _stub, run_preflight

# Free RAM is $FAKE_FREE_MB. Every other call (the memguard's reclaim, the
# snapshot's host section) is logged and answers nothing.
FAKE_POWERSHELL = r"""#!/usr/bin/env bash
case "$*" in
  "-NoProfile -Command [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)") echo "${FAKE_FREE_MB-4000}" ;;
  *) echo "$*" | tr '\n' ' ' >>"$FAKE_BOX/powershell_calls"; echo >>"$FAKE_BOX/powershell_calls"
     echo "free MB: ${FAKE_FREE_MB-4000} of 16088" ;;
esac
exit 0
"""

# A guest that answers. FAKE_GUEST=wedged: listed, and its shell times out.
# FAKE_GUEST=offline: not listed.
FAKE_ADB = r"""#!/usr/bin/env bash
echo "$*" >>"$FAKE_BOX/adb_calls"
if [ "$1" = "devices" ]; then
  printf 'List of devices attached\n'
  [ "${FAKE_GUEST:-up}" = "offline" ] || printf 'emulator-5554\tdevice\n'
  exit 0
fi
[ "${1:-}" = "-s" ] && shift 2
[ "${FAKE_GUEST:-up}" = "wedged" ] && exit 124
case "$*" in
  "shell cat /proc/meminfo") printf 'MemTotal: 2500000 kB\nMemFree: 90000 kB\nMemAvailable: 400000 kB\n' ;;
  "shell cat /proc/pressure/"*) echo "some avg10=0.42 avg60=0.10 avg300=0.02 total=1234" ;;
  "shell vmstat 1 5") echo " r  b  swpd  free  buff cache  si  so  bi  bo  in  cs us sy id wa" ;;
  "shell dumpsys activity lastanr") echo "  <no ANR has occurred since boot>" ;;
  logcat*) printf '10-11 06:55:01.000  600  600 I lowmemorykiller: Kill com.example\n'
           printf '10-11 06:55:02.000  900  950 E OpenGLRenderer: GL error: GL_OUT_OF_MEMORY\n' ;;
esac
exit 0
"""


class Leg:
    """A scratch repo, the real leg scripts, and scripted tools around them."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.work = tmp_path / "work" / "crimeradar"
        self.work.mkdir(parents=True)
        self.emu = self.work / "emu"
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        _stub(self.bin / "powershell", FAKE_POWERSHELL)
        _stub(self.bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")
        _stub(self.bin / "nvidia-smi", "#!/usr/bin/env bash\necho 'P0, 12.12 W, 0 %, 175 MiB'\n")
        self.adb = _stub(self.bin / "adb", FAKE_ADB)
        self.monitor = _stub(self.bin / "monitor", "#!/usr/bin/env bash\n"
                             'echo "$*" >>"$FAKE_BOX/monitor_calls"\nexit "${FAKE_MONITOR_RC:-0}"\n')
        # The real siblings, except the preflight: the emit and the morning pass
        # are under test here, not the boot.
        self.scripts = tmp_path / "leg"
        self.scripts.mkdir()
        for name in ("crimeradar_memguard.sh", "crimeradar_diag.sh", "adb_bounded.sh"):
            shutil.copy(LEG / name, self.scripts / name)
        _stub(self.scripts / "crimeradar_preflight.sh",
              '#!/usr/bin/env bash\necho preflight >>"$FAKE_BOX/order"\nexit "${FAKE_PREFLIGHT_RC:-0}"\n')

    def run(self, script: str, *args: str, **extra: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                   CR_REPO=self.root.as_posix(), CR_SCRIPTS=self.scripts.as_posix(),
                   CR_PYTHON=self.monitor.as_posix(), ADB_BIN=self.adb.as_posix(),
                   FAKE_BOX=self.root.as_posix(), CR_EMIT_FORCE="1", CR_MEM_WINDOW="none")
        for knob in ("CR_DIAG", "CR_MEM_FLOOR_MB", "CR_MEM_DRY", "CR_EMULOG_MAX_MB", "CR_DEVICE"):
            env.pop(knob, None)
        env.update(extra)
        return subprocess.run([_bash(), (LEG / script).as_posix(), *args], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    def ram_log(self) -> list[str]:
        p = self.work / "host_ram.log"
        return p.read_text().splitlines() if p.exists() else []

    def reclaims(self) -> list[str]:
        p = self.root / "powershell_calls"
        return [ln for ln in (p.read_text().splitlines() if p.exists() else []) if "Stop-Process" in ln]

    def snapshots(self) -> list[Path]:
        return sorted(self.emu.glob("diag_*.txt")) if self.emu.exists() else []


@pytest.fixture
def leg(tmp_path):
    if not _bash():
        pytest.skip("no bash on this machine (Git Bash on Windows)")
    return Leg(tmp_path)


THIS_HOUR = time.strftime("%H")


# ---- the memguard as the leg's RAM gauge
def test_a_reading_is_recorded_outside_the_memguards_hours_and_nothing_is_closed(leg):
    # Pin the hour: the memguard reads the wall clock, so 07:50 PT is inside the
    # 06-09 morning window as soon as CI runs in UTC and this test went red on
    # 2026-10-20 at 08:25Z. 13:00 is outside both windows at any timezone.
    r = leg.run("crimeradar_memguard.sh", "morning",
                CR_MEM_HOUR="13", FAKE_FREE_MB="900")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "host RAM 900 MB free before the morning step" in r.stdout
    assert "nothing is closed" in r.stdout
    assert leg.reclaims() == []            # 900 MB is under the floor, and it is 07:50
    (line,) = leg.ram_log()
    assert " morning free=900MB floor=1500MB outside-hours" in line


def test_a_reading_is_recorded_when_ram_is_fine(leg):
    r = leg.run("crimeradar_memguard.sh", "night",
                CR_MEM_HOUR="23", CR_MEM_WINDOW="23", FAKE_FREE_MB="3600")
    assert "host RAM 3600 MB free before the night step" in r.stdout
    assert leg.reclaims() == []
    assert " night free=3600MB floor=1500MB ok" in leg.ram_log()[0]


def test_below_the_floor_in_its_hours_it_still_names_only_its_two_apps(leg):
    # Pinned to a night hour, and to the night window only, so the 06-09 morning
    # window cannot add JagexLauncher and turn this into a 3-call assertion.
    r = leg.run("crimeradar_memguard.sh", "night",
                CR_MEM_HOUR="23", CR_MEM_WINDOW="23", FAKE_FREE_MB="1321")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "below 1500 MB" in r.stdout
    calls = leg.reclaims()
    assert len(calls) == 2 and "'RuneLite'" in calls[0] and "'chrome'" in calls[1]
    assert not any(name in " ".join(calls) for name in ("Discord", "claude", "Predator"))
    assert "free=1321MB floor=1500MB below-floor after=1321MB" in leg.ram_log()[0]


def test_the_hour_knob_pins_the_morning_window(leg):
    # Regression guard for the 2026-10-20 red gate: with the hour pinned to 08 the
    # morning window must open and name ONE app, whatever the real clock says.
    r = leg.run("crimeradar_memguard.sh", "morning",
                CR_MEM_HOUR="08", CR_MEM_WINDOW="none", FAKE_FREE_MB="1321")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = leg.reclaims()
    assert len(calls) == 1 and "'JagexLauncher'" in calls[0], calls


def test_no_reading_is_recorded_as_no_reading(leg):
    r = leg.run("crimeradar_memguard.sh", "emit", FAKE_FREE_MB="")
    assert r.returncode == 0 and "no reading before the emit step" in r.stdout
    assert leg.ram_log()[0].endswith(" emit no reading")


@pytest.mark.parametrize("script, step", [("crimeradar_emit.sh", "emit"),
                                          ("crimeradar_morning.sh", "morning"),
                                          ("crimeradar_night.sh", "night")])
def test_every_leg_step_records_ram_before_it_touches_the_emulator(leg, script, step):
    if step == "night":                    # its clock guard: make it Monday 21:xx
        _stub(leg.bin / "date", '#!/usr/bin/env bash\ncase "$1" in\n  +%H) echo 21 ;;\n'
              '  +%u) echo 1 ;;\n  *) exec /usr/bin/date "$@" ;;\nesac\n')
    r = leg.run(script, FAKE_FREE_MB="2222")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"host RAM 2222 MB free before the {step} step" in r.stdout
    assert f" {step} free=2222MB" in leg.ram_log()[0]
    assert (leg.root / "order").read_text().split() == ["preflight"]   # and the leg went on
    assert (leg.root / "monitor_calls").exists()
    assert leg.snapshots() == []           # a run that worked leaves no snapshot


def test_a_leg_step_runs_without_the_memguard_or_the_snapshot_script(leg):
    (leg.scripts / "crimeradar_memguard.sh").unlink()
    (leg.scripts / "crimeradar_diag.sh").unlink()
    r = leg.run("crimeradar_morning.sh", FAKE_MONITOR_RC="8")
    assert r.returncode == 8, r.stdout + r.stderr
    assert "crimeradar_memguard.sh is missing; no reading" in r.stdout


# ---- the snapshot
@pytest.mark.parametrize("rc, kept", [("0", False), ("1", False), ("2", False), ("4", True),
                                      ("5", True), ("6", False), ("7", True), ("8", True),
                                      ("9", False)])
def test_the_monitors_screen_codes_leave_a_snapshot_and_keep_their_code(leg, rc, kept):
    r = leg.run("crimeradar_emit.sh", FAKE_MONITOR_RC=rc)
    assert r.returncode == int(rc), r.stdout + r.stderr
    assert bool(leg.snapshots()) is kept
    if kept:
        assert f"== reason: emit: monitor exit {rc}" in leg.snapshots()[0].read_text()


def test_a_failed_preflight_is_passed_on_and_the_monitor_never_runs(leg):
    r = leg.run("crimeradar_morning.sh", FAKE_PREFLIGHT_RC="5")
    assert r.returncode == 5 and "preflight code 5" in r.stdout
    assert not (leg.root / "monitor_calls").exists()
    assert len(leg.ram_log()) == 1         # the reading is there for the failure


def test_a_snapshot_holds_every_section_and_counts_its_own_signals(leg):
    leg.emu.mkdir()
    (leg.emu / "emulator_2026-10-11_065000.log").write_text(
        "emulator: Graphics Adapter Vendor NVIDIA\nemulator: ERROR: eglMakeCurrent failed\n")
    r = leg.run("crimeradar_diag.sh", "emit: monitor exit 8", FAKE_FREE_MB="1321")
    assert r.returncode == 0, r.stdout + r.stderr
    (snap,) = leg.snapshots()
    assert snap.as_posix() in r.stdout
    text = snap.read_text()
    for section in ("== reason: emit: monitor exit 8", "== host gpu", "P0, 12.12 W, 0 %, 175 MiB",
                    "== host ram", "== emulator log", "Graphics Adapter Vendor NVIDIA",
                    "== guest memory", "MemAvailable", "== guest psi", "== guest vmstat",
                    "== last ANR", "== systemui frames", "== logcat", "== signals"):
        assert section in text, section
    signals = text.split("== signals")[1]
    assert "emulator log, EGL or GL error lines: 1" in signals
    assert "logcat, EGL or GL error lines: 1" in signals
    assert "logcat, low-memory lines: 1" in signals
    assert "guest memory pressure: some avg10=0.42" in signals
    assert "host: free MB: 1321 of 16088" in signals


@pytest.mark.parametrize("guest, says", [
    ("wedged", "online but its shell did not answer in 10 s"),
    ("offline", "is not online")])
def test_a_guest_that_cannot_be_read_is_said_so_and_the_host_is_still_recorded(leg, guest, says):
    r = leg.run("crimeradar_diag.sh", "preflight exit 12", FAKE_GUEST=guest)
    assert r.returncode == 0, r.stdout + r.stderr
    text = leg.snapshots()[0].read_text()
    assert says in text and "== host gpu" in text and "free MB: 4000" in text
    assert "== logcat" not in text
    assert "guest: not read" in text.split("== signals")[1]     # no zero that reads as "clean"
    assert "logcat, low-memory lines" not in text


def test_the_snapshot_never_fails_a_run(leg):
    r = leg.run("crimeradar_diag.sh", "stop", CR_DIAG="0")
    assert r.returncode == 0 and "off" in r.stdout and leg.snapshots() == []
    shutil.rmtree(leg.work)
    r = leg.run("crimeradar_diag.sh", "stop")
    assert r.returncode == 0 and "nothing written" in r.stdout


def test_an_emulator_log_over_its_cap_is_cut_and_says_so(leg):
    leg.emu.mkdir()
    big = leg.emu / "emulator_2026-10-11_210000.log"
    big.write_bytes(b"emulator: backend line\n" + b"x" * (3 * 1024 * 1024) + b"\nlast line\n")
    small = leg.emu / "emulator_2026-10-11_050000.log"
    small.write_text("emulator: short\n")
    r = leg.run("crimeradar_diag.sh", "--tidy", CR_EMULOG_MAX_MB="2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "-verbose writes too much" in r.stdout and "CR_EMU_VERBOSE=0" in r.stdout
    cut = big.read_bytes()
    assert len(cut) < 2 * 1024 * 1024 + 4096
    assert len(cut) > 1024 * 1024
    assert cut.startswith(b"emulator: backend line") and cut.rstrip().endswith(b"last line")
    assert b"cut here: this log was 3 MB, over the 2 MB cap" in cut
    assert small.read_text() == "emulator: short\n"
    assert "over the 2 MB cap" in (leg.emu / "NOTES.txt").read_text()
    r = leg.run("crimeradar_diag.sh", "--tidy", CR_EMULOG_MAX_MB="2")
    assert "writes too much" not in r.stdout           # once cut, it is under the cap


def test_tidy_drops_files_older_than_two_weeks(leg):
    leg.emu.mkdir()
    old, new = leg.emu / "diag_2026-09-20_070000.txt", leg.emu / "diag_2026-10-11_070000.txt"
    for p in (old, new):
        p.write_text("x")
    stale = time.time() - 16 * 86400
    os.utime(old, (stale, stale))
    leg.run("crimeradar_diag.sh", "--tidy")
    assert not old.exists() and new.exists()


# ---- the real preflight and the real stop
def test_the_preflight_keeps_the_emulators_own_output(tmp_path):
    r = run_preflight(tmp_path, "ok", offline_once=True, CR_DIAG="1")
    assert r.returncode == 0, r.stdout + r.stderr
    args = (tmp_path / "state" / "emulator").read_text()
    assert "-verbose" in args and "-no-snapshot-load" in args
    (log,) = (tmp_path / "work" / "crimeradar" / "emu").glob("emulator_*.log")
    assert log.as_posix() in r.stdout
    for _ in range(50):                    # the emulator is started in the background
        if "fake boot line" in log.read_text():
            break
        time.sleep(0.1)
    assert "fake boot line" in log.read_text()


def test_the_verbose_flag_can_be_dropped_and_the_log_kept(tmp_path):
    r = run_preflight(tmp_path, "ok", offline_once=True, CR_DIAG="1", CR_EMU_VERBOSE="0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "-verbose" not in (tmp_path / "state" / "emulator").read_text()
    assert list((tmp_path / "work" / "crimeradar" / "emu").glob("emulator_*.log"))


def test_an_unreadable_screen_leaves_a_snapshot_and_still_exits_5(tmp_path):
    r = run_preflight(tmp_path, "fail", CR_DIAG="1")
    assert r.returncode == 5, r.stdout + r.stderr
    (snap,) = (tmp_path / "work" / "crimeradar" / "emu").glob("diag_*.txt")
    assert "== reason: preflight exit 5: the screen cannot be read" in snap.read_text()


def test_a_ready_preflight_leaves_no_snapshot(tmp_path):
    r = run_preflight(tmp_path, "ok", CR_DIAG="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list((tmp_path / "work" / "crimeradar").glob("emu/diag_*.txt"))


def _stop(leg: Leg, **extra: str) -> subprocess.CompletedProcess:
    # Up for the first two looks (the stop's own, then the snapshot's), gone after the kill.
    _stub(leg.adb, "#!/usr/bin/env bash\n"
          'echo "$*" >>"$FAKE_BOX/adb_calls"\n'
          'if [ "$1" = "devices" ]; then\n'
          "  printf 'List of devices attached\\n'\n"
          '  grep -q "emu kill" "$FAKE_BOX/adb_calls" || printf \'emulator-5554\\tdevice\\n\'\n'
          "fi\nexit 0\n")
    shutil.copy(LEG / "crimeradar_emu_stop.sh", leg.scripts / "crimeradar_emu_stop.sh")
    return leg.run("crimeradar_emu_stop.sh", CR_LEG_APPS="0", **extra)


def test_a_stop_takes_the_healthy_baseline_before_it_kills_the_guest(leg):
    r = _stop(leg)
    assert r.returncode == 0 and "emulator stopped" in r.stdout, r.stdout + r.stderr
    (snap,) = leg.snapshots()
    assert "== reason: stop" in snap.read_text()
    calls = (leg.root / "adb_calls").read_text()
    assert calls.index("logcat") < calls.index("emu kill")


def test_the_wedge_recycle_stop_takes_no_snapshot_of_its_own(leg):
    r = _stop(leg, CR_WEDGE_RETRY="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert leg.snapshots() == []
