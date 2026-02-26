param(
  [string]$ConfigPath    = "config.toml",
  [string]$TaskName      = "GlobalBackgroundLoop",
  [string]$PythonExe     = "",
  [string]$ProxyServer   = "http://child-prc.intel.com:913",
  [switch]$RunNow
)

<#
.SYNOPSIS
  One-click installer for the GlobalBackground 24-hour animated wallpaper loop.

.DESCRIPTION
  1. Auto-detects screen resolution and patches config.toml.
  2. Finds an appropriate Python (3.11+) and installs Pillow if missing.
  3. Registers a Windows Scheduled Task that starts the 'loop' command at
     every user logon.  The loop:
       • Backfills up to 24 hourly satellite images on startup.
       • Downloads a new frame at every UTC top-of-hour.
       • Continuously cycles through the 24 frames as a wallpaper slideshow.
  4. Optionally starts the task immediately.

.NOTES
  To stop:       .\stop-loop-task.ps1
  To uninstall:  .\uninstall-loop-task.ps1
  Logs:          <repo>\logs\loop.log
  Ring buffer:   <repo>\out\hourly\h00.jpg … h23.jpg
#>

$ErrorActionPreference = "Stop"

$repoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$configAbs  = Join-Path $repoRoot $ConfigPath
if (-not (Test-Path $configAbs)) {
  throw "Config file not found: $configAbs"
}

# ---------------------------------------------------------------------------
# Helper: test whether a Python executable is usable
# ---------------------------------------------------------------------------
function Test-PythonRunnable([string]$Candidate) {
  try {
    $raw = & $Candidate -c "import sys; print(sys.executable)" 2>$null
    $exe = ($raw -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' } | Select-Object -Last 1)
    if (-not $exe) { return $null }
    if (-not (Test-Path $exe -PathType Leaf -ErrorAction SilentlyContinue)) { return $null }
    if ($exe -like "*\\.venv\\*") { return $null }
    if ($exe -like "*WindowsApps*\\python.exe") { return $null }
    return $exe
  } catch {
    return $null
  }
}

function Test-PythonHasPillow([string]$ExePath) {
  try {
    $null = & $ExePath -c "import PIL" 2>&1
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Get-WinHttpProxy {
  try {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $enabled = (Get-ItemProperty $key -ErrorAction SilentlyContinue).ProxyEnable
    if ($enabled -eq 1) {
      $server = (Get-ItemProperty $key -ErrorAction SilentlyContinue).ProxyServer
      if ($server) {
        if ($server -notmatch '://') { $server = "http://$server" }
        return $server
      }
    }
  } catch {}
  try {
    $wpout = netsh winhttp show proxy 2>$null
    $match = $wpout | Select-String 'Proxy Server\(s\)\s*:\s*(.+)'
    if ($match -and $match.Matches[0].Groups[1].Value.Trim() -ne 'Direct access') {
      $srv = $match.Matches[0].Groups[1].Value.Trim()
      if ($srv -notmatch '://') { $srv = "http://$srv" }
      return $srv
    }
  } catch {}
  return $null
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
        $raw = & py $ver -c "import sys; print(sys.executable)" 2>$null
        $exe = ($raw -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' } | Select-Object -Last 1)
        if ($exe -and (Test-Path $exe -PathType Leaf -ErrorAction SilentlyContinue) `
            -and -not ($exe -like "*\\.venv\\*") `
            -and -not ($exe -like "*WindowsApps*\\python.exe")) {
          $resolved += $exe
        }
      } catch {}
    }
  }
  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if ($python) {
    $exe1 = Test-PythonRunnable $python.Source
    if ($exe1) { $resolved += $exe1 }
  }
  foreach ($p in @(
    (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe")
  )) {
    if (Test-Path $p) {
      $e = Test-PythonRunnable $p
      if ($e) { $resolved += $e }
    }
  }

  $resolved = @($resolved | Select-Object -Unique)
  if (-not $resolved -or $resolved.Count -eq 0) {
    throw "python not found in PATH. Install Python 3.11+ and ensure it's on PATH."
  }

  foreach ($e in $resolved) {
    if (Test-PythonHasPillow $e) { return $e }
  }

  $target = $resolved[0]
  Write-Host "Pillow not found. Installing Pillow into: $target ..."
  $proxy = Get-WinHttpProxy
  if (-not $proxy -and $ProxyServer) { $proxy = $ProxyServer }
  $proxyArgs = @()
  if ($proxy) {
    Write-Host "Using proxy: $proxy"
    $proxyArgs = @("--proxy", $proxy)
  }
  foreach ($installArgs in @(
    (@("-m", "pip", "install", "--quiet", "--user") + $proxyArgs + @("Pillow")),
    (@("-m", "pip", "install", "--quiet") + $proxyArgs + @("Pillow"))
  )) {
    & $target @installArgs 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-PythonHasPillow $target)) {
      Write-Host "Pillow installed successfully."
      return $target
    }
  }
  Write-Host "Warning: Could not auto-install Pillow. Images may not be resized properly."
  return $target
}

# ---------------------------------------------------------------------------
# Step 1: Detect screen resolution → patch config.toml
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== GlobalBackground Loop Installer ==="
Write-Host ""
Write-Host "Step 1: Detecting screen resolution..."
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  $sw = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width
  $sh = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height
  try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class GBDpiHelper {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
"@ -ErrorAction Stop
    [GBDpiHelper]::SetProcessDPIAware() | Out-Null
    $dw = [GBDpiHelper]::GetSystemMetrics(0)
    $dh = [GBDpiHelper]::GetSystemMetrics(1)
    if ($dw -gt 0 -and $dh -gt 0) { $sw = $dw; $sh = $dh }
  } catch {}

  if ($sw -gt 0 -and $sh -gt 0) {
    Write-Host "  Screen: ${sw}x${sh}"
    $lines = Get-Content $configAbs -Encoding UTF8
    $inImage = $false; $patched = $false; $newLines = @()
    foreach ($line in $lines) {
      if ($line -match '^\s*\[image\]')  { $inImage = $true }
      elseif ($line -match '^\s*\[')     { $inImage = $false }
      if ($inImage -and $line -match '^\s*width\s*=')  { $newLines += "width = $sw";  $patched = $true }
      elseif ($inImage -and $line -match '^\s*height\s*=') { $newLines += "height = $sh"; $patched = $true }
      else   { $newLines += $line }
    }
    if ($patched) {
      $newLines | Set-Content $configAbs -Encoding UTF8
      Write-Host "  Updated $ConfigPath → ${sw}x${sh}."
    }
  }
} catch {
  Write-Host "  Warning: Could not detect resolution. Using existing config values."
}

# ---------------------------------------------------------------------------
# Step 2: Locate Python + install Pillow
# Prefer .venv\Scripts\python.exe in the repo (has all deps already)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Step 2: Locating Python..."

$venvExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if ($PythonExe -eq "" -and (Test-Path $venvExe)) {
  # Venv exists — use it directly; skip Pillow install (already there)
  $exe = $venvExe
  Write-Host "  Using .venv Python: $exe"
} else {
  $exe = Resolve-PythonExe $PythonExe
  Write-Host "  Python: $exe"
}

# Use python.exe (not pythonw.exe) so output truly reaches the log file.
$pythonForTask = $exe

# ---------------------------------------------------------------------------
# Step 3: Register at-logon Scheduled Task
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Step 3: Registering Scheduled Task '$TaskName'..."

try {
  Import-Module ScheduledTasks -ErrorAction Stop
} catch {
  throw "ScheduledTasks module not available. Please run on Windows 10/11."
}

# Stop any currently running instance before re-registering.
try {
  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($existing -and $existing.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "  Stopped existing running instance."
    Start-Sleep -Seconds 2
  }
} catch {}

$taskRun     = (Resolve-Path (Join-Path $PSScriptRoot "loop-task-run.ps1")).Path
$configResolved = (Resolve-Path $configAbs).Path

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$taskRun`" -ConfigPath `"$configResolved`" -PythonExe `"$pythonForTask`""
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $arg `
  -WorkingDirectory $repoRoot

# Trigger: at every logon of the current user (no admin required)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Limited

# IgnoreNew: if the task is already running, don't start a second instance.
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -RestartInterval (New-TimeSpan -Minutes 5) `
  -RestartCount 3 `
  -ExecutionTimeLimit (New-TimeSpan -Days 0)  # 0 = no time limit

Register-ScheduledTask `
  -TaskName  $TaskName `
  -Action    $action `
  -Trigger   $trigger `
  -Principal $principal `
  -Settings  $settings `
  -Force | Out-Null

Write-Host "  Task '$TaskName' registered (trigger: at user logon)."

# ---------------------------------------------------------------------------
# Step 4: Optionally start right now
# ---------------------------------------------------------------------------
if ($RunNow) {
  Write-Host ""
  Write-Host "Step 4: Starting task now..."
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "  Task started. Backfilling 24 hourly images (may take a few minutes)..."
}

Write-Host ""
Write-Host "=== Installation complete ==="
Write-Host ""
Write-Host "  Task name  : $TaskName"
Write-Host "  Trigger    : At user logon"
Write-Host "  Config     : $ConfigPath"
Write-Host "  Log file   : logs\loop.log"
Write-Host "  Ring buffer: out\hourly\h00.jpg … h23.jpg"
Write-Host ""
Write-Host "  To stop    : .\windows\scripts\stop-loop-task.ps1"
Write-Host "  To remove  : .\windows\scripts\uninstall-loop-task.ps1"
Write-Host ""
