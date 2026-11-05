"""Adapter for the existing scan and playback-order rules; no UI ownership."""
from pathlib import Path
import stat

from application.library import NavigationStep
from core import EXTENSIONS, ScanRequired, scan


class LibraryScanner:
    def __init__(self, store):
        self.store = store

    def scan(self, folder, cancel):
        return scan(folder, self.store, cancel)

    @staticmethod
    def _import_target(path):
        target = Path(path).absolute()
        info = target.stat(follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            return target, False
        if (stat.S_ISREG(info.st_mode) and target.suffix.lower() in EXTENSIONS
                and not getattr(info, 'st_file_attributes', 0) & 0x400):
            return target, True
        raise ValueError('请拖入一个文件夹或受支持的视频文件。')

    def can_import(self, path):
        try:
            self._import_target(path)
        except (OSError, ValueError):
            return False
        return True

    def scan_import(self, path, cancel):
        """Revalidate at execution time and freeze identity before scanning."""
        if cancel.is_set():
            raise InterruptedError('扫描已取消')
        target, is_video = self._import_target(path)
        video_id = self.store.register(target) if is_video else None
        snapshot, errors = self.scan(target.parent if is_video else target, cancel)
        return snapshot, errors, video_id

    def step(self, context, location, direction):
        try:
            return NavigationStep(context.step(location, direction))
        except ScanRequired:
            return NavigationStep(needs_scan=True)

    def step_loaded(self, context, location, direction, cancel):
        return context.step_loaded(location, direction, self.store, cancel)
