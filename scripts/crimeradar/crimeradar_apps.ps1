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
#   start    0 running now, 2 did not come up, 4 nothing to start it with
param(
  [Parameter(Mandatory = $true)][ValidateSet('running', 'stop', 'start')][string]$Verb,
  [Parameter(Mandatory = $true)][ValidateSet('discord', 'claude-desktop')][string]$App
)
$ErrorActionPreference = 'Stop'

$Roots = @{
  'discord'        = @{ Name = 'Discord.exe'; Like = (Join-Path $env:LOCALAPPDATA 'Discord\app-*\Discord.exe') }
  'claude-desktop' = @{ Name = 'claude.exe';  Like = '*\WindowsApps\Claude_*\app\claude.exe' }
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
if ($found.Tree.Count -gt 0) { Write-Output ('already running: ' + (Get-Size $found.Tree)); exit 0 }
if ($App -eq 'discord') {
  $upd = Join-Path $env:LOCALAPPDATA 'Discord\Update.exe'
  if (-not (Test-Path $upd)) { Write-Output "no launcher at $upd"; exit 4 }
  # Discord's own start-up line, with its own "start minimised" switch.
  Start-Process -FilePath $upd -ArgumentList '--processStart', 'Discord.exe', '--process-start-args', '--start-minimized'
} else {
  $pkg = Get-AppxPackage -Name 'Claude' | Select-Object -First 1
  if (-not $pkg) { Write-Output 'the Claude package is not installed for this user'; exit 4 }
  Start-Process -FilePath ('shell:AppsFolder\' + $pkg.PackageFamilyName + '!Claude')
}
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 500
  $now = (Get-Tree).Tree
  if ($now.Count -gt 0) { Write-Output (Get-Size $now); exit 0 }
}
Write-Output 'started, but no process appeared within 30 s'; exit 2
