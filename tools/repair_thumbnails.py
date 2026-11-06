import ctypes  # 通知资源管理器重新读取文件关联。
import json  # 保存可恢复的关联备份和实测报告。
import os  # 展开 Windows 系统组件路径。
import sys  # 允许使用明确备份执行回滚。
import time  # 为本次修复生成独立备份文件名。
import winreg  # 仅修复当前用户的缩略图关联。
from pathlib import Path  # 将备份和日志放在用户指定的工具目录。

THUMBNAIL = '{e357fccd-a995-4576-b01f-234630154e96}'  # Windows IThumbnailProvider 关联接口。
NATIVE = '{9DBD2C50-62AD-11D0-B806-00C04FD706EC}'  # 本机已注册的 Windows 属性缩略图处理程序。
SUFFIXES = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm']  # 仅涉及播放器明确支持的视频容器。

def read(root, key, name=''):  # 读取值并保留注册表数据类型。
    try:  # 不存在的用户覆盖值需要区别于空字符串。
        with winreg.OpenKey(root, key) as handle:  # 只读打开目标键。
            value, kind = winreg.QueryValueEx(handle, name)  # 保留原值及类型供回滚。
            return {'exists': True, 'value': value, 'kind': kind}  # 返回结构化备份。
    except FileNotFoundError:  # 不存在时不构造虚假原值。
        return {'exists': False}  # 回滚时删除本次新增值即可。

def available(provider):  # 确认处理程序 DLL 真正存在，而不只判断 GUID 字符串。
    if not provider:  # 无处理程序表示无法复用。
        return False  # 交给调用方选择有效组件。
    server = read(winreg.HKEY_CLASSES_ROOT, 'CLSID\\' + provider + r'\InProcServer32')  # 查询本机组件注册。
    return server['exists'] and Path(os.path.expandvars(server['value'].strip('"'))).is_file()  # 避免复用已卸载组件。

def provider_for(suffix):  # 保留有效现有处理程序，否则使用 Windows 自带组件。
    existing = read(winreg.HKEY_CLASSES_ROOT, suffix + '\\shellex\\' + THUMBNAIL)  # 查看当前格式配置。
    provider = existing.get('value')  # 缺失时返回空值。
    return provider if available(provider) else NATIVE if available(NATIVE) else None  # 不安装或伪造第三方解码器。

def configure_moplayer(write):  # 注册默认播放器时同时保留视频缩略图能力。
    provider = provider_for('.mp4')  # 六种格式优先复用当前系统的视频处理程序。
    if not provider:  # 没有有效组件时不能声称缩略图可用。
        return  # 留待明确修复和测试。
    for association in ['MoPlayer.Video', r'Applications\MoPlayer.exe']:  # 同时覆盖默认应用与手动选择 EXE 两种方式。
        write('Software\\Classes\\' + association + '\\shellex\\' + THUMBNAIL, '', provider)  # 用缩略图处理程序生成画面，DefaultIcon 仅作后备。

def repair():  # 为本机已有失效视频组件建立当前用户级安全覆盖。
    directory = Path(r'E:\tools\videoplayerenv\backups\thumbnail-associations')  # 遵守工具和备份路径限制。
    directory.mkdir(parents=True, exist_ok=True)  # 创建修复记录目录。
    backup = directory / f'before-{time.time_ns()}.json'  # 不覆盖任何历史备份。
    changes = []  # 精确记录本次涉及的值而非导出整个用户注册表。
    def write(key, name, value):  # 每次写入前先持久化原值。
        changes.append({'key': key, 'name': name, 'before': read(winreg.HKEY_CURRENT_USER, key, name), 'after': value})  # 记录可逆变更。
        backup.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')  # 即使中途失败也有已完成步骤的原值。
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:  # 只在当前用户下覆盖损坏关联。
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)  # 保留系统范围和其他用户设置。
    for suffix in SUFFIXES:  # 修复六种明示支持的格式。
        provider = provider_for(suffix)  # 检查对应组件是否仍在。
        if not provider:  # 没有可用组件时不写入无效引用。
            raise RuntimeError('未找到可用的 Windows 视频缩略图处理程序。')  # 明确报告需要系统支持。
        for association in [suffix, 'SystemFileAssociations\\' + suffix]:  # 让缩略图设置跨默认播放器变化仍可用。
            write('Software\\Classes\\' + association + '\\shellex\\' + THUMBNAIL, '', provider)  # 替换失效组件引用。
    configure_moplayer(write)  # 给 MoPlayer 的两种关联身份补充缩略图能力。
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # 请求 Shell 重新读取关联缓存。
    print(str(backup))  # 输出可追溯备份位置。

def restore(backup):  # 将本次修复精确还原为写入前的值。
    for change in reversed(json.loads(Path(backup).read_text(encoding='utf-8'))):  # 逆序处理完整变更记录。
        key, name, before = change['key'], change['name'], change['before']  # 读取明确备份的目标值。
        if not key.startswith('Software\\Classes\\'):  # 不允许备份指定其他注册表区域。
            raise ValueError('备份包含不允许的注册表位置。')  # 避免误改无关设置。
        current = read(winreg.HKEY_CURRENT_USER, key, name)  # 检查修复后是否又被其他程序修改。
        if not current['exists'] or current['value'] != change['after']:  # 不覆盖用户后来的新设置。
            continue  # 保留新的明确选择。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:  # 只还原已记录的单个值。
            if before['exists']:  # 原值存在时恢复值及类型。
                winreg.SetValueEx(handle, name, 0, before['kind'], before['value'])  # 还原原来的处理程序。
            else:  # 原值不存在说明是本次新增的覆盖。
                winreg.DeleteValue(handle, name)  # 删除本次新增值，使系统范围配置重新生效。
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # 通知 Shell 已恢复原设置。

if __name__ == '__main__':  # 仅明确执行修复脚本时调整系统关联。
    restore(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--restore' else repair()  # 明确指定备份时回滚，否则执行可追踪修复。
