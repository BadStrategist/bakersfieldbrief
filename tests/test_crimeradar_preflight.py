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

The preflight lives outside the repo, in %LOCALAPPDATA%/hermes/scripts, so its
tests run on the box and skip anywhere the script is not installed (CI). They
run the real script against a scripted adb: no emulator, no adb, no network.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_preflight.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = "com.newsbreak.crimeradar"
GOOD = "UI hierchary dumped to: /sdcard/.cr_probe.xml"
IDLE = "ERROR: could not get idle state."

# Answers every call the preflight makes on its ready path. `uiautomator dump`
# replays FAKE_DUMPS one word per call ("ok" or "fail") and repeats the last.
FAKE_ADB = r"""#!/usr/bin/env bash
[ "${1:-}" = "-s" ] && shift 2
case "$*" in
  devices) printf 'List of devices attached\nemulator-5554\tdevice\n' ;;
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
    found = sorted(local.glob("hermes/tools/git-*/usr/bin/bash.exe"))
    found += [p for p in (Path(r"C:\Program Files\Git\usr\bin\bash.exe"),) if p.exists()]
    return str(found[0]) if found else None


def _preflight() -> Path:
    return Path(os.environ.get("CR_PREFLIGHT") or Path(
        os.environ.get("LOCALAPPDATA", "")) / "hermes" / "scripts" / "crimeradar_preflight.sh")


def run_preflight(tmp_path: Path, dumps: str) -> subprocess.CompletedProcess:
    script, bash = _preflight(), _bash()
    if not script.is_file() or not bash:
        pytest.skip("the hermes preflight script (or Git Bash) is not on this machine")
    # Without this override the script would drive the real adb, and the real
    # emulator's screen with it.
    assert "${ADB_BIN:-" in script.read_text(encoding="utf-8"), \
        f"{script} ignores ADB_BIN; refusing to run it against the real adb"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "work" / "crimeradar").mkdir(parents=True)
    (bindir / "adb").write_text(FAKE_ADB, encoding="utf-8", newline="\n")
    # The script's waits are real seconds; none of them is under test.
    (bindir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    (bindir / "setreg").write_text("#!/usr/bin/env bash\necho 'Bakersfield, CA'\nexit 0\n",
                                   encoding="utf-8", newline="\n")
    env = dict(os.environ,
               PATH=str(bindir) + os.pathsep + os.environ["PATH"],
               ADB_BIN=(bindir / "adb").as_posix(),
               CR_REPO=tmp_path.as_posix(),
               CR_SETREG=(bindir / "setreg").as_posix(),
               FAKE_STATE=state.as_posix(), FAKE_DUMPS=dumps)
    return subprocess.run([bash, script.as_posix()], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120)


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


def test_the_monitor_starts_the_way_the_leg_scripts_start_it(tmp_path):
    """`python scripts/crimeradar_monitor.py`, with nothing else on the path."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "crimeradar_monitor.py"), "--help"],
                       cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
