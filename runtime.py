"""Resource paths and explicit native playback bootstrap.

Importing UI/application modules must not load DLLs or change the environment.
Only creating a player (or an explicit native integration test) calls load_vlc.
"""
from functools import lru_cache
import importlib
import os
from pathlib import Path
import sys
import tempfile


BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
BUNDLE = Path(getattr(sys, '_MEIPASS', BASE))
_dll_handle = None


def configure_portable(base=BASE):
    """Set process-local cache locations before creating Qt or VLC objects.

    VLC 3 on Windows recognizes `portable` beside the process executable.
    Never change the user's profile environment or move existing system caches.
    """
    base = Path(base).absolute()
    if getattr(sys, 'frozen', False) and len(str(sys.executable).encode('utf-16-le')) // 2 >= 260:
        raise OSError('VLC 便携目录要求程序路径少于 260 个字符，请缩短解压路径。')
    temporary = base / 'data' / 'temp'
    for directory in (temporary, base / 'portable'):
        directory.mkdir(parents=True, exist_ok=True)
    # Qt's OpenGL cache uses Windows known folders, with no path override.
    # Disable that optional disk cache rather than silently using AppData.
    os.environ['QT_DISABLE_SHADER_DISK_CACHE'] = '1'
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    tempfile.tempdir = str(temporary)
    from PySide6.QtCore import QCoreApplication, QSettings, Qt
    QCoreApplication.setOrganizationName('MoPlayer')
    QCoreApplication.setApplicationName('MoPlayer')
    QCoreApplication.setAttribute(Qt.AA_DisableShaderDiskCache)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(base / 'data' / 'qt-settings'))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(base / 'data' / 'qt-settings'))


@lru_cache(maxsize=1)
def load_vlc():
    global _dll_handle
    directory = (BUNDLE / 'vlc' if getattr(sys, 'frozen', False) else
                 Path(os.environ.get('MOPLAYER_VLC_DIR', BASE / 'dist/MoPlayer-UI-preview/_internal/vlc')))
    os.environ['PYTHON_VLC_LIB_PATH'] = str(directory / 'libvlc.dll')
    os.environ['PYTHON_VLC_MODULE_PATH'] = str(directory)
    os.environ['VLC_PLUGIN_PATH'] = str(directory / 'plugins')
    _dll_handle = os.add_dll_directory(str(directory))
    return importlib.import_module('vlc')


def create_player():
    vlc = load_vlc()
    instance = vlc.Instance('--no-video-title-show', '--no-metadata-network-access', '--no-snapshot-preview')
    player = instance.media_player_new()
    player.video_set_key_input(False)
    player.video_set_mouse_input(False)
    return vlc, instance, player
