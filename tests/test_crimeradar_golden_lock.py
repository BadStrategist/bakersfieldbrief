"""The emulator lock, and the golden snapshot's check / request / refresh states.

2026-10-20, the two things that had to become true before any repair matters:

  * ONE owner at a time. The monitor always held work/crimeradar/emulator.lock; the
    preflight, the region setter, the stops and the emits did not, so a poll and a
    preflight could boot or tap over each other. They all take the same lock now,
    and a second caller waits for its deadline and then says "busy" instead of
    acting. (Proven live too; this pins the rule.)
  * A golden snapshot is only usable while it is fresh and built on the version the
    guest actually has; otherwise the leg cold-boots and ASKS for a rebuild in a
    window with room for it, because a 10-cycle rebuild does not fit at 07:50.

The scripts run for real against a scripted adb: no emulator, nothing tapped.

Run:  .venv/Scripts/python.exe -m pytest tests/test_crimeradar_golden_lock.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts" / "crimeradar"
LOCK = SCRIPTS / "crimeradar_lock.sh"
GOLDEN = SCRIPTS / "crimeradar_golden.sh"
BASH = shutil_which = None


def bash() -> str:
    global BASH
    if BASH is None:
        cand = Path(r"C:/Users/tscac/AppData/Local/hermes/git/bin/bash.exe")
        BASH = str(cand) if cand.exists() else "bash"
    return BASH


STUB_ADB = r"""#!/usr/bin/env bash
# A device that is online, running 26.39.0.
case "$*" in
  *devices*) printf 'List of devices attached\nemulator-5554\tdevice\n' ;;
  *dumpsys\ package*) printf '    versionName=%s\n' "${FAKE_VERSION-26.39.0}" ;;
  *getprop*) printf '1\n' ;;
esac
exit 0
"""


@pytest.fixture
def box(tmp_path):
    repo = tmp_path / "repo"
    (repo / "work" / "crimeradar" / "emu").mkdir(parents=True)
    (repo / "work" / "crimeradar" / "emea").mkdir(exist_ok=True)
    adb = tmp_path / "adb.sh"
    adb.write_text(STUB_ADB.replace("\n", "\n"), encoding="utf-8")
    # adb_bounded.sh execs the stub. Git Bash on the box runs any shebang file, but
    # Linux (the CI runner) needs the execute bit: without it every adb call failed,
    # the guest read as offline, and `check` skipped the version gate (exit 0, not 4).
    adb.chmod(0o755)
    # The golden snapshot directory the check looks for.
    snap = tmp_path / "avd" / "CrimeRadar.avd" / "snapshots" / "golden"
    snap.mkdir(parents=True)
    env = dict(os.environ, CR_REPO=str(repo).replace("\\", "/"),
               CR_SCRIPTS=str(SCRIPTS).replace("\\", "/"),
               ADB_BIN=str(adb), ANDROID_AVD_HOME=str(tmp_path / "avd"),
               CR_PYTHON=sys.executable)
    return repo, env


def run(script, *args, env, timeout=180):
    return subprocess.run([bash(), str(script), *args], capture_output=True, text=True,
                          timeout=timeout, env=env, stdin=subprocess.DEVNULL)


def write_golden(repo, **fields):
    (repo / "work" / "crimeradar" / "emu" / "golden.json").write_text(
        json.dumps(fields), encoding="utf-8")


# -- the lock ----------------------------------------------------------------

def test_a_second_caller_waits_its_deadline_and_then_says_busy(box):
    repo, env = box
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        first = run(LOCK, "acquire", "--pid", str(holder.pid), "--label", "test-holder",
                    "--wait", "2", env=env)
        assert first.returncode == 0, first.stdout + first.stderr
        t0 = time.time()
        second = run(LOCK, "acquire", "--pid", "1", "--label", "second", "--wait", "5", env=env)
        took = time.time() - t0
        assert second.returncode == 75, second.stdout + second.stderr
        assert took >= 4                                   # it waited, it did not barge in
        assert "busy" in (second.stdout + second.stderr).lower()
        assert run(LOCK, "release", "--pid", str(holder.pid), env=env).returncode == 0
        assert run(LOCK, "status", env=env).returncode == 0  # free again
    finally:
        holder.kill()


def test_a_lock_left_by_a_dead_owner_is_reclaimed(box):
    """The monitor's rule (owner gone) when it can answer, age when it cannot."""
    repo, env = box
    lock = repo / "work" / "crimeradar" / "emulator.lock"
    lock.write_text("999999 2026-10-20T07:00:00\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lock, (old, old))   # this checkout has no kern_overnight, so the
                                 # monitor cannot answer and age decides
    p = run(LOCK, "acquire", "--pid", "1", "--label", "after-crash", "--wait", "2", env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    assert lock.read_text(encoding="utf-8").startswith("1 ")


def test_the_monitors_rule_reclaims_a_dead_pid_with_a_fresh_heartbeat(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("crmon", ROOT / "scripts"
                                                  / "crimeradar_monitor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lock = tmp_path / "emulator.lock"
    monkeypatch.setattr(m, "LOCK", lock)
    lock.write_text("999999 now\n", encoding="utf-8")
    assert m.lock_reclaimable() is True
    lock.write_text(f"{os.getpid()} now\n", encoding="utf-8")
    assert m.lock_reclaimable() is False


def test_the_lock_records_the_holder_it_was_given(box):
    repo, env = box
    p = run(LOCK, "acquire", "--pid", "4242", "--label", "t", "--wait", "2", env=env)
    assert p.returncode == 0
    assert (repo / "work" / "crimeradar" / "emulator.lock").read_text(
        encoding="utf-8").startswith("4242 ")


# -- golden: check states ----------------------------------------------------

def test_the_stub_device_answers(box):
    """Every check state below assumes the scripted guest is reachable. If it is not,
    `check` treats the guest as offline and skips the version gate, so a green run
    here would prove nothing."""
    repo, env = box
    p = run(GOLDEN, "version", env=env)
    assert p.stdout.strip() == "26.39.0", p.stdout + p.stderr


def test_no_snapshot_is_exit_2(box):
    repo, env = box
    p = run(GOLDEN, "check", env=env)
    assert p.returncode == 2


def test_usable_snapshot_is_exit_0(box):
    repo, env = box
    write_golden(repo, built=time.strftime("%Y-%m-%d"), app_version="26.39.0")
    p = run(GOLDEN, "check", env=env)
    assert p.returncode == 0, p.stdout
    assert "usable" in p.stdout


def test_an_old_snapshot_is_exit_3(box):
    repo, env = box
    write_golden(repo, built="2026-01-01", app_version="26.39.0")
    assert run(GOLDEN, "check", env=env).returncode == 3


def test_a_snapshot_built_on_another_app_version_is_exit_4(box):
    repo, env = box
    write_golden(repo, built=time.strftime("%Y-%m-%d"), app_version="26.10.0")
    p = run(GOLDEN, "check", env=env)
    assert p.returncode == 4
    assert "26.10.0" in p.stdout and "26.39.0" in p.stdout


def test_a_request_does_not_block_the_snapshot_it_marks(box):
    repo, env = box
    write_golden(repo, built=time.strftime("%Y-%m-%d"), app_version="26.39.0")
    assert run(GOLDEN, "request", "preflight: golden check exit 3", env=env).returncode == 0
    d = json.loads((repo / "work" / "crimeradar" / "emu" / "golden.json").read_text())
    assert "rebuild_requested" in d and "exit 3" in d["rebuild_requested"]
    p = run(GOLDEN, "check", env=env)
    assert p.returncode == 0 and "rebuild is due" in p.stdout


def test_refresh_without_a_request_does_nothing(box):
    repo, env = box
    write_golden(repo, built=time.strftime("%Y-%m-%d"), app_version="26.39.0")
    p = run(GOLDEN, "refresh", "3", env=env)
    assert p.returncode == 0
    assert "nothing to do" in p.stdout
