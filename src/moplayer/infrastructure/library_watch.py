"""Qt directory notifications, debounce and retry around library refresh."""
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QFileSystemWatcher, QTimer


class LibraryWatch(QObject):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._closed = False
        self._dirty = False
        self._root_identity = None
        self._fallback = {}
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._changed)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(400)
        self.debounce.timeout.connect(self._refresh)
        self.poll = QTimer(self)
        self.poll.setInterval(2000)
        self.poll.timeout.connect(self._probe)
        controller.subscribe(self._library_changed)

    @staticmethod
    def _stamp(path):
        try:
            info = Path(path).stat()
            return info.st_dev, info.st_ino, info.st_mtime_ns
        except OSError:
            return None

    def _library_changed(self, change):
        if not self._closed and change.kind in ('folder', 'directory', 'contents'):
            self._bind()
            self.poll.start()

    def _bind(self):
        snapshot = self.controller.browsing
        if snapshot is None:
            return
        desired = set(snapshot.folders)
        parent = Path(snapshot.root).parent
        while not parent.is_dir() and parent.parent != parent:
            parent = parent.parent
        if parent.is_dir():
            desired.add(str(parent))
        current = set(self.watcher.directories())
        if current - desired:
            self.watcher.removePaths(sorted(current - desired))
        failed = self.watcher.addPaths(sorted(desired - current)) if desired - current else []
        self._fallback = {path: self._stamp(path) for path in failed}
        self._root_identity = self._stamp(snapshot.root)

    def _changed(self, path):
        snapshot = self.controller.browsing
        if self._closed or snapshot is None:
            return
        # Watching the nearest parent permits root deletion/recreation without
        # refreshing for unrelated siblings changing in that parent.
        if path not in snapshot.folders and self._stamp(snapshot.root) == self._root_identity:
            return
        self._dirty = True
        self.debounce.start(400)

    def _probe(self):
        snapshot = self.controller.browsing
        if self._closed or snapshot is None:
            return
        changed = self._stamp(snapshot.root) != self._root_identity
        for path, previous in self._fallback.items():
            if self._stamp(path) != previous:
                changed = True
        if changed:
            self._dirty = True
        if self._dirty and not self.debounce.isActive():
            self.debounce.start()

    def _refresh(self):
        if self._closed or not self._dirty:
            return
        if self.controller.refresh_pending:
            self.debounce.start()
            return
        self._dirty = False
        operation = self.controller.refresh_browsing()

        def ready(outcome):
            if self._closed:
                return
            if not outcome.succeeded:
                self._dirty = True
                if outcome.error:
                    logging.warning('目录自动刷新暂缓：%s', outcome.error)
                self.debounce.start(2000)
            elif self._dirty:
                self.debounce.start(400)
        operation.on_finished(ready)

    def stop(self):
        self._closed = True
        self.debounce.stop()
        self.poll.stop()
        paths = self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)
