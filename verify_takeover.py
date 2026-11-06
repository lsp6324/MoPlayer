"""Native takeover preview/import with real playback, hardlinks and DPI checks."""
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import Qt, QThreadPool, QEvent
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from app import Window
    from runtime import BUNDLE
    from core import identity
    from theme import apply_theme
    from takeover_dialog import TakeoverDialog
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1280, 900)
    window.show()
    app.setActiveWindow(window)
    report = {'checks': []}
    window.fail = lambda error: report.setdefault('errors', []).append(str(error))

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

    def open_dialog():
        settings = window.title_bar.findChild(QPushButton, 'settingsButton').menu()
        next(action for action in settings.actions() if action.text() == '接管已有文件夹').trigger()
        assert wait(lambda: any(dialog.isVisible() for dialog in window.findChildren(TakeoverDialog)))
        return next(dialog for dialog in window.findChildren(TakeoverDialog) if dialog.isVisible())

    def scan(dialog):
        QTest.mouseClick(dialog.scan, Qt.LeftButton)
        assert wait(lambda: not dialog.pending)
        assert dialog.model.plan is not None, dialog.status.text()

    try:
        playing = output / 'playing'
        playing.mkdir()
        movie = playing / '持续播放.mp4'
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                        '-t', '60', '-c:v', 'libx264', '-threads', '2', '-y', str(movie)],
                       check=True, capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        movie_id = window.store.register(movie)
        loaded = window.load_folder(str(playing), movie_id)
        check('接管前真实视频持续播放', wait(lambda: not loaded.pending and window.player.get_time() > 400))
        handle, context, mrl, before = window.player_view.video_handle(), window.context, window.player.get_media().get_mrl(), window.player.get_time()
        root = output / '已有媒体'
        image = QImage(640, 360, QImage.Format_RGB32)
        image.fill(QColor('#819a88'))
        def picture(relative):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(path))
            return path
        original = picture('2025/风景/山川/山间晨光.png')
        alias = root / '2025/风景/海岸/海岸别名.png'
        alias.parent.mkdir(parents=True)
        os.link(original, alias)
        copy = picture('2025/风景/海岸/独立副本.png')
        film, photo = picture('2025/电影/其他/片段.png'), picture('2025/摄影/其他/照片.png')
        plain = picture('根目录图片.png')
        keep = window.store.register(copy)
        window.store.execute('INSERT INTO tags VALUES(?)', ('原有标签',))
        window.store.execute('UPDATE videos SET tags=?,score=9,star=1,played=123,position=456 WHERE id=?', (json.dumps(['原有标签']), keep))
        old_record = window.catalog.video(keep)
        disk = {str(path): (identity(path), path.read_bytes()) for path in (original, alias, copy, film, photo, plain)}
        def metadata():
            return [(row['id'], row['score'], row['star'], row['tags'], row['in_library'], row['archived'])
                    for row in window.store.query('SELECT * FROM videos ORDER BY id')], window.store.tag_layout()
        baseline = metadata()
        dialog = open_dialog()
        dialog.path.setText(str(root))
        dispatch, queued = window.takeover.dispatch, []
        window.takeover.dispatch = lambda work, done: queued.append((work, done))
        QTest.mouseClick(dialog.scan, Qt.LeftButton)
        QTest.mouseClick(dialog.scan, Qt.LeftButton)
        work, ready = queued.pop()
        try:
            ready(work(), None)
        except InterruptedError as error:
            ready(None, error)
        window.takeover.dispatch = dispatch
        check('取消扫描不遗留记录', wait(lambda: not dialog.pending) and dialog.model.plan is None
              and metadata() == baseline)
        scan(dialog)
        check('仅入库扫描合并硬链接并保留普通副本', len(dialog.model.plan.items) == 5
              and sum(len(item.file.paths) for item in dialog.model.plan.items) == 6)
        check('扫描预览不写库', metadata() == baseline)
        dialog.mode.setCurrentIndex(1)
        dialog.first.setValue(2)
        check('修改规则立即失效旧预览', dialog.model.plan is None and not dialog.confirm.isEnabled())
        scan(dialog)
        plan = dialog.model.plan
        check('指定层级识别父子标签', any(item.labels == ('风景 › 山川', '风景 › 海岸') or set(item.labels) == {'风景 › 山川', '风景 › 海岸'} for item in plan.items))
        conflicts = sum(bool(item.conflicts) for item in plan.items)
        check('同名子标签和已有标记冲突明确列出', conflicts == 3 and '父级不一致' in dialog.details.toPlainText()
              and '现有标记' in dialog.details.toPlainText())
        check('冲突项默认不选', len(dialog.model.selected) == 2)
        dialog.only_conflicts.click()
        check('冲突过滤保留全局选择', dialog.model.rowCount() == 3 and len(dialog.model.selected) == 2)
        dialog.only_conflicts.click()
        app.processEvents()
        dialog.grab().save(str(output / 'takeover-tags-preview.png'))
        dialog.conflicts.click()
        check('明确包含冲突项仅纳入库', len(dialog.model.selected) == 5)
        QTest.mouseClick(dialog.confirm, Qt.LeftButton)
        check('确认后接管成功', wait(lambda: dialog.imported))
        check('五个身份纳入库且不标记为归档', len(window.catalog.videos('catalog')) == 5
              and all(not row['archived'] for row in window.catalog.videos('catalog')))
        linked_id = next(row['id'] for row in window.store.query('SELECT * FROM paths') if row['path'] == str(original))
        check('硬链接标签合并且父子结构正确', set(window.catalog.tag_values(linked_id).tags) == {'山川', '海岸'}
              and window.store.tag_layout()['山川']['parent'] == '风景')
        check('现有标记历史进度和入库时间保留', window.catalog.video(keep) == old_record)
        check('同名父级冲突不创建错误标签', not {'其他', '电影', '摄影', '2025'}.intersection(window.store.tag_layout()))
        check('本地文件内容身份及硬链接均不变', disk == {path: (identity(path), Path(path).read_bytes()) for path in disk})
        dialog.grab().save(str(output / 'takeover-complete.png'))
        QTest.mouseClick(dialog.confirm, Qt.LeftButton)
        check('完成后可以查看库', wait(lambda: window.library_view.mode == 'catalog' and not window.library_controller.catalog_pending)
              and window.library_controller.catalog_total == 5)
        app.processEvents()
        window.grab().save(str(output / 'takeover-library.png'))
        apply_theme(window, 'dark')
        classified = output / '旧分类目录'
        zero = classified / '0分/已收藏/旅行/零分.png'
        none = classified / '未评分/未收藏/未分类/未评分.png'
        for path in (zero, none):
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(path))
        dialog = open_dialog()
        dialog.path.setText(str(classified))
        dialog.mode.setCurrentIndex(2)
        dialog.favorite.setChecked(True)
        dialog.order.setCurrentIndex(1)
        scan(dialog)
        check('旧评分优先顺序可显式指定', len(dialog.model.selected) == 2 and not any(item.conflicts for item in dialog.model.plan.items))
        app.processEvents()
        dialog.grab().save(str(output / 'takeover-archive-dark.png'))
        QTest.mouseClick(dialog.confirm, Qt.LeftButton)
        check('旧分类目录确认导入', wait(lambda: dialog.imported))
        rows = {row['name']: row for row in window.catalog.videos('catalog')}
        check('0分与未评分不同且收藏正确', rows['零分.png']['score'] == 0 and rows['零分.png']['star'] == 1
              and rows['未评分.png']['score'] is None and rows['未评分.png']['star'] == 0)
        check('未分类目录不创建标签', '未分类' not in window.store.tag_layout() and rows['未评分.png']['tags'] == '[]')
        check('归档开关和源文件位置未改变', window.storage.enabled and zero.exists() and none.exists()
              and not rows['零分.png']['archived'])
        dialog.reject()
        check('接管全程不重载真实视频或播放队列', window.current == movie_id and window.context is context
              and window.player_view.video_handle() == handle and window.player.get_media().get_mrl() == mrl and window.player.get_time() > before)
        check('无原生操作异常', not report.get('errors'))
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        for dialog in window.findChildren(TakeoverDialog):
            dialog.reject()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
