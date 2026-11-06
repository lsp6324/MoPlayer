"""Real files and durable jobs for configurable archive directory ownership."""
from itertools import product
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

import pytest

from application.archive_folders import ArchiveFolders
from core import Archiver, Store, identity
from infrastructure.archive_configuration import ArchiveConfiguration
from storage_settings import StorageSettings
from tag_migration import TagMigration
from video_delete import DeletionManager


def setup(tmp_path):
    store = Store(tmp_path / 'data')
    settings = StorageSettings(store.directory)
    settings.save(tmp_path / 'archive')
    archiver = Archiver(store, settings.root)
    return store, settings, archiver, ArchiveConfiguration(store, settings, archiver)


def video(store, path, *, favorite=0, archived=True, archiver=None):
    path.write_bytes((path.name + ' isolated video content').encode() * 100)
    vid = store.register(path)
    store.execute('UPDATE videos SET star=?,position=1234,played=456 WHERE id=?', (favorite, vid))
    if archived:
        archiver.submit(vid, 8, ['标签甲', '标签乙'])
    return vid


@pytest.mark.parametrize('tags,score,favorite', product([False, True], repeat=3))
def test_all_eight_folder_combinations_preserve_metadata_and_file_identity(tmp_path, tags, score, favorite):
    store, settings, archive, service = setup(tmp_path)
    vid = video(store, tmp_path/'sample.mp4', favorite=1, archiver=archive)
    entity = identity(store.resolve(vid))
    policy = ArchiveFolders(tags, score, favorite)
    service.submit(archive.root, policy)
    paths = [Path(row['path']) for row in store.query('SELECT * FROM paths WHERE id=?',(vid,))]
    prefixes = (['已收藏'] if favorite else []) + (['8分'] if score else [])
    expected = {tuple(prefixes + [tag]) for tag in ['标签甲','标签乙']} if tags else {tuple(prefixes)}
    assert {p.relative_to(archive.root).parts[:-1] for p in paths} == expected
    assert all(p.exists() and identity(p)==entity for p in paths)
    row = store.video(vid)
    assert (row['position'],row['star'],row['played'],row['score'],row['original_name']) == (1234,1,456,8,'sample.mp4')
    assert set(json.loads(row['tags'])) == {'标签甲','标签乙'}
    assert StorageSettings(store.directory).folders == policy
    assert not store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done"')


def test_move_all_archived_videos_leave_unarchived_and_preserve_both_favorite_states(tmp_path):
    store, settings, archive, service = setup(tmp_path)
    a=video(store,tmp_path/'a.mp4',favorite=1,archiver=archive)
    b=video(store,tmp_path/'b.mp4',archiver=archive)
    unarchived=tmp_path/'unarchived.mp4'
    c=video(store,unarchived,archived=False)
    old={vid:store.resolve(vid) for vid in (a,b)}
    newroot=tmp_path/'新归档目录'
    service.submit(newroot,ArchiveFolders(False,False,True))
    assert store.resolve(a).parent == newroot/'已收藏'
    assert store.resolve(b).parent == newroot/'未收藏'
    assert all(not p.exists() for p in old.values())
    assert store.resolve(c)==unarchived and unarchived.exists()
    assert not store.video(c)['archived']


def test_reorder_score_first_library_preserves_identity_and_metadata(tmp_path):
    store, settings, archive, service = setup(tmp_path)
    archive.folders = ArchiveFolders(favorite=True, favorite_first=False)
    ids = [video(store, tmp_path/f'{star}.mp4', favorite=star, archiver=archive) for star in (0, 1)]
    old = {vid: [Path(row['path']) for row in store.query('SELECT path FROM paths WHERE id=?', (vid,))] for vid in ids}
    metadata = {vid: dict(store.video(vid)) for vid in ids}
    entities = {vid: identity(store.resolve(vid)) for vid in ids}
    assert all(paths[0].relative_to(archive.root).parts[0] == '8分' for paths in old.values())
    service.submit(archive.root, ArchiveFolders(favorite=True))
    for vid in ids:
        paths = [Path(row['path']) for row in store.query('SELECT path FROM paths WHERE id=?', (vid,))]
        prefix = '已收藏' if metadata[vid]['star'] else '未收藏'
        assert {path.relative_to(archive.root).parts[:-1] for path in paths} == {
            (prefix, '8分', '标签甲'), (prefix, '8分', '标签乙')}
        assert all(identity(path) == entities[vid] for path in paths)
        assert dict(store.video(vid)) == metadata[vid]
        assert all(not path.exists() for path in old[vid])


def test_unversioned_settings_batch_retains_old_order_on_resume(tmp_path):
    store, settings, archive, service = setup(tmp_path)
    ids = [video(store, tmp_path/f'{star}.mp4', favorite=star, archiver=archive) for star in (0, 1)]
    def interrupted(state):
        if state == 'migrating':
            raise OSError('interrupted between videos')
    service.fault = interrupted
    target = tmp_path/'old-frozen-target'
    with pytest.raises(OSError):
        service.submit(target, ArchiveFolders(favorite=True, favorite_first=False))
    row = store.query('SELECT * FROM archive_setting_jobs WHERE state<>"done"')[0]
    plan = json.loads(row['plan'])
    del plan['archive_folders']['favorite_first']  # Actual pre-upgrade journal format.
    store.execute('UPDATE archive_setting_jobs SET plan=? WHERE id=?', (json.dumps(plan), row['id']))
    restarted = Archiver(store, settings.root, folders=ArchiveFolders(favorite=True))
    assert ArchiveConfiguration(store, settings, restarted).recover() == []
    for vid in ids:
        paths = [Path(row['path']) for row in store.query('SELECT path FROM paths WHERE id=?', (vid,))]
        prefix = '已收藏' if store.video(vid)['star'] else '未收藏'
        assert all(path.parent.parent == target/'8分'/prefix for path in paths)
    assert not settings.folders.favorite_first


def test_unversioned_tag_batch_retains_old_order_for_remaining_videos(tmp_path):
    store, settings, archive, service = setup(tmp_path)
    archive.folders = ArchiveFolders(favorite=True, favorite_first=False)
    ids = [video(store, tmp_path/f'{star}.mp4', favorite=star, archiver=archive) for star in (0, 1)]
    def interrupted(state):
        if state == 'migrating':
            raise OSError('interrupted between videos')
    migration = TagMigration(store, archive, fault=interrupted)
    with pytest.raises(OSError):
        migration.submit(ids[0], 8, ['标签甲'], [dict(name='标签甲', kind='major', parent=None)])
    row = store.query('SELECT * FROM hierarchy_jobs WHERE state<>"done"')[0]
    plan = json.loads(row['plan'])
    del plan['archive_folders']['favorite_first']
    store.execute('UPDATE hierarchy_jobs SET plan=? WHERE id=?', (json.dumps(plan), row['id']))
    archive.folders = ArchiveFolders(favorite=True)
    assert TagMigration(store, archive).recover() == []
    for vid in ids:
        prefix = '已收藏' if store.video(vid)['star'] else '未收藏'
        assert store.resolve(vid).parent == archive.root/'8分'/prefix/'标签甲'


def test_legacy_storage_config_defaults_and_atomic_save_failure(tmp_path):
    data=tmp_path/'data';data.mkdir()
    config=data/'storage.json'
    config.write_text(json.dumps({'archive_root':str(tmp_path/'old')}),encoding='utf-8')
    settings=StorageSettings(data)
    assert settings.folders == ArchiveFolders()
    before=config.read_bytes()
    with patch('storage_settings.os.replace',side_effect=OSError('write failed')):
        with pytest.raises(OSError):
            settings.save(tmp_path/'new',ArchiveFolders(False,False,True))
    assert settings.root==tmp_path/'old' and settings.folders==ArchiveFolders()
    assert config.read_bytes()==before


def test_batch_recovers_original_target_and_policy_after_restart(tmp_path):
    store, settings, archive, service=setup(tmp_path)
    ids=[video(store,tmp_path/(name+'.mp4'),favorite=i,archiver=archive) for i,name in enumerate(['a','b'])]
    target=tmp_path/'新目录';policy=ArchiveFolders(False,False,True)
    def fail(state):
        if state=='migrating':
            raise OSError('power interrupted after one video')
    service.fault=fail
    with pytest.raises(OSError):
        service.submit(target,policy)
    assert settings.folders==ArchiveFolders() and settings.root!=target
    # Active preferences may differ after restart; the pending job owns its plan.
    restarted=Archiver(store,tmp_path/'unrelated',folders=ArchiveFolders(False,True,False))
    recovering=ArchiveConfiguration(store,StorageSettings(store.directory),restarted)
    assert recovering.recover()==[]
    assert restarted.root==target and restarted.folders==policy
    assert all(store.resolve(vid).parent == target/('已收藏' if store.video(vid)['star'] else '未收藏') for vid in ids)
    assert recovering.recover()==[]


def test_json_commit_failure_keeps_recoverable_completed_batch(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    old_config=settings.file.read_bytes()
    target=tmp_path/'new'
    with patch('storage_settings.os.replace',side_effect=OSError('settings disk full')):
        with pytest.raises(OSError):
            service.submit(target,ArchiveFolders(False,False,False))
    assert store.resolve(vid).parent==target
    assert settings.file.read_bytes()==old_config and archive.root!=target
    assert store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done"')
    assert service.recover()==[]
    assert settings.root==target and archive.root==target


@pytest.mark.parametrize('stage',['prepared','linked','committed'])
def test_incomplete_child_job_recovers_before_batch_continues(tmp_path,stage):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    entity=identity(store.resolve(vid))
    def fail(state):
        if state==stage:
            raise OSError('child interruption')
    archive.fault=fail
    with pytest.raises(OSError):
        service.submit(tmp_path/'new',ArchiveFolders(False,True,True))
    archive.fault=None
    assert service.recover()==[]
    assert identity(store.resolve(vid))==entity
    assert store.resolve(vid).parent==tmp_path/'new'/'未收藏'/'8分'


def test_pending_configuration_blocks_conflicting_mutations(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    service.fault=lambda state: (_ for _ in ()).throw(OSError('interruption'))
    with pytest.raises(OSError):
        service.submit(tmp_path/'new',ArchiveFolders(False,False,False))
    with pytest.raises(RuntimeError):
        archive.submit(vid,9,['标签甲'])
    with pytest.raises(RuntimeError):
        TagMigration(store,archive).submit(vid,9,['标签甲'],list(store.tag_layout().values()))
    with pytest.raises(RuntimeError):
        DeletionManager(store).submit(vid)
    with pytest.raises(RuntimeError):
        service.submit(tmp_path/'another',ArchiveFolders())


def test_favorite_metadata_commits_with_path_and_recovers_on_failure(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    service.submit(archive.root,ArchiveFolders(False,True,True))
    def fail(state):
        if state=='linked':
            raise OSError('before metadata commit')
    archive.fault=fail
    with pytest.raises(OSError):
        archive.submit(vid,8,['标签甲','标签乙'],favorite=1)
    assert store.video(vid)['star']==0
    archive.fault=None
    assert archive.recover()==[]
    assert store.video(vid)['star']==1
    assert store.resolve(vid).parent==archive.root/'已收藏'/'8分'


def test_tag_batch_freezes_folder_policy_for_restart(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    service.submit(archive.root,ArchiveFolders(False,False,True))
    def fail(state):
        if state=='migrating':
            raise OSError('tag batch interruption')
    migration=TagMigration(store,archive,fault=fail)
    with pytest.raises(OSError):
        migration.submit(vid,9,['新标签'],[dict(name='新标签',kind='major',parent=None)])
    archive.folders=ArchiveFolders()
    assert TagMigration(store,archive).recover()==[]
    assert store.resolve(vid).parent==archive.root/'未收藏'


def test_settings_and_tag_submission_can_finish_concurrently_without_lock_inversion(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'sample.mp4',archiver=archive)
    rows=list(store.tag_layout().values())
    archive_held,tag_started=threading.Event(),threading.Event()
    failures=[]
    def configure():
        try:
            with archive.lock:
                archive_held.set()
                assert tag_started.wait(2)
                # Let the tag worker reach its first lock while this lock is held.
                time.sleep(.15)
                service.submit(tmp_path/'new',ArchiveFolders(False,False,True))
        except Exception as error:
            failures.append(error)
    def tag():
        try:
            assert archive_held.wait(2)
            tag_started.set()
            TagMigration(store,archive).submit(vid,9,['标签甲'],rows)
        except Exception as error:
            failures.append(error)
    workers=[threading.Thread(target=configure,daemon=True),threading.Thread(target=tag,daemon=True)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(4)
    assert not any(worker.is_alive() for worker in workers), 'Concurrent settings and tags deadlocked'
    assert not failures
    assert store.resolve(vid).parent==tmp_path/'new'/'未收藏'
    assert store.video(vid)['score']==9


def test_disabling_retains_all_paths_and_needs_no_available_archive_volume(tmp_path, monkeypatch):
    from unittest.mock import Mock
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'source.mp4',archiver=archive)
    paths=store.query('SELECT * FROM paths ORDER BY path')
    before=store.video(vid)
    root=settings.root
    probe=Mock(side_effect=AssertionError('Disable must not access storage'))
    monkeypatch.setattr('infrastructure.archive_configuration.validate_storage_path',probe)
    assert service.submit('unavailable-relative-input',ArchiveFolders(False,False,True),enabled=False)==[]
    assert not probe.called and not settings.enabled and not StorageSettings(store.directory).enabled
    assert settings.root==root and archive.root==root
    assert store.query('SELECT * FROM paths ORDER BY path')==paths and store.video(vid)==before
    assert not store.query('SELECT * FROM archive_setting_jobs')


def test_disable_write_failure_and_pending_job_do_not_change_effective_switch(tmp_path,monkeypatch):
    from unittest.mock import Mock
    store,settings,archive,service=setup(tmp_path)
    before=settings.file.read_bytes()
    monkeypatch.setattr('storage_settings.os.replace',Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError): service.submit(settings.root,settings.folders,enabled=False)
    assert settings.enabled and settings.file.read_bytes()==before
    store.execute('INSERT INTO archive_setting_jobs VALUES(?,?,?,?,?)',('pending','planned','{}',None,1))
    with pytest.raises(RuntimeError): service.submit(settings.root,settings.folders,enabled=False)
    assert settings.enabled and settings.file.read_bytes()==before


def test_reenable_migrates_only_archived_and_restores_frozen_enabled_after_crash(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    a=video(store,tmp_path/'a.mp4',archiver=archive)
    b=video(store,tmp_path/'b.mp4',archived=False)
    service.submit(settings.root,settings.folders,enabled=False)
    store.execute('UPDATE videos SET tags=?,score=4,star=1 WHERE id=?',('["标签甲"]',b))
    target=tmp_path/'new-archive'
    service.fault=lambda state: (_ for _ in ()).throw(OSError('checkpoint')) if state=='migrating' else None
    with pytest.raises(OSError): service.submit(target,ArchiveFolders(False,True,True))
    assert not settings.enabled and store.resolve(b)==tmp_path/'b.mp4'
    assert json.loads(store.query('SELECT plan FROM archive_setting_jobs WHERE state<>"done"')[0]['plan'])['archive_enabled']
    restarted=ArchiveConfiguration(store,StorageSettings(store.directory),Archiver(store,archive.root))
    assert restarted.recover()==[] and restarted.settings.enabled
    assert store.resolve(a).is_relative_to(target) and store.resolve(b)==tmp_path/'b.mp4'


def test_disabled_archive_does_not_create_automatic_original_name_restoration(tmp_path):
    store,settings,archive,service=setup(tmp_path)
    vid=video(store,tmp_path/'source.mp4',archiver=archive)
    service.submit(settings.root,settings.folders,enabled=False)
    store.execute('UPDATE videos SET original_name=? WHERE id=?',('old-source-name.mp4',vid))
    before=store.query('SELECT * FROM paths ORDER BY path')
    assert service.restore_original_names()==[]
    assert store.query('SELECT * FROM paths ORDER BY path')==before
    assert not store.query('SELECT * FROM archive_setting_jobs')
