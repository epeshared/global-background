param(
  [string]$ConfigPath,
  [string]$PythonExe,
  [switch]$DryRun,
  [int]$MaxRunSeconds = 900
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

  # Run via Start-Process so we can enforce a hard timeout.
  # Note: cmd.exe expects the whole command string after /c; it must be quoted
  # so redirections like 1> file 2>&1 are parsed correctly.
  $cmdQuoted = '"' + $cmd + '"'
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/s", "/c", $cmdQuoted) -WindowStyle Hidden -PassThru
  $finished = $p.WaitForExit([Math]::Max(1, $MaxRunSeconds) * 1000)
  if (-not $finished) {
    # Kill the whole tree (cmd.exe + python/pythonw) to avoid a stuck task blocking future runs.
    try {
      taskkill /T /F /PID $p.Id | Out-Null
    } catch {
      try { Stop-Process -Id $p.Id -Force } catch {}
    }
    "[global-background] ERROR: task-run timed out after ${MaxRunSeconds}s; killed process tree." | Out-File -FilePath $logPath -Append -Encoding UTF8
    Copy-Item -Force $logPath $latestPath
    Write-Error "global_background timed out after ${MaxRunSeconds}s. See: $latestPath"
    exit 124
  }

  $exitCode = $p.ExitCode

  if (-not (Test-Path $logPath)) {
    "[global-background] ERROR: task-run did not produce a log file. cmd exit code=$exitCode" | Out-File -FilePath $logPath -Encoding UTF8
  }
  Copy-Item -Force $logPath $latestPath

  if ($exitCode -ne 0) {
    Write-Error "global_background failed with exit code $exitCode. See: $latestPath"
    exit $exitCode
  }
} finally {
  Pop-Location
}
