#!/usr/bin/env bash
# CrimeRadar night monitor for The Kern Overnight (bakersfieldbrief.com).
# Second path to the same dispatch feed: polls the CrimeRadar emulator (AVD CrimeRadar)
# for new HIGH+ postings and captures each one's dispatch clip out of the app's
# own ExoPlayer cache. Script-only, no LLM.
#
# The Hermes cron runner injects PYTHONPATH/PYTHONHOME; the project .venv must
# not inherit them, so they are cleared first.
set -u
unset PYTHONPATH PYTHONHOME

# Siblings and the repo root resolve from this file's own location
# (scripts/crimeradar/ in the repo; hermes/scripts/<name> is a shim that execs
# it). CR_SCRIPTS and CR_REPO override them. Exit 13 = a sibling is missing.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
cd "$REPO" || { echo "[cr] repo missing: $REPO"; exit 2; }
for NEED in crimeradar_memguard.sh crimeradar_preflight.sh; do
  [ -f "$SCRIPTS/$NEED" ] || { echo "[cr] FAILED: script missing: $SCRIPTS/$NEED (CR_SCRIPTS overrides the directory)"; exit 13; }
done

# Clock guard. Hermes runs a missed schedule once, immediately ("executed once
# now", cron/jobs.py), so a poll that was missed can fire at any hour and would
# cold-boot the emulator in the middle of the owner's day, which is the one thing
# he asked to stop. Only the three real windows may start it:
#   */15 21-22 dow 0-4  evening burst (Sun-Thu nights, 21:00-22:45)
#   */15 0     dow 6,0  weekend burst (Fri, Sat nights, 00:00-00:45)
#   */15 5-6   daily    pre-dawn block (05:00-06:45)
# Skipping is not a failure, so it exits 0 with a line of explanation.
H=$((10#$(date +%H))); U=$(date +%u)   # 1=Mon .. 7=Sun
case "$H:$U" in
  21:[123457]|22:[123457]) : ;;
  0:[67])                  : ;;
  5:*|6:*)                 : ;;
  *) echo "[cr] $(date '+%a %H:%M') is outside the capture window; not starting the emulator"
     exit 0 ;;
esac

# Free host RAM first: a starved host ANRs, and the ANR owns the screen while
# every tap lands on it, so the leg dies looking like an app UI change. Only the
# two apps the owner named, only in the night window, only when free RAM is under
# the floor. It never fails the run.
bash "$SCRIPTS/crimeradar_memguard.sh" </dev/null || true

# adb is only a transport: if the emulator process is gone there is nothing to
# talk to. Bring it up (and the app to the foreground) before polling.
bash "$SCRIPTS/crimeradar_preflight.sh" </dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  # Propagate the preflight's own code (3 offline, 4 no foreground app, 5 screen
  # unreadable, 6 no network, 11 region could not be set). Collapsing every fault
  # to 3 hid a keyguard and a dead route behind the same number for two days.
  echo "[cr] emulator unavailable (preflight code $rc); poll skipped"
  exit "$rc"
fi

# </dev/null: the Hermes cron runner hands scripts an invalid stdin.
exec ./.venv/Scripts/python.exe scripts/crimeradar_monitor.py --once --audio --json </dev/null
