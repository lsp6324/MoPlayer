"""Resource paths and explicit native playback bootstrap.

Importing UI/application modules must not load DLLs or change the environment.
Only creating a player (or an explicit native integration test) calls load_vlc.
"""
from functools import lru_cache
import importlib
import os
from pathlib import Path
import sys


BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
BUNDLE = Path(getattr(sys, '_MEIPASS', BASE))
_dll_handle = None


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
