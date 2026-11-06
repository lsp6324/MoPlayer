import argparse  # 提供明确的启用、检查和回滚入口。
import base64
import ctypes  # 通知资源管理器刷新关联。
import hashlib  # 验证官方组件包完整性。
import json  # 保存逐值备份和运行状态。
import os  # 展开系统路径中的环境变量。
import shutil  # 将系统注册脚本放到稳定工具目录。
import sys
import subprocess  # 必要时由 Windows UAC 执行一次系统类注册。
import time  # 为每次配置保留独立备份。
import urllib.request  # 从官方 GitHub 下载原始便携包。
import winreg  # 注册当前用户的视频缩略图处理程序。
import zipfile  # 解压官方采用 LZMA 压缩的 ZIP。
from pathlib import Path  # 强制组件和可配置缓存使用指定工具目录。
from moplayer.runtime import BASE, BUNDLE

ENVIRONMENT = BASE / 'data' / 'integrations' / 'explorer-thumbnails'
VERSION = '3.3.6'  # 固定本次已验证的官方版本。
URL = f'https://github.com/Xanashi/Icaros/releases/download/v{VERSION}/Icaros_v{VERSION}.zip'  # 只下载作者发布的便携包。
SHA256 = '18854b445420e7167b5f54696009c9ffbc0e7917da9d9a686eac71ea3c81d47a'  # 官方 GitHub Release 给出的摘要。
DIRECTORY = ENVIRONMENT / 'plugins' / f'Icaros-{VERSION}'  # 注册后组件路径需保持稳定。
PROVIDER = '{c5aec3ec-e812-4677-a9a7-4fee1f9aa000}'  # Icaros 视频缩略图 COM 类。
THUMBNAIL = '{e357fccd-a995-4576-b01f-234630154e96}'  # Windows IThumbnailProvider 关联接口。
EXTENSIONS = '.mp4 .mkv .avi .mov .wmv .webm .m4v .mpg .mpeg .mpe .mpv .m2v .m2ts .mts .ts .m2t .vob .flv .f4v .ogv .ogm .rm .rmvb .3gp .3g2 .asf .mxf .divx .qt .mk3d .av1 .hevc .h264 .264 .265 .y4m'.split()  # 常见视频容器和视频码流扩展名。

def current(key, name=''):  # 精确读取当前用户值，区分不存在与空字符串。
    try:  # 允许首次启用时不存在配置。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:  # 不读取或备份无关用户数据。
            value, kind = winreg.QueryValueEx(handle, name)  # 保存值和原数据类型。
            return {'exists': True, 'value': value, 'kind': kind}  # 支持精确回滚。
    except FileNotFoundError:  # 未配置与已配置为空有不同含义。
        return {'exists': False}  # 回滚时删除此次新增值。

def allowed(key):  # 限定脚本可以更改的注册表范围。
    return key.startswith('Software\\Classes\\') or key == r'Software\Icaros'  # 不修改系统范围、默认打开方式或安全设置。

def notify():  # 让资源管理器重新枚举处理程序。
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # 使关联缓存失效而不重启桌面。

def ensure_machine(provider):  # 保持 Windows 缩略图隔离宿主可加载此组件。
    key = 'SOFTWARE\\Classes\\CLSID\\' + PROVIDER + r'\InprocServer32'  # 仅检查本组件的系统级 COM 注册。
    try:  # 已正确注册时不再触发 UAC。
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:  # 不修改默认应用设置。
            existing = winreg.QueryValueEx(handle, '')[0]  # 读取实际 DLL 路径。
            if Path(os.path.expandvars(existing)).resolve() == provider.resolve():  # 必须与本次已校验组件一致。
                return  # 无需重复提升权限。
    except FileNotFoundError:  # 尚未进行系统级类注册。
        pass  # 准备清晰的一次性注册操作。
    script = BUNDLE / ('register_thumbnail_component.ps1' if getattr(sys, 'frozen', False) else 'tools/register_thumbnail_component.ps1')
    target = ENVIRONMENT / 'register_thumbnail_component.ps1'  # UAC 只执行指定工具目录内的脚本。
    shutil.copyfile(script, target)  # 避免注册依赖源码或便携包位置。
    status = ENVIRONMENT / 'verification/global-video-thumbnails/machine-registration-result.json'  # 等待系统注册的明确回执。
    status.parent.mkdir(parents=True, exist_ok=True)  # 首次启用时先创建状态目录。
    status.unlink(missing_ok=True)  # 不把上一次回执误认为本次操作成功。
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'  # 使用 Windows 自带的系统脚本宿主。
    command = registration_command(powershell, target)
    result = subprocess.run(command, capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    reply = json.loads(status.read_text(encoding='utf-8-sig')) if status.is_file() else {}  # 缺失回执同样属于失败。
    if result.returncode or not reply.get('Success'):  # 用户取消或系统写入失败都不显示成功。
        raise OSError(reply.get('Error', 'Windows 未完成组件注册；请在 UAC 提示中允许这次注册后重试。'))  # 给出明确可重试状态。


def registration_command(powershell, script):
    """Quote arbitrary portable paths without treating their text as shell code."""
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    inner = '& ' + literal(script)
    encoded_inner = base64.b64encode(inner.encode('utf-16le')).decode('ascii')
    command = ('$registrationTask=Start-Process -FilePath ' + literal(powershell) +
               " -ArgumentList '-NoProfile -ExecutionPolicy Bypass -EncodedCommand " + encoded_inner +
               "' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $registrationTask.ExitCode")
    encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
    return [str(powershell), '-NoProfile', '-EncodedCommand', encoded]

def prepare():  # 获取原样发布的官方便携组件，无需运行安装器。
    archive = ENVIRONMENT / 'downloads' / f'Icaros_v{VERSION}.zip'  # 下载文件留在指定工具目录。
    archive.parent.mkdir(parents=True, exist_ok=True)  # 确保下载目录可用。
    if not archive.is_file():  # 已有下载也必须通过后续摘要校验。
        urllib.request.urlretrieve(URL, archive)  # 不从第三方镜像获取组件。
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:  # 验证整个文件而非文件名。
        raise ValueError('Icaros 官方包 SHA256 不匹配，请重新下载。')  # 不注册来源或内容不匹配的 DLL。
    DIRECTORY.mkdir(parents=True, exist_ok=True)  # 为原样便携包准备固定目录。
    with zipfile.ZipFile(archive) as package:  # Python 支持官方包的 LZMA ZIP 压缩。
        for entry in package.infolist():  # 解压前检查每个归档路径。
            destination = (DIRECTORY / entry.filename).resolve()  # 计算最终绝对路径。
            if not destination.is_relative_to(DIRECTORY.resolve()):  # 防止归档条目写到指定目录外。
                raise ValueError('组件包包含不安全路径。')  # 不执行部分越界解压。
        missing = [entry for entry in package.infolist() if not (DIRECTORY / entry.filename).exists()]  # 已部署并被 Shell 加载的文件无需重复覆盖。
        for entry in missing:  # 只补齐缺失文件，保留原样包内容。
            package.extract(entry, DIRECTORY)  # 许可证与全部运行依赖一并保留。
    provider = DIRECTORY / '64-bit' / 'IcarosThumbnailProvider.dll'  # 本机 Windows x64 使用对应架构。
    if not provider.is_file():  # 不注册失效的组件路径。
        raise FileNotFoundError(provider)  # 明确说明缺失组件。
    return provider  # 返回实际注册路径。

def install():  # 为当前用户的全部视频浏览配置统一缩略图能力。
    provider = prepare()  # 先确保原包与运行依赖已就绪。
    backups = ENVIRONMENT / 'backups' / 'explorer-thumbnails'  # 保存完整、可逆的注册记录。
    backups.mkdir(parents=True, exist_ok=True)  # 不在系统目录散放备份。
    backup = backups / f'before-{time.time_ns()}.json'  # 每次配置独立留档。
    changes = []  # 仅备份本次将要写入的注册表值。
    def write(key, name, value, kind=winreg.REG_SZ):  # 每次修改前持久化旧值。
        if not allowed(key):  # 强制限定修改范围。
            raise ValueError('不允许修改此注册表位置。')  # 避免脚本误改其他设置。
        previous = current(key, name)  # 获取当前用户覆盖值。
        if previous == {'exists': True, 'value': value, 'kind': kind}:  # 已正确配置的值无需重复记录。
            return  # 重复启用保持幂等。
        changes.append({'key': key, 'name': name, 'before': previous, 'after': value, 'kind': kind})  # 为回滚记录精确目标。
        backup.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')  # 先保留原值再修改。
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:  # 使用用户级 COM 与文件类型关联。
            winreg.SetValueEx(handle, name, 0, kind, value)  # 不需要管理员权限或系统目录安装。
    try:  # 任意注册失败时回滚已完成部分。
        component = 'Software\\Classes\\CLSID\\' + PROVIDER  # 注册该组件到当前用户 COM 视图。
        write(component, '', 'Icaros Thumbnail Provider')  # 显示标准组件名称。
        write(component + r'\InprocServer32', '', str(provider))  # 从指定工具目录加载 DLL。
        write(component + r'\InprocServer32', 'ThreadingModel', 'Apartment')  # 使用兼容 Shell 缩略图的 COM STA 模型。
        write(r'Software\Icaros', 'Cache', 0, winreg.REG_DWORD)  # 禁用 Icaros 独立索引缓存，使用 Windows 自己的缩略图缓存。
        write(r'Software\Icaros', 'Offset', 10, winreg.REG_DWORD)  # 优先从视频约百分之十处选取缩略图。
        write(r'Software\Icaros', 'FrameThresh', 8, winreg.REG_DWORD)  # 启用适中的黑白帧避让。
        for suffix in EXTENSIONS:  # 按扩展名长期配置，不需要逐文件手动生成。
            for association in [suffix, 'SystemFileAssociations\\' + suffix]:  # 默认播放器变化后仍能获得缩略图。
                write('Software\\Classes\\' + association + '\\shellex\\' + THUMBNAIL, '', PROVIDER)  # 新文件进入任意目录后由 Shell 按需提取。
        for association in ['MoPlayer.Video', r'Applications\MoPlayer.exe']:  # 覆盖默认应用和手动选择 EXE 的两种关联身份。
            write('Software\\Classes\\' + association + '\\shellex\\' + THUMBNAIL, '', PROVIDER)  # 保持云璃 EXE 图标与视频画面缩略图独立。
        ensure_machine(provider)  # 让正常隔离提取也可使用组件，而非仅在诊断进程中成功。
    except Exception:  # 不遗留半完成关联。
        if backup.exists():  # 只回滚实际记录过的值。
            restore(backup)  # 还原本次已完成部分。
        raise  # 向用户显示真实失败。
    notify()  # 配置完成后请求 Shell 重新读取关联。
    state = ENVIRONMENT / 'explorer-thumbnails.json'  # 读取已有维护记录以保留首次配置备份。
    previous = json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}  # 重复启用不丢弃已保存的备份路径。
    result = {'version': VERSION, 'provider': str(provider), 'archive_sha256': SHA256, 'extensions': EXTENSIONS, 'backup': str(backup) if changes else previous.get('backup'), 'changed_values': len(changes)}  # 保存可追踪的实际部署结果。
    (ENVIRONMENT / 'explorer-thumbnails.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')  # 为后续检查与维护提供清单。
    return result  # 不把完成注册当作全部编码已通过验收。

def restore(backup):  # 精确回滚而不覆盖用户后来做的新选择。
    changes = json.loads(Path(backup).read_text(encoding='utf-8'))  # 读取指定启用记录。
    for change in reversed(changes):  # 先恢复关联，再恢复组件路径。
        key, name = change['key'], change['name']  # 使用已记录的单一值。
        if not allowed(key):  # 不接受能修改其他系统区域的伪造备份。
            raise ValueError('备份包含不允许的注册表路径。')  # 在写入前拒绝越界。
        previous, value = change['before'], current(key, name)  # 检查当前值是否仍属于本次配置。
        if not value['exists'] or value['value'] != change['after']:  # 保留后来被其他程序修改过的值。
            continue  # 不强行覆盖用户新设置。
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:  # 仅修改目标值。
            if previous['exists']:  # 原值存在时连同原类型恢复。
                winreg.SetValueEx(handle, name, 0, previous['kind'], previous['value'])  # 恢复原缩略图处理程序或配置。
            else:  # 原来没有此用户覆盖时删除新增值。
                winreg.DeleteValue(handle, name)  # 让原系统范围设置重新生效。
    notify()  # 请求 Shell 重新读取回滚后的关联。

if __name__ == '__main__':  # 源码工具可独立启用或回滚。
    parser = argparse.ArgumentParser(description='启用全局视频缩略图支持；组件与维护记录存放在程序旁 data/integrations/explorer-thumbnails。')
    parser.add_argument('--restore', metavar='BACKUP_JSON')  # 回滚需要用户明确提供某次备份。
    arguments = parser.parse_args()  # 不接受隐含路径或未定义操作。
    print(json.dumps(restore(arguments.restore) if arguments.restore else install(), ensure_ascii=False, indent=2))  # 输出实际配置结果。
