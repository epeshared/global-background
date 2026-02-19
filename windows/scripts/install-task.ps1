param(
  [string]$ConfigPath = "config.toml",
  [string]$TaskName = "GlobalBackground",
  [int]$IntervalMinutes = 30,
  [string]$PythonExe = "",
  [string]$ProxyServer = "http://child-prc.intel.com:913"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$configAbs = Resolve-Path (Join-Path $repoRoot $ConfigPath)

function Test-PythonRunnable([string]$Candidate) {
  try {
    $raw = & $Candidate -c "import sys; print(sys.executable)" 2>$null
    # Take only the last non-empty line (ignore warnings/banners on earlier lines)
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
  # 从注册表读取 WinINet 代理（IE/系统代理）
  try {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $enabled = (Get-ItemProperty $key -ErrorAction SilentlyContinue).ProxyEnable
    if ($enabled -eq 1) {
      $server = (Get-ItemProperty $key -ErrorAction SilentlyContinue).ProxyServer
      if ($server) {
        # 格式可能是 "host:port" 或 "http=host:port;https=host:port"
        if ($server -notmatch '://') { $server = "http://$server" }
        return $server
      }
    }
  } catch {}
  # 回退：读取 WinHTTP 代理
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
        if ($exe -and (Test-Path $exe -PathType Leaf -ErrorAction SilentlyContinue) -and -not ($exe -like "*\\.venv\\*") -and -not ($exe -like "*WindowsApps*\\python.exe")) {
          $resolved += $exe
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

  # 用 @() 强制保持数组类型，避免单元素时 Select-Object -Unique 降解为字符串（字符串索引会取首字符）
  $resolved = @($resolved | Select-Object -Unique)
  if (-not $resolved -or $resolved.Count -eq 0) {
    throw "python not found in PATH. Install Python 3.11+ and ensure it's on PATH."
  }

  # Prefer a Python that already has Pillow
  foreach ($e in $resolved) {
    if (Test-PythonHasPillow $e) { return $e }
  }

  # No Python has Pillow — auto-install into the first available Python
  $target = $resolved[0]
  Write-Host "Pillow not found. Installing Pillow into: $target ..."

  # 自动检测系统代理（公司网络场景）
  $proxy = Get-WinHttpProxy
  if (-not $proxy -and $ProxyServer) {
    $proxy = $ProxyServer
  }
  $proxyArgs = @()
  if ($proxy) {
    Write-Host "Using proxy: $proxy"
    $proxyArgs = @("--proxy", $proxy)
  }

  # 先尝试 --user 安装（不需要管理员权限，适合安装在 Program Files 的 Python）
  try {
    & $target -m pip install --quiet --user @proxyArgs Pillow 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-PythonHasPillow $target)) {
      Write-Host "Pillow installed successfully (user)."
      return $target
    }
  } catch {
    # ignore
  }
  # 再尝试全局安装
  try {
    & $target -m pip install --quiet @proxyArgs Pillow 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-PythonHasPillow $target)) {
      Write-Host "Pillow installed successfully."
      return $target
    }
  } catch {
    # pip might not be available; try ensurepip first
  }

  # Fallback: try ensurepip then pip install
  try {
    Write-Host "Trying ensurepip..."
    & $target -m ensurepip --upgrade 2>&1 | Out-Null
    & $target -m pip install --quiet --user @proxyArgs Pillow 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-PythonHasPillow $target)) {
      Write-Host "Pillow installed successfully (via ensurepip, user)."
      return $target
    }
  } catch {
    # ignore
  }

  Write-Host "Warning: Could not auto-install Pillow. Full-disk images may not be resized properly."
  $pipProxy = if ($proxy) { " --proxy $proxy" } else { "" }
  Write-Host "         Run manually:  $target -m pip install --user$pipProxy Pillow"
  return $target
}
$exe = Resolve-PythonExe $PythonExe

if (-not $exe -or -not (Test-Path $exe -PathType Leaf -ErrorAction SilentlyContinue)) {
  throw "Could not locate a valid Python executable. Install Python 3.11+ and ensure it is on PATH."
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
