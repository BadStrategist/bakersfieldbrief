#!/usr/bin/env bash
# Stage the CrimeRadar emulator's overnight incidents for the 07:30 report publish.
#
# STAGING ONLY. This writes work/crimeradar/emulator_incidents_<date>.json and
# never touches incidents/<date>.json: the publish creates and rewrites that
# file, so it does not exist yet at 07:15 and anything written into it would be
# lost. kern_overnight/merge_crimeradar.py merges the staged rows after the
# publish has extracted the transcript's incidents (publish step 2b, and
# ko_publish.py does the same on the backstop path).
#
# The History sweep takes 3-4 minutes, so the 06:50 and 07:10 emits clear the
# 07:30 publish.
# The app aggregates with a lag (26-47 min observed), so the staged data ends
# short of 07:00. The emit prints the newest row it read.
#
# Exit codes: 0 staged, 2 device offline, 3 emulator could not be started,
# 4 History had no rows in the window, 5 the app's UI could not be read,
# 6 emulator busy, 13 the preflight script is missing.
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
cd "$REPO" || { echo "[cr] repo missing: $REPO"; exit 2; }
[ -f "$SCRIPTS/crimeradar_preflight.sh" ] || { echo "[cr] FAILED: script missing: $SCRIPTS/crimeradar_preflight.sh (CR_SCRIPTS overrides the directory)"; exit 13; }

# Clock guard. Hermes runs a missed schedule once, immediately ("executed once
# now", cron/jobs.py), so an emit that was missed can fire hours later and stage
# rows for a report that is already published. Only the emit window may stage,
# 06:00 to 07:29:
#   50 6   daily  the cold-boot read of Replay > History
#   10 7   daily  the read the 07:30 publish consumes
# Skipping is not a failure, so it exits 0 with a line of explanation.
# Numeric compare, not a "H:MM" glob: `date +%M` has no leading zero, so 07:05
# reads "7:5" and a glob pattern refuses it.
# CR_EMIT_FORCE=1 bypasses the window for a manual recovery run (the leg was
# wedged, no emit ran, and the night is still inside the app's ~24 h history).
# It prints the bypass so the log can never show a silent late staging.
H=$((10#$(date +%H))); M=$((10#$(date +%M)))
if [ "${CR_EMIT_FORCE:-0}" = "1" ]; then
  echo "[cr] emit window OVERRIDE (CR_EMIT_FORCE=1) at $(date '+%a %H:%M'); staging outside 06:00-07:29"
elif [ "$H" -eq 6 ] || { [ "$H" -eq 7 ] && [ "$M" -le 29 ]; }; then
  :
else
  echo "[cr] $(date '+%a %H:%M') is outside the emit window; not staging"
  exit 0
fi

# Record free host RAM before the emulator is touched. The 2026-10-11 06:55 and
# 07:54 failures came through the emit and the morning pass and left no reading
# at all, because only the night script called the memguard. It closes nothing
# outside its own windows or above its own floor; before 07:00 that is RuneLite,
# Chrome and the Jagex Launcher, and from 07:00 the Jagex Launcher alone. It
# never fails the run, and a missing script is a line, not exit 13.
if [ -f "$SCRIPTS/crimeradar_memguard.sh" ]; then
  bash "$SCRIPTS/crimeradar_memguard.sh" emit </dev/null || true
else
  echo "[cr] host RAM: $SCRIPTS/crimeradar_memguard.sh is missing; no reading"
fi

bash "$SCRIPTS/crimeradar_preflight.sh" </dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  # Propagate the preflight's own code (3 offline, 4 no foreground app, 5 screen
  # unreadable, 6 no network). Collapsing every fault to 3 hid a keyguard and a
  # dead route behind the same number for two days.
  echo "[cr] emulator unavailable (preflight code $rc); emit skipped"
  exit "$rc"
fi

# </dev/null: the Hermes cron runner hands scripts an invalid stdin, which makes
# every child process the monitor spawns fail on Windows.
# CR_PYTHON is overridable so tests/test_crimeradar_leg.py can run this against a
# scripted monitor. No scheduled job sets it.
PY="${CR_PYTHON:-./.venv/Scripts/python.exe}"
"$PY" scripts/crimeradar_monitor.py --emit "$(date +%F)" </dev/null
rc=$?
# 4 no rows, 5 the read path failed, 7 a system dialog, 8 unreadable: the codes
# where the guest was up and the screen was not usable. Keep what it looked like.
case "$rc" in
  4|5|7|8) [ -f "$SCRIPTS/crimeradar_diag.sh" ] && bash "$SCRIPTS/crimeradar_diag.sh" "emit: monitor exit $rc" </dev/null ;;
esac
exit "$rc"
