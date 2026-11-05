import json
from pathlib import Path
import pytest
from core import Store, Archiver, identity
from infrastructure.archive_configuration import ArchiveConfiguration
from storage_settings import StorageSettings


def fixture(tmp_path, names=('电影甲','电影乙')):
    store=Store(tmp_path/'data')
    settings=StorageSettings(store.directory)
    settings.save(tmp_path/'configured-root')
    archive=Archiver(store,settings.root)
    ids=[]
    for name in names:
        directory=tmp_path/'旧归档'/'8分'/'标签'
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'8分 标签 {name}.mp4'
        path.write_bytes(name.encode()*100)
        vid=store.register(path)
        store.execute('UPDATE videos SET archived=1,original_name=?,score=8,tags=?,star=1,position=2345,played=6 WHERE id=?',
                      (name+'.mp4',json.dumps(['标签']),vid))
        ids.append(vid)
    store.execute('INSERT INTO tags VALUES(?)',('标签',))
    return store,settings,archive,ArchiveConfiguration(store,settings,archive),ids


def test_restore_all_known_names_preserves_directories_preferences_and_metadata(tmp_path):
    store,settings,archive,service,ids=fixture(tmp_path)
    before={vid:(store.resolve(vid).parent,identity(store.resolve(vid))) for vid in ids}
    config=settings.file.read_bytes()
    assert set(service.restore_original_names())==set(ids)
    for vid in ids:
        path=store.resolve(vid)
        assert path.parent==before[vid][0] and identity(path)==before[vid][1]
        row=store.video(vid)
        assert path.name==row['original_name']==row['name']
        assert (row['star'],row['position'],row['played'],row['score'])==(1,2345,6,8)
    assert settings.file.read_bytes()==config
    assert service.restore_original_names()==[]


def test_unknown_original_and_unarchived_records_are_not_renamed(tmp_path):
    store,settings,archive,service,ids=fixture(tmp_path)
    store.execute('UPDATE videos SET original_name=NULL WHERE id=?',(ids[0],))
    store.execute('UPDATE videos SET archived=0 WHERE id=?',(ids[1],))
    before={vid:store.resolve(vid) for vid in ids}
    assert service.restore_original_names()==[]
    assert all(store.resolve(vid)==path and path.exists() for vid,path in before.items())


@pytest.mark.parametrize('stage',['prepared','linked','committed'])
def test_original_name_child_failure_restarts_from_frozen_paths(tmp_path,stage):
    store,settings,archive,service,ids=fixture(tmp_path)
    parents={vid:store.resolve(vid).parent for vid in ids}
    def fail(state):
        if state==stage:
            raise OSError('interrupted restore')
    archive.fault=fail
    with pytest.raises(OSError):
        service.restore_original_names()
    archive.fault=None
    archive.root=tmp_path/'unrelated'
    assert service.recover()==[]
    assert all(store.resolve(vid).parent==parents[vid] and store.resolve(vid).name==store.video(vid)['original_name'] for vid in ids)


def test_parent_batch_failure_and_conflicting_file_do_not_lose_content(tmp_path):
    store,settings,archive,service,ids=fixture(tmp_path,('同名',))
    path=store.resolve(ids[0])
    occupied=path.with_name('同名.mp4')
    occupied.write_bytes(b'unrelated video')
    service.fault=lambda state: (_ for _ in ()).throw(OSError('batch interrupted'))
    with pytest.raises(OSError):
        service.restore_original_names()
    service.fault=None
    assert service.recover()==[]
    restored=store.resolve(ids[0])
    assert restored!=occupied and restored.name.startswith('同名 [')
    assert occupied.read_bytes()==b'unrelated video'
    assert service.restore_original_names()==[]
