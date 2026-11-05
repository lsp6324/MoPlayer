"""Still-image browsing inside the playback area on a private Windows desktop."""
import json
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import QEvent, QPoint, QPointF, QThreadPool, Qt
    from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QWheelEvent
    from PySide6.QtWidgets import QApplication
    from app import Window
    from runtime import BUNDLE
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1200, 800)
    window.show()
    application.setActiveWindow(window)
    report = dict(checks=[])
    view = window.player_view.image_view

    def check(name, passed):
        report['checks'].append(dict(name=name, ok=bool(passed)))
        assert passed, name

    def wait(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return predicate()

    def window_pixel(point):
        image = window.grab().toImage()
        ratio = image.devicePixelRatio()
        return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))

    def wheel(delta):
        centre = QPointF(view.width() / 2, view.height() / 2)
        event = QWheelEvent(centre, QPointF(view.mapToGlobal(centre.toPoint())), QPoint(0, 0),
                            QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(view, event)
        application.processEvents()

    def mouse(kind, point, buttons=Qt.LeftButton):
        local = QPointF(point)
        event = QMouseEvent(kind, local, QPointF(view.mapToGlobal(local.toPoint())),
                            Qt.LeftButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(view, event)
        application.processEvents()

    try:
        samples = output / 'samples'
        samples.mkdir()
        picture = QImage(1200, 900, QImage.Format_RGB32)
        painter = QPainter(picture)
        painter.fillRect(picture.rect(), QColor('#1d3a5f'))
        painter.fillRect(0, 0, 400, 300, QColor('#e05a4f'))
        painter.fillRect(780, 560, 420, 340, QColor('#4fb27a'))
        for x in range(0, 1200, 60):
            painter.setPen(QColor('#dfe8f5'))
            painter.drawLine(x, 0, x, 900)
        painter.end()
        first = samples / 'A.png'
        check('生成 PNG 样例', picture.save(str(first)))
        check('生成 JPG 样例', picture.save(str(samples / 'B.jpg')))
        check('生成 WebP 样例', picture.save(str(samples / 'C.webp')))

        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        movie = samples / 'D.mp4'
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                        '-t', '20', '-c:v', 'libx264', '-threads', '2', '-y', str(movie)],
                       check=True, capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)

        loaded = window.load_folder(str(samples))
        check('图片与视频共同进入扫描候选', wait(lambda: not loaded.pending) and loaded.outcome.succeeded)
        context = window.library_controller.browsing
        names = [name for vid, name in context.folders[str(samples)][1]]
        check('扫描顺序包含全部候选', names == ['A.png', 'B.jpg', 'C.webp', 'D.mp4'])

        window.start(context, (str(samples), 0))
        check('打开图片不经过播放内核', wait(lambda: window.current is not None) and window.current_kind == 'image')
        check('图片解码后显示在播放区', wait(lambda: view.isVisible() and view.has_image()))
        report['scale_fit'] = view._scale
        centre = QPoint(view.width() // 2, view.height() // 2)
        before = window_pixel(window.player_view.surface.mapTo(window, centre))
        check('播放区渲染的是图片而非黑底',
              before.lightness() > 40 or before.saturation() > 40)
        check('图片模式禁用进度条与播放按钮',
              not window.player_view.seekbar.isEnabled() and not window.player_view.play_button.isEnabled())
        check('图片模式仍可用上一个/下一个按钮',
              window.player_view.transport_buttons[0].isEnabled() and
              window.player_view.transport_buttons[2].isEnabled())
        check('图片模式保留分类按钮',
              window.player_view.tags_button.isEnabled() and window.player_view.rating_button.isEnabled())
        window.grab().save(str(output / 'image-fit.png'))

        wheel(120)
        wheel(120)
        report['scale_zoomed'] = view._scale
        check('滚轮放大改变实际缩放', report['scale_zoomed'] > report['scale_fit'] + 0.05)
        zoomed = window_pixel(window.player_view.surface.mapTo(window, centre))
        check('放大后播放区像素发生变化', zoomed != before)
        window.grab().save(str(output / 'image-zoom.png'))

        edge = QPoint(view.width() // 2, view.height() // 2)
        mouse(QEvent.MouseButtonPress, edge)
        mouse(QEvent.MouseMove, QPointF(edge.x() - 260, edge.y() - 160))
        mouse(QEvent.MouseButtonRelease, QPointF(edge.x() - 260, edge.y() - 160), Qt.NoButton)
        panned = window_pixel(window.player_view.surface.mapTo(window, centre))
        check('拖拽平移改变可见区域', panned != zoomed)
        window.grab().save(str(output / 'image-pan.png'))

        mouse(QEvent.MouseButtonDblClick, centre)
        check('双击切换回适应倍率', abs(view._scale - report['scale_fit']) < 0.05)

        window.player_view.fullscreen.enter()
        application.processEvents()
        check('全屏显示同一张图片', wait(lambda: view.isVisible()))
        fullscreen = window_pixel(window.player_view.surface.mapTo(window, centre))
        check('全屏画面仍是图片内容', fullscreen.lightness() > 40 or fullscreen.saturation() > 40)
        window.grab().save(str(output / 'image-fullscreen.png'))
        window.player_view.fullscreen.exit()
        application.processEvents()

        for _ in range(4):
            window.tick()
        check('图片不写续播进度', window.catalog.video(window.current)['position'] == 0)

        window.advance(1)
        check('X 切到下一张图片仍为图片模式',
              wait(lambda: window.current_kind == 'image') and
              window.catalog.video(window.current)['name'] == 'B.jpg')
        window.advance(1)
        window.advance(1)
        check('继续翻到视频切换为播放模式',
              wait(lambda: window.current_kind == 'video') and
              window.catalog.video(window.current)['name'] == 'D.mp4')
        check('视频真的开始播放', wait(lambda: window.player.get_time() > 500))
        check('视频模式隐藏图片层', not view.isVisible())
        window.advance(-1)
        check('Z 翻回图片恢复图片层',
              wait(lambda: window.current_kind == 'image' and view.isVisible() and view.has_image()))
        window.grab().save(str(output / 'image-back.png'))
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
        try:
            window.grab().save(str(output / 'failure.png'))
        except Exception:
            pass
    finally:
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
