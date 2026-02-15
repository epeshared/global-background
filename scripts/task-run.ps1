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

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Push-Location $repoRoot
try {
  $env:PYTHONPATH = (Join-Path $repoRoot "src")
  $args = @("-m", "global_background", "once", "--config", (Resolve-Path $ConfigPath).Path)
  if ($DryRun) { $args += "--dry-run" }

  & $PythonExe @args
} finally {
  Pop-Location
}
