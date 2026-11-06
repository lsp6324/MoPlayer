import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import pytest
from moplayer.core import Store, identity
from moplayer.application.archive_folders import ArchiveFolders
from moplayer.application.takeover import TakeoverRules, infer, Takeover
from moplayer.application.operations import Operation, Outcome, Status
from moplayer.application.file_tasks import FileTasks
from moplayer.infrastructure.takeover import TakeoverService


@pytest.fixture
def store(tmp_path):
    data = Store(tmp_path / 'data')
    yield data
    data.db.close()


def media(root, relative, content=b'takeover media'):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def preview(store, root, rules=TakeoverRules()):
    return TakeoverService(store).preview(str(root), rules, Event())


def apply(store, plan, **options):
    return TakeoverService(store).apply(plan, frozenset(item.file.identity for item in plan.items), **options)


def dump(store):
    return tuple(store.db.iterdump())


@pytest.mark.parametrize('parts,rules,expected', [
    (('any', '8分'), TakeoverRules(), (None, None, ())),
    (('year', '摄影', '山川'), TakeoverRules('tags', 2, 3), (None, None, ('摄影', '山川'))),
    (('摄影', '山川'), TakeoverRules('tags', 2, 0), (None, None, ('山川',))),
    (('已收藏', '0分', '摄影', '山川'), TakeoverRules('archive', folders=ArchiveFolders(favorite=True)), (0, True, ('摄影', '山川'))),
    (('未评分', '未收藏', '未分类'), TakeoverRules('archive', folders=ArchiveFolders(favorite=True, favorite_first=False)), (None, False, ())),
    ((), TakeoverRules('archive', folders=ArchiveFolders(False, False, False)), (None, None, ())),
])
def test_explicit_directory_rules_never_parse_filename(parts, rules, expected):
    assert infer(parts, rules) == expected


def test_unused_tag_range_does_not_block_switching_back_to_library_mode():
    with pytest.raises(ValueError):
        TakeoverRules('tags', 3, 1)
    assert infer(('any',), TakeoverRules('library', 3, 1)) == (None, None, ())


@pytest.mark.parametrize('parts', [('8',), ('11分',), ('8分', 'extra')])
def test_archive_rules_do_not_guess_unknown_directory_meaning(parts):
    with pytest.raises(ValueError):
        infer(parts, TakeoverRules('archive', folders=ArchiveFolders(tags=False)))


def test_read_only_preview_has_no_records_tags_or_schema_writes(store, tmp_path):
    root = tmp_path / 'old'
    media(root, '风景/山川/a.mp4')
    media(root, 'root.png')
    before, changes = dump(store), store.db.total_changes
    plan = preview(store, root, TakeoverRules('tags'))
    assert len(plan.items) == 2 and any(item.labels == ('风景 › 山川',) for item in plan.items)
    assert dump(store) == before and store.db.total_changes == changes


def test_plain_takeover_enrolls_unmarked_files_at_import_time_without_moving(store, tmp_path):
    root = tmp_path / 'old'
    paths = [media(root, 'video.mp4'), media(root, 'sub/image.png')]
    baseline = {str(path): (identity(path), path.read_bytes()) for path in paths}
    plan = preview(store, root)
    ids = apply(store, plan)
    assert len(ids) == 2
    rows = store.query('SELECT * FROM videos')
    assert all(row['in_library'] and row['library_added_at'] and not row['archived'] and row['archived_at'] is None for row in rows)
    assert all(row['score'] is None and row['star'] == 0 and row['tags'] == '[]' and row['played'] == row['position'] == 0 for row in rows)
    assert {str(path): (identity(path), path.read_bytes()) for path in paths} == baseline
    again = preview(store, root)
    assert set(apply(store, again)) == set(ids)
    assert store.query('SELECT * FROM videos') == rows


def test_nested_tags_hardlinks_are_merged_and_other_copies_stay_separate(store, tmp_path):
    root = tmp_path / 'old'
    first = media(root, '摄影/山川/a.mp4')
    linked = root / '摄影/海岸/alias.mp4'
    linked.parent.mkdir(parents=True)
    os.link(first, linked)
    copy = media(root, '摄影/海岸/copy.mp4', first.read_bytes())
    plan = preview(store, root, TakeoverRules('tags'))
    assert len(plan.items) == 2 and sorted(len(item.file.paths) for item in plan.items) == [1, 2]
    ids = apply(store, plan)
    linked_id = next(row['id'] for row in store.query('SELECT * FROM paths') if row['path'] == str(first))
    assert set(json.loads(store.video(linked_id)['tags'])) == {'山川', '海岸'}
    assert store.tag_layout()['山川']['parent'] == '摄影' and store.tag_layout()['摄影']['is_parent']
    assert len(ids) == 2 and len(store.query('SELECT * FROM paths')) == 3
    assert all(path.exists() for path in (first, linked, copy))


@pytest.mark.parametrize('favorite_first', [True, False])
def test_archive_takeover_reads_zero_rating_favorite_and_hierarchy_without_archiving(store, tmp_path, favorite_first):
    root = tmp_path / 'old'
    prefix = '已收藏/0分' if favorite_first else '0分/已收藏'
    path = media(root, prefix + '/摄影/山川/a.mp4')
    rules = TakeoverRules('archive', folders=ArchiveFolders(favorite=True, favorite_first=favorite_first))
    ids = apply(store, preview(store, root, rules))
    row = store.video(ids[0])
    assert row['score'] == 0 and row['star'] == 1 and json.loads(row['tags']) == ['山川'] and not row['archived']
    assert store.resolve(ids[0]) == path


def test_conflicting_hardlink_scores_require_explicit_enrollment_only(store, tmp_path):
    root = tmp_path / 'old'
    path = media(root, '4分/摄影/a.mp4')
    second = root / '8分/摄影/a.mp4'
    second.parent.mkdir(parents=True)
    os.link(path, second)
    plan = preview(store, root, TakeoverRules('archive'))
    assert len(plan.items) == 1 and any('不同评分' in error for error in plan.items[0].conflicts)
    with pytest.raises(ValueError, match='冲突'):
        apply(store, plan)
    assert not store.query('SELECT * FROM videos')
    ids = apply(store, plan, include_conflicts=True)
    assert store.video(ids[0])['score'] is None and store.video(ids[0])['tags'] == '[]'
    assert store.video(ids[0])['in_library'] and not store.tag_layout()


def test_duplicate_child_names_under_distinct_parents_are_both_conflicts(store, tmp_path):
    root = tmp_path / 'old'
    media(root, '摄影/其他/a.mp4')
    media(root, '电影/其他/b.mp4')
    plan = preview(store, root, TakeoverRules('tags'))
    assert all(item.conflicts for item in plan.items)
    apply(store, plan, include_conflicts=True)
    assert not store.tag_layout() and all(row['tags'] == '[]' for row in store.query('SELECT * FROM videos'))


def test_existing_marks_hierarchy_progress_dates_and_archived_state_are_preserved(store, tmp_path):
    root = tmp_path / 'old'
    path = media(root, '8分/风景/a.mp4')
    vid = store.register(path)
    store.execute('INSERT INTO tags VALUES(?)', ('原有',))
    store.execute('UPDATE videos SET score=0,tags=?,star=0,archived=1,archived_at=111,position=999,played=123,library_added_at=456 WHERE id=?', (json.dumps(['原有']), vid))
    original = store.video(vid)
    plan = preview(store, root, TakeoverRules('archive'))
    assert plan.items[0].kept_existing and plan.items[0].conflicts
    assert apply(store, plan, include_conflicts=True) == (vid,)
    assert store.video(vid) == original and set(store.tag_layout()) == {'原有'}


def test_previously_scanned_unmarked_record_can_receive_inferred_markers(store, tmp_path):
    root = tmp_path / 'old'
    path = media(root, '摄影/a.mp4')
    vid = store.register(path)
    store.progress(vid, 400)
    plan = preview(store, root, TakeoverRules('tags'))
    assert not plan.items[0].kept_existing
    assert apply(store, plan) == (vid,)
    assert json.loads(store.video(vid)['tags']) == ['摄影'] and store.video(vid)['position'] == 400


def test_mid_transaction_failure_rolls_back_every_record_and_tag_and_can_retry_same_plan(store, tmp_path):
    root = tmp_path / 'old'
    paths = [media(root, '摄影/a.mp4'), media(root, '风景/b.mp4')]
    plan = preview(store, root, TakeoverRules('tags'))
    before = dump(store)
    def fault(count):
        if count == 1:
            raise OSError('injected transaction failure')
    with pytest.raises(OSError):
        TakeoverService(store, fault=fault).apply(plan, {item.file.identity for item in plan.items})
    assert dump(store) == before and all(path.exists() for path in paths)
    assert len(apply(store, plan)) == 2


@pytest.mark.parametrize('change', ['file', 'schema', 'marker', 'binding'])
def test_stale_preview_never_imports_different_files_or_overwrites_newer_marks(store, tmp_path, change):
    root = tmp_path / 'old'
    path = media(root, '摄影/a.mp4')
    vid = store.register(path) if change == 'marker' else None
    plan = preview(store, root, TakeoverRules('tags'))
    if change == 'file':
        path.write_bytes(b'changed file contents')
    elif change == 'schema':
        store.execute('INSERT INTO tags VALUES(?)', ('new',))
    elif change == 'marker':
        store.execute('UPDATE videos SET score=9 WHERE id=?', (vid,))
    else:
        store.register(path)
    before = dump(store)
    with pytest.raises(ValueError, match='变化'):
        apply(store, plan)
    assert dump(store) == before


def test_cancelled_preview_and_partial_directory_read_error_leave_database_clean(store, tmp_path, monkeypatch):
    root = tmp_path / 'old'
    media(root, 'valid/a.mp4')
    media(root, 'locked/b.mp4')
    cancel = Event()
    cancel.set()
    before = dump(store)
    with pytest.raises(InterruptedError):
        TakeoverService(store).preview(str(root), TakeoverRules(), cancel)
    real_scan = os.scandir
    def scan(path):
        if Path(path).name == 'locked':
            raise PermissionError('injected unreadable directory')
        return real_scan(path)
    monkeypatch.setattr(os, 'scandir', scan)
    plan = preview(store, root)
    assert len(plan.items) == 1 and plan.warnings and 'locked' in plan.warnings[0]
    assert dump(store) == before


def test_retired_cleanup_entrance_is_not_reactivated_by_takeover(store, tmp_path):
    root = tmp_path / 'old'
    path = media(root, 'retired.mp4')
    vid = store.register(path)
    info = path.stat()
    store.execute('INSERT INTO cleanup_jobs VALUES(?,?,?,?,?,?,?,?,?)', ('c', vid, str(path), identity(path), info.st_size, info.st_mtime_ns, 'pending', None, 1))
    store.execute('DELETE FROM paths WHERE path=?', (str(path),))
    plan = preview(store, root)
    assert plan.items == () and any('待清理' in warning for warning in plan.warnings)
    assert not store.query('SELECT * FROM paths')


def test_only_selected_rows_create_tags_and_file_records(store, tmp_path):
    root = tmp_path / 'old'
    media(root, 'selected/a.mp4')
    media(root, 'excluded/b.mp4')
    plan = preview(store, root, TakeoverRules('tags'))
    item = next(item for item in plan.items if item.markers.tags == ('selected',))
    ids = TakeoverService(store).apply(plan, {item.file.identity})
    assert len(ids) == 1 and set(store.tag_layout()) == {'selected'}
    assert len(store.query('SELECT * FROM paths')) == 1


def test_replaced_known_path_gets_new_identity_without_inheriting_old_marks(store, tmp_path):
    root = tmp_path / 'old'
    path = media(root, '摄影/a.mp4')
    old_id = store.register(path)
    store.execute('UPDATE videos SET score=9,star=1 WHERE id=?', (old_id,))
    saved = root / 'previous.bin'
    path.rename(saved)
    path.write_bytes(b'new physical file')
    plan = preview(store, root, TakeoverRules('tags'))
    assert plan.warnings and not plan.items[0].conflicts
    new_id, = apply(store, plan)
    assert new_id != old_id and store.video(new_id)['score'] is None and store.video(new_id)['star'] == 0
    assert store.video(old_id)['score'] == 9 and store.video(old_id)['star'] == 1
    assert json.loads(store.video(new_id)['tags']) == ['摄影']


def test_confirmed_import_refresh_and_navigation_wait_for_atomic_commit(store, tmp_path):
    from moplayer.application.operations import UserActions
    root = tmp_path / 'old'
    media(root, 'plain.mp4')
    plan = preview(store, root)
    queued, policies, order = [], [], []
    tasks = FileTasks(lambda work, done: queued.append((work, done)), policies.append,
                      lambda bookmark: order.append('end'), lambda: False)
    workflow = Takeover(TakeoverService(store), tasks, lambda work, done: None,
        available=lambda: True, refresh=lambda ids: order.append(('refresh', ids)),
        drafts=SimpleNamespace(dirty_ids=(), discard=lambda vid: order.append(('discard', vid))))
    operation = workflow.apply(plan, {item.file.identity for item in plan.items})
    actions = UserActions(before_action=lambda: tasks.completion or Operation.success())
    actions.request(lambda: order.append('navigate'), Operation.success)
    assert operation.pending and 'navigate' not in order and not policies[0].release_media
    assert not store.query('SELECT * FROM videos')
    work, ready = queued.pop()
    ids = work()
    ready(ids, None)
    assert operation.outcome.succeeded and tasks.completion is None
    assert order[-2:] == [('refresh', ids), 'navigate']


def test_cancelled_late_scan_is_discarded_without_releasing_media_or_publishing_plan():
    queued = []
    workflow = Takeover(SimpleNamespace(preview=lambda root, rules, token: 'late'), None,
        lambda work, done: queued.append((work, done)), available=lambda: True,
        refresh=lambda ids: None, drafts=None)
    operation = workflow.preview('root', TakeoverRules())
    assert workflow.preview('other', TakeoverRules()).outcome.status is Status.CANCELLED
    work, ready = queued.pop()
    plan = work()
    workflow.cancel()
    ready(plan, None)
    assert operation.outcome.status is Status.CANCELLED and operation.outcome.value is None
    assert workflow.scanning is None


def test_pending_jobs_and_unsaved_global_drafts_block_import_before_any_write(store, tmp_path):
    root = tmp_path / 'old'
    media(root, 'plain.mp4')
    plan = preview(store, root)
    workflow = Takeover(TakeoverService(store), None, None, available=lambda: True, refresh=lambda ids: None,
                        drafts=SimpleNamespace(dirty_ids=('unrelated-failed-draft',)))
    outcome = workflow.apply(plan, {item.file.identity for item in plan.items}).outcome
    assert outcome.status is Status.FAILED and '草稿' in str(outcome.error)
    store.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', ('job', 'video', 'planned', '{}', None, 1))
    before = dump(store)
    with pytest.raises(RuntimeError, match='未完成'):
        apply(store, plan)
    assert dump(store) == before
