#!/usr/bin/env bash
# One emulator, one owner: the same lock the monitor has always taken.
#
# WHY: the monitor, the preflight, set_region and every emit reach the same screen.
# Two of them at once tap each other's pages (2026-10-09: a capture and a launch
# overlapped and the read failed with "could not get idle state"), and the leg's
# worst failures have been two processes taking turns on a screen neither of them
# owned. The monitor already serialises its polls on work/crimeradar/emulator.lock
# (a pid, an ISO stamp, and an mtime heartbeat; stale after 600 s). This script
# takes that same file, in that same format, so a shell script and the python
# monitor exclude each other.
#
# The monitor's own rule decides staleness (pid liveness, not age), so that logic
# is not duplicated here: `crimeradar_monitor.py --lock-reclaim` is asked, and it
# removes a stale lock only when its owner is gone.
#
# Usage:
#   crimeradar_lock.sh acquire [--label NAME] [--wait SECS]
#       0 the lock is ours (or an ancestor already holds it: CR_LOCK_HELD=1)
#       75 busy: a live owner held it for the whole wait
#       13 a path this script needs is missing
#   crimeradar_lock.sh release      remove it if the recorded pid is this process
#   crimeradar_lock.sh heartbeat    touch it if it is ours
#   crimeradar_lock.sh status       0 free, 1 held, prints the owner and its age
#
# Reentrancy: a caller that already holds the lock exports CR_LOCK_HELD=1 for its
# children (preflight sets it before it runs set_region or the golden helpers), so
# a nested call returns at once instead of waiting on its parent.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
LOCK="${CR_LOCK:-$REPO/work/crimeradar/emulator.lock}"
MON="${CR_MONITOR:-$REPO/scripts/crimeradar_monitor.py}"
PY="${CR_PYTHON:-$REPO/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python || true)"

owner() {  # pid in the lock file, or empty
  [ -f "$LOCK" ] || return 1
  head -c 200 "$LOCK" 2>/dev/null | tr -d '\r\n' | cut -d' ' -f1
}

stale() {   # 0 = free or stale (the monitor removes a stale one itself)
  [ -f "$LOCK" ] || return 0
  if [ -f "$MON" ] && [ -n "$PY" ] && [ -x "$PY" ]; then
    ASK="$( ( cd "${MON%/*}/.." && CR_EMU_LOCK="$LOCK" "$PY" "$MON" --lock-reclaim </dev/null ) 2>&1 )"
    RC=$?
    case "$RC" in
      0) return 0 ;;                    # no live owner: free, and it was removed
    esac
    # Only the monitor's own verdict counts. A Python that cannot import the
    # module (a Store stub, a moved checkout, a traceback) also exits 1, and
    # reading that as "held by a live owner" wedges the lock forever.
    case "$ASK" in *"live owner"*) return 1 ;; esac
    # Anything else (a missing module, a traceback, a moved checkout) is NOT a
    # verdict. Never let a broken helper mean "held forever": fall through to the
    # age rule and let the deadline decide.
  fi
  # No monitor to ask (a Linux CI copy, or a partial checkout): age only, the
  # rule the monitor had before pid liveness was added.
  A=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
  if [ "$A" -gt 600 ]; then
    # Aged out: nobody is heartbeating, so remove it here. The monitor removes its
    # own (it is the only thing that can check pid liveness), but a caller that
    # reached this rule has no monitor to ask, and noclobber cannot replace a file
    # that is still on disk.
    rm -f "$LOCK" 2>/dev/null || true
    return 0
  fi
  return 1
}

case "${1:-}" in
  acquire)
    shift
    LABEL="unknown"; WAIT=120; MYPID=$$
    while [ $# -gt 0 ]; do
      case "$1" in
        --label) LABEL="${2:-unknown}"; shift 2 ;;
        --wait) WAIT="${2:-120}"; shift 2 ;;
        --pid) MYPID="${2:-$$}"; shift 2 ;;
        *) shift ;;
      esac
    done
    case "$WAIT" in ''|*[!0-9]*) echo "[cr] lock: --wait needs seconds"; exit 2 ;; esac
    # --pid: the pid to RECORD. This helper is a short-lived child, so its own $$
    # would name a process that exits one line later and every lock would look
    # stale at once. The holder passes its own $$ (preflight, golden) or its python
    # pid (emit_leg.py), which is the process that actually drives the screen.
    case "$MYPID" in ''|*[!0-9]*) echo "[cr] lock: --pid needs a pid"; exit 2 ;; esac
    if [ "${CR_LOCK_HELD:-0}" = "1" ]; then
      echo "[cr] lock: held by an ancestor ($LABEL)"
      exit 0
    fi
    mkdir -p "${LOCK%/*}" 2>/dev/null || { echo "[cr] lock: FAILED: no directory for $LOCK"; exit 13; }
    DEADLINE=$(( $(date +%s) + WAIT ))
    WAITED=0
    while :; do
      if stale; then
        # O_EXCL, the same primitive the monitor uses: set -o noclobber makes the
        # redirect fail when the file exists, even between the test and the write.
        if ( set -o noclobber; printf '%s %s\n' "$MYPID" "$(date -Iseconds)" >"$LOCK" ) 2>/dev/null; then
          [ "$WAITED" -gt 0 ] && echo "[cr] lock: acquired after ${WAITED}s ($LABEL, pid $MYPID)"
          exit 0
        fi
      fi
      [ "$(date +%s)" -ge "$DEADLINE" ] && break
      sleep 5
      WAITED=$((WAITED + 5))
    done
    echo "[cr] lock: busy for ${WAITED}s (owner pid $(owner || echo none), $LABEL did not act)"
    exit 75
    ;;
  release)
    MYPID=$$
    [ "${2:-}" = "--pid" ] && MYPID="${3:-$$}"
    P="$(owner || true)"
    if [ -n "$P" ] && [ "$P" = "$MYPID" ]; then
      rm -f "$LOCK" 2>/dev/null
      exit 0
    fi
    # An exec'd parent keeps its pid, so this is the normal path for a retry.
    exit 0
    ;;
  heartbeat)
    MYPID=$$
    [ "${2:-}" = "--pid" ] && MYPID="${3:-$$}"
    P="$(owner || true)"
    [ -n "$P" ] && [ "$P" = "$MYPID" ] && touch "$LOCK" 2>/dev/null
    exit 0
    ;;
  status)
    if [ ! -f "$LOCK" ]; then echo "free"; exit 0; fi
    if stale; then echo "free (stale lock removed)"; exit 0; fi
    AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
    echo "held by pid $(owner || echo unknown), heartbeat ${AGE}s ago"
    exit 1
    ;;
  *)
    echo "usage: crimeradar_lock.sh acquire [--label NAME] [--wait SECS] | release | heartbeat | status" >&2
    exit 2
    ;;
esac
