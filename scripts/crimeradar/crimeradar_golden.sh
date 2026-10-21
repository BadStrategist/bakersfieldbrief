#!/usr/bin/env bash
# A known-good emulator snapshot, and the leg's own health record.
#
# WHY THIS EXISTS (2026-10-20): every failure this leg has had is "the guest came
# up in a state nobody chose". Two cold boots a morning, the app's location picker
# refusing to open, a chip that reads "Set location": all of it is the guest
# rebuilding its screen from scratch and the app having no saved region. The fix
# is to stop rebuilding it. Boot from one snapshot that was proven good
# (`-snapshot golden -no-snapshot-save`, read-only, so no run can write a bad
# state back), and keep the cold boot only as the fallback.
#
# This file also owns the leg's health line: one JSON object per emulator start in
# work/crimeradar/emu/health.jsonl, so the 09:50 report can say which boot the
# morning used, how the region ended up, and which app version it ran. The golden
# build date lives in work/crimeradar/emu/golden.json.
#
# Subcommands:
#   check         0 golden is usable; 2 none; 3 expired (older than CR_GOLDEN_MAX_DAYS);
#                 4 the installed app version is not the one the snapshot was built
#                 on (a snapshot would roll the app back), 13 a path is missing
#   info          print golden.json (empty object when there is none)
#   version       print the installed versionName, or "unknown"
#   build         save the RUNNING emulator as "golden" and write golden.json.
#                 Refuses unless region_check passes: a bad state must never be
#                 the thing every later run starts from.
#   cycles N      N times: stop -> boot from golden -> region_check -> sweep -> stop.
#                 Prints one line per cycle and a total. Exit 0 only if all pass.
#   health        append one health line. Args: --boot golden|cold [--region ok|
#                 fixed-by-script|fixed-by-Claude|failed] [--app X.Y.Z] [--step NAME]
#   tally         N days of health lines, summarised (used by report.py)
set -u
unset PYTHONPATH PYTHONHOME

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"
ADB_BIN="${ADB_BIN:-C:/Users/tscac/Android/Sdk/platform-tools/adb.exe}"
export ADB_BIN
ADB="$SCRIPTS/adb_bounded.sh"
EMU="${CR_EMU:-C:/Users/tscac/Android/Sdk/emulator/emulator.exe}"
AVD="${CR_AVD:-CrimeRadar}"
DEV="${CR_DEVICE:-emulator-5554}"
PKG=com.newsbreak.crimeradar
SETREG="${CR_SETREG:-$SCRIPTS/crimeradar_set_region.sh}"
EMU_DIR="$REPO/work/crimeradar/emu"
GOLDEN_JSON="$EMU_DIR/golden.json"
HEALTH="$EMU_DIR/health.jsonl"
SNAP="golden"
MAX_DAYS="${CR_GOLDEN_MAX_DAYS:-21}"

[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }
[ -f "$ADB" ] || { echo "[cr] FAILED: script missing: $ADB (CR_SCRIPTS overrides the directory)"; exit 13; }
mkdir -p "$EMU_DIR" 2>/dev/null || true

PY="${CR_PYTHON:-$REPO/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "[cr] FAILED: no python to read the golden record"; exit 13; }

snapshot_dir() {   # where the AVD keeps snapshots; ANDROID_AVD_HOME overrides ~/.android/avd
  local root="${ANDROID_AVD_HOME:-$HOME/.android/avd}"
  printf '%s/%s.avd/snapshots/%s\n' "${root%/}" "$AVD" "$SNAP"
}

online() { "$ADB" devices 2>/dev/null | grep -q "^$DEV[[:space:]]*device"; }

version() {
  local v
  v="$("$ADB" -s "$DEV" shell dumpsys package "$PKG" 2>/dev/null \
        | grep -m1 -oE 'versionName=[^ ]+' | cut -d= -f2 | tr -d '\r')"
  printf '%s\n' "${v:-unknown}"
}

json_get() {   # $1 = key; prints the value or "" (golden.json is always this small)
  "$PY" - "$GOLDEN_JSON" "$1" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    d = {}
v = d.get(sys.argv[2], "")
print("" if v is None else v)
EOF
}

check() {
  [ -f "$GOLDEN_JSON" ] || { echo "[cr] golden: none ($GOLDEN_JSON)"; return 2; }
  [ -d "$(snapshot_dir)" ] || { echo "[cr] golden: golden.json exists but $(snapshot_dir) does not"; return 2; }
  local built age ver want
  built="$(json_get built)"
  want="$(json_get app_version)"
  [ -n "$built" ] || { echo "[cr] golden: golden.json has no build date"; return 2; }
  # Whole days since the build, in the leg's own clock.
  age="$("$PY" - "$built" <<'EOF'
import sys, datetime
try:
    b = datetime.date.fromisoformat(sys.argv[1][:10])
except Exception:
    print(-1); raise SystemExit
print((datetime.date.today() - b).days)
EOF
)"
  [ "$age" -ge 0 ] 2>/dev/null || { echo "[cr] golden: unreadable build date '$built'"; return 2; }
  if [ "$age" -gt "$MAX_DAYS" ]; then
    echo "[cr] golden: built $built, ${age} days old (limit ${MAX_DAYS}); rebuild it"
    return 3
  fi
  if online; then
    ver="$(version)"
    if [ -n "$want" ] && [ "$ver" != "$want" ] && [ "$ver" != "unknown" ]; then
      echo "[cr] golden: the app is $ver but the snapshot was built on $want; a load would roll it back"
      return 4
    fi
  fi
  local req
  req="$(json_get rebuild_requested)"
  echo "[cr] golden: usable (built $built, ${age} days old${want:+, app $want})"
  [ -n "$req" ] && echo "[cr] golden: a rebuild is due ($req); it keeps working until one passes"
  return 0
}

build() {
  if ! online; then
    echo "[cr] golden: FAILED: $DEV is not running; start it and set the region first"
    return 3
  fi
  # A region that is not Bakersfield is never a golden state.
  if ! bash "$SETREG" --print >/dev/null 2>&1; then
    echo "[cr] golden: FAILED: region_check does not pass; not saving this screen as golden"
    return 11
  fi
  bash "$SCRIPTS/crimeradar_lock.sh" acquire --pid $$ --label "golden build" --wait 300 </dev/null     || { echo "[cr] golden: FAILED: another run owns the emulator"; return 75; }
  export CR_LOCK_HELD=1
  trap 'bash "$SCRIPTS/crimeradar_lock.sh" release --pid $$ >/dev/null 2>&1 || true' EXIT
  # Make the state one an unattended run wants: no error dialogs, no immersive
  # cling, screen stays on, a plausible position. These are settings, and a
  # snapshot carries them, which is the point.
  "$ADB" -s "$DEV" shell settings put global hide_error_dialogs 1 >/dev/null 2>&1
  "$ADB" -s "$DEV" shell settings put secure immersive_mode_confirmations confirmed >/dev/null 2>&1
  "$ADB" -s "$DEV" shell svc power stayon true >/dev/null 2>&1
  "$ADB" -s "$DEV" shell settings put secure lockscreen.disabled 1 >/dev/null 2>&1
  "$ADB" -s "$DEV" emu geo fix -119.0187 35.3733 >/dev/null 2>&1
  sleep 2
  # Keep the previous golden until the new one is written: "save" overwrites, so
  # a failure here must not leave the leg with nothing to boot.
  local out
  out="$("$ADB" -s "$DEV" emu avd snapshot save "$SNAP" 2>&1 | tr -d '\r')"
  echo "[cr] golden: save said: ${out:-nothing}"
  case "$out" in
    *OK*) ;;
    *) echo "[cr] golden: FAILED: the snapshot was not saved"; return 1 ;;
  esac
  local ver
  ver="$(version)"
  "$PY" - "$GOLDEN_JSON" "$(date +%F)" "$ver" "$AVD" "$SNAP" <<'EOF'
import json, sys
path, built, ver, avd, snap = sys.argv[1:6]
d = {"built": built, "app_version": ver, "avd": avd, "snapshot": snap,
     "screen": "720x1560", "state": "region=Bakersfield, local feed tab selected"}
json.dump(d, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
EOF
  echo "[cr] golden: saved ($(json_get built), app $ver)"
  return 0
}

stop_emu() { bash "$SCRIPTS/crimeradar_emu_stop.sh" >/dev/null 2>&1 || true; }

boot_golden() {
  rm -f "$EMU_DIR/emulator_goldenboot.log"
  nohup "$EMU" -avd "$AVD" -no-window -snapshot "$SNAP" -no-snapshot-save \
    >"$EMU_DIR/emulator_goldenboot.log" 2>&1 &
  disown 2>/dev/null || true
  for _ in $(seq 1 60); do
    sleep 5
    online || continue
    [ "$("$ADB" -s "$DEV" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && {
      printf 'golden %s\n' "$(date -Iseconds)" >"$EMU_DIR/boot_mode" 2>/dev/null
      return 0
    }
  done
  return 1
}

# "emit-style sweep": read the visible feed with the parser the emit itself uses
# (scripts/crimeradar_monitor.py: home_feed + parse_feed), and require that it
# names the Kern chip and returns at least one card. Deliberately NOT
# `--once --json`: that poll writes seen.json, which would swallow the evening's
# "new" rows and change what the night leg reports. This read writes nothing.
sweep() {
  local x="$EMU_DIR/golden_cycle.xml"
  "$ADB" -s "$DEV" shell rm -f /sdcard/.cr_golden.xml >/dev/null 2>&1
  if ! "$ADB" -s "$DEV" shell uiautomator dump /sdcard/.cr_golden.xml >/dev/null 2>&1; then
    echo "[cr] golden: the sweep could not dump the screen"
    return 5
  fi
  "$ADB" -s "$DEV" shell cat /sdcard/.cr_golden.xml >"$x" 2>/dev/null
  "$PY" - "$REPO/scripts/crimeradar_monitor.py" "$x" <<'PY_EOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("crmon", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
xml = open(sys.argv[2], encoding="utf-8", errors="replace").read()
chip, local = m.home_feed(xml)
cards = m.parse_feed(xml)
print(f"[cr] golden: sweep read chip={chip!r} local_tab={local} cards={len(cards)}")
ok = m.chip_names_kern(chip) and local and len(cards) > 0
sys.exit(0 if ok else 5)
PY_EOF
}

cycles() {
  local n="${1:-10}" i pass=0 fail=0 rc reg sw
  case "$n" in ''|*[!0-9]*) echo "[cr] golden: cycles needs a count (1-50)"; return 2 ;; esac
  [ "$n" -ge 1 ] && [ "$n" -le 50 ] || { echo "[cr] golden: cycles count out of range"; return 2; }
  for i in $(seq 1 "$n"); do
    # Same lock as every other caller: a cycle must not boot over a poll.
    if ! bash "$SCRIPTS/crimeradar_lock.sh" acquire --pid $$ --label "golden cycle $i" --wait 300 </dev/null; then
      echo "[cr] golden cycle $i/$n: FAIL (another run owns the emulator)"
      fail=$((fail + 1)); continue
    fi
    export CR_LOCK_HELD=1
    stop_emu; sleep 5
    if ! boot_golden; then
      echo "[cr] golden cycle $i/$n: FAIL boot (golden did not come online)"
      fail=$((fail + 1)); stop_emu; continue
    fi
    bash "$SETREG" --print >/dev/null 2>&1; reg=$?
    sweep; sw=$?
    if [ "$reg" -eq 0 ] && [ "$sw" -eq 0 ]; then
      echo "[cr] golden cycle $i/$n: PASS (region ok, sweep ok)"
      pass=$((pass + 1))
    else
      echo "[cr] golden cycle $i/$n: FAIL (region_check exit $reg, sweep exit $sw)"
      fail=$((fail + 1))
    fi
    stop_emu
    unset CR_LOCK_HELD
    bash "$SCRIPTS/crimeradar_lock.sh" release --pid $$ >/dev/null 2>&1 || true
  done
  echo "[cr] golden: $pass/$n cycles passed, $fail failed"
  [ "$fail" -eq 0 ]
}

request() {   # $1 = why. Marks the snapshot as due for a rebuild in a window with room.
  local why="${1:-manual}"
  [ -f "$GOLDEN_JSON" ] || { echo "[cr] golden: no golden.json to mark"; return 2; }
  "$PY" - "$GOLDEN_JSON" "$why" "$(date -Iseconds)" <<'EOF'
import json, sys
path, why, ts = sys.argv[1:4]
try:
    d = json.load(open(path, encoding="utf-8"))
except Exception:
    d = {}
d["rebuild_requested"] = f"{ts} {why}"
json.dump(d, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
EOF
  echo "[cr] golden: rebuild requested ($why)"
}

refresh() {   # $1 = cycles to verify (default 3). Only runs when one was requested.
  local n="${1:-3}" why snap prev
  why="$(json_get rebuild_requested)"
  if [ -z "$why" ]; then
    echo "[cr] golden: no rebuild requested; nothing to do"
    return 0
  fi
  echo "[cr] golden: rebuild requested at $why"
  if ! bash "$SCRIPTS/crimeradar_lock.sh" acquire --pid $$ --label "golden refresh" --wait 300 </dev/null; then
    echo "[cr] golden: another run owns the emulator; the request stays for the next window"
    return 75
  fi
  export CR_LOCK_HELD=1
  stop_emu; sleep 5
  if ! boot_golden; then
    echo "[cr] golden: FAILED: the old snapshot does not boot; the request stays"
    return 3
  fi
  if ! bash "$SETREG" --print >/dev/null 2>&1; then
    echo "[cr] golden: FAILED: the region is not Bakersfield; not saving this as golden"
    return 11
  fi
  snap="$(snapshot_dir)"; prev="$EMU_DIR/golden_prev"
  # Keep the previous golden until the new one passes its cycles (add-on, A).
  rm -rf "$prev"
  [ -d "$snap" ] && cp -a "$snap" "$prev"
  if ! build; then
    echo "[cr] golden: FAILED to save; the old snapshot is still in place"
    return 1
  fi
  if cycles "$n"; then
    "$PY" - "$GOLDEN_JSON" <<'EOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d.pop("rebuild_requested", None)
json.dump(d, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
EOF
    echo "[cr] golden: refreshed and verified ($n cycles); the request is cleared"
    return 0
  fi
  echo "[cr] golden: the new snapshot failed its cycles; restoring the previous one"
  if [ -d "$prev" ]; then
    rm -rf "$snap" && cp -a "$prev" "$snap"
    echo "[cr] golden: previous snapshot restored"
  else
    echo "[cr] golden: FAILED: there was no previous snapshot to restore"
  fi
  return 1
}

health() {
  local boot=unknown region=unknown app="" step=unknown
  while [ $# -gt 0 ]; do
    case "$1" in
      --boot) boot="${2:-unknown}"; shift 2 ;;
      --region) region="${2:-unknown}"; shift 2 ;;
      --app) app="${2:-}"; shift 2 ;;
      --step) step="${2:-unknown}"; shift 2 ;;
      *) shift ;;
    esac
  done
  [ -n "$app" ] || app="$(version)"
  case "$boot" in golden|cold|unknown) ;; *) boot=unknown ;; esac
  case "$region" in ok|fixed-by-script|fixed-by-Claude|failed|unknown) ;; *) region=unknown ;; esac
  "$PY" - "$HEALTH" "$(date -Iseconds)" "$step" "$boot" "$region" "$app" <<'EOF'
import json, sys
path, ts, step, boot, region, app = sys.argv[1:7]
line = {"ts": ts, "step": step, "boot": boot, "region": region, "app": app}
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(line, sort_keys=True) + "\n")
EOF
  echo "emulator: boot=$boot, region=$region, app=$app"
}

tally() {
  local days="${1:-14}"
  "$PY" - "$HEALTH" "$days" <<'EOF'
import json, sys, datetime, collections
path, days = sys.argv[1], int(sys.argv[2])
cut = datetime.date.today() - datetime.timedelta(days=days)
rows = []
try:
    for ln in open(path, encoding="utf-8"):
        try:
            d = json.loads(ln)
            if datetime.date.fromisoformat(d["ts"][:10]) >= cut:
                rows.append(d)
        except Exception:
            pass
except OSError:
    pass
c = collections.Counter((d.get("boot"), d.get("region")) for d in rows)
print(f"emulator, last {days} days: {len(rows)} start(s)")
for (b, r), n in sorted(c.items(), key=lambda kv: -kv[1]):
    print(f"  boot={b} region={r}: {n}")
EOF
}

case "${1:-}" in
  check) check ;;
  info) [ -f "$GOLDEN_JSON" ] && cat "$GOLDEN_JSON" || echo "{}" ;;
  version) version ;;
  build) build ;;
  cycles) shift; cycles "$@" ;;
  request) shift; request "${1:-manual}" ;;
  refresh) shift; refresh "${1:-3}" ;;
  health) shift; health "$@" ;;
  tally) shift; tally "$@" ;;
  *) echo "usage: crimeradar_golden.sh check|info|version|build|cycles N|request WHY|refresh [N]|health --boot X --region Y|tally N" >&2; exit 2 ;;
esac
