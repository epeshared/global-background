param(
  [string]$ConfigPath,
  [string]$PythonExe
)

$ErrorActionPreference = "Stop"

if (-not $ConfigPath) {
  throw "ConfigPath is required."
}
if (-not (Test-Path $ConfigPath)) {
  throw "Config file not found: $ConfigPath"
}
if (-not $PythonExe) {
  throw "PythonExe is required."
}
if (-not (Test-Path $PythonExe)) {
  throw "Python executable not found: $PythonExe"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Push-Location $repoRoot
try {
  $env:PYTHONPATH = (Join-Path $repoRoot "src")

  $logsDir = Join-Path $repoRoot "logs"
  if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
  }
  $logPath = Join-Path $logsDir "loop.log"

  $configResolved = (Resolve-Path $ConfigPath).Path

  # The loop command runs indefinitely: it backfills 24 hourly images on startup,
  # then downloads a new frame at every UTC top-of-hour and cycles through them as
  # a wallpaper slideshow.  Output appended to loop.log.
  #
  # Use cmd.exe for redirection (same pattern as the working task-run.ps1).
  # -u = unbuffered output so lines appear in the log immediately.
  # Start-Process -Wait keeps this script alive so Task Scheduler shows "Running".
  $cmd = '"' + $PythonExe + '" -u -m global_background loop --config "' + $configResolved + '" >> "' + $logPath + '" 2>&1'
  $cmdQuoted = '"' + $cmd + '"'

  $p = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/d", "/s", "/c", $cmdQuoted) `
    -WorkingDirectory $repoRoot `
    -NoNewWindow `
    -PassThru

  $p.WaitForExit()
  exit $p.ExitCode
} finally {
  Pop-Location
}
