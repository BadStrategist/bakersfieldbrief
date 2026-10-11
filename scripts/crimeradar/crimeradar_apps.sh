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
#
# The memguard is separate and unchanged: it still closes RuneLite and Chrome
# under its own floor. This script has no floor: the rule is the leg itself.
#
# CR_LEG_APPS=0 turns it off. CR_APPS_DRIVER replaces the process driver
# (tests/test_crimeradar_apps.py drives this script against a scripted one).
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
  close|reopen) : ;;
  *) echo "[cr] leg apps: usage: crimeradar_apps.sh close|reopen"; exit 0 ;;
esac
if [ "${CR_LEG_APPS:-1}" = "0" ]; then
  echo "[cr] leg apps: off (CR_LEG_APPS=0)"
  exit 0
fi
[ -d "$REPO/work/crimeradar" ] || { echo "[cr] leg apps: $REPO/work/crimeradar is missing; nothing recorded, nothing touched"; exit 0; }

# One bounded call per app. 90 s covers the driver's own 30 s start deadline.
drv() {
  local rc
  if [ -n "${CR_APPS_DRIVER:-}" ]; then
    timeout 90 "$CR_APPS_DRIVER" "$@" </dev/null 2>&1 | tr -d '\r'
    rc="${PIPESTATUS[0]}"
  else
    timeout 90 powershell -NoProfile -ExecutionPolicy Bypass -File "$HERE/crimeradar_apps.ps1" "$@" \
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
    case "$OUT" in
      "already running"*) echo "[cr] leg apps: $APP is already open again" ;;
      *) echo "[cr] leg apps: reopened $APP ($OUT)" ;;
    esac
    note "reopen $APP rc=0 $OUT"
    forget "$APP"
  else
    # It stays in the state file, so the next stop job opens it.
    echo "[cr] leg apps: could not reopen $APP (driver code $RC: ${OUT:-no output}); the next stop job tries again"
    note "reopen $APP FAILED rc=$RC $OUT"
  fi
done
exit 0
