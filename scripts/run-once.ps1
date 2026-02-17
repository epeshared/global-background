param(
  [string]$ConfigPath = "config.toml",
  [switch]$DryRun,
  [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$configAbs = Resolve-Path (Join-Path $repoRoot $ConfigPath)

function Test-PythonRunnable([string]$Candidate) {
  try {
    $exe = & $Candidate -c "import sys; print(sys.executable)" 2>$null
    if (-not $exe) { return $null }
    if ($exe -like "*WindowsApps*\\python.exe") { return $null }
    return $exe
  } catch {
    return $null
  }
}

function Test-PythonHasPillow([string]$ExePath) {
  try {
    & $ExePath -c "import PIL; import sys; print(sys.executable)" 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Resolve-PythonExe([string]$Preferred) {
  $resolved = @()
  if ($Preferred -and (Test-Path $Preferred)) {
    $exe0 = Test-PythonRunnable (Resolve-Path $Preferred).Path
    if ($exe0) { $resolved += $exe0 }
  }

  $py = (Get-Command py -ErrorAction SilentlyContinue)
  if ($py) {
    foreach ($ver in @("-3.12", "-3.11", "-3")) {
      try {
        $exe = & py $ver -c "import sys; print(sys.executable)" 2>$null
        if ($exe -and -not ($exe -like "*WindowsApps*\\python.exe")) {
          $resolved += $exe.Trim()
        }
      } catch {
        # ignore
      }
    }
  }

  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if ($python) {
    $exe1 = Test-PythonRunnable $python.Source
    if ($exe1) { $resolved += $exe1 }
  }

  # Common python.org installs
  $local312 = Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"
  if (Test-Path $local312) {
    $exe2 = Test-PythonRunnable $local312
    if ($exe2) { $resolved += $exe2 }
  }
  $local311 = Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"
  if (Test-Path $local311) {
    $exe3 = Test-PythonRunnable $local311
    if ($exe3) { $resolved += $exe3 }
  }

  $resolved = $resolved | Select-Object -Unique
  if (-not $resolved -or $resolved.Count -eq 0) {
    throw "python not found in PATH. Install Python 3.11+ or pass -PythonExe with the real python path."
  }

  foreach ($e in $resolved) {
    if (Test-PythonHasPillow $e) { return $e }
  }
  return $resolved[0]
}

$exe = Resolve-PythonExe $PythonExe

Push-Location $repoRoot
try {
  $env:PYTHONPATH = (Join-Path $repoRoot "src")
  $pyParams = @("-m", "global_background", "once", "--config", $configAbs)
  if ($DryRun) { $pyParams += "--dry-run" }
  & $exe @pyParams
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}
