"""Real Qt drops and VLC, with generated media on a private desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    desktop = require_private_desktop()
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QThreadPool, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    from application.operations import Operation, Outcome, Status
    from app import Window
    from runtime import BUNDLE

    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    samples = output / '中文 有空格'
    samples.mkdir()
    ffmpeg = BUNDLE / 'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    a, b, c = [samples / name for name in ('A.mp4', 'B.MP4', 'C.mp4')]
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25',
                    '-t', '45', '-c:v', 'libx264', '-threads', '2', '-y', str(a)],
                   check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    for path in (b, c):
        shutil.copyfile(a, path)
    application = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1200, 800)
    window.show()
    application.setActiveWindow(window)
    window.storage.save(output / 'archive')
    window.archiver.root = window.storage.root
    errors = []
    window.fail = lambda error: errors.append(str(error))
    report = dict(desktop=desktop, checks=[])
    released = threading.Event()

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
        return False

    def drop(urls):
        mime = QMimeData()
        mime.setUrls(urls)
        viewport = window.library_view.tree.viewport()
        enter = QDragEnterEvent(QPoint(24, 24), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        application.sendEvent(viewport, enter)
        event = QDropEvent(QPointF(24, 24), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        application.sendEvent(viewport, event)
        return enter.isAccepted() and event.isAccepted()

    def local(path):
        return [QUrl.fromLocalFile(str(path))]

    flush = window.player_view.options.flush_pending
    try:
        aid, bid, cid = [window.catalog.register(path) for path in (a, b, c)]
        window.catalog.progress(bid, 10000)
        window.catalog.set_score(bid, 7)
        window.catalog.set_favorite(bid, True)
        check('空白文件页接受单个视频', drop(local(b)))
        check('按目标身份播放而非目录第一项', wait(lambda: window.current == bid and window.player.get_time() > 9000))
        check('中文空格路径加载所在目录', window.library_controller.browsing.root == str(samples))
        check('原评分收藏和续播记录保持', window.catalog.video(bid)['score'] == 7 and window.catalog.video(bid)['star'] == 1)
        check('重新拖入A成功换片', drop(local(a)) and wait(lambda: window.current == aid and window.player.get_time() > 500))
        handle = window.player_view.video_handle()
        media = window.player.get_media().get_mrl()
        entered = threading.Event()

        def fault(stage):
            if stage == 'prepared':
                entered.set()
                if not released.wait(15):
                    raise TimeoutError('drop verification gate expired')
        window.archiver.fault = fault
        operation = window.classification.archive(aid, 8, [])
        check('分类文件任务进入等待点且视频仍播放', wait(entered.is_set) and window.busy and not window.file_tasks.media_released)
        check('保存中允许依次拖入B和C', drop(local(b)) and drop(local(c)))
        before = window.player.get_time()
        check('等待保存时保持A且继续前进', wait(lambda: window.player.get_time() > before + 350) and window.current == aid
              and window.player.get_media().get_mrl() == media)
        released.set()
        check('保存完成后只执行最后选择C', wait(lambda: not operation.pending and window.current == cid and window.player.get_time() > 500)
              and operation.outcome.succeeded)
        window.archiver.fault = None
        check('换片保留同一原生视频宿主', window.player_view.video_handle() == handle)
        media = window.player.get_media().get_mrl()
        check('拖入文件夹仍可浏览且不主动换片', drop(local(samples)) and wait(lambda: not window.library_controller.scanning)
              and window.current == cid and window.player.get_media().get_mrl() == media)
        text = samples / 'notes.txt'
        text.write_text('unsupported', encoding='utf-8')
        check('拒绝文本文件远程URL和多文件', not drop(local(text)) and not drop([QUrl('https://example.test/a.mp4')])
              and not drop(local(b) + local(c)))
        missing = samples / '待删除.mp4'
        shutil.copyfile(c, missing)
        saving = Operation()
        window.player_view.options.flush_pending = lambda: saving if saving.pending else Operation.success()
        check('文件等待保存时不抢先换片', drop(local(missing)) and window.current == cid)
        missing.unlink()
        saving.finish(Outcome(Status.SUCCEEDED))
        check('执行时文件消失明确报错并保留当前播放', wait(lambda: bool(errors)) and window.current == cid
              and window.player.get_media().get_mrl() == media and window.library_controller.browsing.root == str(samples))
        window.player_view.options.flush_pending = flush
        window.grab().save(str(output / 'single-video-drop.png'))
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        released.set()
        window.archiver.fault = None
        window.player_view.options.flush_pending = flush
        wait(lambda: not window.busy)
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
