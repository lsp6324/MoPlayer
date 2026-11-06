"""Portable writes and default archiving on a private Windows desktop."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


def profile_snapshot():
    paths = [Path(os.environ['LOCALAPPDATA']) / 'MoPlayer',
             Path(os.environ['LOCALAPPDATA']) / 'qtshadercache-x86_64-little_endian-llp64',
             Path(os.environ['APPDATA']) / 'vlc', Path(os.environ['LOCALAPPDATA']) / 'vlc']
    result = {}
    for root in paths:
        if root.exists():
            result[str(root)] = 'directory'
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    result[str(path)] = 'directory'
    return result


def run(destination):
    from tools.verify.verify_ui_refresh import require_private_desktop
    from moplayer.runtime import BASE, BUNDLE, configure_portable
    require_private_desktop()
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    frozen = bool(getattr(sys, 'frozen', False))
    base = BASE if frozen else output / '解压目录'
    assert not (base / 'data').exists(), 'Use a fresh disposable extraction, never the user player'
    profiles = profile_snapshot()
    report = dict(checks=[],frozen=frozen,base=str(base))
    window = None

    def check(name, passed):
        report['checks'].append(dict(name=name,ok=bool(passed)))
        assert passed, name

    try:
        configure_portable(base)
        from PySide6.QtCore import QCoreApplication, QSettings, QTemporaryFile, Qt, QThreadPool
        from PySide6.QtWidgets import QApplication
        from moplayer.app import Window
        from moplayer.storage_settings import StorageSettings
        from tools import setup_explorer_thumbnails as integration
        application = QApplication([])
        application.setApplicationName('MoPlayer')
        check('Qt可选磁盘着色器缓存已禁用', QCoreApplication.testAttribute(Qt.AA_DisableShaderDiskCache))
        with tempfile.NamedTemporaryFile() as stream:
            check('Python临时文件写入包内', Path(stream.name).is_relative_to(base/'data/temp'))
        temporary = QTemporaryFile()
        check('Qt临时文件写入包内', temporary.open() and Path(temporary.fileName()).is_relative_to(base/'data/temp'))
        temporary.remove()
        settings = QSettings()
        settings.setValue('portable-probe', True)
        settings.sync()
        check('应用默认Qt设置写入包内INI', Path(settings.fileName()).is_relative_to(base/'data/qt-settings')
              and settings.status() == QSettings.NoError)
        check('VLC便携目录已创建', (base/'portable').is_dir())
        if frozen:
            check('可选组件部署不依赖开发机路径', integration.ENVIRONMENT == base/'data/integrations/explorer-thumbnails')
            check('提权脚本随包存在', (BUNDLE/'register_thumbnail_component.ps1').is_file())
        window = Window(base/'data')
        window.show()
        errors = []
        window.fail = lambda error: errors.append(str(error))

        def wait(predicate, seconds=15):
            deadline = time.monotonic()+seconds
            while time.monotonic()<deadline:
                application.processEvents()
                if predicate():
                    return True
                time.sleep(.02)
            return False

        window.initialize_storage()
        check('首次启动默认video且无强制设置弹窗', window.storage.root == base/'video'
              and window.archiver.root == base/'video' and application.activeModalWidget() is None)
        check('启动不自动播放或扫描', window.current is None and window.library_controller.browsing is None)
        if frozen:
            library = ctypes.CDLL(str(Path(os.environ['PYTHON_VLC_LIB_PATH']).with_name('libvlccore.dll')))
            get_directory = library.config_GetUserDir
            get_directory.argtypes, get_directory.restype = [ctypes.c_int], ctypes.c_void_p
            free = window.vlc.dll.libvlc_free
            free.argtypes, free.restype = [ctypes.c_void_p], None
            paths = {}
            for kind in (1,2,3):
                pointer = get_directory(kind)
                assert pointer
                paths[str(kind)] = ctypes.string_at(pointer).decode('utf-8')
                free(pointer)
            report['vlc_directories'] = paths
            check('实际VLC配置数据缓存均解析到包内portable', all(Path(path) == base/'portable' for path in paths.values()))
        ffmpeg = BUNDLE/'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        samples = base/'test-media'
        samples.mkdir()
        sample = samples/'原文件名.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=20',
                        '-t','20','-c:v','libx264','-threads','2','-y',str(sample)],
                       check=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        loaded = window.load_folder(str(samples))
        check('真实样例扫描成功',wait(lambda:not loaded.pending) and loaded.outcome.succeeded)
        context = window.library_controller.browsing
        vid = context.folders[str(samples)][1][0][0]
        window.start(context,(str(samples),0))
        window.player.audio_set_mute(True)
        check('内置VLC实际播放',wait(lambda:window.player.get_time()>800))
        check('缩略图缓存写入包内',wait(lambda:(base/'data/thumbnails'/f'{vid}.jpg').is_file()))
        media = window.player.get_media().get_mrl()
        operation = window.classification.archive(vid,8,['教程'])
        check('无需选择目录即可归档成功',wait(lambda:not operation.pending) and operation.outcome.succeeded)
        target = window.catalog.resolve(vid)
        check('默认归档使用video评分标签目录且不改名',target == base/'video/8分/教程/原文件名.mp4' and target.is_file())
        check('默认归档仍持续播放',window.player.get_media().get_mrl()==media and window.player.get_state()==window.vlc.State.Playing)
        window.storage.save(window.storage.root,window.storage.folders)
        check('默认归档配置保存相对标记',json.loads(window.storage.file.read_text(encoding='utf-8'))['archive_root']=='video')
        check('重新读取默认配置有效',StorageSettings(base/'data').root==base/'video')
        window.grab().save(str(output/'portable-default.png'))
        window.clear_player()
        window.cleanup.request(force=True)
        check('源入口释放后清理不阻塞',wait(lambda:window.cleanup.active is None) and not errors)
        window.close()
        application.processEvents()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        window.player.release()
        window.instance.release()
        window.store.db.close()
        window = None
        check('本次运行未新增或改变已检查的用户目录缓存',profile_snapshot()==profiles)
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        if window is not None:
            window.close()
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
