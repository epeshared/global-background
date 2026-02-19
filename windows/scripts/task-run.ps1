param(
  [string]$ConfigPath,
  [string]$PythonExe,
  [switch]$DryRun
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
  $pyParams = @("-m", "global_background", "once", "--config", (Resolve-Path $ConfigPath).Path)
  if ($DryRun) { $pyParams += "--dry-run" }

  $logsDir = Join-Path $repoRoot "logs"
  if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
  }
  $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
  $logPath = Join-Path $logsDir "task-run_$stamp.log"
  $latestPath = Join-Path $logsDir "task-run.latest.log"

  # Capture stdout/stderr for post-mortem debugging.
  # Note: Windows PowerShell may treat native stderr as an error record (NativeCommandError)
  # even when redirecting. Invoking via cmd.exe avoids that behavior.
  $configResolved = (Resolve-Path $ConfigPath).Path
  $dry = if ($DryRun) { " --dry-run" } else { "" }
  $cmd = '"' + $PythonExe + '" -m global_background once --config "' + $configResolved + '"' + $dry + ' 1> "' + $logPath + '" 2>&1'
  cmd.exe /d /s /c $cmd | Out-Null
  $exitCode = $LASTEXITCODE
  Copy-Item -Force $logPath $latestPath

  if ($exitCode -ne 0) {
    Write-Error "global_background failed with exit code $exitCode. See: $latestPath"
    exit $exitCode
  }
} finally {
  Pop-Location
}
