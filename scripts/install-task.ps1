param(
  [string]$ConfigPath = "config.toml",
  [string]$TaskName = "GlobalBackground",
  [int]$IntervalMinutes = 30,
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
    & $ExePath -c "import PIL" 1>$null 2>$null
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
    throw "python not found in PATH. Install Python 3.11+ and ensure it's on PATH."
  }

  foreach ($e in $resolved) {
    if (Test-PythonHasPillow $e) { return $e }
  }
  return $resolved[0]
}
$exe = Resolve-PythonExe $PythonExe

$pythonw = Join-Path (Split-Path $exe) "pythonw.exe"
if (-not (Test-Path $pythonw)) {
  $pythonw = $exe
}

# Use a small PowerShell entrypoint script to avoid fragile quoting.
$taskRun = (Resolve-Path (Join-Path $PSScriptRoot "task-run.ps1")).Path

# Create or update scheduled task using ScheduledTasks module (more reliable than schtasks quoting)
try {
  Import-Module ScheduledTasks -ErrorAction Stop
} catch {
  throw "ScheduledTasks module not available. Please run on Windows 10/11 with built-in Scheduled Tasks support."
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$taskRun`" -ConfigPath `"$configAbs`" -PythonExe `"$pythonw`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $repoRoot

# Repeating trigger: run once starting soon, repeat every N minutes.
# Note: Windows Task Scheduler caps repetition duration; we set a long duration and you can re-run this installer later to extend.
$startAt = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (every $IntervalMinutes minutes)."
Write-Host "Run now: schtasks /Run /TN $TaskName"
