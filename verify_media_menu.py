"""Media context actions against real Qt/VLC on an isolated desktop."""
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import Qt, QPoint, QTimer, QThreadPool
    from PySide6.QtGui import QImage, QColor, QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton, QDialogButtonBox, QCheckBox, QLineEdit
    from app import Window
    from runtime import BUNDLE
    from theme import apply_theme
    from video_delete import DeletionManager
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1280, 900)
    window.show()
    app.setActiveWindow(window)
    report = {'checks': []}
    window.fail = lambda error: report.setdefault('errors', []).append(str(error))

    def wait(predicate, seconds=12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return True
            QThreadPool.globalInstance().waitForDone(1)
            time.sleep(.01)
        return False

    def check(name, condition):
        report['checks'].append({'name': name, 'ok': bool(condition)})
        assert condition, name

    def popup_action(mode, video_id, caption=None):
        view = window.library_view
        view.show_mode(mode)
        listing = view.files if mode == 'files' else view.lists[mode]
        assert wait(lambda: any(listing.model().index(n, 0).data(Qt.UserRole) == video_id for n in range(listing.model().rowCount())))
        model = listing.model()
        index = next(model.index(n, 0) for n in range(model.rowCount()) if model.index(n, 0).data(Qt.UserRole) == video_id)
        listing.scrollTo(index)
        app.processEvents()
        point = listing.visualRect(index).center()
        captured = []
        def choose():
            menu = window.media_menu.active_menu
            if menu is None:
                return
            actions = [action for action in menu.actions() if not action.isSeparator()]
            captured.append([action.text() for action in actions])
            if caption is None:
                menu.grab().save(str(output / ('menu-' + mode + '.png')))
            else:
                next(action for action in actions if action.text() == caption).trigger()
            menu.close()
        QTimer.singleShot(30, choose)
        event = QContextMenuEvent(QContextMenuEvent.Mouse, point, listing.viewport().mapToGlobal(point))
        QApplication.sendEvent(listing.viewport(), event)
        assert wait(lambda: bool(captured)), 'Context event did not open a menu'
        return captured[0]

    try:
        samples = output / 'samples'
        samples.mkdir()
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor('#547b92'))
        target_path = samples / '右键 操作目标.png'
        image.save(str(target_path))
        target = window.store.register(target_path)
        window.store.execute('UPDATE videos SET score=4,star=1,played=1 WHERE id=?', (target,))
        window.store.execute('INSERT INTO tags VALUES(?)', ('摄影',))
        movie = samples / '保持播放.mp4'
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                        '-t', '60', '-c:v', 'libx264', '-threads', '2', '-y', str(movie)],
                       check=True, capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        movie_id = window.store.register(movie)
        loaded = window.load_folder(str(samples), movie_id)
        check('隔离目录视频真实播放', wait(lambda: not loaded.pending and window.current == movie_id and window.player.get_time() > 400))
        handle, context = window.player_view.video_handle(), window.context
        apply_theme(window, 'dark')
        expected = ['取消收藏', '编辑标签…', '评分…', '重命名…', '删除…', '在资源管理器中打开']
        for mode, name in (('files', '文件'), ('catalog', '库'), ('videos', '最近'), ('stars', '收藏')):
            captions = popup_action(mode, target)
            check(name + '页实际右键菜单包含六个指定动作', captions == expected and window.current == movie_id)
        before = window.player.get_time()
        popup_action('stars', target, '取消收藏')
        check('取消收藏作用于右键目标且当前视频继续', wait(lambda: window.catalog.video(target)['star'] == 0
              and window.player.get_time() > before + 200) and window.current == movie_id)
        popup_action('files', target, '收藏')
        check('未收藏目标菜单可重新收藏', window.catalog.video(target)['star'] == 1)
        popup_action('files', target, '评分…')
        dialog = window.media_menu.active_dialog
        dialog.grab().save(str(output / 'rating-dark.png'))
        dialog.choose(0)
        check('右键评分支持零分且不修改播放对象', wait(lambda: window.media_menu.active_dialog is None)
              and window.catalog.video(target)['score'] == 0 and window.current == movie_id)
        popup_action('files', target, '评分…')
        window.media_menu.active_dialog.findChild(QPushButton, 'score_unrated').click()
        check('右键评分支持清除', wait(lambda: window.media_menu.active_dialog is None)
              and window.catalog.video(target)['score'] is None)
        apply_theme(window, 'light')
        popup_action('files', target, '重命名…')
        dialog = window.media_menu.active_dialog
        dialog.findChild(QLineEdit, 'mediaRenameField').setText('改名后的目标.png')
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
        check('右键改名更新相同身份并保持播放宿主', wait(lambda: window.media_menu.active_dialog is None)
              and window.catalog.resolve(target).name == '改名后的目标.png' and window.current == movie_id
              and window.player_view.video_handle() == handle)
        popup_action('files', target, '编辑标签…')
        dialog = window.media_menu.active_dialog
        dialog.grab().save(str(output / 'edit-tags.png'))
        dialog.chips['摄影'].click()
        dialog.buttons.button(QDialogButtonBox.Ok).click()
        check('右键标签通过草稿和实际分类流程保存到目标', wait(lambda: window.media_menu.active_dialog is None)
              and json.loads(window.catalog.video(target)['tags']) == ['摄影'] and window.current == movie_id)
        assert wait(lambda: not window.library_controller.catalog_pending)
        revealed = []
        window.media_menu.reveal = revealed.append
        popup_action('catalog', target, '在资源管理器中打开')
        check('资源管理器动作解析目标当前有效位置', revealed == [window.catalog.resolve(target)])
        kept = window.catalog.resolve(target)
        content = kept.read_bytes()
        popup_action('catalog', target, '删除…')
        dialog = window.media_menu.active_dialog
        check('删除确认默认不勾选本地文件', not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked())
        dialog.grab().save(str(output / 'delete-confirm.png'))
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).click()
        check('取消删除保留标记和本地文件', window.catalog.video(target)['star'] == 1 and kept.read_bytes() == content)
        popup_action('catalog', target, '删除…')
        window.media_menu.active_dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        check('默认删除仅移除软件记录且保留文件', wait(lambda: window.media_menu.active_dialog is None)
              and window.catalog.video(target) is None and kept.read_bytes() == content)
        local_path = samples / '允许回收的目标.png'
        image.save(str(local_path))
        local_id = window.store.register(local_path)
        linked = samples / '同一文件的另一个入口.png'
        os.link(local_path, linked)
        window.store.register(linked)
        window.store.execute('UPDATE videos SET star=1 WHERE id=?', (local_id,))
        window.library_controller.refresh((local_id,), window.context, catalog_changed=True)
        recycled = output / 'controlled-recycle'
        recycled.mkdir()
        window.deletion.submit = DeletionManager(window.store, recycle=lambda path: path.rename(recycled / path.name)).submit
        popup_action('stars', local_id, '删除…')
        dialog = window.media_menu.active_dialog
        dialog.findChild(QCheckBox, 'deleteLocalFiles').setChecked(True)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        check('勾选后通过受控回收器处理全部登记入口', wait(lambda: window.media_menu.active_dialog is None)
              and not local_path.exists() and not linked.exists() and len(list(recycled.iterdir())) == 2
              and window.catalog.video(local_id) is None)
        check('全部非当前项操作保持真实视频和队列', window.current == movie_id and window.context is context
              and window.player_view.video_handle() == handle and window.player.get_time() > before)
        movie_path = window.catalog.resolve(movie_id)
        window.library_view.show_mode('files')
        window.library_view.files.clearSelection()
        QTest.keyClick(window.player_view.surface, Qt.Key_D, Qt.ControlModifier)
        dialog = window.media_menu.active_dialog
        check('Ctrl+D使用同一确认框且默认保留本地文件', dialog is not None
              and not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked() and movie_path.exists())
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).click()
        popup_action('files', movie_id, '删除…')
        dialog = window.media_menu.active_dialog
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        check('删除当前软件记录后释放旧播放且保留视频文件', wait(lambda: window.media_menu.active_dialog is None and window.current != movie_id)
              and window.catalog.video(movie_id) is None and movie_path.exists() and window.context is context)
        assert wait(lambda: not window.library_controller.refresh_pending)
        rows = window.store.query('SELECT * FROM videos WHERE name=?', (movie.name,))
        check('保留文件重新列出时不恢复旧标记或播放进度', rows and all(row['position'] == 0 and row['played'] == 0
              and row['score'] is None and row['star'] == 0 and not row['in_library'] for row in rows))
        check('菜单和编辑器无原生异常', not report.get('errors'))
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        if window.media_menu.active_dialog is not None:
            window.media_menu.active_dialog.reject()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
