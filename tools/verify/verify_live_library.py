"""Real disk notifications update the library without touching VLC playback."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import traceback


def run(destination):
    from tools.verify.verify_ui_refresh import require_private_desktop
    desktop = require_private_desktop()
    from PySide6.QtCore import QPoint, QPersistentModelIndex, QThreadPool, Qt
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QApplication, QAbstractItemView
    from moplayer.app import Window
    from moplayer.runtime import BUNDLE
    from moplayer.gui.library_views import FOLDER_ROLE, LOCATION_ROLE

    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    playback_folder = output / 'playback'
    playback_folder.mkdir()
    fixture = playback_folder / 'playing.mp4'
    ffmpeg = BUNDLE / 'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
        '-t', '90', '-c:v', 'libx264', '-threads', '2', '-y', str(fixture)],
        check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    root = output / '中文 监听目录'
    root.mkdir()
    for n in range(30):
        shutil.copyfile(fixture, root / f'片段{n:02}.mp4')
    application = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1200, 800)
    window.show()
    application.setActiveWindow(window)
    window.storage.save(output / 'archive')
    window.archiver.root = window.storage.root
    report = dict(desktop=desktop, checks=[])
    errors, events, changes = [], [], []
    window.fail = lambda error: errors.append(str(error))
    window.library_controller.subscribe(lambda change: changes.append(change.kind))
    panel, view = window.library_view, window.library_view.files
    released = threading.Event()

    def wait(predicate, seconds=15):
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

    def names():
        model = view.model()
        return [model.index(n, 0).data(Qt.DisplayRole) for n in range(model.rowCount())]

    def settle(seconds):
        deadline = time.monotonic() + seconds
        wait(lambda: time.monotonic() >= deadline, seconds + 2)

    try:
        loaded = window.load_folder(str(playback_folder))
        assert wait(lambda: not loaded.pending) and loaded.outcome.succeeded
        playback = window.library_controller.browsing
        frozen = list(playback.folders[str(playback_folder)][1])
        window.start(playback, (str(playback_folder), 0))
        check('独立源真实播放', wait(lambda: window.player.get_time() > 600 and window.playback.resume is None))
        playing = window.current
        handle, media = window.player_view.video_handle(), window.player.get_media().get_mrl()
        for kind in (window.vlc.EventType.MediaPlayerStopped, window.vlc.EventType.MediaPlayerOpening,
                     window.vlc.EventType.MediaPlayerMediaChanged):
            window.player.event_manager().event_attach(kind, lambda event: events.append(str(event.type)))
        loaded = window.load_folder(str(root))
        check('导入目录开启监听', wait(lambda: not loaded.pending) and loaded.outcome.succeeded
              and str(root) in window.library_watch.watcher.directories())
        model = view.model()
        view.setCurrentIndex(model.index(15, 0))
        selected = QPersistentModelIndex(view.currentIndex())
        selected_id = selected.data(Qt.UserRole)
        view.scrollTo(view.currentIndex(), QAbstractItemView.PositionAtTop)
        view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 17)
        anchor = QPersistentModelIndex(view.indexAt(QPoint(1, 1)))
        anchor_id, offset = anchor.data(Qt.UserRole), view.visualRect(anchor).top()
        resets = QSignalSpy(model.modelReset)
        added = root / '00 新增.mp4'
        shutil.copyfile(fixture, added)
        check('外部新增视频自动出现', wait(lambda: '00 新增.mp4' in names()))
        check('前方插入不改变选中视频且更新逻辑位置', view.currentIndex().data(Qt.UserRole) == selected_id
              and selected.data(LOCATION_ROLE) == (str(root), 16))
        check('刷新保留可见滚动锚点', view.indexAt(QPoint(1, 1)).data(Qt.UserRole) == anchor_id
              and view.visualRect(anchor).top() == offset)
        source = root / '片段15.mp4'
        renamed = root / 'Z 外部改名.mp4'
        window.catalog.set_score(selected_id, 7)
        window.catalog.set_favorite(selected_id, True)
        window.library_controller.refresh([selected_id])
        source.rename(renamed)
        check('外部改名自动显示且选中身份保持', wait(lambda: selected.data(Qt.DisplayRole) == renamed.name)
              and view.currentIndex().data(Qt.UserRole) == selected_id)
        check('改名保留评分收藏记录', window.catalog.video(selected_id)['score'] == 7
              and window.catalog.video(selected_id)['star'] == 1)
        window.library_controller.refresh([selected_id])
        check('元数据刷新不恢复过时文件名', selected.data(Qt.DisplayRole) == renamed.name)
        added.unlink()
        check('外部删除视频自动移除', wait(lambda: added.name not in names()) and panel.file_count.text() == '30 部')
        child = root / '新建文件夹'
        child.mkdir()
        check('外部新增文件夹自动出现', wait(lambda: model.index(0, 0).data(FOLDER_ROLE) == str(child)))
        nested = child / 'nested.mp4'
        shutil.copyfile(fixture, nested)
        check('未进入的子目录内容也自动更新', wait(lambda: bool(window.library_controller.browsing.folders[str(child)][1])))
        panel.browse_folder(str(child))
        check('进入子目录可见最新视频', names() == ['nested.mp4'])
        window.thumbnail_service.pause(True)
        window.thumbnail_service.stop()
        window.thumbnails.pool.waitForDone()
        nested.unlink()
        child.rmdir()
        check('当前子目录被删除自动返回上级', wait(lambda: panel.current_folder == str(root)))
        window.thumbnail_service.pause(False)
        entered = threading.Event()
        def fault(stage):
            if stage == 'prepared':
                entered.set()
                if not released.wait(15):
                    raise TimeoutError('live library verification gate expired')
        window.archiver.fault = fault
        operation = window.classification.archive(playing, 8, [])
        check('分类文件任务进入等待阶段', wait(entered.is_set) and window.busy)
        delayed = root / '保存期间新增.mp4'
        shutil.copyfile(fixture, delayed)
        before = window.player.get_time()
        settle(.8)
        check('文件任务期间推迟目录发布且继续播放', delayed.name not in names() and window.player.get_time() > before)
        released.set()
        check('分类完成后自动补上目录变化', wait(lambda: not operation.pending and delayed.name in names())
              and operation.outcome.succeeded)
        window.archiver.fault = None
        check('浏览刷新没有改变原播放快照', window.context is playback
              and playback.folders[str(playback_folder)][1] == frozen and window.current == playing)
        check('新增删除改名和分类全程不重载媒体', not events and window.player.get_media().get_mrl() == media
              and window.player_view.video_handle() == handle)
        watch = window.library_watch
        watch.watcher.removePaths([str(root)])
        fallback = root / '通知丢失后新增.mp4'
        shutil.copyfile(fixture, fallback)
        check('目录通知丢失时根目录探测可以补偿', wait(lambda: fallback.name in names(), 8))
        check('自动刷新使用增量通知而非重置列表', resets.count() == 0)
        window.grab().save(str(output / 'live-library.png'))
        window.thumbnail_service.pause(True)
        window.thumbnail_service.stop()
        window.thumbnails.pool.waitForDone()
        assert root.resolve().is_relative_to(output.resolve()) and root != output
        for path in root.iterdir():
            assert path.is_file()
            path.unlink()
        root.rmdir()
        check('导入根被移除时清空可见列表', wait(lambda: view.model().rowCount() == 0))
        root.mkdir()
        shutil.copyfile(fixture, root / '重新出现.mp4')
        check('导入根重建后自动恢复监听', wait(lambda: names() == ['重新出现.mp4']))
        window.thumbnail_service.pause(False)
        check('根目录消失重建仍保留原媒体', not events and window.current == playing
              and window.player.get_media().get_mrl() == media)
        settle(1)
        count = changes.count('contents')
        settle(1.2)
        check('目录稳定后不会反复扫描发布', changes.count('contents') == count)
        check('全过程没有弹出错误', not errors)
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        released.set()
        window.archiver.fault = None
        window.thumbnail_service.pause(False)
        wait(lambda: not window.busy)
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
