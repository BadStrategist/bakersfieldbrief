#!/usr/bin/env bash
# Bring the CrimeRadar emulator up and the app to the foreground.
#
# Why this exists: adb is only a transport. The app lives inside the running
# Android VM, so if the emulator process is gone (the window was closed, the
# host rebooted) every CLI call has nothing to talk to. Verified: the monitor
# prints "device emulator-5554 not online" and exits 2.
#
# Safe to run when everything is already up: it then only foregrounds the app.
# Exit codes: 0 ready (or a capture owns the screen and the app is top),
# 3 could not bring the device online, 4 the app is not in the foreground,
# 5 the screen cannot be read, 6 the guest cannot reach the network,
# 11 the app's region could not be set to Bakersfield (the setter's own code),
# 12 the guest is wedged (online, but its shell does not answer),
# 13 a path this script needs is missing (the repo, or a sibling script).
set -u
unset PYTHONPATH PYTHONHOME

# This file lives in the repo at scripts/crimeradar/, next to its siblings; the
# hermes/scripts/<name> the cron jobs point at is a shim that execs it. So the
# siblings and the repo root resolve from this file's own location. CR_SCRIPTS
# and CR_REPO override them.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"
REPO="${CR_REPO:-$(cd "$HERE/../.." && { pwd -W 2>/dev/null || pwd; })}"

# ADB_BIN, CR_EMU, CR_REPO and CR_SETREG are overridable so
# tests/test_crimeradar_preflight.py can drive this script against a scripted
# adb. No scheduled job sets them.
ADB_BIN="${ADB_BIN:-C:/Users/tscac/Android/Sdk/platform-tools/adb.exe}"
export ADB_BIN
ADB="$SCRIPTS/adb_bounded.sh"     # bounded: a wedged guest must fail, never hang
EMU="${CR_EMU:-C:/Users/tscac/Android/Sdk/emulator/emulator.exe}"
AVD="${CR_AVD:-CrimeRadar}"     # NOT "CrimeRadar5554": that is only the window title
DEV="${CR_DEVICE:-emulator-5554}"
PKG=com.newsbreak.crimeradar
LOCK="$REPO/work/crimeradar/emulator.lock"
SETREG="${CR_SETREG:-$SCRIPTS/crimeradar_set_region.sh}"

# Before anything touches adb: a missing sibling used to surface much later, as
# an offline device or a region that "could not be set".
[ -d "$REPO" ] || { echo "[cr] FAILED: repo missing: $REPO (CR_REPO overrides)"; exit 13; }
for NEED in "$ADB" "$SCRIPTS/crimeradar_emu_stop.sh" "$SETREG"; do
  [ -f "$NEED" ] || { echo "[cr] FAILED: script missing: $NEED (CR_SCRIPTS overrides the directory)"; exit 13; }
done

online() { "$ADB" devices | grep -q "^$DEV[[:space:]]*device"; }

# The owner's rule (2026-10-11): Discord and Claude Desktop are closed while the
# leg runs. Here, because every path that starts the emulator comes through this
# script, and before the boot, because the RAM is wanted for it. The stop script
# reopens what this closed. It never fails the run, and a missing script is a
# line in the log, not exit 13: the leg does not depend on it. Not on the wedge
# re-exec: the first pass already closed them.
if [ "${CR_WEDGE_RETRY:-0}" != "1" ]; then
  if [ -f "$SCRIPTS/crimeradar_apps.sh" ]; then
    bash "$SCRIPTS/crimeradar_apps.sh" close </dev/null || true
  else
    echo "[cr] leg apps: $SCRIPTS/crimeradar_apps.sh is missing; Discord and Claude Desktop stay open"
  fi
fi

if ! online; then
  # Headless by default so it survives unattended. Set CR_EMU_WINDOW=1 to see it.
  WIN=""
  [ "${CR_EMU_WINDOW:-0}" = "1" ] || WIN="-no-window"
  echo "[cr] $DEV offline: starting AVD $AVD ${WIN:-with window}"
  # -no-snapshot-save: a killed emulator can leave a snapshot that refuses to
  # load; never depend on one. Audio stays ENABLED: clips are written by the
  # player as it plays, and a null audio sink is not verified to still fill the
  # ExoPlayer cache.
  # -no-snapshot-load matters as much as -no-snapshot-save: the AVD had
  # fastboot.forceFastBoot=yes, so a restart restored a snapshot whose app state
  # and GPS were wrong, and the guest looked healthy while the read path was
  # dead. A cold boot is the point.
  nohup "$EMU" -avd "$AVD" $WIN -no-snapshot-save -no-snapshot-load >/dev/null 2>&1 &
  disown 2>/dev/null || true
  for _ in $(seq 1 60); do
    sleep 5
    online || continue
    [ "$("$ADB" -s "$DEV" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
  done
fi

if ! online; then
  echo "[cr] FAILED to bring $DEV online (AVD $AVD)"
  exit 3
fi

# A guest can be wedged, and that is not the same fault as being offline:
# `adb devices` still lists it as `device` while every `shell` call blocks
# forever. Verified 2026-10-10: the guest wedged just after midnight and five
# jobs sat on one `settings put global hide_error_dialogs 1` for 2.5 h, so the
# night's second source never staged and the publish held all day. Prove one
# shell round-trip before anything else touches the screen, and recycle the
# emulator once (a wedged guest cannot be rescued from inside).
if ! "$ADB" -s "$DEV" shell true >/dev/null 2>&1; then
  if [ "${CR_WEDGE_RETRY:-0}" = "1" ]; then
    echo "[cr] FAILED: $DEV still does not answer its shell after a cold boot; the guest is wedged"
    exit 12
  fi
  echo "[cr] $DEV is online but its shell does not answer (adb timed out); recycling the emulator"
  CR_WEDGE_RETRY=1 bash "$SCRIPTS/crimeradar_emu_stop.sh" >/dev/null 2>&1
  sleep 5
  CR_WEDGE_RETRY=1 exec bash "$0"
fi

# A cold boot leaves the app stopped, and normalise_feed's tab taps would then
# land on the launcher. Foreground it.
# Verified 2026-10-09: the old version discarded the launch result and printed
# "foregrounded" without looking, so a system ANR dialog and a bare launcher both
# passed as ready. Two guards, both cheap:
#   * hide_error_dialogs: Android kills a hung process instead of covering the
#     screen with a dialog the monitor's taps cannot reach (set every run; it is
#     a global setting that can be reset by an image update). Its value is read
#     back at the end: setting it and printing "suppressed" was a claim the old
#     version never checked.
#   * the geo fix below is NOT a region guard. It only gives the guest a
#     plausible position. The app runs off its own location picker, every
#     provider here reports last location=null, and a pinned GPS proved nothing
#     while the feed was serving Mendocino County. The region guard is in the
#     monitor: it reads the feed name and location off the screen and exits 9
#     when they are not Bakersfield Police, Fire and EMS / Kern, California.
"$ADB" -s "$DEV" shell settings put global hide_error_dialogs 1 >/dev/null 2>&1
# Android covers anything full screen with its immersive cling ("Viewing full
# screen / Got it"), and it reappears on every new full-screen activity. Verified
# 2026-10-09: a playing unlock ad sat behind that cling for 72+ seconds and taps
# at the cling did not clear it. Confirming the setting once stops the cling.
"$ADB" -s "$DEV" shell settings put secure immersive_mode_confirmations confirmed >/dev/null 2>&1
"$ADB" -s "$DEV" emu geo fix -119.0187 35.3733 >/dev/null 2>&1
focus() { "$ADB" -s "$DEV" shell dumpsys activity activities 2>/dev/null \
            | grep -m1 -oE 'topResumedActivity=ActivityRecord\{[^ ]+ [^ ]+ [^ ]+' \
            | awk '{print $NF}' | cut -d/ -f1; }

# Do not touch the screen while a capture is running.
# Claude's review, 2026-10-09: the launch, the keyguard keys, the uiautomator
# probe and the volume keys all reach the screen, and a run playing a clip
# cannot survive them. The probe can also fail during playback ("could not get
# idle state"), which turned a benign overlap into "emulator unavailable". The
# monitor holds emulator.lock with a heartbeat, so a fresh lock means another run
# owns the screen. The heartbeat alone is not enough: a run killed mid-capture
# leaves a fresh mtime behind for a process that is already gone, and the next
# ten minutes of runs then refuse to touch the screen. Verified 2026-10-09: a
# cut-off poll left `53776 <iso>` behind and the emit refused with
# "busy ... 46s ago". The monitor owns that rule (pid liveness, not age alone),
# so ask it instead of testing the mtime here.
if [ -f "$LOCK" ]; then
  if ( cd "$REPO" && ./.venv/Scripts/python.exe scripts/crimeradar_monitor.py --lock-reclaim </dev/null ); then
    :                                  # no live owner: the lock is gone, carry on
  else
    NOW=$(date +%s)
    MT=$(stat -c %Y "$LOCK" 2>/dev/null || echo 0)
    AGE=$((NOW - MT))
    TOP="$(focus)"
    if [ "$TOP" = "$PKG" ]; then
      echo "[cr] $DEV busy: a capture holds emulator.lock (${AGE}s), leaving the screen alone"
      exit 0
    fi
    echo "[cr] FAILED: a capture holds emulator.lock but the foreground app is '${TOP:-unknown}', not $PKG"
    exit 4
  fi
fi

# An unattended emulator must hold no keyguard and keep its screen on, and this
# must happen BEFORE the launch. Verified 2026-10-09 on a cold boot: the guest
# came up locked with the LAUNCHER in front, and starting the app behind a live
# keyguard does not bring it to the foreground. The launch loop then retried for
# a minute against a locked screen and the probe failed with "null root node".
# `-no-snapshot-load` makes this the normal path, not an edge case: every boot
# starts locked.
"$ADB" -s "$DEV" shell svc power stayon true >/dev/null 2>&1
"$ADB" -s "$DEV" shell locksettings set-disabled true >/dev/null 2>&1
"$ADB" -s "$DEV" shell settings put secure lockscreen.disabled 1 >/dev/null 2>&1
keyguard_up() { "$ADB" -s "$DEV" shell dumpsys window 2>/dev/null | grep -m1 -q "mDreamingLockscreen=true"; }
for _ in $(seq 1 8); do
  keyguard_up || break
  "$ADB" -s "$DEV" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
  "$ADB" -s "$DEV" shell wm dismiss-keyguard >/dev/null 2>&1
  "$ADB" -s "$DEV" shell input keyevent 82 >/dev/null 2>&1
  sleep 3
done

# Positive marker with a deadline, not a fixed sleep. Verified 2026-10-09: the
# first launch after a cold boot can still be settling at 8 s, and a single check
# then reports a false failure. Relaunch while waiting instead of giving up.
launch() { "$ADB" -s "$DEV" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; }
launch
for _ in $(seq 1 12); do
  sleep 5
  [ "$(focus)" = "$PKG" ] && break
  launch
done
# Readability, not just focus: a locked screen has no root node, and
# `topResumedActivity` named the app while every dump returned "null root node".
#
# One successful dump is the answer. The old version broke out of the loop on a
# good dump and then dumped AGAIN to decide, so a screen it had just read could
# still exit 5 on that one extra, unretried dump. Verified 2026-10-11: the 00:15
# poll exited 5 in 29 s, and the path through six failed dumps sleeps 29 s here
# plus the memguard's own 4.7 s before any adb call, so a dump had succeeded.
# uiautomator's own words are kept for the failure line: "keyguard or black
# screen" was a guess, and the output that would have told them apart went to
# /dev/null on every failure so far.
DUMP_SAID=""
dump_ok() {
  ADB_TIMEOUT=45 "$ADB" -s "$DEV" shell rm -f /sdcard/.cr_probe.xml >/dev/null 2>&1
  DUMP_SAID="$(ADB_TIMEOUT=45 "$ADB" -s "$DEV" shell uiautomator dump /sdcard/.cr_probe.xml 2>&1 \
    | tr -d '\r' | tr '\n' ' ' | cut -c1-200)"
  printf '%s\n' "$DUMP_SAID" | grep -qi "dumped to"
}
READABLE=0
for _ in $(seq 1 6); do
  if dump_ok; then READABLE=1; break; fi
  "$ADB" -s "$DEV" shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
  "$ADB" -s "$DEV" shell wm dismiss-keyguard >/dev/null 2>&1
  sleep 4
done
if [ "$READABLE" != "1" ]; then
  KG="$("$ADB" -s "$DEV" shell dumpsys window 2>/dev/null | grep -m1 -oE 'isKeyguardShowing=(true|false)')"
  WAKE="$("$ADB" -s "$DEV" shell dumpsys power 2>/dev/null | grep -m1 -oE 'mWakefulness=[A-Za-z]+')"
  echo "[cr] FAILED: $DEV is online but the screen cannot be read; uiautomator said: '${DUMP_SAID:-nothing (no answer within 45 s)}'; foreground is '$(focus)', ${KG:-isKeyguardShowing=unknown}, ${WAKE:-mWakefulness=unknown}"
  exit 5
fi

# Region self-heal. VERIFIED 2026-10-09: a cold boot loses the app's chosen
# location. After `adb emu kill` and a cold start the chip read
# "5000 Vista Del Lago Rd" and the feed served Mendocino rows, which the monitor
# refuses (exit 9). Setting it here is what lets the emulator stay DOWN between
# the morning pass and the 19:00 monitor instead of holding about 3 GB of host
# RAM all day for one saved setting.
# Exit 11 = the region could not be set. Not 7: the monitor owns 7 (system
# dialog) and 9 (wrong feed), and this script owns 3/4/5/6.
OUT="$(bash "$SETREG" --print 2>/dev/null)"; SRC=$?
CHIP="$(printf '%s\n' "$OUT" | head -n 1)"
if [ "$SRC" = "0" ]; then
  echo "[cr] region: ${CHIP:-unknown}"
else
  echo "[cr] region is '${CHIP:-unknown}' (set_region code $SRC); setting it to Bakersfield"
  if ! bash "$SETREG" </dev/null; then
    echo "[cr] FAILED: the region is '$(bash "$SETREG" --print 2>/dev/null | head -n 1)' and could not be set to Bakersfield"
    exit 11
  fi
  echo "[cr] region set: $(bash "$SETREG" --print 2>/dev/null | head -n 1)"
fi

# Keep the emulator SILENT on the host. Clips are captured by playing them, and
# with media volume up every capture plays scanner audio through the PC
# speakers all night. Volume 0 does not affect capture: the clip is rebuilt from
# the player's download cache, not from the sound output (verified). The
# volume-down key is used because `cmd media_session volume --set` is ignored
# on this image. Keys are only sent when the volume is not already 0.
vol() { "$ADB" -s "$DEV" shell cmd media_session volume --stream 3 --get 2>/dev/null | grep -o 'volume is [0-9]*' | grep -o '[0-9]*$' | tail -n 1; }
if [ "$(vol)" != "0" ]; then
  for _ in $(seq 1 16); do "$ADB" -s "$DEV" shell input keyevent 25 >/dev/null 2>&1; done
  sleep 4     # let the volume panel close before anything reads the screen
  echo "[cr] emulator media volume was up; now $(vol)"
fi
TOP="$(focus)"
if [ "$TOP" != "$PKG" ]; then
  echo "[cr] FAILED: $DEV is online but the foreground app is '${TOP:-unknown}', not $PKG"
  exit 4
fi

# Network: a lost default route was one of the faults on 2026-10-09. wlan0 held
# its AVD address, the app said "Couldn't load updates", and the monitor reported
# zero cards, which it blamed on the UI. The route table here is not a reliable
# test (it can be empty while the guest still reaches the network), so this
# pings, tries ONE Wi-Fi cycle, and only then fails.
net_up() { "$ADB" -s "$DEV" shell ping -c 1 -W 3 8.8.8.8 2>&1 | grep -qE "[1-9] (packets )?received"; }
NET=unknown
if net_up; then
  NET=ok
else
  echo "[cr] the guest cannot reach 8.8.8.8; cycling Wi-Fi"
  "$ADB" -s "$DEV" shell svc wifi disable >/dev/null 2>&1
  sleep 3
  "$ADB" -s "$DEV" shell svc wifi enable >/dev/null 2>&1
  for _ in $(seq 1 12); do
    sleep 5
    net_up && { NET=ok; break; }
  done
  [ "$NET" = "ok" ] || NET=down
fi
if [ "$NET" = "down" ]; then
  echo "[cr] FAILED: $DEV is up and $PKG is foreground, but the guest has no network; the feed cannot load"
  exit 6
fi

HIDE="$("$ADB" -s "$DEV" shell settings get global hide_error_dialogs 2>/dev/null | tr -d '\r')"
echo "[cr] $DEV ready, $PKG foregrounded, screen readable, hide_error_dialogs=${HIDE:-unset}, network=$NET"