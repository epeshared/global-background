param(
  [string]$ConfigPath = "config.toml",
  [string]$TaskName = "GlobalBackground",
  [string]$PythonExe = "",
  [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$installScript = Join-Path $PSScriptRoot "install-task.ps1"
if (-not (Test-Path $installScript)) {
  throw "Missing script: $installScript"
}

# Install as scheduled task (every 60 minutes)
if ($PythonExe) {
  & $installScript -ConfigPath $ConfigPath -TaskName $TaskName -IntervalMinutes 60 -PythonExe $PythonExe
} else {
  & $installScript -ConfigPath $ConfigPath -TaskName $TaskName -IntervalMinutes 60
}

if ($RunNow) {
  schtasks /Run /TN $TaskName | Out-Null
  Write-Host "Triggered scheduled task '$TaskName' to run now."
}

Write-Host "Done. This will update wallpaper every hour via Scheduled Task '$TaskName'."
