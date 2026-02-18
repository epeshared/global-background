param(
  [string]$ConfigPath = "config.toml",
  [string]$TaskName = "GlobalBackground",
  [string]$PythonExe = "",
  [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$configAbs = Join-Path $repoRoot $ConfigPath
if (-not (Test-Path $configAbs)) {
  throw "Config file not found: $configAbs"
}

$installScript = Join-Path $PSScriptRoot "install-task.ps1"
if (-not (Test-Path $installScript)) {
  throw "Missing script: $installScript"
}

# ---- Auto-detect screen resolution and patch config.toml ----
Write-Host "Detecting screen resolution..."
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $sw = [int]$screen.Width
  $sh = [int]$screen.Height

  # Try DPI-aware detection for real pixel count (handles 125%/150% scaling)
  try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DpiHelper {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
"@ -ErrorAction Stop
    [DpiHelper]::SetProcessDPIAware() | Out-Null
    $dpiW = [DpiHelper]::GetSystemMetrics(0)
    $dpiH = [DpiHelper]::GetSystemMetrics(1)
    if ($dpiW -gt 0 -and $dpiH -gt 0) {
      $sw = $dpiW
      $sh = $dpiH
    }
  } catch {
    # Fallback to WinForms value above
  }

  if ($sw -gt 0 -and $sh -gt 0) {
    Write-Host "Screen resolution: ${sw}x${sh}"

    # Patch width/height in config.toml (only under [image] section)
    $lines = Get-Content $configAbs -Encoding UTF8
    $inImageSection = $false
    $patched = $false
    $newLines = @()
    foreach ($line in $lines) {
      if ($line -match '^\s*\[image\]') {
        $inImageSection = $true
      } elseif ($line -match '^\s*\[') {
        $inImageSection = $false
      }
      if ($inImageSection -and $line -match '^\s*width\s*=') {
        $newLines += "width = $sw"
        $patched = $true
      } elseif ($inImageSection -and $line -match '^\s*height\s*=') {
        $newLines += "height = $sh"
        $patched = $true
      } else {
        $newLines += $line
      }
    }

    if ($patched) {
      $newLines | Set-Content $configAbs -Encoding UTF8
      Write-Host "Updated $ConfigPath with screen resolution ${sw}x${sh}."
    } else {
      Write-Host "Config already has resolution set."
    }
  }
} catch {
  Write-Host "Warning: Could not detect screen resolution. Using existing config values."
}

# ---- Install scheduled task ----
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
