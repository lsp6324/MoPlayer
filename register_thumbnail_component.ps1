$ErrorActionPreference = 'Stop' # 任意注册失败立即停止，避免伪报成功。
$componentRoot = 'E:\tools\videoplayerenv\plugins\Icaros-3.3.6' # 所有组件文件留在指定目录。
$componentDll = Join-Path $componentRoot '64-bit\IcarosThumbnailProvider.dll' # 系统隔离宿主使用 x64 处理程序。
$componentClass = '{c5aec3ec-e812-4677-a9a7-4fee1f9aa000}' # 仅注册 Icaros 缩略图类。
$registryPath = 'HKLM:\SOFTWARE\Classes\CLSID\' + $componentClass # 不改系统默认应用和其他 Shell 扩展。
$statusDirectory = 'E:\tools\videoplayerenv\verification\global-video-thumbnails' # 日志和状态留在工具目录。
New-Item -ItemType Directory -Force $statusDirectory | Out-Null # 确保回执位置存在。
try { # 由 Windows UAC 授权后运行一次系统级类注册。
    if (-not (Test-Path -LiteralPath $componentDll -PathType Leaf)) { throw 'Icaros DLL 不存在' } # 不注册无效路径。
    $backupFile = Join-Path $statusDirectory ('machine-class-before-' + [DateTime]::UtcNow.Ticks + '.json') # 每次运行保留独立备份。
    $classExists = Test-Path -LiteralPath $registryPath # 记录原系统级类是否存在。
    $classValues = if ($classExists) { Get-ItemProperty -LiteralPath $registryPath } else { $null } # 只备份本次目标类。
    $serverPath = Join-Path $registryPath 'InprocServer32' # 类的实际 DLL 注册位置。
    $serverExists = Test-Path -LiteralPath $serverPath # 记录原服务器是否存在。
    $serverValues = if ($serverExists) { Get-ItemProperty -LiteralPath $serverPath } else { $null } # 备份原 DLL 和线程模型。
    @{ ClassExists=$classExists; ClassValues=$classValues; ServerExists=$serverExists; ServerValues=$serverValues; Target=$registryPath } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $backupFile -Encoding utf8 # 写入前保存原值。
    New-Item -Path $registryPath -Force | Out-Null # 创建或打开唯一目标组件类。
    Set-Item -LiteralPath $registryPath -Value 'Icaros Thumbnail Provider' # 保持官方组件名称。
    New-Item -Path $serverPath -Force | Out-Null # 为隔离宿主提供实际模块路径。
    Set-Item -LiteralPath $serverPath -Value $componentDll # 注册路径仍然完全位于指定工具目录。
    New-ItemProperty -LiteralPath $serverPath -Name ThreadingModel -Value Apartment -PropertyType String -Force | Out-Null # 使用官方注册入口要求的 COM 线程模型。
    @{ Success=$true; Dll=$componentDll; Backup=$backupFile } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $statusDirectory 'machine-registration-result.json') -Encoding utf8 # 让主进程能够核验结果。
} catch { # 提供明确失败回执。
    @{ Success=$false; Error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $statusDirectory 'machine-registration-result.json') -Encoding utf8 # 不隐藏权限或写入错误。
    exit 1 # 向启动进程返回失败。
} # 系统注册仅涉及一个组件类及其 InprocServer32 子键。

