"""Library workflows. Browsing never owns or replaces the playback session.

The scanner, repository and dispatcher are injected ports. Completions and
notifications are delivered on the application thread by the dispatcher.
"""
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from application.operations import Operation, Outcome, Status
from application.catalog import CatalogFilter, CatalogContext, select_rows


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
    location: tuple | None = None


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
    def __init__(self, repository, scanner, dispatch, *, refresh_allowed=lambda: True):
        self.repository, self.scanner, self.dispatch = repository, scanner, dispatch
        self.refresh_allowed = refresh_allowed
        self.browsing = None
        self.details = {}
        self._lists = {}
        self._tasks = {}
        self._observers = []
        self.catalog_filter = CatalogFilter()
        self.catalog_schema = {}
        self.catalog_ids = []
        self.catalog_total = 0
        self.catalog_loaded = False
        self.catalog_error = None
        self._catalog_revision = 0

    def subscribe(self, observer):
        self._observers.append(observer)

    def _changed(self, kind, ids=(), *, location=None):
        change = LibraryChange(kind, tuple(ids), location)
        for observer in tuple(self._observers):
            observer(change)

    @property
    def scanning(self):
        return any(slot not in ('refresh', 'catalog') for slot in self._tasks)

    @property
    def catalog_pending(self):
        return 'catalog' in self._tasks

    def query_catalog(self, filters=None):
        if filters is not None:
            self.catalog_filter = filters
        filters, revision = self.catalog_filter, self._catalog_revision
        baseline = dict(self.details)
        self.catalog_error = None

        def work(cancel):
            rows, schema = self.repository.catalog_data()
            return select_rows(rows, schema, filters, cancel), schema, len(rows)

        def publish(value):
            if revision != self._catalog_revision:
                raise InterruptedError('资料库已更新')
            rows, schema, total = value
            for row in rows:
                current = self.details.get(row['id'], {})
                previous = baseline.get(row['id'], {})
                if 'unavailable' in current:
                    row['unavailable'] = current['unavailable']
                for key in ('position', 'played'):
                    if current.get(key) != previous.get(key):
                        row[key] = current[key]
            if filters.sort == 'played':
                rows = select_rows(rows, schema, filters, Event())
            self.details.update((row['id'], row) for row in rows)
            self.catalog_ids = [row['id'] for row in rows]
            self.catalog_schema, self.catalog_total = schema, total
            self.catalog_loaded = True
            self._changed('catalog')
            return tuple(self.catalog_ids)

        operation = self._run('catalog', work, publish)
        def finished(outcome):
            if outcome.status is Status.FAILED:
                self.catalog_error = str(outcome.error)
                self._changed('catalog')
        operation.on_finished(finished)
        return operation

    def rename_catalog_tags(self, renames):
        """Keep selected tag predicates attached to a confirmed global rename."""
        self.catalog_filter = self.catalog_filter.updated(
            tags=tuple(dict.fromkeys(renames.get(name, name) for name in self.catalog_filter.tags)))

    def catalog_selection(self, video_id, *, allow_pending=False):
        if (self.catalog_pending and not allow_pending) or video_id not in self.catalog_ids:
            return None
        rows = self.list_rows('catalog')
        context = CatalogContext(rows)
        return LibrarySelection(video_id, context, (context.root, self.catalog_ids.index(video_id)))

    def media_availability(self, video_id, error=None):
        if video_id in self.details:
            self.details[video_id] = dict(self.details[video_id], unavailable=str(error) if error else '')
            self._changed('videos', (video_id,))

    @property
    def refresh_pending(self):
        return 'refresh' in self._tasks

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
            except InterruptedError:
                operation.finish(Outcome(Status.CANCELLED))
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

    def last_folder(self):
        """The folder loaded most recently, so a restart can reopen it."""
        rows = self.repository.folders()
        return Path(rows[0]['path']) if rows else None

    def load_folder(self, folder, play_id=None):
        def scan(cancel):
            snapshot, errors = self.scanner.scan(folder, cancel)
            return snapshot, errors, play_id
        return self._browse(scan, playback_request=play_id is not None)

    def can_import(self, path):
        return self.scanner.can_import(path)

    def import_path(self, path):
        """An explicit drop may select a video; superseded imports cannot play."""
        return self._browse(lambda cancel: self.scanner.scan_import(path, cancel), playback_request=True)

    def _browse(self, scan, *, playback_request):
        self.cancel('refresh')
        def work(cancel):
            snapshot, errors, play_id = scan(cancel)
            ids = (vid for _, files in snapshot.folders.values() for vid, _ in files)
            return snapshot, tuple(errors), self.repository.video_details(ids), play_id

        def publish(value):
            snapshot, errors, details, play_id = value
            location = self.locate(snapshot, play_id) if play_id else None
            if play_id and location is None:
                raise FileNotFoundError('扫描后未找到原视频身份；文件可能已被移动或替换。')
            self.repository.remember_folder(snapshot.root)
            self.adopt_snapshot(snapshot, details, location=location)
            return BrowseResult(snapshot, errors, location)

        return self._run('browse', work, publish, playback_request=playback_request)

    def refresh_browsing(self):
        """Replace only the browse snapshot; never change a playback context."""
        if self.refresh_pending:
            return self._tasks['refresh'].operation
        if self.browsing is None or 'browse' in self._tasks or not self.refresh_allowed():
            return Operation.cancelled()
        baseline = self.browsing
        baseline_details = dict(self.details)

        def work(cancel):
            snapshot = self.scanner.refresh(baseline.root, cancel)
            ids = (vid for _, files in snapshot.folders.values() for vid, _ in files)
            return snapshot, self.repository.video_details(ids)

        def publish(value):
            if self.browsing is not baseline or not self.refresh_allowed() or 'browse' in self._tasks:
                raise InterruptedError('浏览刷新已过期。')
            snapshot, details = value
            self.details.update((vid, row) for vid, row in details.items()
                                if self.details.get(vid) == baseline_details.get(vid))
            self.browsing = snapshot
            self._changed('contents')
            return snapshot

        return self._run('refresh', work, publish)

    def adopt_snapshot(self, snapshot, details=None, *, location=None):
        """Publish a prepared browse snapshot; playback remains caller-owned."""
        if details is None:
            details = self.repository.video_details(
                vid for _, files in snapshot.folders.values() for vid, _ in files)
        self.details.update(details)
        self.browsing = snapshot
        self._changed('folder', location=location)

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

    def clear_history(self):
        """Empty the recent list without touching metadata or playback progress."""
        self.repository.clear_history()
        self.load_list('videos')

    def list_rows(self, mode):
        ids = self.catalog_ids if mode == 'catalog' else self._lists.get(mode, ())
        return [self.details[vid] for vid in ids if vid in self.details]

    def refresh(self, video_ids, playback_context=None, *, catalog_changed=False):
        ids = tuple(dict.fromkeys(video_ids))
        rows = self.repository.video_details(ids)
        fields = ('name', 'score', 'star', 'tags', 'in_library', 'library_added_at')
        changed = catalog_changed or any(
            any(self.details.get(vid, {}).get(key) != rows.get(vid, {}).get(key) for key in fields) for vid in ids)
        # Preserve prepared presentation fields when progress-only refreshes arrive.
        rows = {vid: dict(self.details.get(vid, {}), **row) for vid, row in rows.items()}
        renamed = {vid for vid, row in rows.items() if self.details.get(vid, {}).get('name') != row['name']}
        self.details.update(rows)
        for vid in set(ids) - rows.keys():
            self.details.pop(vid, None)
        for snapshot in (self.browsing, playback_context):
            if snapshot is None:
                continue
            for _, files in snapshot.folders.values():
                for number, (vid, name) in enumerate(files):
                    if vid in renamed:
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
        if not changed and self.catalog_filter.sort == 'played':
            self.catalog_ids.sort(key=lambda vid: -self.details.get(vid, {}).get('played', 0))
            self._changed('catalog', ids)
        if changed and (self.catalog_loaded or self.catalog_pending):
            self._catalog_revision += 1
            self.query_catalog()

    def exclude(self, video_ids, playback_context=None):
        ids = tuple(video_ids)
        for snapshot in (self.browsing, playback_context):
            if snapshot is not None:
                snapshot.excluded.update(ids)
                snapshot.visible_cache.clear()
        self.refresh(ids, playback_context)
