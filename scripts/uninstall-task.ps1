param(
  [string]$TaskName = "GlobalBackground"
)

$ErrorActionPreference = "Stop"

schtasks /Delete /F /TN $TaskName | Out-Null
Write-Host "Removed scheduled task '$TaskName'."
