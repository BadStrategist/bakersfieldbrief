#!/usr/bin/env bash
# Put the CrimeRadar app back on Bakersfield.
#
# WHY: the app runs off its own location picker and does NOT keep the choice
# across a cold boot. Verified 2026-10-09: after `adb emu kill` and a cold start
# the chip read "Nationwide Ukiah, CA" and the feed served Mendocino rows, which
# the leg would have staged as Bakersfield Police, Fire and EMS. GPS is no help:
# every provider in the guest reports last location=null, and pinning the
# emulator position changed nothing.
#
# Selectors, all verified against live dumps on 2026-10-09 (720x1560):
#   chip          com.newsbreak.crimeradar:id/txt_location_feed_tab
#   chip button   com.newsbreak.crimeradar:id/location_feed_tab_container
#                 (clickable, [32,169][438,241], carries selected="true")
#   scope tab     com.newsbreak.crimeradar:id/national_feed_tab_container
#                 "Nationwide" [462,169][688,241] - a DIFFERENT control, and
#                 tapping it opens no picker
#   picker open   topResumedActivity contains
#                 com.particlemedia.feature.map.MapLocationListActivity
#   picker search com.newsbreak.crimeradar:id/search_tv
#                 "Search address or zip code"
#   picker rows   com.newsbreak.crimeradar:id/place_name_txt
#                 ("Bakersfield, CA", "5000 Vista Del Lago Rd", ...)
#
# Exit codes: 0 the chip reads Bakersfield and the local feed tab is selected,
# 11 the region could not be set. 11 is deliberate: the monitor owns 7 (system
# dialog) and 9 (wrong feed), and the preflight owns 3/4/5/6, so a region fault
# must not borrow any of them. It used to exit 7, which read as a system dialog.
# 13 a sibling script this one needs is missing.
set -u
unset PYTHONPATH PYTHONHOME

# Siblings resolve from this file's own location (scripts/crimeradar/ in the
# repo; hermes/scripts/<name> is a shim that execs it). CR_SCRIPTS overrides.
# pwd -W: the C:/ form under Git Bash. A /c/ path passed to a Windows program as
# an argument is only converted when MSYS path conversion is on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
SCRIPTS="${CR_SCRIPTS:-$HERE}"

ADB_BIN="C:/Users/tscac/Android/Sdk/platform-tools/adb.exe"
export ADB_BIN
ADB="$SCRIPTS/adb_bounded.sh"     # bounded: a wedged guest must fail, never hang
[ -f "$ADB" ] || { echo "[cr] FAILED: script missing: $ADB (CR_SCRIPTS overrides the directory)"; exit 13; }
DEV="${CR_DEVICE:-emulator-5554}"
PKG=com.newsbreak.crimeradar
ID="$PKG:id"
RID=11    # region-unset; see the exit-code note at the top

dump() {
  "$ADB" -s "$DEV" shell rm -f /sdcard/.cr_region.xml >/dev/null 2>&1
  "$ADB" -s "$DEV" shell uiautomator dump /sdcard/.cr_region.xml >/dev/null 2>&1
  "$ADB" -s "$DEV" shell cat /sdcard/.cr_region.xml 2>/dev/null | tr '<' '\n'
}

# Evidence for a region failure: the screen as the app showed it. The log line
# "the location chip is not on screen" says what was NOT there; on 2026-10-20 no
# run could say what WAS (no dump was kept), so nobody could fix it. Saves the
# layout, a screenshot and the top activity to work/crimeradar/emu/region_fail_*.
# Best effort and bounded: evidence must never be why a run fails or hangs.
EVIDENCE_DIR="${CR_EVIDENCE_DIR:-$(cd "$HERE/../.." 2>/dev/null && { pwd -W 2>/dev/null || pwd; })/work/crimeradar/emu}"
evidence() {   # $1 = a short reason, used in the file name
  local ts base
  ts="$(date +%Y-%m-%d_%H%M%S)"
  base="$EVIDENCE_DIR/region_fail_${ts}_$1"
  mkdir -p "$EVIDENCE_DIR" 2>/dev/null || return 0
  dump > "$base.xml" 2>/dev/null
  { echo "reason: $1"; echo "top: $(top_activity)"; } > "$base.txt" 2>/dev/null
  "$ADB" -s "$DEV" shell screencap -p /sdcard/.cr_region.png >/dev/null 2>&1 \
    && "$ADB_BIN" -s "$DEV" pull /sdcard/.cr_region.png "$base.png" >/dev/null 2>&1
  echo "[cr] evidence: $base.{xml,png,txt}" >&2
  return 0
}

top_activity() {
  "$ADB" -s "$DEV" shell dumpsys activity activities 2>/dev/null \
    | grep -m1 -oE 'topResumedActivity=ActivityRecord\{[^ ]+ [^ ]+ [^ ]+' | awk '{print $NF}'
}
picker_open() { case "$(top_activity)" in *MapLocationListActivity*) return 0 ;; esac; return 1; }

node_by_id() { dump | grep -F "resource-id=\"$ID/$1\"" | head -1; }
text_of()    { printf '%s\n' "$1" | grep -oE 'text="[^"]*"' | head -1 | sed 's/^text="//;s/"$//'; }
center() {   # $1 = a node line; prints "x y" of its centre
  local b n
  b="$(printf '%s\n' "$1" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1)"
  [ -n "$b" ] || return 1
  n="$(printf '%s\n' "$b" | grep -oE '[0-9]+')"
  printf '%s %s\n' \
    "$(( ($(printf '%s\n' "$n" | sed -n 1p) + $(printf '%s\n' "$n" | sed -n 3p)) / 2 ))" \
    "$(( ($(printf '%s\n' "$n" | sed -n 2p) + $(printf '%s\n' "$n" | sed -n 4p)) / 2 ))"
}
tap_node() {
  local xy
  xy="$(center "$1")" || return 1
  # shellcheck disable=SC2086
  "$ADB" -s "$DEV" shell input tap $xy >/dev/null 2>&1
}

# The chip, by resource-id. The old version took the first text above y=320,
# which grabbed the picker's own search box ("Search address or zip code") when
# the picker happened to be open, and "5000 Vista Del Lago Rd" was not even
# recognised as a place. Both faults were seen live on 2026-10-09.
chip() {
  local i line t
  for i in 1 2 3; do
    line="$(node_by_id txt_location_feed_tab)"
    t="$(text_of "$line")"
    [ -n "$t" ] && { printf '%s\n' "$t"; return 0; }
    sleep 3    # the first dump of a run can land while the feed is laying out
  done
  return 1
}

# The Home header is two tabs and `selected` sits on whichever feed is showing.
# The chip can read "Bakersfield" while "Nationwide" is selected and the cards
# are national, which is a refused poll all night. Select the local tab first.
local_tab_selected() {
  node_by_id location_feed_tab_container | grep -q 'selected="true"'
}
select_local_tab() {
  local line
  line="$(node_by_id location_feed_tab_container)"
  [ -n "$line" ] || return 1
  tap_node "$line" || return 1
  sleep 3
  local_tab_selected
}

# (center_of/tap_text removed 2026-10-09: they matched nodes by text, which is
# what made the first version tap the Nationwide tab. tap_node works from a node
# line found by resource-id.)

# A picker left open by an earlier run must not be mistaken for the feed.
if picker_open; then
  # stderr: on stdout this line became the chip that `--print` reported
  # (2026-10-14 06:54: "the region is '[cr] the location picker was already open...'").
  echo "[cr] the location picker was already open; closing it" >&2
  "$ADB" -s "$DEV" shell input keyevent 4 >/dev/null 2>&1
  sleep 3
fi

C="$(chip)"

# --print: report the chip for the health check and any other caller, so the
# detection lives in exactly one place. Exit 0 only when it reads Bakersfield and
# the local tab is selected.
if [ "${1:-}" = "--print" ]; then
  if [ -z "${C:-}" ]; then
    echo "unknown"
    exit 1
  fi
  echo "$C"
  case "$C" in
    Bakersfield*)
      # Exit 2 = the chip is right but the Nationwide scope tab is selected, so
      # the cards are national. One line of output only: callers read the chip
      # from the first line.
      local_tab_selected && exit 0
      exit 2
      ;;
  esac
  exit 1
fi

case "$C" in
  Bakersfield*)
    if local_tab_selected; then
      echo "[cr] region is '$C'"
      exit 0
    fi
    echo "[cr] region is '$C' but the Nationwide tab is selected; selecting the local feed"
    select_local_tab || { echo "[cr] FAILED: could not select the local feed tab"; exit $RID; }
    echo "[cr] region is '$C', local feed selected"
    exit 0
    ;;
esac
echo "[cr] region is '${C:-unknown}', not Bakersfield; setting it"

# The app must be forward for the tap to land on the feed.
"$ADB" -s "$DEV" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 4

if ! local_tab_selected; then
  echo "[cr] the Nationwide tab is selected; selecting the local feed first"
  select_local_tab || echo "[cr] could not select the local feed tab; carrying on"
fi

# 1. Open the picker from the chip button. Confirm it opened: tapping and hoping
#    was how the first version silently did nothing.
OPENED=0
for _ in 1 2; do
  line="$(node_by_id location_feed_tab_container)"
  [ -n "$line" ] || line="$(node_by_id txt_location_feed_tab)"
  if [ -n "$line" ]; then
    tap_node "$line"
  elif [ -z "$(dump | grep -m1 -F 'resource-id=')" ]; then
    # Not the same fault: nothing was read at all. 2026-10-16 printed "not on
    # screen" over a screen that showed the chip, and the hunt began at the UI.
    echo "[cr] the screen dump came back empty (the chip may well be there)"
  else
    echo "[cr] the location chip is not on screen"
    evidence chip_missing
  fi
  for _ in $(seq 1 4); do
    sleep 2
    picker_open && { OPENED=1; break; }
  done
  [ "$OPENED" = "1" ] && break
done
if [ "$OPENED" != "1" ]; then
  echo "[cr] FAILED: the location picker did not open (top is '$(top_activity)')"
  evidence picker_closed
  exit $RID
fi

# 2. The picker lists the city; the history row holds "Bakersfield, CA". Match
#    the exact text: "Bakersfield*" alone would also match the search box once it
#    contains the typed city.
#    The same text is also on the "Current Location" card at the top (inside
#    location_vp), and tapping that card does nothing: the picker stays open.
#    Verified live 2026-10-16 08:08: head -1 took the card, the chip read came
#    from the picker screen and found no chip, and the 07:55 emit exited 11.
#    Take a row below the card, and check the picker closed.
P="$(dump)"
vp_bottom="$(printf '%s\n' "$P" | grep -F "resource-id=\"$ID/location_vp\"" | head -1 \
  | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | grep -oE '[0-9]+' | sed -n 4p)"
row=""
while IFS= read -r cand; do
  top="$(printf '%s\n' "$cand" | grep -oE 'bounds="\[[0-9]+,[0-9]+\]' | grep -oE '[0-9]+' | sed -n 2p)"
  [ -n "$top" ] && [ "$top" -ge "${vp_bottom:-0}" ] && { row="$cand"; break; }
done <<EOF
$(printf '%s\n' "$P" | grep -F "resource-id=\"$ID/place_name_txt\"" | grep -F 'text="Bakersfield, CA"')
EOF
if [ -n "$row" ]; then
  tap_node "$row" && echo "[cr] chose 'Bakersfield, CA' from the picker"
  sleep 3
  picker_open && echo "[cr] the picker is still open after the row was tapped"
else
  # 3. No such row: type the city into the picker's own search box.
  echo "[cr] no 'Bakersfield, CA' row; typing the city into the search box"
  box="$(dump | grep -F "resource-id=\"$ID/search_tv\"" | head -1)"
  if [ -n "$box" ]; then
    tap_node "$box"
    sleep 2
    "$ADB" -s "$DEV" shell input text 'Bakersfield,%sCA' >/dev/null 2>&1
    sleep 3
    "$ADB" -s "$DEV" shell input keyevent 66 >/dev/null 2>&1
    sleep 6
    # First result row that names the city. The search box itself is excluded: it
    # is an EditText and now holds the typed text.
    sug="$(dump | grep -F "resource-id=\"$ID/place_name_txt\"" | grep -E 'text="Bakersfield' | head -1)"
    [ -n "$sug" ] && tap_node "$sug" && echo "[cr] chose a Bakersfield result from the search"
  else
    echo "[cr] the picker's search box was not found"
  fi
fi

# The feed reloads after a location change; give it time before judging it.
sleep 10
C="$(chip)"
case "$C" in
  Bakersfield*)
    if local_tab_selected; then
      echo "[cr] region is now '$C'"
      exit 0
    fi
    echo "[cr] region is now '$C' but the Nationwide tab is selected; selecting the local feed"
    select_local_tab || { echo "[cr] FAILED: could not select the local feed tab"; exit $RID; }
    echo "[cr] region is now '$C', local feed selected"
    exit 0
    ;;
esac
echo "[cr] FAILED: the chip still reads '${C:-unknown}', not Bakersfield"
evidence still_unset
exit $RID
