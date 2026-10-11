#!/usr/bin/env bash
# Stop the CrimeRadar emulator when nothing needs it.
#
# WHY: the emulator holds roughly 1 GB of host RAM, and the host is the binding
# constraint on this leg (a starved host ANRs the AVD, and the ANR owned the
# screen while every tap landed on it). Nothing needs the emulator between the
# morning pass (~07:50) and the 19:00 monitor, so it does not need to run all
# day. This is only safe because the app's region is re-set at every start:
# verified 2026-10-09 that a cold boot loses the app's chosen location and comes
# back on the previous saved address (Mendocino), which crimeradar_set_region.sh
# now fixes automatically from the preflight.
#
# Exit codes: 0 the emulator is gone, 1 it is still up, 13 a path this script
# needs is missing (the repo, or adb_bounded.sh).
set -u
unset PYTHONPATH PYTHONHOME

# Siblings and the repo root resolve from this file's own location
# (scripts/crimeradar/ in the repo; hermes/scripts/<name> is a shim that execs
# it). CR_SCRIPTS and CR_REPO override them.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"

ADB_BIN="C:/Users/tscac/Android/Sdk/platform-tools/adb.exe"
export ADB_BIN
ADB="$SCRIPTS/adb_bounded.sh"     # bounded: a wedged guest must fail, never hang
DEV="${CR_DEVICE:-emulator-5554}"
[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }
[ -f "$ADB" ] || { echo "[cr] FAILED: script missing: $ADB (CR_SCRIPTS overrides the directory)"; exit 13; }

up() { "$ADB" devices 2>/dev/null | grep -q "^$DEV[[:space:]]*device"; }

if ! up; then
  echo "[cr] emulator already stopped"
  exit 0
fi

# Do not cut a capture short. The monitor holds work/crimeradar/emulator.lock
# while it reads the screen; the 23:05 stop lands 20 minutes after the last poll,
# but a slow poll or a manual run must not be truncated mid-capture. A stale lock
# (over 600 s, the monitor's own LOCK_STALE) is ignored.
LOCK="$REPO/work/crimeradar/emulator.lock"
for _ in $(seq 1 20); do
  [ -f "$LOCK" ] || break
  age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  [ "$age" -gt 600 ] && break
  echo "[cr] a capture holds the lock (${age}s old); waiting for it to finish"
  sleep 15
done

"$ADB" -s "$DEV" emu kill >/dev/null 2>&1
for _ in $(seq 1 12); do
  sleep 5
  up || { echo "[cr] emulator stopped"; exit 0; }
done

# `adb emu kill` can leave the process behind when the guest is wedged.
echo "[cr] adb emu kill did not take; stopping the process by name"
powershell -NoProfile -Command \
  "Get-Process qemu-system-x86_64-headless -ErrorAction SilentlyContinue | Stop-Process -Force" \
  >/dev/null 2>&1
for _ in $(seq 1 6); do
  sleep 5
  up || { echo "[cr] emulator stopped"; exit 0; }
done

echo "[cr] FAILED: the emulator is still up"
exit 1