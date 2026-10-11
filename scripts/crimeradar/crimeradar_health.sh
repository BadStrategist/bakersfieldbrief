#!/usr/bin/env bash
# CrimeRadar leg health. For the Hermes cron runner (script-only, no LLM).
#
# WHY: on 2026-10-06 the leg died and nobody knew until 07:16 the next morning,
# because each 15-minute run failed statelessly into a `deliver: local` job with
# no failure delivery. This prints the whole chain in one short block so a human
# can see the state without reading four job histories, and exits non-zero when
# the leg is broken so the failure lands on the job's failure delivery.
#
# Checks, in the order that matters: device online, app foreground, screen
# READABLE (a locked screen breaks every read while the app still looks top),
# region chip, today's polls, the staged file, and the published report.
#
# Exit codes: 0 healthy, 1 broken, 13 a path this script needs is missing (the
# repo, or a sibling script).
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
DATE="$(date +%F)"
BAD=0

[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }
for NEED in "$ADB" "$SCRIPTS/crimeradar_set_region.sh" "$SCRIPTS/crimeradar_health_jobs.py"; do
  [ -f "$NEED" ] || { echo "[cr] FAILED: script missing: $NEED (CR_SCRIPTS overrides the directory)"; exit 13; }
done

echo "CrimeRadar leg health - $(date '+%Y-%m-%d %H:%M %Z')"
echo "-----------------------------------------------"

if "$ADB" devices 2>/dev/null | grep -q "^emulator-5554[[:space:]]*device"; then
  echo "emulator   : online"
  # Host RAM is the binding constraint on this leg: a starved AVD ANRs, and the
  # ANR used to own the screen while every tap landed on it. Measure it instead
  # of assuming it.
  RAMMB=$(powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r')
  echo "host RAM   : ${RAMMB:-unknown} MB free"
else
  echo "emulator   : OFFLINE"
  BAD=1
fi

TOP="$("$ADB" shell dumpsys activity activities 2>/dev/null \
        | grep -m1 -oE 'topResumedActivity=ActivityRecord\{[^ ]+ [^ ]+ [^ ]+' \
        | awk '{print $NF}' | cut -d/ -f1)"
if [ "$TOP" = "com.newsbreak.crimeradar" ]; then
  echo "foreground : CrimeRadar"
else
  echo "foreground : ${TOP:-unknown} (not CrimeRadar)"
  BAD=1
fi

"$ADB" shell rm -f /sdcard/.cr_health.xml >/dev/null 2>&1
if "$ADB" shell uiautomator dump /sdcard/.cr_health.xml 2>/dev/null | grep -qi "dumped to"; then
  echo "screen     : readable"
  # One place knows how to read the chip: crimeradar_set_region.sh --print. The
  # old inline grep took the first two matching texts, which included the
  # "Nationwide" scope tab, so a correct region reported as "Nationwide" and the
  # warning below fired on a healthy screen.
  CHIP="$(bash "$SCRIPTS/crimeradar_set_region.sh" --print 2>/dev/null | head -n 1)"
  echo "region     : ${CHIP:-not found on screen}"
  case "$CHIP" in
    *[Bb]akersfield*|*Kern*) : ;;
    *) echo "  !! the screen does not say Bakersfield or Kern"
       BAD=1 ;;
  esac
else
  echo "screen     : NOT READABLE (keyguard, hung app, or blank)"
  BAD=1
fi

POLLS="$REPO/work/crimeradar/polls_$DATE.jsonl"
if [ -f "$POLLS" ]; then
  echo "polls today: $(wc -l < "$POLLS") records, last write $(date -r "$POLLS" '+%H:%M')"
else
  echo "polls today: none yet"
fi

STAGED="$REPO/work/crimeradar/emulator_incidents_$DATE.json"
if [ -f "$STAGED" ]; then
  echo "staged     : emulator_incidents_$DATE.json ($(stat -c%s "$STAGED") bytes)"
else
  echo "staged     : no file for $DATE"
fi

REPORT="$REPO/data/overnight_reports/$DATE.md"
if [ -f "$REPORT" ]; then
  echo "report     : $DATE published, $(grep -icE 'crimeradar|emulator' "$REPORT" || true) CrimeRadar mentions"
else
  echo "report     : no report for $DATE"
fi
echo "-----------------------------------------------"

if [ -f "$SCRIPTS/crimeradar_health_jobs.py" ]; then
  "$REPO/.venv/Scripts/python.exe" "$SCRIPTS/crimeradar_health_jobs.py" 2>/dev/null || true
fi

if [ "$BAD" != "0" ]; then
  echo "RESULT: BROKEN - the emulator leg needs attention before the next publish"
  exit 1
fi
echo "RESULT: healthy"