#!/usr/bin/env bash
# CrimeRadar morning pass for The Kern Overnight (bakersfieldbrief.com).
#
# Runs after the 07:30 publish and before the 08:30 posting kit:
#   1. --verify  : sweep Replay > History (~24 h of app-logged incidents) and
#                  report HIGH+ incidents inside the report window that our own
#                  transcript never produced. This is the miss-check.
#
# No --reel: the reel is cut from the radio transcript's own audio, because every
# row carries offset_s into its block, so the emulator no longer has to be awake
# for it. The emulator clip path stays in make_dispatch_audio as an OPTIONAL
# source for a night whose manifest happens to exist (load_emulator_clips).
#
# The Hermes cron runner injects PYTHONPATH/PYTHONHOME; clear them so the
# project .venv resolves its own site-packages.
set -u
unset PYTHONPATH PYTHONHOME

# Siblings and the repo root resolve from this file's own location
# (scripts/crimeradar/ in the repo; hermes/scripts/<name> is a shim that execs
# it). CR_SCRIPTS and CR_REPO override them. Exit 13 = the preflight is missing.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
cd "$REPO" || { echo "[cr] repo missing: $REPO"; exit 2; }
[ -f "$SCRIPTS/crimeradar_preflight.sh" ] || { echo "[cr] FAILED: script missing: $SCRIPTS/crimeradar_preflight.sh (CR_SCRIPTS overrides the directory)"; exit 13; }

# Record free host RAM before the emulator is touched (see crimeradar_emit.sh:
# the 2026-10-11 07:54 failure came through here with no reading at all). At
# this hour the memguard is outside its own window, so it measures and closes
# nothing. It never fails the run, and a missing script is a line, not exit 13.
if [ -f "$SCRIPTS/crimeradar_memguard.sh" ]; then
  bash "$SCRIPTS/crimeradar_memguard.sh" morning </dev/null || true
else
  echo "[cr] host RAM: $SCRIPTS/crimeradar_memguard.sh is missing; no reading"
fi

bash "$SCRIPTS/crimeradar_preflight.sh" </dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  # Propagate the preflight's own code (3 offline, 4 no foreground app, 5 screen
  # unreadable, 6 no network). Collapsing every fault to 3 hid a keyguard and a
  # dead route behind the same number for two days.
  echo "[cr] emulator unavailable (preflight code $rc); morning pass skipped"
  exit "$rc"
fi

D=$(date +%F)
# NO --emit here: this pass runs AFTER the 07:30 publish has committed, and an
# emit now would append to incidents/<date>.json and leave the tree dirty with
# changes the report never saw. The 07:15 emit job owns that.
# CR_PYTHON is overridable so tests/test_crimeradar_leg.py can run this against a
# scripted monitor. No scheduled job sets it.
PY="${CR_PYTHON:-./.venv/Scripts/python.exe}"
# </dev/null: the Hermes cron runner hands scripts an invalid stdin.
"$PY" scripts/crimeradar_monitor.py --verify "$D" </dev/null
rc=$?
# 4 no rows, 5 the read path failed, 7 a system dialog, 8 unreadable: the codes
# where the guest was up and the screen was not usable. Keep what it looked like.
case "$rc" in
  4|5|7|8) [ -f "$SCRIPTS/crimeradar_diag.sh" ] && bash "$SCRIPTS/crimeradar_diag.sh" "morning: monitor exit $rc" </dev/null ;;
esac
exit "$rc"
