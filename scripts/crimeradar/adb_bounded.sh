#!/usr/bin/env bash
# Every adb call in the CrimeRadar bash scripts goes through here.
#
# Why: `adb devices` keeps listing a wedged guest as `device`, while every
# `adb shell` call blocks forever. Verified 2026-10-10: the guest wedged just
# after midnight, and five scheduled jobs (the 00:15 burst, the 06:50 and 07:10
# emits, the 07:15 emit, the 07:50 morning pass) were each stuck on one
# `settings put global hide_error_dialogs 1` call for 2.5 h. The night's second
# source never staged, so the publish held the whole day. No adb call may block
# without a bound.
#
# The bound is a per-call timeout, not a retry: a caller that gets exit 124
# knows the guest did not answer, which is exactly what the preflight's wedged
# gate and the scripts' exit codes are built on.
#
# Usage: identical to adb. Set ADB_BIN to override the binary, ADB_TIMEOUT for a
# different bound (the preflight raises it for uiautomator dumps).
set -u
# Device paths go to adb.exe exactly as written. adb.exe is a native Windows
# program, so MSYS rewrites any argument that looks like a POSIX path before it
# gets there: `shell cat /sdcard/.cr_region.xml` arrived as
# `C:/Users/tscac/AppData/Local/hermes/tools/git-.../sdcard/.cr_region.xml`. The
# dump then landed nowhere, every read came back empty, and the region setter
# reported "the location chip is not on screen" over a Home screen that showed
# it. Verified 2026-10-16: the 06:50, 07:10 and 07:11 emits all exited 11 that
# way. Whether conversion is on was decided by the caller's environment, not by
# these scripts: Claude Code and Hermes's terminal export MSYS_NO_PATHCONV=1, so
# every manual run worked, while the BB Morning Runner (a scheduled task)
# exports nothing. Set here, where every adb call in the leg passes, so no
# caller can turn it back on. Git for Windows reads the first, MSYS2 the second.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
adb_bin="${ADB_BIN:-C:/Users/tscac/Android/Sdk/platform-tools/adb.exe}"
adb_bound="${ADB_TIMEOUT:-30}"
exec timeout "$adb_bound" "$adb_bin" "$@"
