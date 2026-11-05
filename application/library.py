"""Library workflows. Browsing never owns or replaces the playback session.

The scanner, repository and dispatcher are injected ports. Completions and
notifications are delivered on the application thread by the dispatcher.
"""
from dataclasses import dataclass
from threading import Event

from application.operations import Operation, Outcome, Status


@dataclass(frozen=True)
class NavigationStep:
    location: tuple | None = None
    needs_scan: bool = False


@dataclass(frozen=True)
class BrowseResult:
    snapshot: object
    errors: tuple
    location: tuple | None = None


@dataclass(frozen=True)
class LibraryChange:
    kind: str
    video_ids: tuple = ()


@dataclass(frozen=True)
class LibrarySelection:
    video_id: str
    context: object = None
    location: tuple | None = None


@dataclass(frozen=True)
class _LibraryTask:
    cancel: Event
    operation: Operation
    playback_request: bool = False


class LibraryController:
    def __init__(self, repository, scanner, dispatch):
        self.repository, self.scanner, self.dispatch = repository, scanner, dispatch
        self.browsing = None
        self.details = {}
        self._lists = {}
        self._tasks = {}
        self._observers = []

    def subscribe(self, observer):
        self._observers.append(observer)

    def _changed(self, kind, ids=()):
        change = LibraryChange(kind, tuple(ids))
        for observer in tuple(self._observers):
            observer(change)

    @property
    def scanning(self):
        return bool(self._tasks)

    @property
    def navigation_pending(self):
        return 'navigation' in self._tasks

    def cancel(self, slot=None):
        slots = tuple(self._tasks) if slot is None else (slot,)
        for key in slots:
            task = self._tasks.pop(key, None)
            if task is not None:
                task.cancel.set()
                task.operation.finish(Outcome(Status.CANCELLED))
        self._changed('scanning')

    def cancel_playback_requests(self):
        """An explicit playback choice supersedes navigation and pending opens.

        A directory import without a requested video remains independent.
        """
        for slot in tuple(self._tasks):
            task = self._tasks.get(slot)
            if task is not None and task.playback_request:
                self.cancel(slot)

    def _run(self, slot, work, publish=lambda value: value, *, playback_request=False):
        cancel, operation = Event(), Operation()
        previous = self._tasks.get(slot)
        task = _LibraryTask(cancel, operation, playback_request)
        self._tasks[slot] = task
        if previous is not None:
            previous.cancel.set()
            previous.operation.finish(Outcome(Status.CANCELLED))
        if self._tasks.get(slot) is not task:
            return operation
        self._changed('scanning')

        def ready(value, error):
            if self._tasks.get(slot) is not task:
                return
            del self._tasks[slot]
            self._changed('scanning')
            if cancel.is_set() or isinstance(error, InterruptedError):
                operation.finish(Outcome(Status.CANCELLED))
                return
            try:
                if error is not None:
                    raise error
                value = publish(value)
            except Exception as failure:
                operation.finish(Outcome(Status.FAILED, error=failure))
            else:
                operation.finish(Outcome(Status.SUCCEEDED, value=value))

        try:
            self.dispatch(lambda: work(cancel), ready)
        except Exception as error:
            ready(None, error)
        return operation

    @staticmethod
    def locate(snapshot, video_id):
        return next(((folder, number) for folder, (_, files) in snapshot.folders.items()
                     for number, (vid, _) in enumerate(files)
                     if vid == video_id and vid not in snapshot.excluded), None)

    def load_folder(self, folder, play_id=None):
        def work(cancel):
            snapshot, errors = self.scanner.scan(folder, cancel)
            ids = (vid for _, files in snapshot.folders.values() for vid, _ in files)
            return snapshot, tuple(errors), self.repository.video_details(ids)

        def publish(value):
            snapshot, errors, details = value
            location = self.locate(snapshot, play_id) if play_id else None
            if play_id and location is None:
                raise FileNotFoundError('扫描后未找到原视频身份；文件可能已被移动或替换。')
            self.repository.remember_folder(folder)
            self.adopt_snapshot(snapshot, details)
            return BrowseResult(snapshot, errors, location)

        return self._run('browse', work, publish, playback_request=play_id is not None)

    def adopt_snapshot(self, snapshot, details=None):
        """Publish a prepared browse snapshot; playback remains caller-owned."""
        if details is None:
            details = self.repository.video_details(
                vid for _, files in snapshot.folders.values() for vid, _ in files)
        self.details.update(details)
        self.browsing = snapshot
        self._changed('folder')

    def advance(self, context, location, direction):
        if self.navigation_pending:
            return self._tasks['navigation'].operation
        try:
            step = self.scanner.step(context, location, direction)
        except Exception as error:
            return Operation.completed(Outcome(Status.FAILED, error=error))
        if not step.needs_scan:
            return Operation.success(step.location)
        return self._run('navigation', lambda cancel:
                         self.scanner.step_loaded(context, location, direction, cancel), playback_request=True)

    def locate_video(self, video_id):
        """Prepare deletion context without changing the visible directory."""
        def work(cancel):
            folder = self.repository.resolve(video_id).parent
            snapshot, _ = self.scanner.scan(folder, cancel)
            location = self.locate(snapshot, video_id)
            if location is None:
                raise FileNotFoundError('所选视频已不可访问。')
            return snapshot, location
        return self._run('context', work)

    def load_list(self, mode):
        rows = self.repository.videos(mode)
        self.details.update((row['id'], row) for row in rows)
        self._lists[mode] = [row['id'] for row in rows]
        self._changed('videos')

    def list_rows(self, mode):
        return [self.details[vid] for vid in self._lists.get(mode, ())]

    def refresh(self, video_ids, playback_context=None):
        ids = tuple(dict.fromkeys(video_ids))
        rows = self.repository.video_details(ids)
        self.details.update(rows)
        for vid in set(ids) - rows.keys():
            self.details.pop(vid, None)
        for snapshot in (self.browsing, playback_context):
            if snapshot is None:
                continue
            for _, files in snapshot.folders.values():
                for number, (vid, name) in enumerate(files):
                    if vid in rows:
                        files[number] = (vid, rows[vid]['name'])
            snapshot.visible_cache.clear()
        for mode, listing in self._lists.items():
            for vid in ids:
                row = rows.get(vid)
                included = row is not None and bool(row['star'] if mode == 'stars' else row['played'])
                if included and vid not in listing:
                    listing.append(vid)
                elif not included and vid in listing:
                    listing.remove(vid)
            listing.sort(key=lambda vid: self.details[vid]['played'], reverse=True)
        self._changed('videos', ids)

    def exclude(self, video_ids, playback_context=None):
        ids = tuple(video_ids)
        for snapshot in (self.browsing, playback_context):
            if snapshot is not None:
                snapshot.excluded.update(ids)
                snapshot.visible_cache.clear()
        self.refresh(ids, playback_context)

    def remove_favorite(self, video_id):
        self.repository.set_favorite(video_id, False)
        self.refresh((video_id,))
