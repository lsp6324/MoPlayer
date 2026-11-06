import ctypes  # 通知 Windows 重读临时测试关联。
import json  # 保存全局缩略图实际验收报告。
import shutil  # 为两个 MoPlayer 关联身份创建独立测试文件。
import subprocess  # 生成真实多容器和多编码视频。
import sys  # 区分源码与打包 EXE 测试。
import winreg  # 用隔离测试扩展名验证 MoPlayer 默认关联。
from pathlib import Path  # 所有样例仅保存在指定测试目录。

def run(destination):  # 打包 EXE 和源码使用相同验收流程。
    from moplayer.app import BUNDLE  # 获取实际随包 FFmpeg。
    from tools.verify.verify import shell_thumbnail  # THUMBNAILONLY 禁止返回播放器图标冒充画面。
    from tools.regenerate_shell_thumbnail import regenerate  # 进一步验证 Windows 缩略图缓存各尺寸。
    from tools.setup_explorer_thumbnails import EXTENSIONS, PROVIDER, THUMBNAIL, current  # 检查已配置的统一关联。
    output = Path(destination).absolute()  # 与用户视频和程序数据完全分离。
    output.mkdir(parents=True, exist_ok=True)  # 保存实际生成的样例与报告。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 优先验证便携包中的工具。
    if not ffmpeg.is_file():  # 源码环境也只使用隔离开发依赖。
        import imageio_ffmpeg  # 不依赖系统全局工具。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 使用指定环境内 FFmpeg。
    report = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': [], 'codecs': [], 'provider': PROVIDER}  # 保存可追踪执行条件。
    temporary = []  # 记录测试新增的扩展名关联以便结束时撤销。
    def check(name, passed):  # 每一条验收条件都明确记录。
        report['checks'].append({'name': name, 'ok': bool(passed)})  # 不仅记录成功项目。
        if not passed:  # 任意失败立即停止后续验收。
            raise AssertionError(name)  # 不声称所有视频都通过。
    try:  # 无论成功或失败都写出结果。
        valid = all(current('Software\\Classes\\' + suffix + '\\shellex\\' + THUMBNAIL).get('value') == PROVIDER for suffix in EXTENSIONS)  # 检查整个视频类型配置而非个别文件。
        check('36种视频类型已配置统一处理程序', len(EXTENSIONS) == 36 and valid)  # 不靠目录扫描逐文件设置。
        specs = [('h264.mp4', 'libx264', 'yuv420p', []), ('hevc.mkv', 'libx265', 'yuv420p', []), ('mpeg4.avi', 'mpeg4', 'yuv420p', []), ('h264.mov', 'libx264', 'yuv420p', []), ('wmv2.wmv', 'wmv2', 'yuv420p', []), ('vp9.webm', 'libvpx-vp9', 'yuv420p', []), ('hevc10.mp4', 'libx265', 'yuv420p10le', ['-tag:v', 'hvc1']), ('av1.mp4', 'libaom-av1', 'yuv420p', ['-cpu-used', '8']), ('h264.ts', 'libx264', 'yuv420p', [])]  # 真实覆盖原失败编码、十位 HEVC 和 AV1。
        for filename, encoder, pixel_format, extra in specs:  # 每个样例都在新目录中创建，起初没有任何旧缓存。
            sample = output / filename  # 自然生成新的视频文件身份。
            command = [str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25', '-t', '2', '-c:v', encoder, '-threads', '2', '-pix_fmt', pixel_format, *extra, '-y', str(sample)]  # 编码可辨认的彩色视频而非修改扩展名。
            subprocess.run(command, check=True, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)  # 有限等待编码且不弹出控制台。
            result = shell_thumbnail(sample)  # 首次读取用正常按需提取，不先手动强制生成。
            report['codecs'].append({'name': filename, 'encoder': encoder, 'pixel_format': pixel_format, 'normal_shell_result': result})  # 保留每种编码的实际错误码。
            check('新视频自动提取 ' + filename, result['ok'])  # 检验以后新下载视频的正常浏览路径。
        for index, association in enumerate(['MoPlayer.Video', r'Applications\MoPlayer.exe']):  # 模拟两种默认打开关联身份。
            suffix = f'.moplayer-thumbnail-test-{index}'  # 使用独立扩展名，不修改 MP4 等用户默认选择。
            key = 'Software\\Classes\\' + suffix  # 限定测试键位置。
            check('隔离测试关联原先不存在 ' + suffix, not current(key)['exists'])  # 不覆盖用户现有配置。
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:  # 只新增测试用默认类型值。
                winreg.SetValueEx(handle, '', 0, winreg.REG_SZ, association)  # 让测试文件优先选择 MoPlayer 的类型配置。
            temporary.append(key)  # 在任何后续错误时都撤销本次新增值。
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # 让 Shell 看到测试关联。
            sample = output / ('associated' + suffix)  # 文件名称本身不透露用户信息。
            shutil.copyfile(output / 'hevc10.mp4', sample)  # 独立复制拥有新身份的十位 HEVC 视频。
            check('MoPlayer关联保留视频缩略图 ' + association, shell_thumbnail(sample)['ok'])  # 实际证明设为 MoPlayer 后仍取视频画面。
        caches = [regenerate(output / name) for name in ['hevc.mkv', 'vp9.webm', 'av1.mp4']]  # 使用默认隔离提取验证多个缓存尺寸。
        report['cache_results'] = caches  # 保存 96、256、1024 像素的实际结果。
        check('HEVC VP9 AV1隔离缓存全部成功', all(size['ok'] for item in caches for size in item['sizes']))  # 不以进程内诊断模式替代实际 Shell 行为。
        report['success'] = True  # 全部条件成立后才标记验收通过。
    except Exception as error:  # 保留真实失败原因。
        report['success'], report['error'] = False, repr(error)  # 不隐瞒不支持的组合。
    finally:  # 不遗留用户默认打开方式变更。
        for key in temporary:  # 只清理本次新增的默认测试值。
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:  # 不递归删除任何键。
                winreg.DeleteValue(handle, '')  # 空测试键不会影响原有视频类型。
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # 通知测试关联已撤销。
        (output / 'explorer-thumbnail-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 不包含用户视频路径或画面。
    return 0 if report.get('success') else 1  # 以退出码表明是否真正通过。

if __name__ == '__main__':  # 允许源码环境独立运行。
    sys.exit(run(sys.argv[1]))  # 测试目录由调用方明确给出。
