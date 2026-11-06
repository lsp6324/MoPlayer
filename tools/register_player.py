import sys  # 接收当前便携版 EXE 位置。
import winreg  # 只在当前用户下注册可选默认应用。
from pathlib import Path  # 验证注册路径。
from tools.refresh_icon import refresh  # 通知 Windows 更新应用关联缓存。
from tools.repair_thumbnails import configure_moplayer  # 保留系统视频缩略图与默认播放器关联。

def register(executable):  # 让默认应用设置识别便携版，不伪造 UserChoice。
    executable = Path(executable).resolve(strict=True)  # 注册确实存在的交付 EXE。
    def write(key, name, value):  # 将关联信息写到当前用户范围。
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:  # 不修改系统范围或请求管理员权限。
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)  # 保存 Unicode 路径和显示名称。
    command = f'"{executable}" "%1"'  # 为程序和带空格的视频路径分别加引号。
    classes = r'Software\Classes'  # Windows 当前用户的文件类型注册根。
    progid = 'MoPlayer.Video'  # 为本应用使用独立视频类型标识。
    write(classes + '\\' + progid, '', 'MoPlayer 视频')  # 显示可读的视频类型名称。
    write(classes + '\\' + progid + r'\DefaultIcon', '', f'"{executable}",0')  # 视频关联使用内嵌云璃图标。
    write(classes + '\\' + progid + r'\shell\open\command', '', command)  # 双击时将选中的文件传给播放器。
    write(classes + '\\' + progid + r'\Application', 'ApplicationName', 'MoPlayer')  # 为系统默认应用选择器提供应用名称。
    write(classes + '\\' + progid + r'\Application', 'ApplicationIcon', f'"{executable}",0')  # 为选择器提供应用图标。
    write(classes + '\\' + progid + r'\Application', 'ApplicationDescription', '本地视频播放与分类管理')  # 完整声明文件类型所属应用。
    application = classes + r'\Applications\MoPlayer.exe'  # 注册到“打开方式”的应用列表。
    write(application, 'FriendlyAppName', 'MoPlayer')  # 显示明确的播放器名称。
    write(application + r'\shell\open\command', '', command)  # 通过同一命令打开文件。
    capabilities = r'Software\MoPlayer\Capabilities'  # 保存 Windows 默认应用能力信息。
    write(capabilities, 'ApplicationName', 'MoPlayer')  # 默认应用列表名称。
    write(capabilities, 'ApplicationDescription', '本地视频播放与分类管理')  # 显示中文应用说明。
    write(capabilities, 'ApplicationIcon', f'"{executable}",0')  # 设置默认应用列表图标。
    for suffix in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm']:  # 注册用户要求的六种视频容器格式。
        write(capabilities + r'\FileAssociations', suffix, progid)  # 声明格式支持而不强行覆盖用户选择。
        write(application + r'\SupportedTypes', suffix, '')  # 允许“打开方式”推荐本应用。
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classes + '\\' + suffix + r'\OpenWithProgids') as handle:  # 保留其他播放器已有注册。
            winreg.SetValueEx(handle, progid, 0, winreg.REG_NONE, b'')  # 添加可选处理程序。
    write(r'Software\RegisteredApplications', 'MoPlayer', capabilities)  # 让系统设置显示此应用。
    configure_moplayer(write)  # 为手动选择 EXE 与默认应用两种关联补充缩略图处理程序。
    refresh(executable)  # 让 Windows 重新枚举刚注册的应用。

if __name__ == '__main__':  # 构建后可手动重新注册移动后的便携路径。
    register(sys.argv[1])  # 只使用调用者明确指定的可执行文件。
