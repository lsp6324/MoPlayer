import json
import os
from pathlib import Path
import pytest

from moplayer.core import Archiver, Store, identity
from moplayer.infrastructure.file_renaming import FileRenaming


@pytest.fixture
def video(tmp_path):
    store = Store(tmp_path/'data')
    source = tmp_path/'原始.mp4'
    source.write_bytes(b'rename fixture')
    vid = store.register(source)
    store.execute('UPDATE videos SET score=7,tags=?,star=1,position=1234,played=55 WHERE id=?', ('["教程"]', vid))
    yield store, vid, source
    store.db.close()


def test_unarchived_rename_preserves_identity_metadata_and_archive_basename(video, tmp_path):
    store, vid, source = video
    before = store.video(vid)
    entity = identity(source)
    FileRenaming(store).submit(vid, '新名字.mp4')
    renamed = source.with_name('新名字.mp4')
    assert not source.exists() and store.resolve(vid) == renamed and identity(renamed) == entity
    after = store.video(vid)
    assert after['name'] == after['original_name'] == renamed.name
    assert {key:value for key,value in before.items() if key not in ('name','original_name')} == {key:value for key,value in after.items() if key not in ('name','original_name')}
    Archiver(store, tmp_path/'archive').submit(vid, 7, ['教程'])
    assert store.resolve(vid).name == renamed.name


def test_all_registered_archive_links_keep_directories_and_metadata(video, tmp_path):
    store, vid, source = video
    archiver = Archiver(store, tmp_path/'archive')
    archiver.submit(vid, 7, ['A','B'])
    old = store.query('SELECT * FROM paths WHERE id=?', (vid,))
    before = store.video(vid)
    FileRenaming(store).submit(vid, '归档 新名称.mp4')
    entries = store.query('SELECT * FROM paths WHERE id=?', (vid,))
    assert len(entries) == 2
    assert {Path(row['path']).parent for row in entries} == {Path(row['path']).parent for row in old}
    assert all(Path(row['path']).name == '归档 新名称.mp4' and identity(row['path']) == row['identity'] for row in entries)
    assert store.video(vid) == dict(before, name='归档 新名称.mp4', original_name='归档 新名称.mp4')


@pytest.mark.parametrize('stage', ['planned','renamed-0','renamed-1','committed'])
def test_partial_and_committed_rename_recovers_frozen_name(video, tmp_path, stage):
    store, vid, source = video
    archiver = Archiver(store, tmp_path/'archive')
    archiver.submit(vid, 7, ['A','B'])
    def fault(state):
        if state == stage:
            raise OSError('interrupted')
    with pytest.raises(OSError):
        FileRenaming(store,fault).submit(vid, '恢复.mp4')
    assert archiver.recover() == []  # Other job kinds must not consume rename plans.
    assert FileRenaming(store).recover() == []
    assert store.video(vid)['name'] == store.video(vid)['original_name'] == '恢复.mp4'
    assert not store.query('SELECT * FROM jobs WHERE state<>"done"')
    assert all(Path(row['path']).name == '恢复.mp4' and Path(row['path']).exists() for row in store.query('SELECT * FROM paths WHERE id=?',(vid,)))
    assert FileRenaming(store).recover() == []


@pytest.mark.parametrize('name', ['../坏.mp4','CON.mp4','坏?.mp4','尾部.mp4 ', '长'*256+'.mp4','改扩展.txt',''])
def test_invalid_input_has_no_file_or_database_side_effects(video, name):
    store, vid, source = video
    before = store.video(vid)
    with pytest.raises(ValueError):
        FileRenaming(store).submit(vid,name)
    assert source.exists() and store.video(vid) == before and not store.query('SELECT * FROM jobs')


def test_collision_in_last_directory_is_rejected_before_any_rename(video, tmp_path):
    store, vid, source = video
    Archiver(store,tmp_path/'archive').submit(vid,7,['A','B'])
    paths = store.query('SELECT * FROM paths WHERE id=? ORDER BY path',(vid,))
    occupied = Path(paths[-1]['path']).with_name('占用.mp4')
    occupied.write_bytes(b'unrelated video')
    with pytest.raises(FileExistsError):
        FileRenaming(store).submit(vid,'占用.mp4')
    assert all(Path(row['path']).exists() for row in paths)
    assert occupied.read_bytes() == b'unrelated video' and store.video(vid)['name'] == '原始.mp4'


def test_recovery_never_overwrites_external_replacement(video):
    store, vid, source = video
    def fault(state):
        if state == 'planned':
            raise OSError('interrupted')
    with pytest.raises(OSError):
        FileRenaming(store,fault).submit(vid,'新.mp4')
    target = source.with_name('新.mp4')
    target.write_bytes(b'foreign')
    assert FileRenaming(store).recover()
    assert source.read_bytes() == b'rename fixture' and target.read_bytes() == b'foreign'
    assert store.video(vid)['name'] == '原始.mp4'


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-insensitive paths')
def test_case_only_rename_changes_disk_spelling_and_database(video):
    store, vid, source = video
    service = FileRenaming(store)
    service.submit(vid,'Title.mp4')
    service.submit(vid,'TITLE.mp4')
    assert 'TITLE.mp4' in [p.name for p in source.parent.iterdir()]
    assert store.resolve(vid).name == store.video(vid)['original_name'] == 'TITLE.mp4'


def test_pending_rename_blocks_archive_and_other_renames(video,tmp_path):
    store, vid, source = video
    def fault(state):
        raise OSError('interrupted')
    with pytest.raises(OSError):
        FileRenaming(store,fault).submit(vid,'pending.mp4')
    with pytest.raises(RuntimeError):
        Archiver(store,tmp_path/'archive').submit(vid,7,[])
    with pytest.raises(RuntimeError):
        FileRenaming(store).submit(vid,'another.mp4')
    assert source.exists()


def test_two_registered_links_in_same_folder_are_rejected_before_any_changes(video):
    store, vid, source=video
    alias=source.with_name('alias.mp4')
    os.link(source,alias)
    assert store.register(alias)==vid
    with pytest.raises(ValueError,match='多个入口'):
        FileRenaming(store).submit(vid,'合并.mp4')
    assert alias.exists() and source.exists() and not store.query('SELECT * FROM jobs')


def test_database_failure_rolls_back_metadata_and_recovers_after_target_was_scanned(video):
    store, vid, source=video
    before=store.video(vid)
    store.execute('CREATE TRIGGER fail_rename BEFORE UPDATE OF name ON videos BEGIN SELECT RAISE(FAIL,"database failure"); END')
    with pytest.raises(Exception,match='database failure'):
        FileRenaming(store).submit(vid,'事务恢复.mp4')
    target=source.with_name('事务恢复.mp4')
    assert target.exists() and store.video(vid)==before
    assert store.register(target)==vid
    store.execute('DROP TRIGGER fail_rename')
    assert FileRenaming(store).recover()==[]
    assert store.resolve(vid)==target and store.video(vid)==dict(before,name=target.name,original_name=target.name)
    assert store.query('SELECT * FROM paths WHERE id=?',(vid,))==[dict(path=str(target),id=vid,identity=identity(target))]
