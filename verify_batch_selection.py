"""Native group selection, shared submenus and real playback preservation."""
import json
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import Qt, QTimer, QThreadPool, QEvent
    from PySide6.QtGui import QImage, QColor, QContextMenuEvent, QMouseEvent, QPainter
    from PySide6.QtTest import QTest, QSignalSpy
    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QLabel
    from app import Window
    from runtime import BUNDLE
    from batch_tag_editor import BatchTagEditor
    from rating_editor import RatingEditor
    from theme import apply_theme
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1280, 900)
    window.show()
    app.setActiveWindow(window)
    report = {'checks': []}
    window.fail = lambda error: report.setdefault('errors', []).append(str(error))
    panel, listing = window.library_view, window.library_view.files

    def wait(predicate, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate():
                return True
            QThreadPool.globalInstance().waitForDone(1)
            time.sleep(.01)
        return False

    def check(name, value):
        report['checks'].append(dict(name=name, ok=bool(value)))
        assert value, name

    def index(vid):
        return next(listing.model().index(n, 0) for n in range(listing.model().rowCount())
                    if listing.model().index(n, 0).data(Qt.UserRole) == vid)

    def click(vid, modifier=Qt.NoModifier):
        item = index(vid)
        listing.scrollTo(item)
        app.processEvents()
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, modifier, listing.visualRect(item).center())

    def selected():
        return {item.video_id for item in panel.selected_files()}

    def idle():
        return not window.busy and window.batch_actions.active is None and window.file_tasks.completion is None

    def popup(vid, caption=None, interact=None):
        item = index(vid)
        listing.scrollTo(item)
        app.processEvents()
        failures, captured = [], []
        def choose():
            menu = window.media_menu.batch_menu.active_menu
            try:
                assert menu is not None
                captured.append([a.text() for a in menu.actions() if not a.isSeparator() and a.isEnabled()])
                if caption:
                    action = next(a for a in menu.actions() if a.text() == caption)
                    submenu = action.menu()
                    if submenu:
                        point = menu.actionGeometry(action).center()
                        QApplication.sendEvent(menu, QMouseEvent(QEvent.MouseMove, point, menu.mapToGlobal(point),
                                                                Qt.NoButton, Qt.NoButton, Qt.NoModifier))
                        check(caption + '悬停展开', wait(submenu.isVisible))
                        area = menu.geometry().united(submenu.geometry())
                        image = QImage(area.size(), QImage.Format_ARGB32)
                        image.fill(Qt.transparent)
                        painter = QPainter(image)
                        painter.drawPixmap(menu.pos() - area.topLeft(), menu.grab())
                        painter.drawPixmap(submenu.pos() - area.topLeft(), submenu.grab())
                        painter.end()
                        image.save(str(output / ('batch-tags.png' if caption == '编辑标签' else 'batch-rating.png')))
                        if interact:
                            interact(submenu)
                    else:
                        action.trigger()
                else:
                    menu.grab().save(str(output / 'batch-menu.png'))
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                if menu:
                    menu.close()
        QTimer.singleShot(50, choose)
        point = listing.visualRect(item).center()
        QApplication.sendEvent(listing.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, point, listing.viewport().mapToGlobal(point)))
        assert captured and not failures, failures
        return captured[0]

    try:
        samples = output / 'samples'
        samples.mkdir()
        (samples / '子文件夹').mkdir()
        ids, paths = [], []
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor('#718a73'))
        for name in ('01 山间晨光.png', '02 城市夜景.png', '03 旅途记录.png', '04 继续浏览.png'):
            path = samples / name
            image.save(str(path))
            paths.append(path)
            ids.append(window.store.register(path))
        movie = samples / '00 保持播放.mp4'
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                        '-t', '60', '-c:v', 'libx264', '-threads', '2', '-y', str(movie)],
                       check=True, capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        movie_id = window.store.register(movie)
        window.storage.enabled = False
        for name in ('风景', '摄影', '原有标签'):
            window.store.execute('INSERT INTO tags VALUES(?)', (name,))
        window.store.execute('UPDATE videos SET tags=? WHERE id=?', (json.dumps(['原有标签']), ids[0]))
        loaded = window.load_folder(str(samples), movie_id)
        check('真实视频播放', wait(lambda: not loaded.pending and window.current == movie_id and window.player.get_time() > 400))
        before, handle, context = window.player.get_time(), window.player_view.video_handle(), window.context
        check('文件页底部开关可见', panel.batch_select_button.isVisible())
        click(ids[0])
        click(ids[2], Qt.ControlModifier)
        check('Ctrl点击多选', selected() == {ids[0], ids[2]})
        click(ids[0])
        click(ids[2], Qt.ShiftModifier)
        check('Shift连续选择', selected() == set(ids[:3]))
        QTest.mouseClick(panel.batch_select_button, Qt.LeftButton)
        listing.clearSelection()
        click(ids[0])
        click(ids[1])
        click(ids[2])
        click(ids[2])
        check('开启后左键增减选择', selected() == set(ids[:2]))
        opened = QSignalSpy(panel.videoRequested)
        QTest.mouseDClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier, listing.visualRect(index(ids[0])).center())
        check('批量双击媒体不换片', opened.count() == 0 and window.current == movie_id)
        listing.setFocus()
        QTest.keyClick(listing, Qt.Key_A, Qt.ControlModifier)
        check('全选不含文件夹', len(selected()) == 5 and len(listing.selectionModel().selectedIndexes()) == 5)
        listing.clearSelection()
        click(ids[0])
        click(ids[1])
        folder = listing.model().index(0, 0)
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier, listing.visualRect(folder).center())
        QTest.mouseDClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier, listing.visualRect(folder).center())
        check('批量模式双击文件夹仍可进入', wait(lambda: panel.current_folder == str(samples / '子文件夹')))
        panel.browse_folder(str(samples))
        check('返回恢复整组选中', selected() == set(ids[:2]))
        window.grab().save(str(output / 'file-selection.png'))
        check('批量菜单仅四类操作', popup(ids[0]) == ['收藏', '编辑标签', '评分', '删除'])
        check('右键已选项保留整组', selected() == set(ids[:2]))
        popup(ids[0], '编辑标签', lambda menu: menu.findChild(BatchTagEditor).editor.chips['风景'].click())
        check('添加标签保留各自原标签', wait(idle) and set(window.catalog.tag_values(ids[0]).tags) == {'原有标签', '风景'}
              and window.catalog.tag_values(ids[1]).tags == ['风景'])
        popup(ids[0], '评分', lambda menu: menu.findChild(RatingEditor).zero.click())
        check('统一评分支持0分', wait(idle) and all(window.catalog.video(vid)['score'] == 0 for vid in ids[:2]))
        popup(ids[0], '收藏', lambda menu: menu.actions()[0].trigger())
        check('批量收藏', wait(idle) and all(window.catalog.video(vid)['star'] for vid in ids[:2]))
        check('关闭归档标记保留原位', all(path.exists() for path in paths))
        popup(ids[0], '删除')
        dialog = window.media_menu.batch_menu.active_dialog
        check('删除数量及保留本地默认值', '2 个文件' in dialog.findChild(QLabel, 'batchStatus').text()
              and not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked())
        app.processEvents()
        status = dialog.findChild(QLabel, 'batchStatus')
        check('删除确认文件名区域无裁切', status.height() >= status.heightForWidth(status.width()))
        dialog.grab().save(str(output / 'batch-delete.png'))
        dialog.findChild(QPushButton, 'batchDeleteConfirm').click()
        check('批量删记录保留物理文件', wait(lambda: window.media_menu.batch_menu.active_dialog is None)
              and all(window.catalog.video(vid) is None for vid in ids[:2]) and all(path.exists() for path in paths))
        check('其他组操作不中断真实播放', window.current == movie_id and window.context is context
              and window.player_view.video_handle() == handle and window.player.get_time() > before)
        assert wait(lambda: idle() and not window.library_controller.refresh_pending)
        # Clear all remaining original successors except the last one: never
        # briefly play a selected successor before deleting it.
        listing.clearSelection()
        for vid in (movie_id, ids[2]):
            click(vid)
        popup(movie_id, '删除')
        window.media_menu.batch_menu.active_dialog.findChild(QPushButton, 'batchDeleteConfirm').click()
        check('删除当前组按原队列跳过已删成员', wait(lambda: idle() and window.current != movie_id)
              and window.current == ids[3] and window.context is context)
        check('当前组原文件仍保留', window.catalog.video(movie_id) is None and movie.exists() and paths[2].exists())
        panel.show_mode('videos')
        check('最近页隐藏批量开关', not panel.batch_select_button.isVisible())
        panel.show_mode('files')
        apply_theme(window, 'dark')
        window.grab().save(str(output / 'file-selection-dark.png'))
        check('无原生异常', not report.get('errors'))
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
