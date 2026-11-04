$ErrorActionPreference = 'Stop' # 验收准备失败立即停止。
$environmentRoot = 'E:\tools\videoplayerenv' # 测试工具和数据全部留在指定目录。
$testRoot = Join-Path $environmentRoot ('verification\portable-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) # 每次使用新目录，避免旧便携版嵌套复制导致误测。
$portableSource = Join-Path $PSScriptRoot 'dist\MoPlayer' # 使用实际交付的打包程序。
New-Item -ItemType Directory -Force $testRoot | Out-Null # 创建测试输出目录。
Copy-Item -LiteralPath $portableSource -Destination (Join-Path $testRoot 'MoPlayer') -Recurse -Force # 将便携版复制到不同位置验证可迁移性。
$pythonDirectory = Join-Path $environmentRoot 'python\tools' # 仅临时隐藏本项目独立 Python。
$vlcDirectory = Join-Path $environmentRoot 'runtime\vlc-3.0.21' # 仅临时隐藏本项目开发 VLC。
$pythonHidden = Join-Path $environmentRoot 'python\tools-isolation-test' # 隐藏目标仍处于指定环境根内。
$vlcHidden = Join-Path $environmentRoot 'runtime\vlc-isolation-test' # VLC 隐藏目标同样不越出环境目录。
foreach ($targetPath in @($pythonDirectory, $vlcDirectory, $pythonHidden, $vlcHidden)) { # 在移动目录前验证全部绝对目标。
    if (-not [IO.Path]::GetFullPath($targetPath).StartsWith($environmentRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '隔离测试路径越界' } # 拒绝任何环境目录外的递归移动。
} # 结束路径验证。
if ((Test-Path -LiteralPath $pythonHidden) -or (Test-Path -LiteralPath $vlcHidden)) { throw '发现遗留隔离目录，请先检查恢复状态' } # 不覆盖已有隔离现场。
$originalPath = $env:PATH # 保存当前进程搜索路径。
$originalPythonHome = $env:PYTHONHOME # 保存当前进程 Python 配置。
$originalPythonPath = $env:PYTHONPATH # 保存当前进程模块配置。
try { # 无论自检结果如何最终恢复开发环境。
    Move-Item -LiteralPath $pythonDirectory -Destination $pythonHidden # 临时使原开发解释器路径不可用。
    Move-Item -LiteralPath $vlcDirectory -Destination $vlcHidden # 临时使原开发播放内核路径不可用。
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot" # 排除系统上其他 Python 和 VLC 的搜索路径。
    $env:PYTHONHOME = '' # 不继承开发 Python 位置。
    $env:PYTHONPATH = '' # 不继承开发模块位置。
    $env:TEMP = Join-Path $environmentRoot 'temp' # 便携测试临时文件仍在指定目录。
    $env:TMP = $env:TEMP # 同步两个 Windows 临时变量。
    $executable = Join-Path $testRoot 'MoPlayer\MoPlayer.exe' # 从新位置启动便携程序。
    $process = Start-Process -FilePath $executable -ArgumentList @('--self-test', (Join-Path $testRoot 'results')) -WindowStyle Hidden -PassThru -Wait # 执行随包真实播放与归档自检。
    if ($process.ExitCode -ne 0) { throw "便携自检失败，退出码：$($process.ExitCode)" } # 失败不标记通过。
    Write-Output '便携版在开发 Python/VLC 路径不可用、PATH 隔离时通过自检。' # 报告精确测试条件。
    Write-Output $testRoot # 输出本次完整证据目录。
} finally { # 必须恢复被临时隐藏的开发目录。
    if (Test-Path -LiteralPath $pythonHidden) { Move-Item -LiteralPath $pythonHidden -Destination $pythonDirectory } # 恢复独立 Python 原路径。
    if (Test-Path -LiteralPath $vlcHidden) { Move-Item -LiteralPath $vlcHidden -Destination $vlcDirectory } # 恢复独立 VLC 原路径。
    $env:PATH = $originalPath # 还原当前进程原搜索路径。
    $env:PYTHONHOME = $originalPythonHome # 还原 Python 配置。
    $env:PYTHONPATH = $originalPythonPath # 还原模块配置。
} # 完成隔离测试清理。
