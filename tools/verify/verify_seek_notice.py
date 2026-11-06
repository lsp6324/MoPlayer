import json  # 记录本次跳转提示的专项结果。
import subprocess  # 生成一段不含用户内容的测试视频。
import sys  # 读取隔离证据目录。
import time  # 对异步解码和提示隐藏设置有限等待。
from pathlib import Path  # 全部样例在指定目录内生成。
from PySide6.QtCore import Qt, QThreadPool, QPoint  # 等待相关后台线程安全结束。
from PySide6.QtTest import QTest  # 按真实 A/D 键验证正式跳转入口。
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLineEdit, QWidget  # 检查输入框不误触提示。
from moplayer.gui.seek_notice import notice_text  # 核对用户要求的两行格式。

def run(destination):  # 只验证跳转提示，不运行完整回归。
    from moplayer.app import Window, BUNDLE  # 使用实际便携播放内核和正式窗口。
    from moplayer.runtime import load_vlc
    vlc = load_vlc()
    output = Path(destination).absolute()  # 不读写用户视频或数据库。
    output.mkdir(parents=True, exist_ok=True)  # 保存隔离样例和截图。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 优先使用便携版内置工具。
    if not ffmpeg.exists():  # 源码运行使用已隔离安装的工具。
        import imageio_ffmpeg  # 不下载或安装新依赖。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 取得现有 FFmpeg。
    sample = output / 'minute.mp4'  # 一分钟样例可精确核对示例百分比。
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x263347:s=1280x720:r=25', '-t', '60', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-y', str(sample)], check=True, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)  # 快速生成纯色真实视频。
    low_resolution = output / 'low-resolution.mp4'
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=0x263347:s=160x90:r=25', '-t', '60', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-threads', '2', '-y', str(low_resolution)],
        check=True, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    app = QApplication.instance() or QApplication([])  # 使用真实 Qt 事件循环。
    window = Window(output / 'data')  # 与用户数据库隔离。
    window.show()  # 提供实际 VLC 原生视频输出区域。
    window.activateWindow()
    checks = []  # 仅记录本次执行的专项。
    def check(name, passed):  # 失败即停止，不误报成功。
        checks.append({'name': name, 'passed': bool(passed)})  # 保留可核对结果。
        assert passed, name  # 明确指出失败环节。
    def wait(predicate, seconds=6):  # 等待实际状态而非使用长固定延迟。
        deadline = time.monotonic() + seconds  # 所有等待有上限。
        while time.monotonic() < deadline:  # 继续处理实际视频解码和 Qt 回调。
            app.processEvents()  # 更新播放恢复和提示计时器。
            if predicate():  # 检查真正的目标条件。
                return True  # 满足后立即继续。
            QTest.qWait(20)  # 给 VLC 解码线程短暂运行时间。
        return False  # 超时不能视作通过。
    def text():
        return window.player_view.seek_notice.text()
    def centered():
        panel = window.player_view.seek_notice.overlay
        center = window.player_view.surface.mapToGlobal(window.player_view.surface.rect().center())
        return (abs(panel.geometry().center().x() - center.x()) <= 1 and
                panel.geometry().center().y() < center.y())
    try:  # 任意失败也释放真实播放器。
        check('两行格式与百分比符合示例', notice_text(5000, 10000, 60000) == '00:05→00:10(01:00)\n16.7%')  # 不显示多余小时或文案。
        window.current = window.store.register(sample)  # 绑定当前播放视频身份。
        window.play_path(sample, 0, False)  # 先完成解码准备，再固定跳转起点。
        assert wait(lambda: window.playback.resume is None and window.player.get_state() == vlc.State.Playing)  # 等待内核进入真实播放状态。
        window.player.set_pause(1)  # 在开始本次跳转检查前暂停。
        assert wait(lambda: window.player.get_state() == vlc.State.Paused)  # VLC 暂停命令异步确认后再设置位置。
        window.set_playback_position(5000, window.player.get_length())  # 精确固定在用户示例的五秒位置。
        check('真实视频准备完成', wait(lambda: abs(window.player.get_time() - 5000) < 100))  # 不把异步暂停期间推进的时间当作提示错误。
        QTest.keyClick(window.player_view.surface, Qt.Key_D)  # 从五秒按 D 跳到十秒。
        check('D键跳转后显示居中偏上两行浮层', wait(lambda: abs(window.player.get_time() - 10000) < 100) and text() == '00:05→00:10(01:00)\n16.7%' and window.player_view.seek_notice.overlay.isVisible() and centered())
        panel = window.player_view.seek_notice.overlay
        panel.grab().save(str(output / 'seek-notice-windowed.png'))
        original_size, original_font = panel.size(), panel.time_label.font()
        check('浮层不抢焦点且内核文字层保持关闭', window.isActiveWindow() and window.player.video_get_marquee_int(vlc.VideoMarqueeOption.Enable) == 0)
        import ctypes
        user = ctypes.WinDLL('user32')
        user.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.GetWindow.restype = ctypes.c_void_p
        style = user.GetWindowLongPtrW(int(panel.winId()), -20)
        check('Windows浮层透明合成且鼠标穿透并归播放器拥有',
              bool(style & 0x80000) and bool(style & 0x20) and bool(style & 0x8000000) and
              not bool(style & 8) and user.GetWindow(int(panel.winId()), 4) == int(window.winId()))
        image = panel.grab().toImage()
        extent = round(14 * image.devicePixelRatio())
        alpha = {image.pixelColor(x, y).alpha() for x in range(extent) for y in range(extent)}
        check('提示圆角按像素透明且有抗锯齿过渡', image.pixelColor(0, 0).alpha() == 0 and len([a for a in alpha if 0 < a < 255]) >= 4)
        window.resize(1100, 760)
        QTest.qWait(30)
        check('窗口缩放后仍居中且字号尺寸不变', panel.isVisible() and centered() and panel.size() == original_size and panel.time_label.font() == original_font)
        window.splitter.setSizes([460, 640])
        QTest.qWait(30)
        check('调整列表宽度后跟随播放区域重新居中', panel.isVisible() and centered())
        original_position = panel.pos()
        window.move(window.pos() + QPoint(20, 15))
        QTest.qWait(30)
        check('移动窗口后提示同步移动', panel.isVisible() and panel.pos() == original_position + QPoint(20, 15))
        QTest.qWait(150)  # 保持短暂停顿，验证隐藏计时独立于播放状态。
        check('暂停时提示也会按时隐藏', wait(lambda: not panel.isVisible(), 3) and window.player.get_state() == vlc.State.Paused)
        QTest.keyClick(window.player_view.surface, Qt.Key_A)  # 后退同样显示前后进度。
        check('A键后退提示百分比正确', wait(lambda: abs(window.player.get_time() - 5000) < 100) and text() == '00:10→00:05(01:00)\n8.3%')
        window.set_playback_position(2000, window.player.get_length())  # 准备后退到开头的边界。
        check('边界准备完成', wait(lambda: abs(window.player.get_time() - 2000) < 100))  # 等待实际定位完成。
        QTest.keyClick(window.player_view.surface, Qt.Key_Left)  # 后退五秒需要截断到零。
        check('边界显示实际零秒和零百分比', wait(lambda: window.player.get_time() == 0) and text() == '00:02→00:00(01:00)\n0.0%')
        window.set_playback_position(5000, window.player.get_length())  # 全屏也从明确的五秒开始。
        assert wait(lambda: abs(window.player.get_time() - 5000) < 100)  # 不接受尚未完成的异步定位。
        window.player_view.fullscreen.toggle()  # 使用正式视频全屏布局。
        app.processEvents()  # 稳定全屏窗口几何。
        QTest.keyClick(window.player_view.surface, Qt.Key_Right)  # 方向键与 D 共用提示。
        check('全屏方向键也显示居中偏上浮层', wait(lambda: abs(window.player.get_time() - 10000) < 100) and text().startswith('00:05→00:10(01:00)') and panel.isVisible() and centered())
        panel.grab().save(str(output / 'seek-notice-fullscreen.png'))
        QTest.qWait(150)  # 等待原生合成画面更新。
        modal = QDialog(window)  # 输入弹窗必须优先处理字母。
        entry = QLineEdit(modal)  # 使用真正的文本输入控件。
        QVBoxLayout(modal).addWidget(entry)  # 输入框在弹窗内可见。
        modal.setModal(True)  # 使用正式模态优先规则。
        modal.show()  # 提供真实输入目标。
        previous = text()  # 保存当前提示，输入时不应改动。
        QTest.keyClick(entry, Qt.Key_D)  # D 应只进入文本框。
        check('输入文字不误触跳转提示', entry.text() == 'd' and text() == previous and abs(window.player.get_time() - 10000) < 100)  # 保留既有输入保护。
        modal.reject()  # 关闭测试输入窗口。
        window.player_view.fullscreen.exit()  # 恢复窗口布局后检查重载清理。
        window.play_path(sample, 0, True)  # 模拟换片或安全重载。
        check('重载清除上一条提示', text() == '' and not panel.isVisible())
        window.current = window.store.register(low_resolution)
        window.play_path(low_resolution, 5000, True)
        check('低分辨率视频解码并暂停', wait(lambda: window.playback.resume is None and window.player.get_state() == vlc.State.Paused and window.player.video_get_size(0) == (160, 90)))
        window.set_playback_position(5000, window.player.get_length())
        assert wait(lambda: abs(window.player.get_time() - 5000) < 100)
        QTest.keyClick(window.player_view.surface, Qt.Key_D)
        check('低分辨率视频浮层与高清样例字号尺寸相同',
              wait(lambda: abs(window.player.get_time() - 10000) < 100) and
              panel.isVisible() and text() == '00:05→00:10(01:00)\n16.7%' and
              panel.size() == original_size and panel.time_label.font() == original_font)
        panel.grab().save(str(output / 'seek-notice-low-resolution.png'))
        other = QWidget()
        other.resize(300, 200)
        other.show()
        other.activateWindow()
        check('切换到其他窗口后提示隐藏', wait(lambda: other.isActiveWindow() and not panel.isVisible()))
        other.close()
        window.activateWindow()
        assert wait(window.isActiveWindow)
        window.player_view.seek_notice.show(5000, 10000, 60000)
        window.showMinimized()
        check('最小化后提示隐藏', wait(lambda: not panel.isVisible()))
    finally:  # 保证测试不遗留播放器和后台线程。
        window.close()  # 只保存隔离数据。
        QThreadPool.globalInstance().waitForDone()  # 释放扫描或其他后台任务。
        window.thumbnails.pool.waitForDone()  # 缩略图线程池安全结束。
        window.store.db.close()  # 关闭隔离数据库。
    (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 保存本轮真实结果。
    print(f'跳转提示专项：{len(checks)}/{len(checks)} 通过')  # 不宣称运行完整测试。

if __name__ == '__main__':  # 仅在显式指定时执行该专项。
    run(sys.argv[1])  # 样例和证据目录由调用者明确传入。
