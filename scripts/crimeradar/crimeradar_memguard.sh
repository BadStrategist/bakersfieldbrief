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
# Deliberately conservative:
#   * only in the night window (19:00-06:59), because the 07:15 emit and the
#     07:50 morning pass must not have the owner's browser pulled out from under
#     him while he reads the brief, and the 09:15 social push uses the Chrome
#     profile on 9223;
#   * only when free physical memory is below the floor, so an idle box is never
#     disturbed;
#   * the floor and the window are overridable for a dry run (see below).
#
# Dry run (nothing is killed):
#   CR_MEM_DRY=1 CR_MEM_WINDOW=13 CR_MEM_FLOOR_MB=999999 bash crimeradar_memguard.sh
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
WINDOW="${CR_MEM_WINDOW:-19 20 21 22 23 00 01 02 03 04 05 06}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
LOG="$REPO/work/crimeradar/memguard.log"
[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }

HOUR=$(date +%H)
FOUND=0
for h in $WINDOW; do
  [ "$HOUR" = "$h" ] && FOUND=1
done
[ "$FOUND" = "1" ] || exit 0

free_mb() {
  powershell -NoProfile -Command \
    "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'
}

BEFORE=$(free_mb)
[ -n "$BEFORE" ] || exit 0
[ "$BEFORE" -ge "$FLOOR_MB" ] && exit 0

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

for NAME in RuneLite chrome; do
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
if [ -n "${AFTER:-}" ] && [ "$AFTER" -lt "$FLOOR_MB" ]; then
  echo "[cr] WARNING: still below ${FLOOR_MB} MB; the leg may ANR. Consider moving this leg to a bigger box."
fi
exit 0
