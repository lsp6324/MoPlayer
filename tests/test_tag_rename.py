"""Global renames preserve references, identities and recoverable frozen jobs."""
import json
import pytest
from core import Store, Archiver, identity
from tag_migration import TagMigration


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path / 'data')
    archive = Archiver(store, tmp_path / 'archive')
    migration = TagMigration(store, archive)
    rows = [dict(name='风景', kind='major', parent=None),
            dict(name='山川', kind='minor', parent='风景')]
    ids, sources = [], []
    for n in range(3):
        source = tmp_path / f'{n}.mp4'
        source.write_bytes(f'isolated rename {n}'.encode())
        sources.append(source)
        ids.append(store.register(source))
    for vid in ids[:2]:
        migration.submit(vid, 8, ['山川'], rows, defer_cleanup=True)
    store.execute('UPDATE videos SET tags=?,star=1,position=123,played=456 WHERE id=?', ('["山川"]', ids[2]))
    yield store, archive, migration, ids, sources
    store.db.close()


@pytest.mark.parametrize('source,target', [('风景', '自然'), ('山川', '群山')])
def test_global_parent_or_child_rename_preserves_unarchived_files(library, source, target):
    store, archive, migration, ids, paths = library
    before = {vid: store.video(vid) for vid in ids}
    identities = {vid: identity(store.resolve(vid)) for vid in ids}
    layout = store.tag_layout()
    renamed = []
    for name, row in layout.items():
        renamed.append(dict(row, name=target if name == source else name,
                            parent=target if row.get('parent') == source else row.get('parent')))
    current_tags = ['群山' if source == '山川' else '山川']
    affected = migration.submit(ids[0], 8, current_tags, renamed, renames={source: target}, defer_cleanup=True)
    assert set(affected) == set(ids)
    for vid in ids:
        assert json.loads(store.video(vid)['tags']) == current_tags
        assert identity(store.resolve(vid)) == identities[vid]
        for field in ('id', 'score', 'star', 'position', 'played', 'in_library', 'library_added_at', 'archived_at'):
            assert store.video(vid)[field] == before[vid][field]
    assert not store.video(ids[2])['archived'] and store.resolve(ids[2]) == paths[2]
    assert source not in store.tag_layout() and target in store.tag_layout()
    assert store.tag_layout()[current_tags[0]]['parent'] == ('自然' if source == '风景' else '风景')


def test_interrupted_rename_replays_frozen_mapping_and_keeps_all_references(library, tmp_path):
    store, archive, migration, ids, paths = library
    layout = [dict(row, name='群山' if name == '山川' else name) for name, row in store.tag_layout().items()]
    migration.fault = lambda stage: (_ for _ in ()).throw(OSError('interrupted')) if stage == 'migrating' else None
    with pytest.raises(OSError):
        migration.submit(ids[0], 8, ['群山'], layout, renames={'山川': '群山'}, defer_cleanup=True)
    plan = json.loads(store.query('SELECT plan FROM hierarchy_jobs WHERE state<>"done"')[0]['plan'])
    assert plan['renames'] == {'山川': '群山'}
    assert TagMigration(store, Archiver(store, tmp_path / 'unrelated-root')).recover() == []
    assert all(json.loads(store.video(vid)['tags']) == ['群山'] for vid in ids)
    assert store.resolve(ids[2]) == paths[2] and not store.video(ids[2])['archived']
    assert '群山' in store.tag_layout() and '山川' not in store.tag_layout()
    assert all(str(store.resolve(vid)).startswith(str(archive.root)) for vid in ids[:2])


def test_invalid_rename_does_not_create_a_job_or_change_records(library):
    store, archive, migration, ids, paths = library
    before = store.query('SELECT * FROM videos')
    jobs = store.query('SELECT * FROM hierarchy_jobs')
    with pytest.raises(ValueError):
        migration.submit(ids[0], 8, ['山川'], list(store.tag_layout().values()), renames={'风景': '山川'})
    assert store.query('SELECT * FROM videos') == before
    assert store.query('SELECT * FROM hierarchy_jobs') == jobs
