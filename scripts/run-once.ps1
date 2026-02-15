param(
  [string]$ConfigPath = "config.toml",
  [switch]$DryRun,
  [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$configAbs = Resolve-Path (Join-Path $repoRoot $ConfigPath)

$pythonSource = $null
if ($PythonExe -and (Test-Path $PythonExe)) {
  $pythonSource = (Resolve-Path $PythonExe).Path
} else {
  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $python) {
    throw "python not found in PATH. Install Python 3.11+ or pass -PythonExe with the real python path."
  }
  $pythonSource = $python.Source
}

# Validate python is runnable (avoid WindowsApps alias stub)
$exe = & $pythonSource -c "import sys; print(sys.executable)" 2>$null
if (-not $exe) {
  throw "Python seems not runnable. Disable App Execution Aliases for python.exe/python3.exe, or pass -PythonExe."
}
if ($exe -like "*WindowsApps*\\python.exe") {
  throw "Detected Microsoft Store python alias ($exe). Install python.org Python and disable App Execution Aliases, or pass -PythonExe."
}

Push-Location $repoRoot
try {
  $env:PYTHONPATH = (Join-Path $repoRoot "src")
  $args = @("-m", "global_background", "once", "--config", $configAbs)
  if ($DryRun) { $args += "--dry-run" }
  & $exe @args
} finally {
  Pop-Location
}
