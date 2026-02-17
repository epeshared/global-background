## global-background

Windows 壁纸自动更新工具：每隔一段可配置的时间，从 NASA GIBS 的近实时地球卫星底图拉取你所在地附近的影像，生成壁纸并设置到 Windows。

### 1) 环境准备（Windows）

- 安装 Python 3.11+（64 位），并确保 `python` 在 PATH
- （推荐）安装 Git 与 VS Code

如果你运行 `where python` 看到的是：

`C:\Users\<you>\AppData\Local\Microsoft\WindowsApps\python.exe`

这通常是 Windows 的“应用执行别名”（会触发 Microsoft Store），不是可用的 Python。解决方法：

- 安装 python.org 的 Python（或公司内部分发的 Python）
- 在 Windows 设置 → 应用 → 高级应用设置 → 应用执行别名里关闭 `python.exe/python3.exe`
- 重新打开终端，确认 `python --version` 能正常输出

### 2) 安装依赖

如果你网络能访问 PyPI：在仓库根目录执行：

`python -m pip install -U pip`

`python -m pip install -e .[full]`

如果你网络访问 PyPI 有困难，也可以先不安装任何依赖：本项目支持“纯标准库模式”（会跳过图片叠字/不生成 BMP，但依然能下载图片并设置壁纸）。

离线/受限网络下运行（推荐）：

- PowerShell：`$env:PYTHONPATH = "$PWD\src"`
- 然后直接运行：`python -m global_background once --config config.toml`

如果公司网络需要代理，可在 PowerShell 里先设置：

- `$env:HTTPS_PROXY = "http://proxy:port"`
- `$env:HTTP_PROXY = "http://proxy:port"`

也可以直接写到 `config.toml` 的 `[network]` 里（计划任务也会自动生效）。

如果你的 Windows 代理是通过 WPAD/PAC 自动配置（例如注册表里有 `AutoConfigURL`，但 `ProxyEnable=0`），本工具也会尝试通过 WinHTTP 自动解析每个 URL 应该走的代理（无需手动找出 proxy host:port）。

如果你机器上 `python` 会弹出 Microsoft Store（Windows 的 App execution alias），请安装 python.org 的 Python，并在“应用执行别名”里关闭 `python.exe/python3.exe` 的别名；或在后面的计划任务脚本里用 `-PythonExe` 显式指定真实的 `python.exe` 路径。

### 3) 配置

复制示例配置：

推荐用 TOML（不需要 PyYAML）：

`copy config.example.toml config.toml`

也支持 YAML（需要安装 PyYAML，即 `pip install -e .[full]`）：

`copy config.example.yaml config.yaml`

常用配置项：

- `update_interval_minutes`: 更新间隔（分钟）
- `auto_location`: 是否用 IP 自动定位（更省事，但精度取决于网络）
- `location.lat / location.lon`: 手动指定经纬度
- `area.half_width_km / area.half_height_km`: 拉取范围（越大越耗流量）
- `image.width / image.height`: 输出分辨率（建议和你屏幕一致）
- `image.width / image.height`: 也可以设置为 `0` 或 `"auto"`，自动读取主显示器分辨率
- `satellite.layers`: 图层列表（会按顺序尝试）
- `region.mode`: `local`（拉取你附近）或 `country`（拉取整国范围，适合“国家云图”）
- `wallpaper.style`: `fill|fit|stretch|center|span`
- `satellite.full_disk_scale`: （仅 full-disk：Himawari/GOES）在 `himawari_layout="fit"` 下缩放圆盘大小，例如 `0.75` 表示缩小 1/4
- `retention.keep_days`: 本地保留最近几天的图片（按日期文件夹清理）；设为 1 表示只保留今天

#### 想要“国家云图”（整国范围）

在 `config.toml` 里加：

- `[region] mode = "country"`

程序会：用 IP 定位拿到国家信息 → 尝试自动解析国家边界 bbox → 用该 bbox 去拉取卫星图。

如果公司网络无法访问自动解析服务，可直接手动指定：

- `country_bbox_latlon = [lat_min, lon_min, lat_max, lon_max]`

云图/云量类图层可以在 `satellite.layers` 里替换为你喜欢的（GIBS 上有很多 daily 云图图层）。

#### 想要“地球全貌 + 国家在中心”（地球球面视角）

这会把全球底图渲染成一个“地球球体”（正射投影），并把你的国家（或定位点）放到中心。

- 在 `config.toml` 里设置：`[region] mode = "globe"`
- `globe_center = "country"`（推荐）或 `"location"`

注意：`globe` 模式需要 Pillow（图像投影会用到）。如果你无法安装依赖，可继续用 `country`（整国矩形底图）模式。

背景效果：

- `globe_background_style = "gradient"` + `globe_background_rgb/globe_background_rgb2` 可以做暗蓝到黑的“太空渐变”
- 如果不想四角纯黑，把 `globe_background_rgb2` 设成非常暗的蓝（例如 `[0,0,6]`）
- `globe_background_stars = true` 会加一点点星点（很淡，避免喧宾夺主）

如果你在公司网络下，需要通过代理安装 Pillow（示例）：

`python -m pip install --proxy http://child-prc.intel.com:913 Pillow`

### 4) 手动运行

拉取一次并设置壁纸：

推荐（不依赖把 `global-background` 加到 PATH）：

`python -m global_background once --config config.toml`

如果你已执行 `pip install -e .` 并且命令在 PATH，也可以用：

`global-background once --config config.toml`

只生成图片不设置壁纸（调试用）：

`python -m global_background once --config config.toml --dry-run`

循环运行（前台常驻）：

`python -m global_background run --config config.toml`

仅测试“设置壁纸”功能（用本地已有图片）：

`python -m global_background set --path out\\2026-02-14\\xxx.bmp --style fill`

完全离线测试（自动生成一张纯色 BMP 并设置为壁纸）：

`python -m global_background demo --width 1920 --height 1080 --rgb 20,40,60 --style fill`

### 5) 安装为计划任务（推荐）

计划任务模式会每 N 分钟运行一次 `once`（执行完就退出），比常驻进程更稳定。

一键脚本都在 `scripts\` 下，支持两种运行方式：

- 方式 A（推荐）：直接双击 `.cmd`
- 方式 B：PowerShell 运行 `.ps1`（命令示例见下方）

#### 手动跑一次（不装任务）

`powershell -ExecutionPolicy Bypass -File scripts\run-once.ps1 -ConfigPath config.toml`

仅生成图片不设置壁纸（调试用）：

`powershell -ExecutionPolicy Bypass -File scripts\run-once.ps1 -ConfigPath config.toml -DryRun`

安装/更新任务：

`powershell -ExecutionPolicy Bypass -File scripts\\install-task.ps1 -ConfigPath config.toml -IntervalMinutes 30`

每小时更新一次（一键安装）：

- PowerShell：`powershell -ExecutionPolicy Bypass -File scripts\\install-hourly-task.ps1 -ConfigPath config.toml`
- 或双击：`scripts\\install-hourly-task.cmd`

安装后立刻跑一次（可选）：

`powershell -ExecutionPolicy Bypass -File scripts\\install-hourly-task.ps1 -ConfigPath config.toml -RunNow`

如果“任务运行了但壁纸没变化”，优先看日志：`logs\\task-run.latest.log`（常见原因是企业代理把 Himawari 资源替换成占位图/拦截页）。

如果需要指定 Python 路径：

`powershell -ExecutionPolicy Bypass -File scripts\\install-task.ps1 -ConfigPath config.toml -IntervalMinutes 30 -PythonExe C:\\Path\\To\\python.exe`

立即运行一次：

`schtasks /Run /TN GlobalBackground`

停止正在运行的任务（不删除）：

- PowerShell：`powershell -ExecutionPolicy Bypass -File scripts\\stop-task.ps1`
- 或双击：`scripts\\stop-task.cmd`

停止并禁用任务（保留但不再按小时触发）：

`powershell -ExecutionPolicy Bypass -File scripts\\stop-task.ps1 -Disable`

如果你想恢复（重新启用）：直接重新运行安装脚本即可（`install-hourly-task` 或 `install-task` 会覆盖更新任务）。

卸载任务：

`powershell -ExecutionPolicy Bypass -File scripts\\uninstall-task.ps1`

### 说明

- 图片会保存在 `output_dir`（默认 `out/`）下按日期分文件夹（如 `out/2026-02-14/`），文件名以时间开头，天然按时间序列排序；同时会额外保存 BMP 以最大化兼容性。
- 影像来源：优先 NASA GIBS WMS（每日图层，脚本会在最近若干天内回退尝试）；如果网络无法访问 NASA，会自动回退到 ESRI World Imagery（非严格实时，但通常更容易访问）。

### 直接下载“地球圆盘云图”（推荐试用）

如果你想要类似“地球全景圆盘 + 云图”的效果（不自己渲染），可以用 Himawari（亚太半球）红外云图：

- 在配置里设置：`[satellite] provider = "himawari"`
- 默认用 `FULL_24h` + `B13`（红外，昼夜可用），并会自动回退最近若干分钟找最新可用帧。

如果你想看“真彩”（白天效果更像真实卫星云图），可以把 Himawari 切到 `D531106`：

- `himawari_product = "D531106"`
- `himawari_band = ""`（该产品 URL 没有 band 段）

如果你想要“地球圆盘 + 太空背景”的全景效果（不裁掉圆盘周围的太空），建议再加：

- `himawari_layout = "fit"`（保持完整地球圆盘，可用渐变背景填充两侧）

如果你在企业网络/代理环境里遇到“生成的图几乎全黑/几乎没内容”，脚本会自动跳过部分站点返回的占位帧；如果仍然失败，并提示 tile 被代理替换（corner/center tiles byte-identical），通常表示域名被代理拦截并返回了统一的占位图片，需要在代理侧为 `himawari8-dl.nict.go.jp` 例外/放行，或改用 GIBS/ESRI 等图源。

注意：Himawari 是固定卫星视角（适合东亚/亚太）；美洲更适合 GOES 系列（有稳定 `latest.jpg`）。

#### 备选：SLIDER（RAMMB/CIRA，Himawari / GK2A）更稳定的“最新帧”

如果你想要“亚洲视角的真实地球圆盘”，并且你的网络更容易访问 `slider.cira.colostate.edu`，可以用 SLIDER 图源：

- 配置：`[satellite] provider = "slider"`
- 常用参数：
	- `slider_satellite = "himawari"`（也可以试 `"gk2a"`）
	- `slider_product = "geocolor"`（真彩合成；也可尝试 `natural_color`/`band_13` 等）
	- `slider_max_level = 3`（越大越清晰但越耗流量；0..4）
	- `himawari_layout = "fit"` + `full_disk_scale = 0.75`（让圆盘完整显示并缩小一点）

SLIDER 会通过 `latest_times.json` 直接取“最新时间戳”，比 Himawari 原站那种回退探测更稳定；如果企业代理拦截了这个域名，同样会触发“corner/center tiles byte-identical”的快速失败提示。

#### 备选：GOES（NOAA，美洲半球）地球圆盘真彩

如果你的网络环境拦截了 Himawari（`himawari8-dl.nict.go.jp`），但你仍然想要“地球圆盘”而不是矩形底图，可以改用 NOAA 的 GOES 全圆盘真彩（GEOCOLOR）：

- 配置：`[satellite] provider = "goes"`
- 常用参数：
	- `goes_satellite = "GOES18"`（更偏太平洋/西半球）或 `"GOES16"`（更偏大西洋/东半球）
	- `goes_product = "GEOCOLOR"`
	- `goes_size = 5424`（也可用 1808/10848，越大越清晰但越耗流量）
	- `himawari_layout = "fit"`（同样适用于 GOES，让圆盘完整显示）

对应的直接下载 URL（示例）：

- GOES18 / GEOCOLOR / 5424：`https://cdn.star.nesdis.noaa.gov/GOES18/ABI/FD/GEOCOLOR/5424x5424.jpg`
- GOES18 / GEOCOLOR / 1808：`https://cdn.star.nesdis.noaa.gov/GOES18/ABI/FD/GEOCOLOR/1808x1808.jpg`
# global-background