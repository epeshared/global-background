param(
  [string]$TaskName = "GlobalBackgroundLoop",
  [switch]$Disable
)

$ErrorActionPreference = "Stop"

# Stop the currently running instance (if any)
try {
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  Write-Host "Stopped task '$TaskName'."
} catch {
  Write-Host "Task '$TaskName' was not running (or could not be stopped)."
}

if ($Disable) {
  try {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Host "Disabled task '$TaskName'. It will not start at next logon."
  } catch {
    throw "Failed to disable task '$TaskName': $_"
  }
}

Write-Host "Done. To remove the task entirely: .\uninstall-loop-task.ps1"
