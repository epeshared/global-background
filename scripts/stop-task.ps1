param(
  [string]$TaskName = "GlobalBackground",
  [switch]$Disable
)

$ErrorActionPreference = "Stop"

# Stop current running instance (if any)
try {
  schtasks /End /TN $TaskName | Out-Null
  Write-Host "Stopped running task '$TaskName' (if it was running)."
} catch {
  Write-Host "Unable to stop task '$TaskName' (it may not be running)."
}

if ($Disable) {
  try {
    schtasks /Change /TN $TaskName /Disable | Out-Null
    Write-Host "Disabled task '$TaskName'."
  } catch {
    throw "Failed to disable task '$TaskName'."
  }
}

Write-Host "Done. (Note: uninstall/delete uses scripts\\uninstall-task.ps1)"
