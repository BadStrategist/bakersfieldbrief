#!/usr/bin/env bash
# Snapshot the guest and the host when the CrimeRadar leg fails, and at every
# stop (the healthy baseline to read a failure against).
#
# WHY: on 2026-10-11 the question "is the GPU path the cause?" could not be
# answered from anything on disk. The emulator's own output went to /dev/null,
# nothing recorded the host GPU at a failure, and two of that day's failures
# (06:55, 07:54) had no RAM reading at all. The answer given was "leave
# hw.gpu.mode=host", on indirect evidence. These files are what makes that
# answer checkable, either way.
#
#   crimeradar_diag.sh "<reason>"   write work/crimeradar/emu/diag_<stamp>.txt
#   crimeradar_diag.sh --tidy       drop files over 14 days old and cut an
#                                   emulator log that outgrew its cap
#
# Called by: the preflight on exit 3, 5 and 12 and before a wedge recycle; the
# night, emit and morning scripts on monitor exit 4, 5, 7 and 8; the stop script
# just before it stops a running emulator. The preflight keeps the emulator's
# own output next to these as emulator_<stamp>.log (see its start line).
#
# How to read one. Compare a failure with the stop snapshot of a night that
# worked. The last section of every file ("signals") counts the same things, so
# two files can be compared without reading the logcat.
#
#   Where              Healthy                    GPU is the cause             RAM or guest state is the cause
#   emulator log       names the NVIDIA adapter,  EGL or GL context errors,    clean
#                      no EGL or GL error lines   or a fallback to a software
#                                                 renderer
#   host gpu           qemu listed, ~175 MiB,     qemu missing, or             same as healthy
#                      low utilisation            utilisation pinned
#   nvlddmkm events    0                          1 or more near the failure   0
#   last ANR           empty                      main or RenderThread in      blocked on binder or IO
#                                                 eglSwapBuffers, a fence
#                                                 wait or gfxstream
#   logcat             no lowmemorykiller kills   GL error, EGL_BAD_, Davey!   lmkd kills, "Low on memory",
#                                                 bursts with no memory lines  kswapd busy
#   guest psi, vmstat  memory "some avg10" near   near 0                       raised PSI, low MemAvailable,
#                      0, low wa                                               high wa (iowait)
#   host ram           above the memguard floor   above the floor              below the floor
#
# A failure whose file matches the middle column is evidence FOR a GPU fault,
# and one such night is enough to trial `-gpu swiftshader`. A failure that
# matches the right column, or none, is evidence against. The signals are
# counts, never a verdict: this script does not decide.
#
# The largest host processes are listed by name so that anything holding RAM
# during a failure is on record without being on a close list (PredatorSense,
# 368 MB when the owner has it open, is the case this was added for).
#
# CR_DIAG=0 turns it off. CR_EMULOG_MAX_MB is the emulator log cap (default 20).
# Exit codes: always 0. It reports; it is never the reason a run fails.
set -u

# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
ADB_BIN="${ADB_BIN:-C:/Users/tscac/Android/Sdk/platform-tools/adb.exe}"
export ADB_BIN
ADB="$SCRIPTS/adb_bounded.sh"     # bounded: a wedged guest must fail, never hang
DEV="${CR_DEVICE:-emulator-5554}"
DIR="$REPO/work/crimeradar/emu"
MAX_MB="${CR_EMULOG_MAX_MB:-20}"
REASON="${1:-unspecified}"

if [ "${CR_DIAG:-1}" = "0" ]; then
  echo "[cr] diagnostics: off (CR_DIAG=0)"
  exit 0
fi
[ -d "$REPO/work/crimeradar" ] || { echo "[cr] diagnostics: $REPO/work/crimeradar is missing; nothing written"; exit 0; }
mkdir -p "$DIR" 2>/dev/null || { echo "[cr] diagnostics: cannot create $DIR; nothing written"; exit 0; }

have() { command -v "$1" >/dev/null 2>&1; }
size_kb() { echo $(( $(stat -c %s "$1" 2>/dev/null || echo 0) / 1024 )); }
newest_emulog() { ls -t "$DIR"/emulator_*.log 2>/dev/null | head -n 1; }

if [ "$REASON" = "--tidy" ]; then
  find "$DIR" -type f -mtime +14 -delete 2>/dev/null
  # -verbose is the emulator's init-time debug output, and how much it writes
  # over a session was not measured when the flag was added. A log over the cap
  # keeps its first 256 KB (the backend it chose) and its newest half-cap, and
  # says so here and in NOTES.txt. It is only cut once its emulator has gone:
  # the rename fails on a file a live process holds, and the file is left whole.
  for L in "$DIR"/emulator_*.log; do
    [ -f "$L" ] || continue
    KB="$(size_kb "$L")"
    [ "$KB" -ge $((MAX_MB * 1024)) ] || continue
    if { head -c 262144 "$L"
         printf '\n[cr] ---- cut here: this log was %s MB, over the %s MB cap ----\n' "$((KB / 1024))" "$MAX_MB"
         tail -c $((MAX_MB * 524288)) "$L"; } >"$L.tmp" 2>/dev/null && mv -f "$L.tmp" "$L" 2>/dev/null; then
      MSG="$(basename "$L") was $((KB / 1024)) MB, over the $MAX_MB MB cap, and was cut. -verbose writes too much for one session: set CR_EMU_VERBOSE=0 in the preflight's environment, which keeps the redirect and drops the flag"
      echo "[cr] diagnostics: $MSG"
      printf '%s %s\n' "$(date '+%F %T')" "$MSG" >>"$DIR/NOTES.txt" 2>/dev/null || true
    else
      rm -f "$L.tmp" 2>/dev/null
    fi
  done
  exit 0
fi

F="$DIR/diag_$(date +%F_%H%M%S).txt"
# One string per remote command: an argument that starts with / is rewritten
# into a Windows path when MSYS path conversion is on.
guest_sh() { ADB_TIMEOUT=20 "$ADB" -s "$DEV" shell "$1" 2>&1 | tr -d '\r'; }

host() {
  echo "== host gpu (pstate, power, utilisation, memory used)"
  if have nvidia-smi; then
    timeout 15 nvidia-smi --query-gpu=pstate,power.draw,utilization.gpu,memory.used --format=csv,noheader 2>&1 | tr -d '\r'
    echo "-- the emulator on the gpu"
    timeout 15 nvidia-smi 2>&1 | tr -d '\r' | grep -iE "qemu|emulator" || echo "nvidia-smi lists no qemu process"
  else
    echo "nvidia-smi is not on this machine"
  fi
  echo "== host ram, the largest processes, and display driver events"
  if have powershell; then
    timeout 60 powershell -NoProfile -Command "
      \$os = Get-CimInstance Win32_OperatingSystem
      'free MB: ' + [int](\$os.FreePhysicalMemory/1024) + ' of ' + [int](\$os.TotalVisibleMemorySize/1024)
      'commit free MB: ' + [int](\$os.FreeVirtualMemory/1024) + ' of ' + [int](\$os.TotalVirtualMemorySize/1024)
      Get-CimInstance Win32_Process | Group-Object Name | ForEach-Object {
        [pscustomobject]@{ MB = [int]((\$_.Group | Measure-Object PrivatePageCount -Sum).Sum/1MB); N = \$_.Count; Name = \$_.Name }
      } | Sort-Object MB -Descending | Select-Object -First 12 | ForEach-Object { '{0,6} MB private  {1,3} x {2}' -f \$_.MB, \$_.N, \$_.Name }
      \$ev = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'nvlddmkm'; StartTime = (Get-Date).AddHours(-24) } -ErrorAction SilentlyContinue)
      'nvlddmkm events, last 24 h: ' + \$ev.Count
      \$ev | Select-Object -First 5 | ForEach-Object { '  ' + \$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + ' id ' + \$_.Id }
    " 2>&1 | tr -d '\r'
  else
    echo "powershell is not on this machine"
  fi
}

emulog() {
  echo "== emulator log"
  L="$(newest_emulog)"
  if [ -z "$L" ]; then
    echo "none kept yet (the preflight writes one each time it starts the emulator)"
    return
  fi
  KB="$(size_kb "$L")"
  echo "$L: $KB KB, last written $(date -r "$L" '+%F %T' 2>/dev/null || echo unknown)"
  if [ "$KB" -ge $((MAX_MB * 1024)) ]; then
    echo "NOTE: over the $MAX_MB MB cap while still being written; -verbose writes too much, set CR_EMU_VERBOSE=0"
  fi
  echo "-- backend and renderer lines"
  grep -iE "renderer|vendor|opengl|gles|vulkan|angle|swiftshader|lavapipe|gpu" "$L" 2>/dev/null | head -n 40
  echo "-- error lines (newest 60)"
  grep -inE "error|fail|fallback|lost" "$L" 2>/dev/null | tail -n 60
}

guest() {
  if ! "$ADB" devices 2>/dev/null | grep -q "^$DEV[[:space:]]*device"; then
    echo "== guest: $DEV is not online; no guest sections"
    return
  fi
  if ! ADB_TIMEOUT=10 "$ADB" -s "$DEV" shell true >/dev/null 2>&1; then
    echo "== guest: $DEV is online but its shell did not answer in 10 s; no guest sections"
    return
  fi
  echo "== guest memory";           guest_sh "cat /proc/meminfo" | head -n 6
  echo "== guest psi (memory, io, cpu)"
  guest_sh "cat /proc/pressure/memory /proc/pressure/io /proc/pressure/cpu"
  echo "== guest vmstat (1 s x 5)"; guest_sh "vmstat 1 5"
  echo "== last ANR";               guest_sh "dumpsys activity lastanr" | head -n 150
  echo "== systemui frames";        guest_sh "dumpsys gfxinfo com.android.systemui" | head -n 40
  echo "== guest renderer";         guest_sh "getprop" | grep -iE "egl|gles|hwui|renderer|gfxstream"
  echo "== logcat (newest 4000 lines)"
  ADB_TIMEOUT=60 "$ADB" -s "$DEV" logcat -d -b main,system,crash -t 4000 2>&1 | tr -d '\r'
}

count() { grep -ciE "$1" "$2" 2>/dev/null || true; }
signals() {
  L="$(newest_emulog)"
  echo "emulator log, EGL or GL error lines: $([ -n "$L" ] && count 'egl.*(error|fail|bad)|opengl.*(error|fail)|gl error|context lost|fallback' "$L" || echo 'no log')"
  if grep -q '^== logcat' "$F" 2>/dev/null; then
    echo "logcat, EGL or GL error lines: $(count 'EGL_BAD_|GL error|eglSwapBuffers|E libEGL|E OpenGLRenderer|E EGL_emulation' "$F")"
    echo "logcat, low-memory lines: $(count 'lowmemorykiller|lmkd.*kill|Low on memory' "$F")"
    echo "logcat, Davey! lines: $(count 'Davey!' "$F")"
    echo "logcat, ANR lines: $(count 'ANR in ' "$F")"
    echo "guest memory pressure: $(grep -m1 '^some avg10' "$F" 2>/dev/null || echo 'no reading')"
  else
    echo "guest: not read ($(grep -m1 '^== guest: ' "$F" 2>/dev/null | cut -c11-))"
  fi
  echo "host: $(grep -m1 '^free MB' "$F" 2>/dev/null || echo 'no RAM reading')"
  echo "host: $(grep -m1 '^nvlddmkm events' "$F" 2>/dev/null || echo 'no driver event reading')"
}

{
  echo "== reason: $REASON"
  echo "== taken:  $(date '+%F %T %a')"
  host
  emulog
  guest
} >"$F" 2>&1
SIG="$(signals)"
{
  echo "== signals (counts from this file and the emulator log; evidence, not a verdict)"
  printf '%s\n' "$SIG"
} >>"$F" 2>&1
echo "[cr] diagnostics: $F ($REASON)"
exit 0
