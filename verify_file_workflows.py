"""Real classification/recovery with generated media on a private desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import time
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def run(destination):
    from verify_ui_refresh import require_private_desktop
    from app import Window, BUNDLE
    from runtime import load_vlc
    desktop = require_private_desktop()
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    samples = output / 'samples'
    samples.mkdir()
    ffmpeg = BUNDLE / 'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x365d8d:size=320x180:rate=25',
                    '-t', '25', '-c:v', 'libx264', '-threads', '2', '-y', str(samples / 'A.mp4')],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    for name in ('B.mp4', 'C.mp4'):
        shutil.copyfile(samples / 'A.mp4', samples / name)
    application = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.storage.save(output / 'archive')
    window.archiver.root = window.storage.root
    window.store.execute('INSERT INTO tags VALUES(?)', ('workflow-tag',))
    failures, checks, diagnostics = [], [], []
    window.fail = lambda error: failures.append(str(error))
    vlc = load_vlc()
    def wait(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            application.processEvents()
            if predicate():
                return True
            QTest.qWait(20)
        return False
    def check(name, result):
        checks.append({'name': name, 'ok': bool(result)})
        if not result:
            raise AssertionError(name)
    def snapshot(name):
        diagnostics.append(dict(name=name, state=str(window.player.get_state()), time=window.player.get_time(),
                                position=window.catalog.video(window.current)['position'] if window.current else None,
                                resume=repr(window.playback.resume), pending_seek=repr(window.playback.pending_seek)))
    try:
        window.show()
        window.activateWindow()
        check('private player active', wait(window.isActiveWindow))
        browsing = window.load_folder(str(samples))
        check('three media scanned', wait(lambda: not browsing.pending) and browsing.outcome.succeeded)
        context = window.library_controller.browsing
        vids = [vid for vid, name in context.folders[str(samples)][1]]
        window.start(context, (str(samples), 0))
        check('A plays through VLC', wait(lambda: window.player.get_time() > 400))
        window.player_view.toggle_tags()
        panel = window.player_view.options.tags_popup
        check('tag draft visible', panel.isVisible())
        panel.editor.chips['workflow-tag'].click()
        window.start(context, (str(samples), 1))
        window.start(context, (str(samples), 2))
        check('actual tag commit continues last selection C', wait(lambda: not window.busy and window.current == vids[2]))
        acknowledged = window.tag_drafts.commit(vids[0])
        check('tag draft acknowledged after commit', not acknowledged.pending and acknowledged.outcome.succeeded)
        check('A has committed tags and accessible archived path', json.loads(window.catalog.video(vids[0])['tags']) == ['workflow-tag'] and window.catalog.resolve(vids[0]).exists())
        check('C decodes after continuation', wait(lambda: window.playback.resume is None and window.player.get_time() > 400))
        check('C reaches bookmark before pause', wait(lambda: window.player.get_time() >= 1500))
        window.player.set_pause(1)
        check('C paused', wait(lambda: window.player.get_state() == vlc.State.Paused))
        position = window.player.get_time()
        snapshot('before archive')
        archive = window.classification.archive(vids[2], 8, ['workflow-tag'])
        check('current archive succeeds', wait(lambda: not archive.pending) and archive.outcome.succeeded)
        restored = wait(lambda: window.playback.resume is None and window.player.get_state() == vlc.State.Paused and abs(window.player.get_time() - position) <= 100)
        snapshot('after archive')
        check('archive restores position and pause', restored)
        check('archive preserves stable identity and playback context', window.current == vids[2] and window.context is context and window.catalog.video(vids[2])['score'] == 8)
        def interrupt(stage):
            raise OSError('expected interrupted archive')
        window.archiver.fault = interrupt
        failed = window.classification.archive(vids[1], 9, ['workflow-tag'])
        check('failed archive remains recoverable', wait(lambda: not failed.pending) and failed.outcome.recoverable and bool(window.catalog.pending_tasks('jobs')))
        window.archiver.fault = None
        recovered = window.recovery.retry()
        check('recovery completes ordinary archive', wait(lambda: not recovered.pending) and recovered.outcome.succeeded and not window.catalog.pending_tasks())
        model = window.library_view.files.model()
        index = model.index(1, 0)
        check('recovered B name visible in original tree', index.data() == window.catalog.video(vids[1])['name'] != 'B.mp4')
        check('recovery preserves C and its pause', wait(lambda: window.current == vids[2] and window.playback.resume is None and window.player.get_state() == vlc.State.Paused))
        check('only the expected interruption was reported', len(failures) == 1 and 'expected interrupted archive' in failures[0])
        window.grab().save(str(output / 'file-workflows.png'))
    finally:
        window.archiver.fault = None
        wait(lambda: not window.busy)
        window.tag_drafts.discard_all()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        window.store.db.close()
        (output / 'results.json').write_text(json.dumps({'desktop': desktop, 'checks': checks,
            'reported_errors': failures, 'diagnostics': diagnostics}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0
