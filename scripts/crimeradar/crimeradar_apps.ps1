# Process driver for crimeradar_apps.sh: find, stop or start one named desktop app.
#
# An app is found by where its executable lives, never by image name alone:
# Claude Desktop and Claude Code are both claude.exe, and the Claude Code runner
# is the orchestrator that may have started this very run.
#   discord        %LOCALAPPDATA%\Discord\app-*\Discord.exe
#   claude-desktop <WindowsApps>\Claude_*\app\claude.exe (the Store package)
# What is stopped is that root and what it spawned (the Desktop app hosts its own
# session workers under %APPDATA%\Claude). Two refusals, both exit 3:
#   * this run is itself inside the app's tree, so stopping it would kill the caller;
#   * nothing under the hermes directory is ever stopped, whatever its parent.
#
# Usage: crimeradar_apps.ps1 <running|stop|start> <discord|claude-desktop>
# Prints one line. Exit codes:
#   running  0 running, 1 not running
#   stop     0 stopped, 1 was not running, 2 still running after the stop, 3 refused
#   start    0 seen running, 2 launched but not seen within the wait, 4 nothing to start it with
#
# start answers 0 only for a process it saw, on two looks in a row, and its line
# says when: "verified 23:05:41, 12 s after the launch: ...". A launch is not a
# running app. Discord is started through its updater, which can hold the client
# back for longer than a fixed sleep (2026-10-11: a count taken straight after
# the launch read "not reopened" for an app that was on its way up). The wait is
# CR_APPS_START_WAIT seconds, default 90.
#
# `selftest` is not an app. tests/test_crimeradar_apps.py runs this file's real
# stop and start against a throwaway executable: CR_APPS_SELFTEST_EXE is its full
# path and CR_APPS_SELFTEST_START the script that launches it. crimeradar_apps.sh
# never asks for it.
param(
  [Parameter(Mandatory = $true)][ValidateSet('running', 'stop', 'start')][string]$Verb,
  [Parameter(Mandatory = $true)][ValidateSet('discord', 'claude-desktop', 'selftest')][string]$App
)
$ErrorActionPreference = 'Stop'

$Roots = @{
  'discord'        = @{ Name = 'Discord.exe'; Like = (Join-Path $env:LOCALAPPDATA 'Discord\app-*\Discord.exe') }
  'claude-desktop' = @{ Name = 'claude.exe';  Like = '*\WindowsApps\Claude_*\app\claude.exe' }
}
if ($App -eq 'selftest') {
  if (-not $env:CR_APPS_SELFTEST_EXE) { Write-Output 'selftest needs CR_APPS_SELFTEST_EXE'; exit 4 }
  $Roots['selftest'] = @{ Name = (Split-Path $env:CR_APPS_SELFTEST_EXE -Leaf); Like = $env:CR_APPS_SELFTEST_EXE }
}
$Hermes = (Join-Path $env:LOCALAPPDATA 'hermes') + '\*'

function Get-Tree {
  $all = @(Get-CimInstance Win32_Process)
  $spec = $Roots[$App]
  $tree = @($all | Where-Object { $_.Name -eq $spec.Name -and $_.ExecutablePath -like $spec.Like })
  $ids = @{}
  foreach ($p in $tree) { $ids[[int]$p.ProcessId] = $p }
  do {
    $grew = $false
    foreach ($p in $all) {
      $parent = $ids[[int]$p.ParentProcessId]
      # A pid is reused after its process exits: a child is never older than its parent.
      if ($parent -and -not $ids.ContainsKey([int]$p.ProcessId) -and $p.CreationDate -ge $parent.CreationDate) {
        $ids[[int]$p.ProcessId] = $p
        $grew = $true
      }
    }
  } while ($grew)
  [pscustomobject]@{ All = $all; Tree = @($ids.Values) }
}

function Get-Size($tree) {
  $mb = [int](($tree | Measure-Object PrivatePageCount -Sum).Sum / 1MB)
  '{0} process(es), {1} MB private' -f @($tree).Count, $mb
}

$found = Get-Tree

if ($Verb -eq 'running') {
  if ($found.Tree.Count -eq 0) { Write-Output 'not running'; exit 1 }
  Write-Output (Get-Size $found.Tree); exit 0
}

if ($Verb -eq 'stop') {
  if ($found.Tree.Count -eq 0) { Write-Output 'not running'; exit 1 }
  $inTree = @{}
  foreach ($p in $found.Tree) { $inTree[[int]$p.ProcessId] = $true }
  $byId = @{}
  foreach ($p in $found.All) { $byId[[int]$p.ProcessId] = $p }
  $id = $PID
  for ($i = 0; $i -lt 64 -and $byId.ContainsKey($id); $i++) {
    if ($inTree.ContainsKey($id)) { Write-Output "refused: this run is inside the $App process tree (pid $id)"; exit 3 }
    $id = [int]$byId[$id].ParentProcessId
  }
  $kept = @($found.Tree | Where-Object { $_.ExecutablePath -like $Hermes })
  if ($kept.Count -gt 0) { Write-Output "refused: a hermes process (pid $($kept[0].ProcessId)) runs under $App"; exit 3 }
  $size = Get-Size $found.Tree
  foreach ($p in $found.Tree) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
  # Stop-Process returns before the process is gone; a positive check with a deadline.
  for ($i = 0; $i -lt 20; $i++) {
    $left = (Get-Tree).Tree
    if ($left.Count -eq 0) { Write-Output $size; exit 0 }
    Start-Sleep -Milliseconds 500
  }
  Write-Output "$size; $($left.Count) still running"; exit 2
}

# start. Start-Process goes through the shell, so the app inherits none of this
# run's handles: a cron job's captured output never waits on the app it opened.
if ($found.Tree.Count -gt 0) {
  Write-Output ('already running at {0:HH:mm:ss}: {1}' -f (Get-Date), (Get-Size $found.Tree)); exit 0
}
$wait = 90
if ($env:CR_APPS_START_WAIT -match '^\d+$') { $wait = [int]$env:CR_APPS_START_WAIT }
$launched = Get-Date
if ($App -eq 'selftest') {
  if (-not $env:CR_APPS_SELFTEST_START) { Write-Output 'selftest needs CR_APPS_SELFTEST_START'; exit 4 }
  Start-Process -FilePath $env:CR_APPS_SELFTEST_START -WindowStyle Hidden
} elseif ($App -eq 'discord') {
  $upd = Join-Path $env:LOCALAPPDATA 'Discord\Update.exe'
  if (-not (Test-Path $upd)) { Write-Output "no launcher at $upd"; exit 4 }
  # Discord's own start-up line, with its own "start minimised" switch.
  Start-Process -FilePath $upd -ArgumentList '--processStart', 'Discord.exe', '--process-start-args', '--start-minimized'
} else {
  $pkg = Get-AppxPackage -Name 'Claude' | Select-Object -First 1
  if (-not $pkg) { Write-Output 'the Claude package is not installed for this user'; exit 4 }
  Start-Process -FilePath ('shell:AppsFolder\' + $pkg.PackageFamilyName + '!Claude')
}
# Poll until the process is there on two looks in a row (a launcher's first child
# can exit as it hands over), or the wait runs out.
$seen = $false
while (((Get-Date) - $launched).TotalSeconds -lt $wait) {
  Start-Sleep -Milliseconds 1000
  $now = (Get-Tree).Tree
  if ($now.Count -eq 0) { $seen = $false; continue }
  if ($seen) {
    $at = Get-Date
    Write-Output ('verified {0:HH:mm:ss}, {1} s after the launch: {2}' -f $at, [int]($at - $launched).TotalSeconds, (Get-Size $now))
    exit 0
  }
  $seen = $true
}
$why = ''
if ($App -eq 'discord') {
  $updPath = Join-Path $env:LOCALAPPDATA 'Discord\Update.exe'
  $busy = @(Get-CimInstance Win32_Process -Filter "Name = 'Update.exe'" | Where-Object { $_.ExecutablePath -eq $updPath })
  if ($busy.Count -gt 0) { $why = "; Discord's updater is still running, so the client may yet appear" }
}
Write-Output ('launched {0:HH:mm:ss}, no process seen by {1:HH:mm:ss} ({2} s){3}' -f $launched, (Get-Date), $wait, $why)
exit 2
