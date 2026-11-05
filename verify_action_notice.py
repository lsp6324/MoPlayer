"""Real archive receipts and native overlay checks on a private desktop."""
import json
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    import ctypes
    from PySide6.QtCore import QPoint, QPointF, QThreadPool, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPolygonF
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from app import Window
    from runtime import BUNDLE
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1200, 800)
    window.show()
    app.setActiveWindow(window)
    app.processEvents()
    report = {'checks': []}
    panel = window.player_view.action_notice

    def check(name, value):
        report['checks'].append({'name': name, 'ok': bool(value)})
        assert value, name

    def wait(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return True
            QTest.qWait(20)
        return bool(predicate())

    def screenshot(name):
        # Tool windows are separate native windows: compose their real Qt grabs
        # at the actual global coordinates for one reviewable application image.
        picture = window.grab()
        painter = QPainter(picture)
        for widget in (window.player_view.fullscreen.title, panel):
            if widget.isVisible():
                painter.drawPixmap(widget.pos() - window.mapToGlobal(QPoint()), widget.grab())
        painter.end()
        picture.save(str(output / name))

    try:
        samples = output / 'samples'
        samples.mkdir(exist_ok=True)
        image = QImage(1600, 1000, QImage.Format_RGB32)
        painter = QPainter(image)
        gradient = QLinearGradient(0, 0, 0, 1000)
        gradient.setColorAt(0, QColor('#6b91ab'))
        gradient.setColorAt(.62, QColor('#bec4bb'))
        gradient.setColorAt(1, QColor('#354f55'))
        painter.fillRect(image.rect(), gradient)
        for color, points in (
            ('#6c8991', [(0, 640), (350, 270), (600, 590), (1000, 300), (1600, 650)]),
            ('#3e666d', [(0, 730), (480, 450), (920, 760), (1350, 440), (1600, 680)]),
            ('#244a50', [(0, 820), (350, 640), (800, 870), (1200, 680), (1600, 810)])):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in
                                           [*points, (1600, 1000), (0, 1000)]]))
        painter.end()
        image.save(str(samples / '山间暮色.png'))
        loaded = window.load_folder(str(samples))
        check('载入独立测试图片', wait(lambda: not loaded.pending) and loaded.outcome.succeeded)
        snapshot = window.library_controller.browsing
        window.start(snapshot, (str(samples), 0))
        check('图片实际显示', wait(lambda: window.player_view.image_view.has_image()))
        vid = window.current
        window.set_rating(vid, 8)
        window.fail = lambda error: report.setdefault('errors', []).append(str(error))
        handle = window.player_view.video_handle()
        focus = app.focusWidget()
        task = window.classification.apply_tags(vid, ['风景'], [{'name': '风景', 'kind': 'major', 'parent': None}], prompt_score=False)
        check('真实归档成功并显示回执', wait(lambda: not task.pending) and task.outcome.succeeded and panel.isVisible())
        check('回执给出实际提交目录', panel.title_label.text() == '已归档' and '8分 / 风景' in panel.detail_label.text())
        check('回执不抢输入焦点', app.focusWidget() is focus)
        origin = window.player_view.surface.mapToGlobal(QPoint())
        check('播放区右上角保留24像素', panel.x() + panel.width() == origin.x() + window.player_view.surface.width() - 24 and panel.y() == origin.y() + 24)
        screenshot('windowed.png')
        panel.grab().save(str(output / 'receipt.png'))
        check('透明圆角', panel.grab().toImage().pixelColor(0, 0).alpha() == 0)
        user = ctypes.WinDLL('user32')
        user.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        flags = user.GetWindowLongW(int(panel.winId()), -20)
        check('原生鼠标穿透且不激活', flags & 0x20 and flags & 0x08000000)
        check('不是全局置顶窗口', not flags & 0x8)

        from application.archive_folders import ArchiveFolders
        flat = window.archive_configuration.apply(str(window.storage.root), ArchiveFolders(False, False, False))
        check('三个目录选项全关并完成实际整理', wait(lambda: not flat.pending) and flat.outcome.succeeded)
        check('整理后图片恢复显示', wait(lambda: window.player_view.image_view.has_image()))
        directories = window.catalog.media_directories(vid)
        schema = [dict(name=name, kind='major', parent=None) for name in ('风景', '旅行')]
        tag_task = window.classification.apply_tags(vid, ['旅行'], schema, prompt_score=False)
        check('全关时仅改标签提示标签已保存', wait(lambda: not tag_task.pending) and tag_task.outcome.succeeded
              and panel.isVisible() and panel.title_label.text() == '标签已保存'
              and panel.detail_label.text() == '山间暮色.png')
        window.set_rating(vid, 9)
        check('全关时仅改评分提示评分已更新', wait(lambda: not window.busy)
              and panel.isVisible() and panel.title_label.text() == '评分已更新')
        screenshot('metadata-only.png')
        window.favorite(toggle=True)
        check('全关时收藏给出对应提示', panel.title_label.text() == '已收藏')
        window.favorite(toggle=True)
        check('全关时取消收藏给出对应提示', panel.title_label.text() == '已取消收藏')
        check('以上元数据操作不改变实际目录', window.catalog.media_directories(vid) == directories)
        panel.clear()
        window.set_rating(vid, 9)
        window.classification.favorite(vid, False)
        same = window.classification.apply_tags(vid, ['旅行'], list(window.store.tag_layout().values()), prompt_score=False)
        check('重复保存相同内容不弹成功回执', wait(lambda: not same.pending) and same.outcome.succeeded and not panel.isVisible())

        start = time.monotonic()
        panel.present('已归档', '8分 / 风景')
        QTest.qWait(1100)
        panel.present('已归档', '9分 / 风景')
        QTest.qWait(1100)
        check('连续操作替换内容并重新计时', panel.isVisible() and panel.detail_label.text() == '9分 / 风景')
        check('新回执2秒到期隐藏', wait(lambda: not panel.isVisible(), 1.2) and 3.0 <= time.monotonic() - start <= 3.5)
        window.resize(1000, 700)
        app.processEvents()
        panel.present('已归档', '8分 / 风景')
        window.move(window.pos() + QPoint(30, 20))
        app.processEvents()
        check('窗口移动时提示跟随', panel.isVisible() and panel.x() + panel.width() == window.player_view.surface.mapToGlobal(QPoint()).x() + window.player_view.surface.width() - 24)
        window.player_view.fullscreen.enter()
        app.processEvents()
        window.player_view.fullscreen.set_presentation(True)
        panel.present('已归档', '8分 / 风景')
        app.processEvents()
        check('全屏避开顶部文件信息', panel.isVisible() and not panel.geometry().intersects(window.player_view.fullscreen.title.geometry()))
        screenshot('fullscreen.png')
        window.player_view.fullscreen.set_presentation(False)
        app.processEvents()
        check('标题隐藏后回到右上角', panel.y() == window.player_view.surface.mapToGlobal(QPoint()).y() + 24)
        window.player_view.fullscreen.exit()
        app.processEvents()
        check('未重建视频宿主', handle == window.player_view.video_handle())

        movie = output / 'playing.mp4'
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                        '-t', '20', '-c:v', 'libx264', '-threads', '2', '-y', str(movie)],
                       check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        window.play_path(movie, 0, False)
        check('真实视频开始播放', wait(lambda: window.player.get_time() > 500))
        before = window.player.get_time()
        panel.present('已归档', '8分 / 风景')
        window.player_view.seek_notice.show(1000, 6000, 20000)
        check('与跳转提示同时显示', panel.isVisible() and window.player_view.seek_notice.overlay.isVisible())
        check('提示期间视频继续播放', wait(lambda: window.player.get_time() > before + 400, 3))
        window.showMinimized()
        app.processEvents()
        check('最小化隐藏回执', not panel.isVisible())
        window.showNormal()
        app.setActiveWindow(window)
        app.processEvents()
        panel.present('已归档', '8分 / 风景')
        other = QWidget()
        other.show()
        app.setActiveWindow(other)
        check('切到其他应用窗口后隐藏', wait(lambda: not panel.isVisible(), 2))
        other.close()
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1


if __name__ == '__main__':
    import sys
    sys.exit(run(sys.argv[1]))
