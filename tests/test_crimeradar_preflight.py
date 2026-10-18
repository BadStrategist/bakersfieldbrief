#!/usr/bin/env python3
"""Regression tests for the CrimeRadar leg's two 2026-10-11 faults.

  * The preflight exited 5 ("the screen cannot be read") on a screen it had just
    read. Its probe loop broke out on a good uiautomator dump and then dumped a
    second time to decide, so one failed dump after a good one was fatal. The
    00:15 poll that night exited 5 in 29 s, less than the sleeps alone on the
    path through six failed dumps. The failure line also guessed at the cause
    ("keyguard or black screen") because uiautomator's output went to /dev/null.
  * The monitor is started as `python scripts/crimeradar_monitor.py`, which puts
    scripts/ on sys.path and not the repo root. merge_crimeradar's
    package-qualified import then failed, and three of that night's four polls
    and both the 07:10 and 07:15 emits died on a traceback AFTER a preflight that
    passed. The other crimeradar tests import from the repo root, where that
    import always resolves, so none of them could see it.

The leg scripts live in scripts/crimeradar/ (the hermes/scripts/<name> files the
cron jobs point at are shims that exec them), so these run wherever the suite
runs, CI included. They run the real preflight against a scripted adb: no
emulator, no adb, no network.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_preflight.py -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEG = ROOT / "scripts" / "crimeradar"
LEG_SCRIPTS = ("crimeradar_preflight.sh", "crimeradar_emit.sh", "crimeradar_health.sh",
               "crimeradar_health_jobs.py", "crimeradar_set_region.sh", "crimeradar_emu_stop.sh",
               "crimeradar_memguard.sh", "crimeradar_night.sh", "crimeradar_morning.sh",
               "crimeradar_apps.sh", "crimeradar_apps.ps1", "crimeradar_diag.sh",
               "adb_bounded.sh")
PKG = "com.newsbreak.crimeradar"
GOOD = "UI hierchary dumped to: /sdcard/.cr_probe.xml"
IDLE = "ERROR: could not get idle state."

# Answers every call the preflight makes on its ready path. `uiautomator dump`
# replays FAKE_DUMPS one word per call ("ok" or "fail") and repeats the last.
# Every call is logged, so a test can prove the script never reached adb.
FAKE_ADB = r"""#!/usr/bin/env bash
echo "$*" >>"$FAKE_STATE/calls"
[ "${1:-}" = "-s" ] && shift 2
case "$*" in
  devices)
    if [ -f "$FAKE_STATE/offline_once" ]; then
      rm -f "$FAKE_STATE/offline_once"; printf 'List of devices attached\n'
    else
      printf 'List of devices attached\nemulator-5554\tdevice\n'
    fi ;;
  "shell getprop sys.boot_completed") echo 1 ;;
  # The stop script falls back to Stop-Process on the REAL qemu by name when the
  # device stays listed, so a kill must make the fake go away for one listing.
  "emu kill") : >"$FAKE_STATE/offline_once" ;;
  "shell uiautomator dump "*)
    n=$(cat "$FAKE_STATE/n" 2>/dev/null || echo 0)
    echo $((n + 1)) >"$FAKE_STATE/n"
    set -- $FAKE_DUMPS
    [ "$n" -lt "$#" ] && shift "$n" || shift $(($# - 1))
    if [ "$1" = "ok" ]; then echo "%(good)s"; else echo "%(idle)s" >&2; fi ;;
  "shell dumpsys activity activities")
    echo "  topResumedActivity=ActivityRecord{1a2b3c u0 %(pkg)s/.ui.MainActivity t12}" ;;
  "shell dumpsys window") echo "  isKeyguardShowing=false" ;;
  "shell dumpsys power") echo "  mWakefulness=Awake" ;;
  "shell cmd media_session volume"*) echo "volume is 0 in range [0..15]" ;;
  "shell ping"*) echo "1 packets transmitted, 1 received, 0%% packet loss" ;;
  "shell settings get global hide_error_dialogs") echo 1 ;;
esac
exit 0
""" % {"good": GOOD, "idle": IDLE, "pkg": PKG}


def _bash() -> str | None:
    """Git Bash, never System32's bash.exe (that one is the WSL launcher)."""
    if os.environ.get("CR_BASH"):
        return os.environ["CR_BASH"]
    if os.name != "nt":
        return "/bin/bash"
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    # The MSYS runtime the BB Morning Runner uses (bb-pipeline/common.py BASH is
    # hermes/git/bin/bash.exe) first, as its raw usr/bin bash. Verified 2026-10-17:
    #   * hermes/tools/git-* bash finds `timeout` and friends from hermes/git on
    #     PATH, two MSYS runtimes in one chain, and that mix rewrites /sdcard paths
    #     even with MSYS_NO_PATHCONV=1, so it failed tests the runner passes;
    #   * hermes/git/bin/bash.exe is Git's launcher, which puts /usr/bin ahead of
    #     the tests' stub directory, so a stubbed `date` never ran.
    found = [p for p in (local / "hermes" / "git" / "usr" / "bin" / "bash.exe",) if p.exists()]
    found += sorted(local.glob("hermes/tools/git-*/usr/bin/bash.exe"))
    found += [p for p in (Path(r"C:\Program Files\Git\usr\bin\bash.exe"),) if p.exists()]
    return str(found[0]) if found else None


def _preflight() -> Path:
    return Path(os.environ.get("CR_PREFLIGHT") or LEG / "crimeradar_preflight.sh")


def _stub(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)       # Linux runs these by their mode; Git Bash by the shebang
    return path


# A region setter that fails its first (ok_at - 1) set attempts. `--print`
# reads Bakersfield only once a set attempt has succeeded.
SETREG_FLAKY = r"""#!/usr/bin/env bash
if [ "${1:-}" = "--print" ]; then
  [ -f "$FAKE_STATE/region_ok" ] && { echo 'Bakersfield, CA'; exit 0; }
  echo unknown; exit 1
fi
n=$(( $(cat "$FAKE_STATE/sets" 2>/dev/null || echo 0) + 1 ))
echo $n >"$FAKE_STATE/sets"
[ "$n" -ge "${FAKE_SET_OK_AT:-1}" ] && { : >"$FAKE_STATE/region_ok"; exit 0; }
echo "[cr] FAILED: the location picker did not open"; exit 11
"""


def run_preflight(tmp_path: Path, dumps: str, offline_once: bool = False,
                  setreg_text: str | None = None,
                  **overrides: str) -> subprocess.CompletedProcess:
    script, bash = _preflight(), _bash()
    assert script.is_file(), f"{script} is missing from the repo"
    if not bash:
        pytest.skip("no bash on this machine (Git Bash on Windows)")
    # Without these overrides the script would drive the real adb, and the real
    # emulator's screen with it, or start the real AVD.
    text = script.read_text(encoding="utf-8")
    for knob in ("ADB_BIN", "CR_EMU"):
        assert "${%s:-" % knob in text, \
            f"{script} ignores {knob}; refusing to run it against the real one"
    # And without this one it would close the real Discord and Claude Desktop.
    assert "${CR_LEG_APPS:-" in (LEG / "crimeradar_apps.sh").read_text(encoding="utf-8"), \
        "crimeradar_apps.sh ignores CR_LEG_APPS; refusing to run the preflight on this machine"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "work" / "crimeradar").mkdir(parents=True)
    adb = _stub(bindir / "adb", FAKE_ADB)
    # The script's waits are real seconds; none of them is under test.
    _stub(bindir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    setreg = _stub(bindir / "setreg", setreg_text
                   or "#!/usr/bin/env bash\necho 'Bakersfield, CA'\nexit 0\n")
    emu = _stub(bindir / "emulator",
                '#!/usr/bin/env bash\necho "$*" >"$FAKE_STATE/emulator"\n'
                'echo "emulator: fake boot line"\nexit 0\n')
    if offline_once:        # the first `adb devices` lists nothing, so the script boots the AVD
        (state / "offline_once").write_text("")
    env = dict(os.environ,
               PATH=str(bindir) + os.pathsep + os.environ["PATH"],
               ADB_BIN=adb.as_posix(),
               CR_EMU=emu.as_posix(),
               CR_REPO=tmp_path.as_posix(),
               CR_SETREG=setreg.as_posix(),
               CR_LEG_APPS="0",
               FAKE_STATE=state.as_posix(), FAKE_DUMPS=dumps)
    env.pop("CR_SCRIPTS", None)
    env.update(overrides)
    r = subprocess.run([bash, script.as_posix()], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=120)
    assert offline_once or not (state / "emulator").exists(), \
        "the preflight tried to start the emulator"
    return r


def test_one_good_dump_is_readable_even_when_the_next_would_fail(tmp_path):
    """The 2026-10-11 00:15 poll: a dump succeeds, the one after it does not."""
    r = run_preflight(tmp_path, "ok fail")
    assert "cannot be read" not in r.stdout, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
    assert "screen readable" in r.stdout


def test_a_dump_that_comes_good_on_a_later_try_is_readable(tmp_path):
    r = run_preflight(tmp_path, "fail fail ok fail")
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_unreadable_screen_exits_5_with_what_uiautomator_said(tmp_path):
    r = run_preflight(tmp_path, "fail")
    assert r.returncode == 5, r.stdout + r.stderr
    line = next(ln for ln in r.stdout.splitlines() if "cannot be read" in ln)
    assert IDLE in line                         # the cause is read, not guessed
    assert "keyguard or black screen" not in line
    assert f"foreground is '{PKG}'" in line
    assert "isKeyguardShowing=false" in line and "mWakefulness=Awake" in line
    # Six tries and no seventh: a failed read is not retried past its budget.
    assert (tmp_path / "state" / "n").read_text().strip() == "6"


def test_a_missing_repo_fails_before_any_adb_call(tmp_path):
    r = run_preflight(tmp_path, "ok", CR_REPO=(tmp_path / "gone").as_posix())
    assert r.returncode == 13, r.stdout + r.stderr
    assert "repo missing" in r.stdout and "gone" in r.stdout
    assert not (tmp_path / "state" / "calls").exists()


def test_a_missing_sibling_script_fails_before_any_adb_call(tmp_path):
    empty = tmp_path / "no_scripts"
    empty.mkdir()
    r = run_preflight(tmp_path, "ok", CR_SCRIPTS=empty.as_posix())
    assert r.returncode == 13, r.stdout + r.stderr
    assert "script missing" in r.stdout and "adb_bounded.sh" in r.stdout
    assert not (tmp_path / "state" / "calls").exists()


def test_the_leg_scripts_are_in_the_repo_and_name_no_other_copy():
    """All of them are versioned here, parse, and reach each other only by $SCRIPTS."""
    bash = _bash()
    for name in LEG_SCRIPTS:
        path = LEG / name
        assert path.is_file(), f"{path} is missing"
        raw = path.read_bytes()
        assert b"\r" not in raw, f"{name} has CRLF line ends; Linux bash cannot run it"
        code = "\n".join(ln for ln in raw.decode("utf-8").splitlines()
                         if not ln.lstrip().startswith("#"))
        assert not re.search(r"hermes[/\\]+scripts|BakersfieldBrief\.com", code), \
            f"{name} hard-codes a path to another copy of the leg scripts or the repo"
        if name.endswith(".sh") and bash:
            r = subprocess.run([bash, "-n", path.as_posix()],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, f"{name}: {r.stderr}"


def test_the_monitor_starts_the_way_the_leg_scripts_start_it(tmp_path):
    """`python scripts/crimeradar_monitor.py`, with nothing else on the path."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "crimeradar_monitor.py"), "--help"],
                       cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]


def test_device_paths_reach_adb_as_written_whatever_the_callers_environment(tmp_path):
    """2026-10-16: every emit exited 11 under the BB Morning Runner.

    adb.exe is a native program, so MSYS rewrote `/sdcard/.cr_region.xml` into a
    path under the Git install before adb saw it, and every screen read came back
    empty. Claude Code and Hermes export MSYS_NO_PATHCONV=1, so every manual run
    worked; the scheduled task exports nothing. The scripted adb above is a bash
    script, which MSYS never rewrites for, so it could not see this: the stand-in
    here is a native program (this Python), started with the variables removed.
    On Linux nothing is rewritten and this passes trivially.
    """
    bash = _bash()
    if not bash:
        pytest.skip("no bash on this machine (Git Bash on Windows)")
    echo = tmp_path / "argv.py"
    echo.write_text("import sys\nprint(*sys.argv[1:])\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("MSYS_NO_PATHCONV", "MSYS2_ARG_CONV_EXCL")}
    env["ADB_BIN"] = Path(sys.executable).as_posix()
    r = subprocess.run([bash, (LEG / "adb_bounded.sh").as_posix(), echo.as_posix(),
                        "shell", "cat", "/sdcard/.cr_region.xml"],
                       env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.split() == ["shell", "cat", "/sdcard/.cr_region.xml"], r.stdout


def _region_run(tmp_path, ok_at: int):
    # CR_DIAG=0: the snapshot runs dozens of adb calls and writes into the real
    # repo's work/crimeradar/emu, and none of it is under test here.
    r = run_preflight(tmp_path, "ok", setreg_text=SETREG_FLAKY, FAKE_SET_OK_AT=str(ok_at),
                      CR_DIAG="0")
    state = tmp_path / "state"
    calls = (state / "calls").read_text(encoding="utf-8")
    sets = int((state / "sets").read_text())
    return r, calls, sets


def test_a_region_the_taps_set_needs_no_recovery(tmp_path):
    r, calls, sets = _region_run(tmp_path, 1)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sets == 1 and "am force-stop" not in calls and "emu kill" not in calls


def test_a_region_that_fails_once_is_set_after_an_app_restart(tmp_path):
    """2026-10-13/14/16: the 07:10 retries re-ran the same taps and failed the same way."""
    r, calls, sets = _region_run(tmp_path, 2)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "restarting the app" in r.stdout
    assert sets == 2 and "am force-stop com.newsbreak.crimeradar" in calls
    assert "emu kill" not in calls


def test_a_region_that_survives_an_app_restart_gets_one_emulator_recycle(tmp_path):
    r, calls, sets = _region_run(tmp_path, 3)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recycling the emulator" in r.stdout
    assert sets == 3 and calls.count("emu kill") == 1


def test_a_region_that_never_sets_exits_11_after_exactly_one_recycle(tmp_path):
    r, calls, sets = _region_run(tmp_path, 99)
    assert r.returncode == 11, r.stdout + r.stderr
    assert "emulator recycle all tried" in r.stdout
    # two set attempts per pass, two passes, one recycle between them: bounded
    assert sets == 4 and calls.count("emu kill") == 1
