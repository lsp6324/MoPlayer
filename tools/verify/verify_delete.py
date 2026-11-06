import ctypes  # 模拟外部程序持有禁止删除的文件句柄。
import json  # 保存实际 GUI 与回收站验证结果。
import shutil  # 创建独立测试视频实体。
import subprocess  # 生成真实可播放样例。
import threading  # 使用正式扫描取消对象。
import time  # 等待异步文件任务与播放状态。
from pathlib import Path  # 所有样例均放入指定隔离目录。
from PySide6.QtCore import Qt, QThreadPool  # 驱动组合快捷键与等待任务结束。
from PySide6.QtTest import QTest  # 发送真实鼠标和键盘事件。
from PySide6.QtWidgets import QApplication, QLineEdit, QDialog, QCheckBox, QDialogButtonBox
from moplayer.core import scan, Archiver  # 验证正式上下文与多标签归档。

def run(destination, *, recycle=None):  # 默认核对真实回收站；测试可显式注入保留文件的回收器。
    from moplayer.app import Window, BUNDLE  # 使用生产播放器与随包依赖。
    from moplayer.runtime import load_vlc
    vlc = load_vlc()
    output = Path(destination).absolute()  # 明确测试输出边界。
    output.mkdir(parents=True, exist_ok=True)  # 不接触用户视频文件。
    samples = output / 'samples'  # 样例使用独立目录。
    samples.mkdir()  # 重复测试应选择新的输出目录。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 优先测试实际随包解码工具。
    if not ffmpeg.exists():  # 源码模式使用隔离环境依赖。
        import imageio_ffmpeg  # 不调用系统全局工具。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 定位已安装二进制。
    first = samples / '1.mp4'  # 创建第一条真实视频。
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25', '-t', '20', '-c:v', 'libx264', '-threads', '2', '-y', str(first)], check=True, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)  # 生成足够长的播放样例。
    for name in ['2.mp4', '3.mp4', '4.mp4']:  # 独立身份可验证目标选择和自然顺序。
        shutil.copyfile(first, samples / name)  # 只复制测试生成内容。
    application = QApplication.instance() or QApplication([])  # 运行真实 Qt 窗口。
    window = Window(output / 'data')  # 使用完全独立数据库。
    if recycle is not None:
        from moplayer.video_delete import DeletionManager
        window.deleter = DeletionManager(window.store, recycle=recycle)
    # Expected external-lock errors must not block an unattended test on a modal.
    failures = []
    window.fail = lambda error: failures.append(str(error))
    window.show()  # VLC 需要真实原生视频表面。
    checks = []  # 保留逐项验收证据。
    def wait(predicate, seconds=20):  # 持续处理 GUI 事件而不阻塞回调。
        deadline = time.monotonic() + seconds  # 超时会明确失败。
        while time.monotonic() < deadline:  # 等待真实异步条件。
            application.processEvents()  # 交付线程结果和播放器定时器。
            if predicate():  # 成功条件由实际状态决定。
                return True  # 不以固定延迟假装完成。
            QTest.qWait(30)  # 给后台工作和解码器执行时间。
        return False  # 返回明确超时。
    def check(name, result):  # 记录检查并在失败时终止。
        checks.append({'name': name, 'passed': bool(result)})  # 保存可读结果。
        if not result:  # 不继续扩大失败后的文件操作范围。
            raise AssertionError(name)  # 让进程返回失败状态。
    def press():  # 从视频表面发送真实 Ctrl+D。
        if window.has_pending_file_tasks():
            if window.media_menu.active_dialog is not None:
                window.media_menu.active_dialog.reject()
            window.recovery.retry()
            return
        window.player_view.surface.setFocus()  # 避免测试输入框影响后续按键。
        QTest.keyClick(window.player_view.surface, Qt.Key_D, Qt.ControlModifier)  # 经过生产事件过滤器。
        dialog = window.media_menu.active_dialog
        assert dialog is not None
        dialog.findChild(QCheckBox, 'deleteLocalFiles').setChecked(True)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    try:  # 出错仍保存验收结果并安全关闭。
        window.load_folder(str(samples))  # 通过异步导入建立浏览树。
        check('异步导入四条样例', wait(lambda: window.library_controller.browsing is not None))  # 等待完整快照。
        context = window.library_controller.browsing  # 固定原播放上下文。
        vids = [entry[0] for entry in context.folders[str(samples)][1]]  # 记录自然排序身份。
        window.start(context, (str(samples), 0))  # 开始真实 VLC 解码。
        check('首条实际播放', wait(lambda: window.playback.resume is None and window.player.get_time() > 500))  # 确认正在读取目标文件。
        edit = QLineEdit(window)  # 创建文本输入接收者。
        edit.show()  # 确保可以获取焦点。
        edit.setFocus()  # 模拟用户编辑文字。
        QTest.keyClick(edit, Qt.Key_D, Qt.ControlModifier)  # 文本组合键不应删除媒体。
        check('文本输入不触发删除', first.exists() and not window.busy)  # 文件保持存在。
        edit.hide()  # 恢复正常播放器焦点。
        dialog = QDialog(window)  # 使用真实模态弹窗。
        dialog.setModal(True)  # 赋予弹窗快捷键优先级。
        dialog.show()  # 不进入嵌套阻塞循环。
        application.processEvents()  # 让 Qt 发布活动模态窗口。
        QTest.keyClick(dialog, Qt.Key_D, Qt.ControlModifier)  # 弹窗期间不能删除视频。
        check('模态弹窗不触发删除', first.exists() and not window.busy)  # 防止后台危险快捷键。
        dialog.close()  # 关闭测试弹窗。
        application.processEvents()  # 清除模态状态。
        replacement = output / 'other'  # 模拟更换左侧浏览目录。
        replacement.mkdir()  # 与播放上下文完全分离。
        window.load_folder(str(replacement))  # 导入空浏览目录。
        check('替换浏览目录保留播放', wait(lambda: window.library_controller.browsing.root == str(replacement)) and window.context is context)  # 不用新目录寻找下一条。
        window.store.execute('UPDATE videos SET star=1 WHERE id=?', (vids[0],))  # 验证删除同步移除收藏。
        kernel = ctypes.windll.kernel32  # 使用实际 Windows 文件共享限制模拟外部占用。
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]  # 正确声明六十四位句柄参数。
        kernel.CreateFileW.restype = ctypes.c_void_p  # 防止句柄被截断。
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]  # 正确释放真实占用句柄。
        handle = kernel.CreateFileW(str(first), 0x80000000, 3, None, 3, 0, None)  # 允许读写共享但明确禁止删除共享。
        check('外部占用句柄建立', handle not in (None, ctypes.c_void_p(-1).value))  # 不用模拟异常代替真实占用。
        try:  # 即使断言失败也释放测试句柄。
            press()  # 当前 VLC 可释放但外部占用仍应阻止删除。
            check('外部占用失败不换片且保留数据', wait(lambda: not window.busy) and first.exists() and window.current == vids[0] and bool(window.store.query('SELECT error FROM deletion_jobs WHERE error IS NOT NULL')))  # 不提前删除数据库。
        finally:  # 不给后续测试留下人为文件锁。
            kernel.CloseHandle(handle)  # 解除外部占用后允许重试。
        press()  # 删除正在播放的第一条。
        check('播放占用释放并回收原文件', wait(lambda: not window.busy and window.current == vids[1]) and not first.exists())  # 下一条来自原上下文。
        check('下一条真正解码播放', wait(lambda: window.playback.resume is None and window.player.get_time() > 500))  # 不只检查当前 ID。
        check('删除身份历史收藏同步清理', not window.store.query('SELECT * FROM videos WHERE id=?', (vids[0],)))  # 无失效收藏记录。
        check('删除不改变原播放上下文', window.context is context and window.library_controller.browsing.root == str(replacement))  # 浏览与播放继续独立。
        window.load_folder(str(samples))  # 重新显示剩余视频以测试单击选择。
        check('剩余目录加载完成', wait(lambda: window.library_controller.browsing.root == str(samples)))  # 等待异步模型。
        selected = window.library_view.files.model().index(1, 0)  # 当前顺序为二、三、四，选择第三条。
        window.library_view.files.scrollTo(selected)  # 保证鼠标目标可见。
        application.processEvents()  # 刷新可见位置。
        QTest.mouseClick(window.library_view.files.viewport(), Qt.LeftButton, Qt.NoModifier, window.library_view.files.visualRect(selected).center())  # 真实鼠标单击选择第三条。
        press()  # 选中优先于当前播放的第二条。
        check('单击选择优先且删除后播放其下一条', wait(lambda: not window.busy and window.current == vids[3]) and not (samples / '3.mp4').exists() and (samples / '2.mp4').exists())  # 不误删正在播放的其他视频。
        check('第四条实际播放', wait(lambda: window.playback.resume is None and window.player.get_time() > 500))  # 确认自动开始解码。
        archive = Archiver(window.store, output / 'archive')  # 仅使用隔离归档根目录。
        window.player.stop()  # 归档前安全释放测试文件。
        window.player.set_media(None)  # 清除原媒体引用。
        archive.submit(vids[3], 8, ['甲', '乙'])  # 创建真实多标签硬链接。
        paths = [Path(row['path']) for row in window.store.query('SELECT path FROM paths WHERE id=?', (vids[3],)) if Path(row['path']).exists()]  # 收集当前有效入口。
        window.play_path(window.store.resolve(vids[3]), 0, False)  # 从归档入口继续实际播放。
        check('多标签视频实际播放', wait(lambda: window.playback.resume is None and window.player.get_time() > 300))  # 确认归档文件占用场景。
        press()  # 删除原上下文最后一条。
        check('全部标签入口回收且末尾停止', wait(lambda: not window.busy and window.current is None) and all(not path.exists() for path in paths))  # 没有下一条时不循环。
        window.grab().save(str(output / 'after-delete.png'))  # 保存实际删除后的界面状态。
    finally:  # 不论验收结果如何释放所有测试句柄。
        wait(lambda: not window.busy)  # 等待文件任务达到安全状态。
        window.close()  # 保存仅限测试数据的进度。
        QThreadPool.globalInstance().waitForDone()  # 防止退出时工作线程仍访问 Qt。
        window.thumbnails.pool.waitForDone()  # 等待取消的缩略图任务结束。
        (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 输出真实检查结果。
    return 0  # 全部断言成功后才报告通过。
