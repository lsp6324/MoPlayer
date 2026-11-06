import ctypes  # 调用 Windows Shell 缩略图接口。
import json  # 保存机器可读测试证据。
import os  # 读取实际运行环境。
import subprocess  # 生成真实编码样例。
import sys  # 支持独立诊断入口。
import threading  # 构造扫描信号。
import time  # 等待异步播放状态。
from pathlib import Path  # 管理隔离测试输出。
from ctypes import wintypes  # 声明 Windows 接口参数。
from PySide6.QtCore import Qt, QTimer, QMimeData, QUrl, QPoint, QPointF  # 运行 Qt 事件和真实目录拖放数据。
from PySide6.QtTest import QTest  # 使用真实 Qt 键盘事件验收快捷键。
from PySide6.QtWidgets import QApplication, QDialog, QComboBox, QLineEdit, QPushButton, QListWidget, QSplitter  # 查找测试窗口中的输入、列表与左右分隔控件。
from moplayer.core import scan, Archiver, identity  # 调用实际扫描和归档实现。

def shell_thumbnail(path):  # 调用资源管理器所用的 Shell 图像工厂验证真实缩略图支持。
    class GUID(ctypes.Structure):  # 表示 Windows COM 接口标识。
        _fields_ = [('a', ctypes.c_ulong), ('b', ctypes.c_ushort), ('c', ctypes.c_ushort), ('d', ctypes.c_ubyte * 8)]  # 使用 Windows GUID 布局。
    class SIZE(ctypes.Structure):  # 传递请求缩略图尺寸。
        _fields_ = [('cx', ctypes.c_long), ('cy', ctypes.c_long)]  # Windows SIZE 按值传递。
    ctypes.windll.ole32.CoInitialize(None)  # 为当前线程初始化 COM。
    guid = GUID()  # 创建接口标识缓冲。
    ctypes.windll.ole32.CLSIDFromString('{bcc18b79-ba16-442f-80c4-8a59c30c463b}', ctypes.byref(guid))  # 指定 IShellItemImageFactory。
    factory = ctypes.c_void_p()  # 接收 Shell COM 对象指针。
    shell = ctypes.windll.shell32  # 使用系统内置 Shell 组件。
    shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]  # 防止 64 位参数被截断。
    shell.SHCreateItemFromParsingName.restype = ctypes.c_long  # HRESULT 是有符号 32 位值。
    result = shell.SHCreateItemFromParsingName(str(path), None, ctypes.byref(guid), ctypes.byref(factory))  # 根据实际视频入口创建对象。
    if result < 0:  # 对象创建失败说明系统无法处理该路径。
        return {'ok': False, 'hresult': hex(result & 0xffffffff)}  # 保存真实系统错误码。
    table = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents  # 读取 COM 虚函数表。
    get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(table[3])  # 绑定 GetImage 方法。
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])  # 绑定 IUnknown.Release。
    bitmap = ctypes.c_void_p()  # 接收系统生成的 HBITMAP。
    result = get_image(factory, SIZE(256, 256), 0x08, ctypes.byref(bitmap))  # THUMBNAILONLY 禁止返回图标冒充视频缩略图。
    answer = {'ok': result >= 0 and bool(bitmap.value), 'hresult': hex(result & 0xffffffff), 'thumbnail_only': True}  # 如实记录系统支持结果。
    if bitmap.value:  # 成功时释放系统图像句柄。
        ctypes.windll.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]  # 保留完整 64 位位图句柄。
        ctypes.windll.gdi32.DeleteObject(bitmap)  # 避免测试造成 GDI 泄漏。
    release(factory)  # 释放 Shell COM 对象。
    ctypes.windll.ole32.CoUninitialize()  # 配对结束 COM 初始化。
    return answer  # 证据单独区别于 VLC 解码结果。

def run(destination):  # 执行源码与便携版共用的实际验收。
    from moplayer.app import Window, BUNDLE  # 在应用已配置运行库路径后导入。
    from moplayer.runtime import load_vlc
    vlc = load_vlc()
    output = Path(destination).absolute()  # 将全部测试数据放到指定隔离目录。
    output.mkdir(parents=True, exist_ok=True)  # 创建测试输出位置。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 优先验证随包的解码工具。
    if not ffmpeg.exists():  # 源码测试使用隔离环境工具。
        import imageio_ffmpeg  # 不向系统安装 FFmpeg。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 获取已下载的独立二进制。
    report = {'python': sys.version, 'frozen': bool(getattr(sys, 'frozen', False)), 'vlc': vlc.libvlc_get_version().decode(), 'checks': [], 'codecs': {}, 'shell_thumbnails': {}}  # 汇总实际运行证据。
    app = QApplication.instance() or QApplication([])  # 创建真实 GUI 事件循环。
    window = Window(output / 'data')  # 用隔离数据目录运行完整应用。
    window.archiver = Archiver(window.store, output / 'archive')  # 测试归档不触碰用户的视频。
    from moplayer.tag_migration import TagMigration  # 全局分类批次也必须使用隔离测试归档器。
    window.tag_migration = TagMigration(window.store, window.archiver)  # 禁止测试标签流程触及真实用户归档根目录。
    window.show()  # 实际显示并渲染窗口。
    def wait_until(predicate, seconds=12):  # 有限等待异步操作完成。
        deadline = time.monotonic() + seconds  # 设置超时避免测试挂起。
        while time.monotonic() < deadline:  # 在截止前处理 Qt 事件。
            app.processEvents()  # 允许后台信号和播放器刷新。
            if predicate():  # 检查实际状态而非固定睡眠猜测。
                return True  # 成功后立即继续。
            QTest.qWait(40)  # 短暂让出主线程。
        return False  # 超时由断言报告失败。
    def check(name, condition):  # 记录每项明确验收结果。
        report['checks'].append({'name': name, 'ok': bool(condition)})  # 保存通过和失败状态。
        if not condition:  # 失败立即保留当前现场。
            raise AssertionError(name)  # 不将失败项目报告为成功。
    def auto_rating(score):  # 自动响应标签全部应用后才出现的评分弹窗。
        completed = []  # 调用方同时等待评分提交与文件任务完成。
        deadline = time.monotonic() + 30  # 防止测试辅助逻辑无限轮询。
        def poll():  # 等待真正出现的新评分界面。
            dialog = QApplication.activeModalWidget()  # 不在标签弹窗未关闭时误点评分。
            from moplayer.gui.score_editor import ScoreEditor  # 通过真实弹窗类型确认操作对象。
            if isinstance(dialog, ScoreEditor):  # 只有标签彻底完成才会进入这里。
                completed.append(True)  # 记录确实自动出现评分界面。
                dialog.choose(score)  # 使用同一个评分提交入口适配五颗心界面。
            elif time.monotonic() < deadline:  # 文件任务尚未结束时继续处理 Qt 事件。
                QTimer.singleShot(30, poll)  # 不阻塞主事件循环。
        QTimer.singleShot(30, poll)  # 与真实标签确认流程并行等待。
        return completed  # 用于断言自动评分实际发生。
    try:  # 任意失败均写出报告与截图。
        check('启动不恢复目录和播放', window.current is None and window.library_controller.browsing is None)  # 验证启动规则。
        specs = [('h264.mp4', 'libx264', 'aac'), ('hevc.mkv', 'libx265', 'ac3'), ('mpeg4.avi', 'mpeg4', 'libmp3lame'), ('h264.mov', 'libx264', 'aac'), ('wmv2.wmv', 'wmv2', 'wmav2'), ('vp9.webm', 'libvpx-vp9', 'libopus')]  # 每种容器绑定实际测试的视频和音频编码。
        for filename, codec, audio_codec in specs:  # 逐个生成真实可解码样例。
            sample = output / 'samples' / filename  # 将生成文件集中存放。
            sample.parent.mkdir(exist_ok=True)  # 确保样例目录存在。
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '4', '-c:v', codec, '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', audio_codec, '-y', str(sample)], check=True, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)  # 生成四秒真实编码音视频。
            context, errors = scan(sample.parent, window.store, threading.Event())  # 使用实际扫描映射样例身份。
            index = next(i for i, (_, name) in enumerate(context.folders[str(sample.parent)][1]) if name == filename)  # 找到当前样例的逻辑位置。
            window.start(context, (str(sample.parent), index))  # 通过正式播放入口打开视频。
            ok = wait_until(lambda: window.player.get_time() > 300 and window.player.video_get_size(0)[0] > 0)  # 验证视频尺寸和时间推进，不仅验证扩展名。
            capture = output / (filename + '.png')  # 保存 VLC 真实解码帧证据。
            snapshot_result = window.player.video_take_snapshot(0, str(capture), 320, 180)  # 从播放内核提取帧而非截取黑色视频窗口。
            has_frame = snapshot_result == 0 and wait_until(lambda: capture.exists() and capture.stat().st_size > 1000)  # 确认真实图像输出。
            report['codecs'][filename] = {'codec': codec, 'audio_codec': audio_codec, 'audio_tracks': window.player.audio_get_track_count(), 'decoded': ok, 'frame_saved': has_frame, 'size': list(window.player.video_get_size(0)), 'time_ms': window.player.get_time()}  # 保存实际解码帧和音轨识别证据。
            check('解码 ' + filename, ok)  # 确认当前编码成功解码。
            check('视频帧与音轨 ' + filename, has_frame and window.player.audio_get_track_count() > 0)  # 避免仅依据时钟推进声称解码成功。
            window.player.stop()  # 释放样例供 Shell 读取。
            report['shell_thumbnails'][filename] = shell_thumbnail(sample)  # 单独验证系统实际缩略图支持。
        source = output / 'sequence'  # 创建顺序与归档测试目录。
        (source / '第1组').mkdir(parents=True, exist_ok=True)  # 第一组包含多个视频。
        (source / '第2组').mkdir(exist_ok=True)  # 第二组提供跨目录目标。
        import shutil  # 为播放测试复制小型样例文件。
        for relative in ['第1组/第2集.mp4', '第1组/第10集.mp4', '第2组/第1集.mp4']:  # 建立自然排序样例。
            shutil.copyfile(output / 'samples/h264.mp4', source / relative)  # 每个样例拥有独立视频身份。
        from PySide6.QtGui import QDragEnterEvent, QDropEvent  # 使用 Qt 实际拖放事件验收目录入口。
        mime = QMimeData()  # 构造来自文件管理器的本地 URL 数据。
        mime.setUrls([QUrl.fromLocalFile(str(source))])  # 每次仅拖入一个根文件夹。
        drag_event = QDragEnterEvent(QPoint(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)  # 模拟进入左侧目录区域。
        app.sendEvent(window.library_view.files.viewport(), drag_event)  # 经 Qt 事件分发而非直接调用导入函数。
        check('左侧接受文件夹拖放', drag_event.isAccepted())  # 验证实际拖放过滤规则。
        drop_event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)  # 构造实际释放事件。
        app.sendEvent(window.library_view.files.viewport(), drop_event)  # 触发左侧导入信号和异步扫描。
        check('异步目录加载', wait_until(lambda: window.library_controller.browsing and window.library_controller.browsing.root == str(source)))  # 等待实际发布目录树。
        context = window.library_controller.browsing  # 保存原始浏览快照。
        folder = str(source / '第1组')  # 选择第一组视频。
        window.library_view.browse_folder(folder)
        video_index = window.library_view.files.model().index(0, 0)
        window.library_view.files.doubleClicked.emit(video_index)  # 触发实际双击信号连接。
        check('双击播放接线', wait_until(lambda: window.player.get_time() > 300))  # 验证右侧开始播放。
        original = window.current  # 保存当前视频身份。
        window.load_folder(str(output / 'samples'))  # 播放时替换浏览目录。
        check('替换浏览保留播放上下文', wait_until(lambda: window.library_controller.browsing.root == str(output / 'samples')) and window.context is context and window.current == original)  # 确认浏览与播放分离。
        QTest.keyClick(window.player_view.surface, Qt.Key_Space)  # 发送真实空格事件。
        check('空格暂停', wait_until(lambda: window.player.get_state() == vlc.State.Paused))  # 验证暂停响应。
        QTest.keyClick(window.player_view.surface, Qt.Key_Left)  # 从短视频当前位置后退五秒。
        check('后退夹紧零点', wait_until(lambda: window.player.get_time() == 0))  # 不允许负播放位置。
        QTest.keyClick(window.player_view.surface, Qt.Key_Right)  # 从零点向前五秒超过样例时长。
        check('快进不超过时长', wait_until(lambda: 3900 <= window.player.get_time() <= window.player.get_length()))  # 夹紧总时长边界。
        QTest.keyClick(window.player_view.surface, Qt.Key_A)  # A 与左方向键一样后退五秒。
        check('A 后退夹紧零点', wait_until(lambda: window.player.get_time() == 0))  # 真正验证 VLC 播放进度。
        QTest.keyClick(window.player_view.surface, Qt.Key_D)  # D 与右方向键一样快进五秒。
        check('D 快进不超过时长', wait_until(lambda: 3900 <= window.player.get_time() <= window.player.get_length()))  # 新键同样不能越界。
        window.player.set_time(500)  # 将暂停位置恢复到可继续验收的范围。
        original_handle, original_geometry = int(window.player_view.surface.winId()), window.geometry()  # 保存视频原生句柄与普通窗口几何。
        original_sizes = window.canvas.findChild(QSplitter).sizes()  # 记录用户工作区比例。
        QTest.keyClick(window.player_view.surface, Qt.Key_Return)  # 发送 Enter 全屏。
        app.processEvents()  # 等待全屏窗口与原生视频重新布局。
        check('仅视频全屏隐藏目录', window.isFullScreen() and not window.library_view.files.isVisible() and window.player_view.surface.isVisible())  # 按用户修订要求隐藏目录。
        check('全屏画面铺满窗口', window.player_view.surface.width() >= window.width() - 2 and window.player_view.surface.height() >= window.height() - 2)  # 不保留卡片留白和其他应用区域。
        check('全屏保留视频句柄和暂停状态', int(window.player_view.surface.winId()) == original_handle and window.player.get_state() == vlc.State.Paused and window.context is context and window.current == original)  # 不重载或改变播放身份。
        QTest.keyClick(window.player_view.surface, Qt.Key_A)  # 视频全屏仍接受 A 后退。
        check('全屏 A 后退有效', wait_until(lambda: window.player.get_time() == 0))  # 不依赖目录视图焦点。
        QTest.keyClick(window.player_view.surface, Qt.Key_D)  # 视频全屏仍接受 D 快进。
        check('全屏 D 快进有效', wait_until(lambda: 3900 <= window.player.get_time() <= window.player.get_length()))  # 全屏使用相同有效时长边界。
        window.player.set_time(500)  # 保持后续暂停状态和归档回归的有效起点。
        from PySide6.QtGui import QCursor  # 使用真实系统指针验证原生视频上的活动检测。
        window.activateWindow()  # 让播放器拥有浮动控制栏的显示条件。
        app.processEvents()  # 处理主窗口激活。
        saved_cursor = QCursor.pos()  # 保存指针位置，测试完成后恢复。
        QCursor.setPos(window.player_view.surface.mapToGlobal(QPoint(window.player_view.surface.width() // 2, window.player_view.surface.height() // 2)))  # 空闲隐藏测试需先将指针放在视频中间，不能停留在本应保持显示的控制栏上。
        app.processEvents()  # 交付本次可控指针位置变化。
        window.player_view.fullscreen.last_cursor = QCursor.pos()  # 固定测试起点，不把上一次移动算成新活动。
        window.player_view.fullscreen.last_activity = time.monotonic() - 3  # 模拟已超过两点五秒的鼠标空闲。
        window.player_view.fullscreen.poll()  # 执行生产自动隐藏逻辑。
        check('全屏控制栏空闲隐藏', not window.player_view.fullscreen.overlay.isVisible())  # 观看时仅显示画面。
        window.player_view.fullscreen.last_cursor -= QPoint(1, 0)  # 模拟下一轮真实指针位置与记录位置不同。
        window.player_view.fullscreen.poll()  # 执行生产鼠标移动检测。
        check('鼠标活动显示全屏控制栏', window.player_view.fullscreen.overlay.isVisible())  # 原生视频不必转发 Qt MouseMove 事件。
        QCursor.setPos(saved_cursor)  # 不改变用户完成验收后的原指针位置。
        window.grab().save(str(output / 'video-fullscreen.png'))  # 保存只有视频区域的实际布局证据。
        window.player_view.fullscreen.overlay.grab().save(str(output / 'fullscreen-controls.png'))  # 单独保存覆盖原生视频的浮层截图。
        fullscreen_modal = QDialog(window)  # 验证全屏期间弹窗优先级。
        fullscreen_modal.setModal(True)  # 模拟 Q/R 弹窗的模态输入规则。
        fullscreen_modal.show()  # 显示真实 Qt 弹窗。
        app.processEvents()  # 应用模态状态。
        window.player_view.fullscreen.poll()  # 全屏浮层遇到弹窗应避让。
        check('全屏弹窗隐藏浮层', not window.player_view.fullscreen.overlay.isVisible())  # 不遮挡标签或评分输入。
        QTest.keyClick(fullscreen_modal, Qt.Key_Escape)  # 第一次 Esc 应关闭弹窗。
        app.processEvents()  # 处理弹窗关闭。
        check('Esc 优先关闭弹窗保留全屏', not fullscreen_modal.isVisible() and window.isFullScreen())  # 不让同一个 Esc 同时退出两层状态。
        QTest.keyClick(window.player_view.surface, Qt.Key_Escape)  # 发送 Esc 退出全屏。
        app.processEvents()  # 等待普通布局恢复。
        check('Esc 退出并恢复目录和控制栏', not window.isFullScreen() and window.library_view.files.isVisible() and window.player_view.playback_panel.parentWidget() is window.player_view.surface.parentWidget())  # 恢复同一套工作控件。
        check('退出全屏恢复窗口大小与目录比例', window.geometry() == original_geometry and window.player_view.fullscreen.splitter.sizes() == original_sizes)  # 不丢失用户进入前布局。
        QTest.mouseClick(window.player_view.fullscreen_button, Qt.LeftButton)  # 验证可见按钮与 Enter 使用同一实现。
        app.processEvents()  # 应用按钮进入全屏。
        check('全屏按钮进入视频模式', window.isFullScreen() and not window.library_view.files.isVisible())  # 不仅验证快捷键。
        QTest.keyClick(window.player_view.surface, Qt.Key_Return)  # 再按 Enter 应退出全屏。
        app.processEvents()  # 应用恢复布局。
        check('Enter 再次退出全屏', not window.isFullScreen() and window.library_view.files.isVisible())  # 支持直接切换而非只进不出。
        QTest.keyClick(window.player_view.surface, Qt.Key_W)  # 收藏当前视频。
        QTest.keyClick(window.player_view.surface, Qt.Key_W)  # 重复收藏不新增身份。
        check('W 幂等收藏', len(window.store.query('SELECT * FROM videos WHERE star=1')) == 1)  # 只有一条收藏。
        modal = QDialog(window)  # 构造真实输入弹窗。
        entry = QLineEdit(modal)  # 使用实际文本输入控件。
        modal.setModal(True)  # 激活弹窗优先级。
        modal.show()  # 显示弹窗。
        entry.setFocus()  # 输入焦点在文本框。
        app.processEvents()  # 应用模态和焦点变更。
        input_position = window.player.get_time()  # 保存暂停视频进度以检查 A/D 不误触。
        QTest.keyClicks(entry, 'x z q r w a d ')  # 输入原有字母、A/D 和空格。
        check('文本输入不误触', entry.text() == 'x z q r w a d ' and window.current == original and window.player.get_time() == input_position)  # 字母只输入文字，不改变播放进度。
        QTest.keyClick(entry, Qt.Key_Escape)  # Esc 应优先关闭弹窗。
        app.processEvents()  # 处理弹窗关闭事件。
        check('Esc 关闭弹窗', not modal.isVisible())  # 验证模态优先规则。
        def rate_zero():  # 自动选择零分并明确确认。
            dialog = QApplication.activeModalWidget()  # 定位当前评分弹窗。
            dialog.findChild(QPushButton, 'score_0').click()  # 点击独立零分按钮，验证不再依赖下拉框。
        QTimer.singleShot(100, rate_zero)  # 在评分弹窗进入事件循环后操作。
        QTest.keyClick(window.player_view.surface, Qt.Key_R)  # 通过真实 R 快捷键打开评分界面。
        check('评分零分且未归档不移动', window.store.video(original)['score'] == 0 and not window.store.video(original)['archived'])  # 与未评分状态区别。
        window.store.execute('UPDATE videos SET score=8 WHERE id=?', (original,))  # 为标签确认准备已有评分。
        def choose_tags():  # 通过真实标签弹窗新增并勾选两个标签。
            dialog = QApplication.activeModalWidget()  # 定位 Q 打开的弹窗。
            text = dialog.entry  # 新界面明确区分搜索框与新增输入框。
            add = dialog.add_button  # 定位胶囊界面底部的新增加号。
            for tag in ['测试甲', '测试乙']:  # 模拟批量添加标签。
                text.setText(tag)  # 输入本次自定义标签。
                add.click()  # 新增只改变弹窗状态。
            check('Q 确认前不移动文件', not window.store.video(original)['archived'] and (source / '第1组/第2集.mp4').exists())  # 勾选不应立即归档。
            dialog.accept()  # 明确确认后才提交归档。
        QTimer.singleShot(100, choose_tags)  # 等待标签弹窗打开后操作。
        first_rating = auto_rating(8)  # 标签完成后通过五颗心界面直接选择八分。
        QTest.keyClick(window.player_view.surface, Qt.Key_Q)  # 使用真实 Q 快捷键启动标签流程。
        check('播放中归档并自动评分成功', wait_until(lambda: bool(first_rating) and not window.busy, 30) and window.store.video(original)['archived'] == 1)  # 等待全局标签应用与评分后移动都完成。
        check('归档保留上下文及暂停状态', wait_until(lambda: window.player.get_state() == vlc.State.Paused) and window.context is context and window.current == original)  # 验证安全重载保持原顺序和暂停。
        entries = list((output / 'archive/8分').glob('*/*.mp4'))  # 获取真实多标签文件入口。
        check('多标签只有一个内容实体', len(entries) == 2 and identity(entries[0]) == identity(entries[1]))  # 检查文件身份相等。
        expected_name = '第2集.mp4'  # 全部标签沿用自然排序，评分使用实际值。
        check('归档全部入口同步分类文件名', all(entry.name == expected_name for entry in entries))  # 检查真实磁盘名称而不是界面文案。
        check('数据库保留永久原名', window.store.video(original)['original_name'] == '第2集.mp4' and window.store.video(original)['name'] == expected_name)  # 原名与显示名各自持久保存。
        check('原播放快照名称更新且序号不变', context.folders[folder][1][0] == (original, expected_name))  # 改名不能重排正在使用的播放顺序。
        def rate_nine():  # 模拟已归档视频通过真实 R 弹窗修改评分。
            dialog = QApplication.activeModalWidget()  # 读取实际评分弹窗。
            QTest.mouseClick(dialog.hearts[4], Qt.LeftButton, pos=QPoint(12, 24))  # 第五颗左半直接确认九分。
        QTimer.singleShot(100, rate_nine)  # 弹窗创建后再操作评分控件。
        QTest.keyClick(window.player_view.surface, Qt.Key_R)  # 测试 GUI 评分确认路径。
        check('修改评分同步改名且保留原身份', wait_until(lambda: not window.busy, 30) and window.store.resolve(original).name == '第2集.mp4' and all(not entry.exists() for entry in entries))  # 新入口先存在，再清理旧评分入口。
        check('改名重载保持暂停与上下文', wait_until(lambda: window.player.get_state() == vlc.State.Paused) and window.context is context)  # 命名变更不强制播放或改顺序。
        def remove_tag():  # 模拟 Q 界面取消其中一个标签。
            dialog = QApplication.activeModalWidget()  # 找到当前标签弹窗。
            for name in list(dialog.selected):  # 本次仅保留测试乙，操作真实胶囊按钮。
                if name != '测试乙':  # 类型与层级仍留在全局标签库。
                    dialog.chips[name].click()  # 点击胶囊取消其他标签。
            dialog.accept()  # 确认后才提交磁盘操作。
        QTimer.singleShot(100, remove_tag)  # 保持与实际用户确认路径一致。
        second_rating = auto_rating(9)  # 每次标签完全应用后再次明确评分。
        QTest.keyClick(window.player_view.surface, Qt.Key_Q)  # 使用真实分类快捷键。
        check('取消标签同步替换前缀并自动评分', wait_until(lambda: bool(second_rating) and not window.busy, 30) and window.store.resolve(original).name == '第2集.mp4')  # 标签和评分流程完整结束后验证实际文件名。
        window.classification.archive(original, 8, ['测试甲', '测试乙'])  # 恢复后续原有回归使用的评分及两个标签。
        check('反复修改不叠加旧前缀', wait_until(lambda: not window.busy, 30) and window.store.resolve(original).name == expected_name)  # 始终由永久原名重建完整名称。
        check('恢复分类后暂停状态保留', wait_until(lambda: window.player.get_state() == vlc.State.Paused))  # 避免短样例在后续导航断言前自然结束。
        entries = list((output / 'archive/8分').glob('*/*.mp4'))  # 后续缩略图检查使用最新有效入口。
        report['shell_thumbnails']['archived_hardlink'] = shell_thumbnail(entries[0])  # 对实际归档硬链接再次验证缩略图。
        QTest.keyClick(window.player_view.surface, Qt.Key_X)  # 从归档视频按 X 切换。
        check('X 使用原目录下一个', window.location == (folder, 1))  # 不跳入标签目录。
        QTest.keyClick(window.player_view.surface, Qt.Key_Z)  # 再按 Z 返回。
        check('Z 使用原目录上一个', window.location == (folder, 0) and window.current == original)  # 通过稳定 ID 找到归档入口。
        check('归档视频可重新播放', wait_until(lambda: window.player.get_time() > 300))  # 证明归档后的文件可解码。
        window.player.set_time(3600)  # 跳到样例末尾触发自然结束。
        check('自然结束自动连播', wait_until(lambda: window.location == (folder, 1), 10))  # 真实 VLC 结束状态触发 X 规则。
        cache1 = window.thumbnail(original)  # 使用实际 FFmpeg 生成软件缩略图。
        cache2 = window.thumbnail(original)  # 再次请求同视频身份。
        check('缩略图缓存共用', cache1 == cache2 and cache1.stat().st_size > 0)  # 不因多标签重复生成。
        from PySide6.QtGui import QImageReader  # 检查实际生成的缩略图文件尺寸。
        thumbnail_size = QImageReader(str(cache1)).size()  # 读取 JPEG 的真实像素尺寸。
        check('缩略图至少120×120', thumbnail_size.width() == 240 and thumbnail_size.height() == 160)  # 验证固定画布大小而非仅设置控件大小。
        report['thumbnail_size'] = [thumbnail_size.width(), thumbnail_size.height()]  # 将尺寸要求记录到交付证据。
        window.start(context, (folder, 0))  # 回到已经归档的收藏视频。
        check('历史测试视频加载', wait_until(lambda: window.player.get_time() > 300))  # 等待真实播放器准备。
        window.player.set_time(1200)  # 设置可识别的续播位置。
        window.player.set_pause(1)  # 固定测试进度。
        check('续播进度准备', wait_until(lambda: window.player.get_state() == vlc.State.Paused and window.player.get_time() >= 1100))  # 等待内核应用位置。
        window.save()  # 持久保存当前视频进度。
        saved = window.store.video(original)['position']  # 记录稍后应该恢复的时间。
        window.library_view.show_mode('stars')
        listing = window.library_view.lists['stars']
        listing.doubleClicked.emit(listing.model().index_for_id(original))
        check('收藏归档后续播', wait_until(lambda: window.context.root == str(window.store.resolve(original).parent) and window.playback.resume is None and window.player.get_time() >= saved - 100))  # 验证当前路径恢复和进度保留。
        window.player.set_pause(1)  # 防止短样例在文件夹历史测试期间自然切换。
        active_context = window.context  # 保存恢复后的播放上下文。
        def open_folder_history():  # 在文件夹历史中选择原始导入根。
            dialog = QApplication.activeModalWidget()  # 获取历史文件夹窗口。
            listing = dialog.findChild(QListWidget)  # 查找历史路径列表。
            item = next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(Qt.UserRole) == str(source))  # 按完整目录路径定位。
            listing.itemDoubleClicked.emit(item)  # 仅恢复浏览目录。
        QTimer.singleShot(100, open_folder_history)  # 在弹窗事件循环中操作。
        window.folder_history()  # 打开独立文件夹历史。
        check('历史文件夹只恢复目录', wait_until(lambda: window.library_controller.browsing.root == str(source)) and window.context is active_context and window.current == original)  # 不切换当前视频或上下文。
        from moplayer.core import Store  # 使用新数据库连接验证持久数据。
        reopened = Store(output / 'data')  # 模拟重新启动读取数据库。
        check('评分收藏进度持久化', reopened.video(original)['score'] == 8 and reopened.video(original)['star'] == 1 and reopened.video(original)['position'] > 0)  # 验证数据落盘。
        report['success'] = True  # 所有关键集成断言已通过。
    except Exception as error:  # 保存失败信息用于实际修复。
        report['success'], report['error'] = False, repr(error)  # 不隐瞒测试失败。
    finally:  # 无论结果如何都交付证据。
        window.grab().save(str(output / 'moplayer.application.png'))  # 保存应用自身渲染截图。
        window.close()  # 正常退出并保存数据。
        from PySide6.QtCore import QThreadPool  # 等待本次后台任务退出。
        QThreadPool.globalInstance().waitForDone()  # 避免进程退出时销毁运行中对象。
        window.thumbnails.pool.waitForDone()  # 等待新的可见行缩略图线程池退出。
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 持久保存详细验收结果。
    return 0 if report.get('success') else 1  # 用进程退出码反映是否全部通过。

if __name__ == '__main__':  # 独立执行源码验收。
    sys.exit(run(sys.argv[1]))  # 输出目录必须显式指定。
