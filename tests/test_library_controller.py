"""Application protocols run without Qt, VLC or the legacy file implementation."""
from pathlib import Path
from types import SimpleNamespace

from application.library import LibraryController, NavigationStep
from application.operations import Status


def snapshot(root, *ids):
    root = str(root)
    return SimpleNamespace(root=root, folders={root: ([], [(vid, vid + '.mp4') for vid in ids])},
                           excluded=set(), visible_cache={})


def video(vid, *, played=1, star=0, name=None):
    return dict(id=vid, name=name or vid + '.mp4', played=played, star=star, position=0, score=None)


class Repository:
    def __init__(self):
        self.rows = {vid: video(vid) for vid in ('a', 'b', 'c')}
        self.history = []

    def video_details(self, ids):
        return {vid: dict(self.rows[vid]) for vid in ids if vid in self.rows}

    def videos(self, mode):
        key = 'star' if mode == 'stars' else 'played'
        return sorted((dict(row) for row in self.rows.values() if row[key]), key=lambda row: -row['played'])

    def resolve(self, vid):
        return Path('/library') / (vid + '.mp4')

    def remember_folder(self, folder):
        self.history.append(folder)

    def set_favorite(self, vid, value):
        self.rows[vid]['star'] = int(value)


class Scanner:
    def __init__(self):
        self.snapshots = {'A': snapshot('A', 'a'), 'B': snapshot('B', 'b'), 'C': snapshot('C', 'c'),
                          str(Path('/library')): snapshot('/library', 'a', 'b', 'c')}
        self.next = ('next', 0)

    def scan(self, folder, cancel):
        # Intentionally ignore cancellation, as an already-finished worker can.
        return self.snapshots[str(folder)], []

    def refresh(self, folder, cancel):
        return self.scan(folder, cancel)[0]

    def can_import(self, path):
        return path in ('A', 'B', 'C', '/library/b.mp4', '/library/c.mp4')

    def scan_import(self, path, cancel):
        if path.endswith('.mp4'):
            return self.snapshots[str(Path('/library'))], [], Path(path).stem
        context, errors = self.scan(path, cancel)
        return context, errors, None

    def step(self, context, location, direction):
        return NavigationStep(needs_scan=True)

    def step_loaded(self, context, location, direction, cancel):
        return self.next


def controller():
    tasks = []
    repo, scanner = Repository(), Scanner()
    library = LibraryController(repo, scanner, lambda work, ready: tasks.append((work, ready)))
    return library, repo, scanner, tasks


def finish(task):
    work, ready = task
    try:
        result = work()
    except Exception as error:
        ready(None, error)
    else:
        ready(result, None)


def test_latest_scan_wins_even_if_old_success_arrives_last():
    library, repo, _, tasks = controller()
    first = library.load_folder('A')
    second = library.load_folder('B')
    assert first.outcome.status is Status.CANCELLED
    finish(tasks[1])
    published = library.browsing
    finish(tasks[0])
    assert second.outcome.succeeded and published.root == 'B'
    assert library.browsing is published and repo.history == ['B']
    assert not library.scanning


def test_import_selects_requested_identity_and_folder_import_does_not_autoplay():
    library, repo, _, tasks = controller()
    changes = []
    library.subscribe(changes.append)
    operation = library.import_path('/library/c.mp4')
    finish(tasks.pop())
    result = operation.outcome.value
    assert operation.outcome.succeeded and result.location == ('/library', 2)
    assert next(change for change in changes if change.kind == 'folder').location == result.location
    assert repo.history == ['/library']
    operation = library.import_path('B')
    finish(tasks.pop())
    assert operation.outcome.succeeded and operation.outcome.value.location is None
    assert library.browsing.root == 'B'


def test_latest_video_import_wins_even_when_previous_scan_finishes_last():
    library, repo, _, tasks = controller()
    first = library.import_path('/library/b.mp4')
    last = library.import_path('/library/c.mp4')
    finish(tasks[1])
    finish(tasks[0])
    assert first.outcome.status is Status.CANCELLED
    assert last.outcome.value.location == ('/library', 2)
    assert repo.history == ['/library']


def test_explicit_playback_cancels_pending_video_import():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.import_path('/library/b.mp4')
    library.cancel_playback_requests()
    finish(tasks[0])
    assert operation.outcome.status is Status.CANCELLED
    assert library.browsing.root == 'A' and not repo.history


def test_failed_video_import_preserves_previous_browse_and_history():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.import_path('/library/b.mp4')
    tasks[0][1](None, FileNotFoundError('removed after drop'))
    assert operation.outcome.status is Status.FAILED
    assert library.browsing.root == 'A' and not repo.history


def test_background_contents_refresh_does_not_mutate_playback_or_write_history():
    library, repo, scanner, tasks = controller()
    original = scanner.snapshots['A']
    library.adopt_snapshot(original)
    scanner.snapshots['A'] = snapshot('A', 'b', 'a')
    changes = []
    library.subscribe(changes.append)
    operation = library.refresh_browsing()
    assert not library.scanning and library.refresh_pending
    assert library.refresh_browsing() is operation and len(tasks) == 1
    finish(tasks[0])
    assert operation.outcome.succeeded and library.browsing is not original
    assert original.folders['A'][1] == [('a', 'a.mp4')]
    assert library.browsing.folders['A'][1][0][0] == 'b' and not repo.history
    assert [change.kind for change in changes].count('contents') == 1


def test_new_import_cancels_old_background_refresh_without_late_publication():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    refresh = library.refresh_browsing()
    browse = library.load_folder('B')
    finish(tasks[1])
    finish(tasks[0])
    assert refresh.outcome.status is Status.CANCELLED and browse.outcome.succeeded
    assert library.browsing.root == 'B' and repo.history == ['B']


def test_background_refresh_failure_keeps_visible_contents_and_can_retry():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.refresh_browsing()
    tasks[0][1](None, PermissionError('temporary'))
    assert operation.outcome.status is Status.FAILED and library.browsing is scanner.snapshots['A']
    operation = library.refresh_browsing()
    finish(tasks[1])
    assert operation.outcome.succeeded and not repo.history


def test_background_refresh_waits_for_file_work_and_rejects_completion_during_busy():
    library, _, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    library.refresh_allowed = lambda: False
    assert library.refresh_browsing().outcome.status is Status.CANCELLED and not tasks
    library.refresh_allowed = lambda: True
    operation = library.refresh_browsing()
    library.refresh_allowed = lambda: False
    finish(tasks[0])
    assert operation.outcome.status is Status.CANCELLED and library.browsing is scanner.snapshots['A']


def test_progress_refresh_does_not_overwrite_actual_external_entry_names():
    library, repo, _, _ = controller()
    original = snapshot('A', 'a')
    library.adopt_snapshot(original)
    original.folders['A'][1][0] = ('a', 'external-name.mp4')
    repo.rows['a']['position'] = 12000
    library.refresh(['a'], original)
    assert original.folders['A'][1][0][1] == 'external-name.mp4'


def test_background_delivery_does_not_overwrite_newer_metadata_updates():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.refresh_browsing()
    work, ready = tasks[0]
    scanned = work()
    repo.rows['a']['position'] = 15000
    library.refresh(['a'])
    ready(scanned, None)
    assert operation.outcome.succeeded and library.details['a']['position'] == 15000


def test_cancel_preserves_visible_folder_and_prevents_requested_playback():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.load_folder('B', 'b')
    library.cancel()
    finish(tasks[0])
    assert operation.outcome.status is Status.CANCELLED
    assert library.browsing.root == 'A' and repo.history == []


def test_old_failure_does_not_clear_new_scan_or_surface_as_current_error():
    library, _, _, tasks = controller()
    first = library.load_folder('A')
    second = library.load_folder('B')
    tasks[0][1](None, PermissionError('old inaccessible directory'))
    assert library.scanning and second.pending
    assert first.outcome.status is Status.CANCELLED
    finish(tasks[1])
    assert library.browsing.root == 'B'


def test_cancel_one_task_does_not_hide_another_active_task():
    library, _, scanner, tasks = controller()
    events = []
    library.subscribe(lambda change: events.append(library.scanning) if change.kind == 'scanning' else None)
    browse = library.load_folder('A')
    navigation = library.advance(scanner.snapshots['B'], ('B', 0), 1)
    library.cancel('navigation')
    assert navigation.outcome.status is Status.CANCELLED
    assert events[-1] and browse.pending
    finish(tasks[1])
    assert library.scanning
    finish(tasks[0])
    assert not library.scanning and not events[-1]


def test_missing_requested_identity_keeps_old_folder_and_history():
    library, repo, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.load_folder('B', 'c')
    finish(tasks[0])
    assert isinstance(operation.outcome.error, FileNotFoundError)
    assert library.browsing.root == 'A' and repo.history == []


def test_scan_failure_and_interruption_are_distinct_results():
    library, _, _, tasks = controller()
    failed = library.load_folder('A')
    tasks[0][1](None, PermissionError('denied'))
    assert failed.outcome.status is Status.FAILED and library.browsing is None
    cancelled = library.load_folder('B')
    tasks[1][1](None, InterruptedError())
    assert cancelled.outcome.status is Status.CANCELLED and not library.scanning


def test_browsing_does_not_replace_navigation_context_or_results():
    library, _, scanner, tasks = controller()
    playback = scanner.snapshots['A']
    operation = library.advance(playback, ('A', 0), 1)
    library.load_folder('B')
    finish(tasks[1])
    finish(tasks[0])
    assert library.browsing.root == 'B'
    assert playback.root == 'A' and operation.outcome.value == ('next', 0)


def test_repeated_navigation_shares_one_pending_operation():
    library, _, scanner, tasks = controller()
    operation = library.advance(scanner.snapshots['A'], ('A', 0), 1)
    assert library.advance(scanner.snapshots['A'], ('A', 0), 1) is operation
    assert len(tasks) == 1
    finish(tasks[0])
    assert not library.navigation_pending


def test_deletion_context_uses_frozen_identity_without_changing_browsing():
    library, _, scanner, tasks = controller()
    library.adopt_snapshot(scanner.snapshots['A'])
    operation = library.locate_video('c')
    finish(tasks[0])
    context, location = operation.outcome.value
    assert context.folders[location[0]][1][location[1]][0] == 'c'
    assert library.browsing.root == 'A'


def test_metadata_and_exclusion_keep_original_playback_indices():
    library, repo, _, _ = controller()
    browse = snapshot('visible', 'a', 'b', 'c')
    playback = snapshot('playing', 'a', 'b', 'c')
    library.adopt_snapshot(browse)
    repo.rows['b']['name'] = 'renamed.mp4'
    library.refresh(['b'], playback)
    assert browse.folders['visible'][1][1] == playback.folders['playing'][1][1] == ('b', 'renamed.mp4')
    del repo.rows['a']
    library.exclude(['a'], playback)
    assert browse.excluded == playback.excluded == {'a'}
    assert playback.folders['playing'][1][2][0] == 'c' and 'a' not in library.details


def test_lists_reconcile_only_changed_id_and_favorite_membership():
    library, repo, _, _ = controller()
    repo.rows['b']['star'] = 1
    library.load_list('videos')
    library.load_list('stars')
    repo.rows['c'].update(played=10, star=1)
    library.refresh(['c'])
    assert [row['id'] for row in library.list_rows('videos')] == ['c', 'a', 'b']
    assert [row['id'] for row in library.list_rows('stars')] == ['c', 'b']
    repo.set_favorite('b', False)
    library.refresh(('b',))
    assert [row['id'] for row in library.list_rows('stars')] == ['c']
    assert repo.rows['b']['star'] == 0


def test_dispatch_failure_completes_operation_and_clears_scan_state():
    library, _, _, _ = controller()
    def rejected(work, ready):
        raise RuntimeError('dispatcher unavailable')
    library.dispatch = rejected
    operation = library.load_folder('A')
    assert operation.outcome.status is Status.FAILED and not library.scanning


def test_new_playback_choice_cancels_old_open_but_keeps_independent_browsing():
    library, _, scanner, tasks = controller()
    browsing = library.load_folder('A')
    navigation = library.advance(scanner.snapshots['B'], ('B', 0), 1)
    library.cancel_playback_requests()
    assert browsing.pending and navigation.outcome.status is Status.CANCELLED
    finish(tasks[0])
    assert browsing.outcome.succeeded and library.browsing.root == 'A'
    opening = library.load_folder('B', 'b')
    library.cancel_playback_requests()
    finish(tasks[-1])
    assert opening.outcome.status is Status.CANCELLED and library.browsing.root == 'A'


def test_reentrant_choice_during_cancellation_keeps_latest_scan():
    library, _, _, tasks = controller()
    first = library.load_folder('A')
    first.on_finished(lambda outcome: library.load_folder('C'))
    middle = library.load_folder('B')
    assert middle.outcome.status is Status.CANCELLED
    assert len(tasks) == 2  # A's worker and C's worker; B was superseded before dispatch.
    finish(tasks[1])
    finish(tasks[0])
    assert library.browsing.root == 'C'
