param(
  [string]$ConfigPath = "config.toml",
  [string]$TaskName = "GlobalBackground",
  [int]$IntervalMinutes = 30,
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
    throw "python not found in PATH. Install Python 3.11+ and ensure it's on PATH."
  }
  $pythonSource = $python.Source
}

# Validate python is runnable and not the Microsoft Store alias stub.
$exe = & $pythonSource -c "import sys; print(sys.executable)" 2>$null
if (-not $exe) {
  throw "Python seems not runnable. If you see Microsoft Store popup, disable 'App execution aliases' for python.exe, or pass -PythonExe with the real python path."
}
if ($exe -like "*WindowsApps*\\python.exe") {
  throw "Detected Microsoft Store python alias ($exe). Install Python from python.org and disable App Execution Aliases, or pass -PythonExe with the real python.exe path."
}

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
