"""Reveal an already resolved local file without invoking a command shell."""
from pathlib import Path
import subprocess


def reveal_file(path):
    target = Path(path).absolute()
    if not target.is_file():
        raise FileNotFoundError('文件已不存在或无法访问。')
    return subprocess.Popen(['explorer.exe', '/select,', str(target)],
                            creationflags=subprocess.CREATE_NO_WINDOW)
