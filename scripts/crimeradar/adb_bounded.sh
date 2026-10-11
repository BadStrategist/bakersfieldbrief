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
adb_bin="${ADB_BIN:-C:/Users/tscac/Android/Sdk/platform-tools/adb.exe}"
adb_bound="${ADB_TIMEOUT:-30}"
exec timeout "$adb_bound" "$adb_bin" "$@"
