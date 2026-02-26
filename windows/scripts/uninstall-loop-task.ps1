param(
  [string]$TaskName = "GlobalBackgroundLoop"
)

$ErrorActionPreference = "Stop"

# Stop any running instance first
try {
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {}

# Unregister the task
try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
  Write-Host "Removed scheduled task '$TaskName'."
} catch {
  Write-Host "Task '$TaskName' not found (already removed or never installed)."
}

Write-Host "Done. The animated wallpaper loop will not start at next logon."
Write-Host "Cached images (out\hourly\) and logs (logs\loop.log) were not deleted."
