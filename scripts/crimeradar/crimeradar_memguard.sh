#!/usr/bin/env bash
# Free host RAM for the CrimeRadar leg, only when the box is genuinely short.
#
# WHY: host RAM is the binding constraint on this leg. A starved host ANRs, and
# the ANR owns the screen while every tap lands on it, so the leg fails looking
# like an app UI change. Measured 2026-10-09: the emulator holds about 3 GB, and
# the big non-leg consumers are the game client and the browser.
#
# The owner's rule (2026-10-09): RuneLite and Chrome may be closed when they are
# eating memory during the CrimeRadar part of the build. Nothing else is touched:
# not Claude Code, not Claude Desktop, not Discord. Every kill is logged.
#
# The owner added the Jagex Launcher on 2026-10-12, for the morning: the six
# JagexLauncher.exe processes sit at about 370 MB together while the launcher
# idles, and the morning steps may close them. Chrome stays night-only: the
# 07:50 morning pass and the 09:15 social push drive the Chrome profile on
# port 9223, so a morning kill there would take the browser out from under a
# step that needs it.
#
# Deliberately conservative:
#   * only in the night window (19:00-06:59) for RuneLite and Chrome, and only
#     in the morning window (06:00-09:59) for the Jagex Launcher, because the
#     07:15 emit and the 07:50 morning pass must not have the owner's browser
#     pulled out from under him while he reads the brief, and the 09:15 social
#     push uses the Chrome profile on 9223;
#   * only when free physical memory is below the floor, so an idle box is never
#     disturbed;
#   * the floor and the window are overridable for a dry run (see below).
#
# It is also the leg's RAM gauge: every call, from the night, emit and morning
# scripts alike, records free memory to work/crimeradar/host_ram.log before the
# two tests above decide whether anything is closed.
#
# Dry run (nothing is killed). The two window variables put a run in any hour,
# so either app list can be exercised at any time of day:
#   CR_MEM_DRY=1 CR_MEM_WINDOW=13 CR_MEM_FLOOR_MB=999999 bash crimeradar_memguard.sh
#   CR_MEM_DRY=1 CR_MEM_MORNING_WINDOW=13 CR_MEM_FLOOR_MB=999999 bash crimeradar_memguard.sh
#
# Exit codes: always 0. This must never fail a poll: it is a helper, and the
# monitor's own guards decide whether the night is usable. The one exception is
# 13, the repo is missing: the kill log has nowhere to go, and night.sh (which
# ignores this script's code) has already refused to run without the repo.
set -u

# The repo root resolves from this file's own location (scripts/crimeradar/ in
# the repo; hermes/scripts/<name> is a shim that execs it). CR_REPO overrides.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
FLOOR_MB="${CR_MEM_FLOOR_MB:-1500}"
# Hours are the guard's own local clock. Night holds the owner's RuneLite and
# Chrome permission; morning holds the Jagex Launcher, which he allowed on
# 2026-10-12. 06 is in the morning list as well as the night list because the
# emit step asks at 06:55. The two lists are separate so a morning run never
# closes Chrome, which the 09:15 social push needs on port 9223.
WINDOW="${CR_MEM_WINDOW:-19 20 21 22 23 00 01 02 03 04 05 06}"
MORNING_WINDOW="${CR_MEM_MORNING_WINDOW:-06 07 08 09}"
APPS_NIGHT="${CR_MEM_APPS_NIGHT:-RuneLite chrome}"
APPS_MORNING="${CR_MEM_APPS_MORNING:-JagexLauncher}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
LOG="$REPO/work/crimeradar/memguard.log"
[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }

# Every call records the reading, whatever it then does: one line on stdout (the
# job's own log) and one in host_ram.log. Until 2026-10-11 a reading existed
# only when this closed something, and the emit and the morning pass never came
# here, so that day's 06:55 and 07:54 failures have no RAM figure at all. $1
# names the step that asked (night, emit, morning). Recording changes nothing
# about what is closed: the window, the floor and the two apps are as they were.
STEP="${1:-leg}"
RAMLOG="$REPO/work/crimeradar/host_ram.log"
record() { printf '%s %s %s\n' "$(date '+%F %T')" "$STEP" "$1" >>"$RAMLOG" 2>/dev/null || true; }

free_mb() {
  powershell -NoProfile -Command \
    "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'
}

BEFORE=$(free_mb)
case "$BEFORE" in
  ''|*[!0-9]*)
    echo "[cr] host RAM: no reading before the $STEP step (powershell gave none)"
    record "no reading"
    exit 0 ;;
esac

HOUR=$(date +%H)
TARGETS=""
for h in $WINDOW; do
  [ "$HOUR" = "$h" ] && TARGETS="$TARGETS $APPS_NIGHT"
done
for h in $MORNING_WINDOW; do
  [ "$HOUR" = "$h" ] && TARGETS="$TARGETS $APPS_MORNING"
done
if [ -z "$TARGETS" ]; then
  echo "[cr] host RAM ${BEFORE} MB free before the $STEP step (floor ${FLOOR_MB} MB; outside the memguard's hours, so nothing is closed)"
  record "free=${BEFORE}MB floor=${FLOOR_MB}MB outside-hours"
  exit 0
fi
if [ "$BEFORE" -ge "$FLOOR_MB" ]; then
  echo "[cr] host RAM ${BEFORE} MB free before the $STEP step (floor ${FLOOR_MB} MB)"
  record "free=${BEFORE}MB floor=${FLOOR_MB}MB ok"
  exit 0
fi

echo "[cr] host RAM ${BEFORE} MB free, below ${FLOOR_MB} MB; checking the apps the owner named"

# $1 = process name without .exe. Prints what it would free, then frees it.
reclaim() {
  powershell -NoProfile -Command "
    \$p = Get-Process -Name '$1' -ErrorAction SilentlyContinue
    if (\$p) {
      \$mb = [int]((\$p | Measure-Object WorkingSet64 -Sum).Sum/1MB)
      \$n = @(\$p).Count
      if ('${CR_MEM_DRY:-0}' -ne '1') { \$p | Stop-Process -Force -ErrorAction SilentlyContinue }
      Write-Output ('$1: ' + \$n + ' process(es), ' + \$mb + ' MB')
    }" 2>/dev/null | tr -d '\r'
}

# shellcheck disable=SC2086
for NAME in $TARGETS; do
  OUT="$(reclaim "$NAME")"
  if [ -n "$OUT" ]; then
    if [ "${CR_MEM_DRY:-0}" = "1" ]; then
      echo "[cr] DRY RUN: would close $OUT"
    else
      echo "[cr] closed $OUT"
      printf '%s %s\n' "$(date '+%F %T')" "$OUT" >>"$LOG" 2>/dev/null || true
    fi
  fi
done

sleep 3
AFTER=$(free_mb)
echo "[cr] host RAM now ${AFTER:-unknown} MB free"
record "free=${BEFORE}MB floor=${FLOOR_MB}MB below-floor after=${AFTER:-unknown}MB"
if [ -n "${AFTER:-}" ] && [ "$AFTER" -lt "$FLOOR_MB" ]; then
  echo "[cr] WARNING: still below ${FLOOR_MB} MB; the leg may ANR. Consider moving this leg to a bigger box."
fi
exit 0
