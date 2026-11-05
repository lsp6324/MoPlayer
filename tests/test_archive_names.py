"""Names remain literal while metadata changes directories and recovers safely."""
from pathlib import Path
import json
import pytest
from core import Store, Archiver, archive_name, identity
from infrastructure.archive_configuration import ArchiveConfiguration
from storage_settings import StorageSettings


def sample(tmp_path):
    source=tmp_path/'source'/'abc-123.mp4'
    source.parent.mkdir()
    source.write_bytes(b'archive-name-test')
    store=Store(tmp_path/'data')
    vid=store.register(source)
    return store,Archiver(store,tmp_path/'archive'),source,vid


def test_score_and_tag_changes_only_move_directories(tmp_path):
    store,archive,source,vid=sample(tmp_path)
    entity=identity(source)
    store.execute('UPDATE videos SET star=1,position=12345,played=1 WHERE id=?',(vid,))
    archive.submit(vid,8,['白丝','标签2'])
    paths=[archive.root/'8分'/tag/source.name for tag in ['白丝','标签2']]
    assert all(path.exists() and identity(path)==entity for path in paths)
    for score,tags,parent in [(9,['白丝'],archive.root/'9分'/'白丝'),
                              (0,[],archive.root/'0分'/'未分类'),
                              (None,['白丝'],archive.root/'未评分'/'白丝')]:
        archive.submit(vid,score,tags)
        assert store.resolve(vid)==parent/source.name
        assert store.video(vid)['name']==store.video(vid)['original_name']==source.name
    assert store.video(vid)['star']==1 and store.video(vid)['position']==12345


def test_old_frozen_job_finishes_then_original_name_restores_without_moving_folders(tmp_path):
    store,archive,source,vid=sample(tmp_path)
    archive.fault=lambda stage: (_ for _ in ()).throw(OSError('interruption')) if stage=='prepared' else None
    with pytest.raises(OSError):
        archive.submit(vid,8,['标签'])
    row=store.query('SELECT * FROM jobs')[0]
    plan=json.loads(row['plan'])
    legacy='8分 标签 abc-123.mp4'
    plan['name']=legacy
    plan['targets']=[str(Path(target).with_name(legacy)) for target in plan['targets']]
    store.execute('UPDATE jobs SET plan=? WHERE id=?',(json.dumps(plan),row['id']))
    archive.fault=None
    assert archive.recover()==[]
    assert store.resolve(vid).name==legacy
    parent=store.resolve(vid).parent
    settings=StorageSettings(store.directory)
    service=ArchiveConfiguration(store,settings,archive)
    assert service.restore_original_names()==[vid]
    assert store.resolve(vid)==parent/source.name
    assert service.restore_original_names()==[]


def test_long_metadata_does_not_extend_name_and_literal_prefix_is_preserved(tmp_path):
    store,archive,source,vid=sample(tmp_path)
    archive.submit(vid,8,[character*80 for character in ['甲','乙','丙','丁']])
    assert store.resolve(vid).name==source.name
    assert archive_name('9分 白丝 original.MKV')=='9分 白丝 original.MKV'
    with pytest.raises(ValueError,match='长度'):
        archive_name('a'*260+'.mp4')


def test_database_schema_upgrade_preserves_identity_and_initializes_literal_name(tmp_path):
    store,archive,source,vid=sample(tmp_path)
    store.execute('UPDATE videos SET star=1,position=4567 WHERE id=?',(vid,))
    store.execute('ALTER TABLE videos DROP COLUMN original_name')
    store.db.close()
    reopened=Store(tmp_path/'data')
    Archiver(reopened,archive.root).submit(vid,8,['白丝'])
    assert reopened.video(vid)['star']==1 and reopened.video(vid)['position']==4567
    assert reopened.video(vid)['original_name']==source.name and reopened.resolve(vid).name==source.name


@pytest.mark.parametrize('value',['../other.mp4',r'..\other.mp4','..','CON.mp4','bad?.mp4','name.','',None])
def test_invalid_recorded_names_are_rejected_before_file_actions(value):
    with pytest.raises(ValueError):
        archive_name(value)
