"""User-visible archive queries, cancellation, identities and frozen queues."""
from threading import Event
import json
from types import SimpleNamespace
import pytest
from application.catalog import CatalogFilter, CatalogContext, select_rows
from application.library import LibraryController
from application.operations import Status
from infrastructure.library_preferences import LibraryPreferences
from infrastructure.library_repository import LibraryRepository
from core import Store


SCHEMA = {'风景': {'parent': None}, '山川': {'parent': '风景'}, '雪山': {'parent': '山川'}, '摄影': {'parent': None}}


def row(vid, name=None, **values):
    return dict(dict(id=vid, name=name or vid+'.mp4', archived=1, in_library=1, score=None, star=0, played=0,
                     position=0, kind='video', tag_names=(), tags='[]', library_added_at=None), **values)


def query(rows, **filters):
    return [r['id'] for r in select_rows(rows, SCHEMA, CatalogFilter(**filters), Event())]


def test_search_natural_order_and_identity_deduplication():
    a, b, c = row('a', 'Clip10.mp4'), row('b', 'clip2.mp4'), row('c', 'clip2.mp4')
    assert query([a, b, c, a, row('d', in_library=0)], search='CLIP') == ['b', 'c', 'a']


def test_membership_is_independent_of_disk_archive_state():
    assert query([row('managed', archived=0), row('unmanaged', archived=1, in_library=0)]) == ['managed']


def test_parent_descendants_multiple_tag_intersection_and_untagged():
    rows = [row('a', tag_names=('雪山', '摄影')), row('b', tag_names=('山川',)), row('c')]
    assert query(rows, tags=('风景',)) == ['a', 'b']
    assert query(rows, tags=('风景', '摄影')) == ['a']
    assert query(rows, untagged=True) == ['c']
    assert query(rows, untagged=True, tags=('风景',)) == []


def test_threshold_is_inclusive_and_never_matches_unrated():
    rows = [row('a', score=6), row('b', score=7), row('c', score=8), row('d', score=None), row('e', score=0)]
    assert query(rows, score=7, score_mode='exact') == ['b']
    assert query(rows, score=7, score_mode='gte') == ['b', 'c']
    assert query(rows, score=0, score_mode='exact') == ['e']
    assert query(rows, score=0, score_mode='gte') == ['a', 'b', 'c', 'e']
    assert query(rows, score='none', score_mode='gte') == ['d']


def test_tag_or_respects_ancestors_and_other_filter_dimensions():
    rows = [row('a', star=1, score=8, tag_names=('雪山',)),
            row('b', star=1, score=7, tag_names=('摄影',)),
            row('c', star=0, score=9, tag_names=('雪山','摄影')),
            row('d', star=1, score=4, tag_names=('雪山','摄影')), row('e', star=1, score=8)]
    assert query(rows, tags=('风景','摄影'), tag_mode='and') == ['c', 'd']
    assert query(rows, tags=('风景','摄影'), tag_mode='or', favorite='yes', score=7, score_mode='gte') == ['a', 'b']
    assert query(rows, tags=('风景',), untagged=True, tag_mode='or') == ['a', 'c', 'd', 'e']
    assert query(rows, tag_mode='or') == ['a', 'b', 'c', 'd', 'e']


def test_preferences_upgrade_keeps_old_filter_meaning_and_view_default(tmp_path):
    prefs = LibraryPreferences(tmp_path)
    prefs.path.write_text(json.dumps(dict(page='catalog', filters=dict(score=7,tags=['山川','摄影'],sort='added_desc'))), encoding='utf-8')
    page, filters, view = prefs.load()
    assert page == 'catalog' and filters.score_mode == 'exact' and filters.tag_mode == 'and' and view == 'list'
    updated = filters.updated(score_mode='gte', tag_mode='or')
    prefs.save(page, updated, 'grid')
    assert prefs.load() == ('catalog', updated, 'grid')
    with pytest.raises(ValueError):
        CatalogFilter(score_mode='less')
    with pytest.raises(ValueError):
        CatalogFilter(tag_mode='xor')


@pytest.mark.parametrize(('filters', 'expected'), [
    ({'favorite':'yes'}, ['a']), ({'favorite':'no'}, ['b','c']),
    ({'score':'none'}, ['c']), ({'score':0}, ['b']), ({'score':7}, ['a']),
    ({'kind':'image'}, ['c']), ({'sort':'score'}, ['a','b','c']),
    ({'sort':'played'}, ['b','a','c']), ({'sort':'added_asc'}, ['a','b','c']),
    ({'sort':'added_desc'}, ['b','a','c']),
])
def test_independent_filters_and_date_unknown_last_in_both_directions(filters, expected):
    rows = [row('a', star=1, score=7, played=3, library_added_at=100),
            row('b', score=0, played=5, library_added_at=200), row('c', kind='image')]
    assert query(rows, **filters) == expected


def test_cancellation_and_large_library_queries():
    rows = [row(str(n), f'项目{n}.mp4', star=n%2, tag_names=('雪山','摄影')) for n in range(10000)]
    assert len(query(rows, favorite='yes', tags=('风景','摄影'))) == 5000
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        select_rows(rows, SCHEMA, CatalogFilter(), cancel)


def test_filter_persistence_validation_and_no_implicit_load_write(tmp_path):
    prefs = LibraryPreferences(tmp_path)
    assert prefs.load() == ('files', CatalogFilter(), 'list') and not prefs.path.exists()
    filters = CatalogFilter(tags=('山川','摄影'), score=7, sort='added_desc')
    prefs.save('catalog', filters)
    assert prefs.load() == ('catalog', filters, 'list')
    prefs.path.write_text('{broken', encoding='utf-8')
    assert prefs.load() == ('files', CatalogFilter(), 'list')
    with pytest.raises(ValueError):
        CatalogFilter(score=True)


def harness():
    rows = {vid: row(vid, score=5, tags='["山川"]', tag_names=('山川',)) for vid in ('a','b','c')}
    class Repository:
        calls = 0
        def catalog_data(self):
            self.calls += 1
            return [dict(r) for r in rows.values()], SCHEMA
        def video_details(self, ids):
            return {vid: dict(rows[vid]) for vid in ids if vid in rows}
    tasks, repo = [], Repository()
    controller = LibraryController(repo, None, lambda work, ready: tasks.append((work, ready)))
    return controller, repo, rows, tasks


def finish(task):
    work, ready = task
    try:
        value = work()
    except Exception as error:
        ready(None, error)
    else:
        ready(value, None)


def test_stale_query_cannot_replace_latest_and_queue_never_scans():
    controller, repo, rows, tasks = harness()
    browsing = object()
    controller.browsing = browsing
    first = controller.query_catalog(CatalogFilter(search='a'))
    second = controller.query_catalog(CatalogFilter(search='b'))
    finish(tasks[1])
    finish(tasks[0])
    assert first.outcome.status is Status.CANCELLED and second.outcome.succeeded
    assert controller.catalog_ids == ['b'] and controller.browsing is browsing
    selection = controller.catalog_selection('b')
    assert selection.context.folders[selection.context.root][1] == [('b','b.mp4')]


def test_queue_survives_filter_and_metadata_changes_while_deleted_ids_are_skipped():
    controller, repo, rows, tasks = harness()
    controller.query_catalog()
    finish(tasks.pop())
    selection = controller.catalog_selection('b')
    context = selection.context
    rows['b']['score'] = 8
    controller.refresh(['b'], context)
    finish(tasks.pop())
    controller.query_catalog(CatalogFilter(score=5, sort='added_desc'))
    finish(tasks.pop())
    assert controller.catalog_ids == ['a','c']
    assert context.folders[context.root][1][1][0] == 'b'
    assert context.step(selection.location, 1) == (context.root, 2)
    del rows['a']
    controller.exclude(['a'], context)
    finish(tasks.pop())
    assert context.step(selection.location, -1) is None
    assert controller.browsing is None


def test_progress_does_not_requery_and_late_query_preserves_newer_progress():
    controller, repo, rows, tasks = harness()
    controller.query_catalog()
    finish(tasks.pop())
    controller.query_catalog()
    work, ready = tasks.pop()
    stale = work()
    for n in range(20):
        rows['a']['position'], rows['a']['played'] = 100+n, 200+n
        controller.refresh(['a'])
    assert not tasks and repo.calls == 2
    ready(stale, None)
    assert controller.details['a']['position'] == 119 and controller.details['a']['played'] == 219


def test_metadata_update_invalidates_inflight_query_even_before_first_load():
    controller, repo, rows, tasks = harness()
    first = controller.query_catalog(CatalogFilter(score=5))
    old_work, old_ready = tasks.pop()
    stale = old_work()
    rows['a']['score'] = 8
    controller.refresh(['a'])
    assert first.outcome.status is Status.CANCELLED
    old_ready(stale, None)
    finish(tasks.pop())
    assert controller.catalog_ids == ['b','c'] and controller.details['a']['score'] == 8


def test_selected_deletion_target_is_retained_during_pending_filter_change():
    controller, repo, rows, tasks = harness()
    controller.query_catalog()
    finish(tasks.pop())
    controller.query_catalog(CatalogFilter(search='a'))
    assert controller.catalog_selection('b') is None
    selected = controller.catalog_selection('b', allow_pending=True)
    assert selected.video_id == 'b'
    assert selected.context.folders[selected.context.root][1][selected.location[1]][0] == 'b'


def test_repository_uses_archived_ids_and_existing_media_kind_with_no_path_scan(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        for n, suffix in enumerate(('.mp4', '.png', '.jpg')):
            media = tmp_path / ('a'+str(n)+suffix)
            media.write_bytes(b'test')
            vid = store.register(media)
            store.execute('UPDATE videos SET archived=? WHERE id=?', (int(n < 2), vid))
        rows, schema = LibraryRepository(store).catalog_data()
        assert len(rows) == 2 and {r['kind'] for r in rows} == {'video', 'image'}
        assert all(r['archived_at'] is None for r in rows)
    finally:
        store.db.close()


def test_archived_rows_keep_display_fields_after_recent_and_star_lists_load(tmp_path):
    """Loading recent/star lists must not strip kind and tag_names from library rows."""
    store = Store(tmp_path / 'data')
    try:
        media = tmp_path / 'a.mp4'
        media.write_bytes(b'test')
        vid = store.register(media)
        store.execute('UPDATE videos SET archived=1, star=1, played=1, tags=? WHERE id=?', ('["山川"]', vid))
        tasks = []
        controller = LibraryController(LibraryRepository(store), None,
                                       lambda work, ready: tasks.append((work, ready)))
        controller.query_catalog()
        finish(tasks.pop())
        controller.load_list('stars')
        rows = controller.list_rows('catalog')
        assert rows and rows[0]['kind'] == 'video' and rows[0]['tag_names'] == ('山川',)
    finally:
        store.db.close()
