"""Adapter for the existing scan and playback-order rules; no UI ownership."""
from pathlib import Path
import os
import stat

from moplayer.application.library import NavigationStep
from moplayer.core import EXTENSIONS, ScanRequired, Snapshot, scan, natural


class DirectorySnapshot(Snapshot):
    """One loaded directory; children are listed but read only when opened."""


class LibraryScanner:
    def __init__(self, store):
        self.store = store

    def scan(self, folder, cancel):
        return scan(folder, self.store, cancel)

    def directory(self, folder, cancel):
        root = Path(folder).absolute()
        if cancel.is_set():
            raise InterruptedError('目录读取已取消')
        children, files, errors = [], [], []
        # Opening the requested directory must succeed before publishing it.
        # Never recurse into its children, including when root is a drive.
        with os.scandir(root) as iterator:
            entries = sorted(iterator, key=lambda entry: natural(entry.name))
        for entry in entries:
            if cancel.is_set():
                raise InterruptedError('目录读取已取消')
            try:
                info = entry.stat(follow_symlinks=False)
                if getattr(info, 'st_file_attributes', 0) & 0x400 or entry.is_symlink():
                    continue
                if stat.S_ISDIR(info.st_mode):
                    children.append(entry.path)
                elif stat.S_ISREG(info.st_mode) and Path(entry.name).suffix.lower() in EXTENSIONS:
                    files.append((self.store.register(entry.path), entry.name))
            except InterruptedError:
                raise
            except OSError as error:
                errors.append(f'{entry.path}: {error}')
        # Preserve the existing one-level sibling playback boundary. Only
        # directory names are read here; their media remain unloaded.
        siblings = []
        if root.parent != root:
            try:
                with os.scandir(root.parent) as iterator:
                    for entry in iterator:
                        if cancel.is_set():
                            raise InterruptedError('目录读取已取消')
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400 and not entry.is_symlink():
                                siblings.append(entry.path)
                        except OSError:
                            continue
            except InterruptedError:
                raise
            except OSError:
                pass
        if cancel.is_set():
            raise InterruptedError('目录读取已取消')
        snapshot = DirectorySnapshot(str(root), {str(root): (children, files)},
                                     sorted(siblings, key=lambda path: natural(Path(path).name)))
        return snapshot, errors

    def refresh_snapshot(self, snapshot, cancel):
        if not isinstance(snapshot, DirectorySnapshot):
            return self.refresh(snapshot.root, cancel)
        folder = Path(snapshot.root)
        while True:
            try:
                refreshed, errors = self.directory(folder, cancel)
                if errors:
                    raise OSError('目录暂时无法完整读取：' + errors[0])
                return refreshed
            except FileNotFoundError:
                if folder.parent == folder:
                    raise
                folder = folder.parent

    def refresh(self, folder, cancel):
        root = Path(folder)
        if cancel.is_set():
            raise InterruptedError('刷新已取消')
        try:
            # Missing roots become empty views; permission errors retain the old view.
            with os.scandir(root) as entries:
                next(entries, None)
        except FileNotFoundError:
            return Snapshot(str(root), {str(root): ([], [])})
        snapshot, errors = self.scan(root, cancel)
        if errors:
            raise OSError('目录暂时无法完整读取：' + errors[0])
        return snapshot

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
