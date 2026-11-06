"""Flat directory browsing and responsive breadcrumbs on a private desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import time
import traceback


def run(destination):
    from tools.verify.verify_ui_refresh import require_private_desktop
    desktop = require_private_desktop()
    from PySide6.QtCore import QPoint, QThreadPool, Qt
    from PySide6.QtWidgets import QApplication, QPushButton, QAbstractItemView, QStyle, QStyleOptionButton
    from PySide6.QtTest import QTest, QSignalSpy
    from moplayer.app import Window
    from moplayer.runtime import BUNDLE
    from moplayer.gui.library_views import FOLDER_ROLE, LOCATION_ROLE
    from moplayer.gui.theme import apply_theme

    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    samples = output / '样例'
    samples.mkdir()
    paths = [samples]
    for name in ('教学素材', '基础课程', '第一章', '运动', '分组', '示例'):
        paths.append(paths[-1] / name)
        paths[-1].mkdir()
    ffmpeg = BUNDLE / 'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    sample = samples / 'preview.mp4'
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
        '-t', '45', '-c:v', 'libx264', '-threads', '2', '-y', str(sample)],
        check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    for n in range(15):
        shutil.copyfile(sample, paths[-1] / f'片段{n:02}.mp4')
    application = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1200, 800)
    window.show()
    application.setActiveWindow(window)
    window.splitter.setSizes([320, 880])
    window.storage.save(output / 'archive')
    window.archiver.root = window.storage.root
    panel, view = window.library_view, window.library_view.files
    errors, events = [], []
    window.fail = lambda error: errors.append(str(error))
    report = dict(desktop=desktop, checks=[])

    def wait(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False

    def check(name, passed):
        report['checks'].append(dict(name=name, ok=bool(passed)))
        assert passed, name

    def double_click(row):
        index = view.model().index(row, 0)
        view.scrollTo(index)
        application.processEvents()
        position = view.visualRect(index).center()
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, position)
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, position)
        application.processEvents()

    try:
        loaded = window.load_folder(str(samples))
        check('完整目录扫描成功', wait(lambda: not loaded.pending) and loaded.outcome.succeeded)
        context = window.library_controller.browsing
        check('列表只显示当前目录的一层内容', view.model().rowCount() == 2 and panel.file_count.text() == '1 部')
        check('导入根目录禁用上一级', not panel.folder_navigation.up.isEnabled())
        assert wait(lambda: any(control.isVisible() and control.property('current')
                   for control in panel.folder_navigation.findChildren(QPushButton)))
        caption = next(control for control in panel.folder_navigation.findChildren(QPushButton)
                       if control.isVisible() and control.property('current'))
        option = QStyleOptionButton()
        caption.initStyleOption(option)
        content = caption.style().subElementRect(QStyle.SE_PushButtonContents, option, caption)
        check('短目录名完整可读而非省略号', caption.text() == samples.name
              and caption.fontMetrics().horizontalAdvance(caption.text()) <= content.width())
        root_left = view.visualRect(view.model().index(1, 0)).left()
        double_click(1)
        check('视频行真实双击播放', wait(lambda: window.player.get_time() > 600))
        current = window.current
        handle, media = window.player_view.video_handle(), window.player.get_media().get_mrl()
        for kind in (window.vlc.EventType.MediaPlayerStopped, window.vlc.EventType.MediaPlayerOpening,
                     window.vlc.EventType.MediaPlayerMediaChanged):
            window.player.event_manager().event_attach(kind, lambda event: events.append(str(event.type)))
        window.grab().save(str(output / 'root-light.png'))
        for path in paths[1:]:
            assert view.model().index(0, 0).data(FOLDER_ROLE) == str(path)
            double_click(0)
            assert panel.current_folder == str(path)
        check('真实双击可逐层进入六级目录', panel.current_folder == str(paths[-1]))
        check('深层视频行仍使用相同左边距', view.visualRect(view.model().index(0, 0)).left() == root_left)
        check('目录内视频计数准确', panel.file_count.text() == '15 部')
        check('浏览使用原快照且保留当前播放', window.library_controller.browsing is context
              and window.context is context and window.current == current)
        navigation = panel.folder_navigation
        overflow = next(control for control in navigation.findChildren(QPushButton) if control.isVisible() and control.menu())
        check('长路径折叠并保留完整路径提示', navigation.toolTip() == str(paths[-1])
              and len(overflow.menu().actions()) == len(paths) - 1)
        check('窄侧栏路径控件无越界', all(control.geometry().right() < navigation.width()
              for control in navigation.findChildren(QPushButton) if control.isVisible()))
        QTest.mouseClick(overflow, Qt.LeftButton)
        check('路径菜单通过实际鼠标操作打开', wait(lambda: overflow.menu().isVisible()))
        menu = overflow.menu()
        QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier, menu.actionGeometry(menu.actions()[0]).center())
        check('路径菜单可返回导入根目录', wait(lambda: panel.current_folder == str(samples)))
        for path in paths[1:]:
            double_click(0)
        check('只浏览目录没有媒体重载', not events and window.player.get_media().get_mrl() == media
              and window.player_view.video_handle() == handle)
        selected = view.model().index(8, 0)
        selected_location = selected.data(LOCATION_ROLE)
        view.setCurrentIndex(selected)
        view.scrollTo(selected, QAbstractItemView.PositionAtTop)
        view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 19)
        application.processEvents()
        anchor = view.indexAt(QPoint(1, 1))
        anchor_location, offset = anchor.data(LOCATION_ROLE), view.visualRect(anchor).top()
        QTest.mouseClick(navigation.up, Qt.LeftButton)
        check('上一级按钮返回父目录', panel.current_folder == str(paths[-2]))
        double_click(0)
        check('返回子目录恢复选择和滚动锚点', view.currentIndex().data(LOCATION_ROLE) == selected_location
              and view.indexAt(QPoint(1, 1)).data(LOCATION_ROLE) == anchor_location
              and view.visualRect(view.indexAt(QPoint(1, 1))).top() == offset)
        panel.show_mode('videos')
        panel.show_mode('files')
        check('切换分页保留浏览位置', panel.current_folder == str(paths[-1])
              and view.currentIndex().data(LOCATION_ROLE) == selected_location)
        operation = window.classification.archive(current, 8, [])
        resets = QSignalSpy(view.model().modelReset)
        check('分类完成不重置当前目录列表', wait(lambda: not operation.pending) and operation.outcome.succeeded
              and resets.count() == 0 and view.currentIndex().data(LOCATION_ROLE) == selected_location)
        check('目录浏览及分类仍不重载当前媒体', not events and window.player.get_media().get_mrl() == media)
        view.verticalScrollBar().setValue(0)
        application.processEvents()
        window.grab().save(str(output / 'deep-light.png'))
        apply_theme(window, 'dark')
        application.processEvents()
        window.grab().save(str(output / 'deep-dark.png'))
        check('明暗主题切换保留位置和视频宿主', panel.current_folder == str(paths[-1])
              and window.player_view.video_handle() == handle and not events)
        chosen = view.model().index(1, 0).data(Qt.UserRole)
        window.catalog.progress(chosen, 10000)
        double_click(1)
        check('深层视频双击按原身份续播', wait(lambda: window.current == chosen and window.player.get_time() > 9000))
        check('深层播放位置保持快照原索引', window.location == (str(paths[-1]), 1))
        check('全过程没有错误提示', not errors)
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        wait(lambda: not window.busy)
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
