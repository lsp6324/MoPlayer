$ErrorActionPreference = 'Stop' # 任意下载或安装错误立即终止环境准备。
$environmentRoot = 'E:\tools\videoplayerenv' # 严格使用用户指定的独立环境目录。
foreach ($directoryName in @('downloads', 'cache\pip', 'cache\pycache', 'temp', 'runtime')) { # 预先建立所有可配置缓存和运行时目录。
    New-Item -ItemType Directory -Force (Join-Path $environmentRoot $directoryName) | Out-Null # 不向系统全局安装依赖。
} # 完成目录初始化。
$env:TEMP = Join-Path $environmentRoot 'temp' # 下载与安装临时文件放入指定目录。
$env:TMP = $env:TEMP # 同步 Windows 临时目录配置。
$env:PIP_CACHE_DIR = Join-Path $environmentRoot 'cache\pip' # 设置 pip 专用缓存路径。
$env:PYTHONPYCACHEPREFIX = Join-Path $environmentRoot 'cache\pycache' # 将 Python 字节码缓存隔离。
$pythonExecutable = Join-Path $environmentRoot 'python\tools\python.exe' # 采用 NuGet 提供的完整独立 Python。
if (-not (Test-Path -LiteralPath $pythonExecutable)) { # 已存在独立环境时不覆盖运行时。
    $pythonArchive = Join-Path $environmentRoot 'downloads\python.zip' # 下载包保留在隔离目录。
    Invoke-WebRequest 'https://www.nuget.org/api/v2/package/python/3.12.10' -OutFile $pythonArchive -TimeoutSec 180 # 通过官方 NuGet 下载指定 Python 版本。
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath (Join-Path $environmentRoot 'python') -Force # 解压不写入全局安装目录。
} # 结束 Python 准备。
& $pythonExecutable -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt') # 将全部 Python 依赖安装到独立运行时。
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' } # 不继续构建缺失依赖的程序。
$vlcLibrary = Join-Path $environmentRoot 'runtime\vlc-3.0.21\libvlc.dll' # 检查所需 VLC 运行库。
if (-not (Test-Path -LiteralPath $vlcLibrary)) { # 已准备的 VLC 不重复下载。
    $vlcArchive = Join-Path $environmentRoot 'downloads\vlc.zip' # 存放官方 Windows 便携 ZIP。
    Invoke-WebRequest 'https://download.videolan.org/pub/videolan/vlc/3.0.21/win64/vlc-3.0.21-win64.zip' -OutFile $vlcArchive -TimeoutSec 180 # 下载固定版本完整插件集。
    Expand-Archive -LiteralPath $vlcArchive -DestinationPath (Join-Path $environmentRoot 'runtime') -Force # 将播放内核部署在指定环境内。
} # 结束 VLC 准备。
Write-Output '开发环境准备完成；可执行 build.ps1 构建便携版。' # 给出明确的后续构建入口。
