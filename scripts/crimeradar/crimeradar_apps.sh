#!/usr/bin/env bash
# Close Discord and Claude Desktop for the CrimeRadar leg, and reopen them after.
#
# The owner's rule (2026-10-11): Discord and Claude Desktop may be closed while
# the emulator leg runs, and Discord is reopened when the leg is done. Claude
# Desktop is reopened too, because this closed it. Measured that day: Discord
# held about 1.25 GB private and Claude Desktop about 1.7 GB, on a host where
# RAM is the binding constraint (see crimeradar_memguard.sh).
#
# Never touched: Claude Code (also claude.exe, and the orchestrator's own
# process), the Hermes gateway, `hermes serve`, and the Hermes desktop app that
# hosts the scheduler. The driver finds an app by where its executable lives,
# not by image name, and refuses to stop a tree this run is inside.
#
#   close   the preflight calls it, so every path that starts the emulator (the
#           night bursts, the emits, the morning pass) closes them first. Each
#           app it closes is written to work/crimeradar/leg_apps.state.
#   reopen  crimeradar_emu_stop.sh calls it on every exit, so the 23:05, 01:05,
#           07:25 and 08:05 stop jobs end the window even when the leg died
#           early or the emulator was already gone. Only an app named in the
#           state file is opened: a leg that closed nothing opens nothing, and
#           an app the owner had already quit stays quit.
#   status  what the driver sees now and what the record holds, with the time.
#           Read-only. This is the check to quote; a process count taken by
#           hand just after a launch is not one (see "reopened" below).
#
# A close only happens when a stop job follows it. Hermes runs a missed
# schedule once, immediately, and the morning pass has no clock guard of its
# own, so a 07:50 pass that fires at 10:00 used to close both apps with nothing
# due to reopen them until 23:05. The hours a close is allowed are the leg's
# own, each ending at its stop job:
#   05:00-08:04 daily          stops 07:25 and 08:05
#   21:00-23:04 Sun-Thu        stop 23:05
#   00:00-01:04 Sat and Sun    stop 01:05
# Outside them a `close` closes nothing, and it reopens whatever an earlier leg
# still has on the record: that run is the first thing to notice, and waiting
# for the next stop job is the stranding this guard exists to end. Change a
# stop job's schedule and these hours change with it.
#
# "Reopened" means seen running, not launched. On 2026-10-11 Discord's updater
# held its client back past the check and "not reopened" reached the owner
# about an app that was coming up. The driver now waits for the process and
# says when it saw it; a launch that was not seen in time is reported as that,
# stays on the record, and the next stop job looks again.
#
# One run at a time holds leg_apps.lock. The same day a stop job's reopen and a
# preflight's close overlapped, the reopen rewrote the state file from its own
# stale copy, and the close's record of Discord was lost: Discord stayed shut
# with nothing left to say the leg had closed it.
#
# The memguard is separate and unchanged: it still closes RuneLite and Chrome
# under its own floor. This script has no floor: the rule is the leg itself.
#
# Not on the list: PredatorSense (368 MB private when open). Decided 2026-10-11.
# Its start-up task is disabled, so it runs only when the owner opens it; a
# reopen would put its window on his screen at the stop; and it is the fan and
# thermal front end on a box that runs Whisper at 03:00 and 05:20. It is 368 MB
# against the 2.9 GB the two apps above return. crimeradar_diag.sh lists the
# largest host processes at every failure, so if it is ever what a failed night
# was short of, the snapshot shows it and this can be decided again on evidence.
#
# CR_LEG_APPS=0 turns it off. CR_APPS_DRIVER replaces the process driver and
# CR_APPS_NOW ("<1-7, Mon-Sun> <HHMM>") the clock: tests/test_crimeradar_apps.py
# drives this script against a scripted driver. No scheduled job sets them.
#
# Exit codes: always 0. A close or a reopen that fails is logged and the leg
# carries on; this must never be the reason a poll or a stop fails.
set -u

# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
STATE="$REPO/work/crimeradar/leg_apps.state"
LOG="$REPO/work/crimeradar/leg_apps.log"
APPS="discord claude-desktop"
VERB="${1:-}"

case "$VERB" in
  close|reopen|status) : ;;
  *) echo "[cr] leg apps: usage: crimeradar_apps.sh close|reopen|status"; exit 0 ;;
esac
if [ "${CR_LEG_APPS:-1}" = "0" ]; then
  echo "[cr] leg apps: off (CR_LEG_APPS=0)"
  exit 0
fi
[ -d "$REPO/work/crimeradar" ] || { echo "[cr] leg apps: $REPO/work/crimeradar is missing; nothing recorded, nothing touched"; exit 0; }

# One bounded call per app. The driver waits up to CR_APPS_START_WAIT seconds
# (default 90) for a launched app to be seen running; the bound here covers that.
START_WAIT="${CR_APPS_START_WAIT:-90}"
export CR_APPS_START_WAIT="$START_WAIT"
DRV_BOUND=$((START_WAIT + 60))
drv() {
  local rc
  if [ -n "${CR_APPS_DRIVER:-}" ]; then
    timeout "$DRV_BOUND" "$CR_APPS_DRIVER" "$@" </dev/null 2>&1 | tr -d '\r'
    rc="${PIPESTATUS[0]}"
  else
    timeout "$DRV_BOUND" powershell -NoProfile -ExecutionPolicy Bypass -File "$HERE/crimeradar_apps.ps1" "$@" \
      </dev/null 2>&1 | tr -d '\r'
    rc="${PIPESTATUS[0]}"
  fi
  return "$rc"
}
# The driver's last line is its answer; anything above it is noise.
last() { printf '%s\n' "$1" | tail -n 1; }
if [ -z "${CR_APPS_DRIVER:-}" ] && ! command -v powershell >/dev/null 2>&1; then
  echo "[cr] leg apps: no powershell on this machine; nothing to $VERB"
  exit 0
fi

note() { printf '%s %s\n' "$(date '+%F %T')" "$1" >>"$LOG" 2>/dev/null || true; }
recorded() { [ -f "$STATE" ] && grep -qx "$1" "$STATE"; }
forget() {
  grep -vx "$1" "$STATE" >"$STATE.tmp" 2>/dev/null
  if [ -s "$STATE.tmp" ]; then mv -f "$STATE.tmp" "$STATE"; else rm -f "$STATE.tmp" "$STATE"; fi
}

LOCKDIR="$REPO/work/crimeradar/leg_apps.lock"
if [ "$VERB" = "status" ]; then
  [ -d "$LOCKDIR" ] && echo "[cr] leg apps: a close or a reopen is running right now; this reading may be mid-change"
  for APP in $APPS; do
    OUT="$(drv running "$APP")"; RC=$?
    OUT="$(last "$OUT")"
    case "$RC" in
      0) SEEN="running ($OUT)" ;;
      1) SEEN="not running" ;;
      *) SEEN="unknown (driver code $RC: ${OUT:-no output})" ;;
    esac
    if recorded "$APP"; then OWED="closed by the leg, reopen still owed"; else OWED="not on the leg's record"; fi
    echo "[cr] leg apps: $(date '+%T') $APP $SEEN; $OWED"
  done
  exit 0
fi

# The leg's hours, each ending at its stop job (see the header).
NOW="${CR_APPS_NOW:-$(date '+%u %H%M')}"
DOW="${NOW% *}"; HM=$((10#${NOW#* }))
in_leg_hours() {
  [ "$HM" -ge 500 ] && [ "$HM" -le 804 ] && return 0
  case "$DOW" in 7|1|2|3|4) [ "$HM" -ge 2100 ] && [ "$HM" -le 2304 ] && return 0 ;; esac
  case "$DOW" in 6|7) [ "$HM" -le 104 ] && return 0 ;; esac
  return 1
}
if [ "$VERB" = "close" ] && ! in_leg_hours; then
  echo "[cr] leg apps: $(printf '%02d:%02d' $((HM / 100)) $((HM % 100))) (weekday $DOW) is outside the leg's hours, so no stop job follows this run; Discord and Claude Desktop stay open"
  if [ ! -s "$STATE" ]; then
    exit 0
  fi
  echo "[cr] leg apps: an earlier leg still has $(tr '\n' ' ' <"$STATE")on its record; reopening now, not at the next stop job"
  note "close outside the leg's hours: reopening what an earlier leg closed"
  VERB=reopen
fi

# One run at a time reads and rewrites the record. A lock older than 10 minutes
# belongs to a run that died (two apps at the driver's bound is under 5).
locked() {
  local age
  for _ in $(seq 1 "${CR_APPS_LOCK_TRIES:-150}"); do
    if mkdir "$LOCKDIR" 2>/dev/null; then
      trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT
      return 0
    fi
    age=$(( $(date +%s) - $(stat -c %Y "$LOCKDIR" 2>/dev/null || echo 0) ))
    if [ "$age" -gt 600 ]; then
      rmdir "$LOCKDIR" 2>/dev/null
      continue
    fi
    sleep 2
  done
  return 1
}
if ! locked; then
  echo "[cr] leg apps: another close or reopen has held the record for the whole wait; nothing touched by this $VERB"
  note "$VERB skipped: the record was locked"
  exit 0
fi

if [ "$VERB" = "close" ]; then
  for APP in $APPS; do
    OUT="$(drv stop "$APP")"; RC=$?
    OUT="$(last "$OUT")"
    case "$RC" in
      0|2)
        # 2: part of it is still running. It was open and this run stopped some
        # of it, so it is recorded either way and the reopen puts it back.
        recorded "$APP" || echo "$APP" >>"$STATE"
        if [ "$RC" = "0" ]; then
          echo "[cr] leg apps: closed $APP ($OUT)"
        else
          echo "[cr] leg apps: $APP did not close cleanly ($OUT); carrying on"
        fi
        note "close $APP rc=$RC $OUT" ;;
      1) echo "[cr] leg apps: $APP already closed" ;;
      3) echo "[cr] leg apps: $APP left open ($OUT)"; note "close $APP refused: $OUT" ;;
      *) echo "[cr] leg apps: could not close $APP (driver code $RC: ${OUT:-no output}); carrying on"
         note "close $APP FAILED rc=$RC $OUT" ;;
    esac
  done
  exit 0
fi

if [ ! -s "$STATE" ]; then
  echo "[cr] leg apps: the leg closed nothing; nothing to reopen"
  exit 0
fi
for APP in $APPS; do
  recorded "$APP" || continue
  OUT="$(drv start "$APP")"; RC=$?
  OUT="$(last "$OUT")"
  if [ "$RC" = "0" ]; then
    # 0 is the driver having seen the process, and its line says when.
    case "$OUT" in
      "already running"*) echo "[cr] leg apps: $APP is already open again ($OUT)" ;;
      *) echo "[cr] leg apps: reopened $APP ($OUT)" ;;
    esac
    note "reopen $APP rc=0 $OUT"
    forget "$APP"
  elif [ "$RC" = "2" ]; then
    # Launched, and not seen within the wait. That is not "failed": an updater
    # can hold the client back longer than any bound. It is not "reopened"
    # either. It stays in the state file, so the next stop job looks again.
    echo "[cr] leg apps: $APP was launched but not seen running ($OUT); not verified, so it stays on the record and the next stop job checks again"
    note "reopen $APP UNVERIFIED rc=2 $OUT"
  else
    # It stays in the state file, so the next stop job opens it.
    echo "[cr] leg apps: could not reopen $APP (driver code $RC: ${OUT:-no output}); the next stop job tries again"
    note "reopen $APP FAILED rc=$RC $OUT"
  fi
done
exit 0
