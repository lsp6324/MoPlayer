$ErrorActionPreference = 'Stop' # 任何准备失败立即停止构建。
$environmentRoot = 'E:\tools\videoplayerenv' # 所有开发工具和缓存使用指定目录。
$env:TEMP = Join-Path $environmentRoot 'temp' # 将构建临时文件放到隔离环境。
$env:TMP = $env:TEMP # 保持 Windows 临时目录变量一致。
$env:PIP_CACHE_DIR = Join-Path $environmentRoot 'cache\pip' # 隔离依赖下载缓存。
$env:PYTHONPYCACHEPREFIX = Join-Path $environmentRoot 'cache\pycache' # 避免源码目录产生字节码缓存。
$env:PYINSTALLER_CONFIG_DIR = Join-Path $environmentRoot 'cache\pyinstaller' # 隔离打包工具缓存。
$pythonExecutable = Join-Path $environmentRoot 'python\tools\python.exe' # 使用独立 Python 运行时。
$vlcDirectory = Join-Path $environmentRoot 'runtime\vlc-3.0.21' # 指向完整 VLC 便携运行库。
Set-Location $PSScriptRoot # 从项目根目录执行构建。
$ffmpegExecutable = & $pythonExecutable -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' # 查询已安装的 FFmpeg 二进制。
$resourceDirectory = Join-Path $environmentRoot 'build-resources' # 将构建资源中间文件放到隔离目录。
New-Item -ItemType Directory -Force $resourceDirectory | Out-Null # 确保资源目录存在。
Copy-Item -LiteralPath $ffmpegExecutable -Destination (Join-Path $resourceDirectory 'ffmpeg.exe') -Force # 使用固定包内文件名。
& $pythonExecutable make_icon.py # 从云璃源图导出多尺寸 EXE 图标。
if ($LASTEXITCODE -ne 0) { throw '图标导出失败' } # 不交付缺失图标的程序。
& $pythonExecutable -m PyInstaller --noconfirm --clean --windowed --onedir --name MoPlayer --distpath (Join-Path $environmentRoot 'build-output') --workpath (Join-Path $environmentRoot 'build') --specpath $resourceDirectory --add-binary "$vlcDirectory\libvlc.dll;vlc" --add-binary "$vlcDirectory\libvlccore.dll;vlc" --add-data "$vlcDirectory\plugins;vlc\plugins" --add-binary "$resourceDirectory\ffmpeg.exe;." --icon "$PSScriptRoot\assets\yunli.ico" --add-data "$PSScriptRoot\assets;assets" --add-data "$PSScriptRoot\register_thumbnail_component.ps1;." --hidden-import verify_ui --hidden-import verify --hidden-import verify_thumbnails --hidden-import PySide6.QtTest --exclude-module tkinter --exclude-module imageio_ffmpeg app.py # 在隔离目录构建，不让 PyInstaller 清理用户正在使用的便携数据目录。
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败' } # 不发布失败的打包结果。
$portableDirectory = Join-Path $PSScriptRoot 'dist\MoPlayer' # 获取可独立运行的便携目录。
New-Item -ItemType Directory -Force $portableDirectory | Out-Null # 保留已有便携目录及其中的历史和收藏数据。
Copy-Item -Path (Join-Path $environmentRoot 'build-output\MoPlayer\*') -Destination $portableDirectory -Recurse -Force # 仅覆盖新程序与运行库，绝不删除 data 目录。
& $pythonExecutable (Join-Path $PSScriptRoot 'refresh_icon.py') (Join-Path $portableDirectory 'MoPlayer.exe') # 覆盖同名 EXE 后通知资源管理器重新读取图标。
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination $portableDirectory -Force # 将运行说明随包交付。
$licensesDirectory = Join-Path $portableDirectory 'licenses' # 为第三方许可证提供可见入口。
New-Item -ItemType Directory -Force $licensesDirectory | Out-Null # 创建许可证目录。
Get-ChildItem -LiteralPath $vlcDirectory -File | Where-Object { $_.Name -match 'COPYING|AUTHORS|THANKS|README' } | Copy-Item -Destination $licensesDirectory -Force # 保留 VLC 原始版权与授权材料。
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD_PARTY.md') -Destination $licensesDirectory -Force # 随包提供组件来源与源码获取方式。
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination $portableDirectory -Force # 随包保留应用开源许可证。
Copy-Item -Path (Join-Path $PSScriptRoot 'third_party_licenses\*') -Destination $licensesDirectory -Recurse -Force # 从完整源码包收集第三方许可文本。
& $ffmpegExecutable -version | Set-Content -Encoding utf8 (Join-Path $licensesDirectory 'ffmpeg-version.txt') # 记录实际 FFmpeg 构建版本与配置。
& $pythonExecutable -m pip freeze | Set-Content -Encoding utf8 (Join-Path $PSScriptRoot 'dependencies.lock.txt') # 记录实际使用的全部构建依赖版本。
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'TEST_RESULTS.md')) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'TEST_RESULTS.md') -Destination $portableDirectory -Force } # 保留交付时已经完成的实际测试报告。
Write-Output $portableDirectory # 输出用户可直接运行的目录。



