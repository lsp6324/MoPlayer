"""Real files and durable online classification, without a player or Qt."""
import os
from pathlib import Path
import sqlite3
import pytest

import core
from core import Store, Archiver, identity
from application.archive_folders import ArchiveFolders
from infrastructure.archive_cleanup import ArchiveCleanup
from infrastructure.library_repository import LibraryRepository
from infrastructure.schema import migrate
from video_delete import DeletionManager


@pytest.fixture
def library(tmp_path):
    store=Store(tmp_path/'data')
    source=tmp_path/'original.mp4'
    source.write_bytes(b'online classification'*100)
    vid=store.register(source)
    store.execute('UPDATE videos SET star=1,position=4321,played=123 WHERE id=?',(vid,))
    yield store,Archiver(store,tmp_path/'archive'),vid,source
    store.db.close()


def test_commit_separates_active_paths_from_protected_retirements(library):
    store,archiver,vid,source=library
    entity=identity(source)
    archiver.submit(vid,7,['A','B'],defer_cleanup=True)
    catalog=LibraryRepository(store)
    assert not catalog.pending_tasks() and catalog.pending_tasks('cleanup_jobs')
    assert source.exists() and store.resolve(vid)!=source
    assert all(row['path']!=str(source) for row in store.query('SELECT * FROM paths'))
    ArchiveCleanup(store).drain((str(source),))
    assert source.exists() and all(Path(row['path']).exists() for row in store.query('SELECT * FROM paths'))
    assert store.video(vid)['position']==4321 and store.video(vid)['star']==1
    assert identity(store.resolve(vid))==entity
    ArchiveCleanup(store).drain()
    assert not source.exists() and not catalog.pending_tasks('cleanup_jobs')


def test_successive_saves_and_reused_target_cannot_replay_old_deletions(library):
    store,archiver,vid,source=library
    for score in (7,8,7):
        archiver.submit(vid,score,['A'],defer_cleanup=True)
    current=store.resolve(vid)
    ArchiveCleanup(store).drain((str(source),))
    assert current.exists() and current.parent.parent.name=='7分'
    assert store.video(vid)['score']==7 and source.exists()
    ArchiveCleanup(store).drain()
    assert current.exists() and not source.exists()
    assert not store.query('SELECT * FROM cleanup_jobs WHERE state<>"done"')


def test_busy_cleanup_is_nonblocking_and_can_be_retried(library):
    store,archiver,vid,source=library
    archiver.submit(vid,7,['A'],defer_cleanup=True)
    def busy(path):
        raise PermissionError('external handle')
    ArchiveCleanup(store,unlink=busy).drain()
    assert source.exists() and LibraryRepository(store).pending_tasks()==[]
    assert any(row['error'] for row in LibraryRepository(store).pending_tasks('cleanup_jobs'))
    archiver.submit(vid,8,['B'],defer_cleanup=True)
    ArchiveCleanup(store).drain()
    assert store.video(vid)['score']==8 and store.resolve(vid).exists() and not source.exists()


def test_foreign_replacement_is_preserved_and_does_not_block_new_classification(library):
    store,archiver,vid,source=library
    archiver.submit(vid,7,['A'],defer_cleanup=True)
    source.unlink()
    source.write_bytes(b'foreign replacement')
    ArchiveCleanup(store).drain()
    assert source.read_bytes()==b'foreign replacement'
    assert LibraryRepository(store).pending_tasks('cleanup_jobs')[0]['error']
    archiver.submit(vid,9,['B'],defer_cleanup=True)
    assert store.video(vid)['score']==9


def test_retired_source_scan_keeps_id_without_reactivating_old_path(library,monkeypatch):
    store,archiver,vid,source=library
    monkeypatch.setattr(core,'same_volume',lambda a,b:False)
    archiver.submit(vid,7,['A'],defer_cleanup=True)
    assert identity(source)!=identity(store.resolve(vid))
    assert store.register(source)==vid
    assert store.resolve(vid)!=source and len(store.query('SELECT * FROM videos'))==1
    assert store.query('SELECT * FROM paths WHERE path=?',(str(source),))==[]


@pytest.mark.parametrize('checkpoint',['linked','committed'])
def test_interrupted_commit_recovers_before_independent_cleanup(library,checkpoint):
    store,archiver,vid,source=library
    def fault(state):
        if state==checkpoint:
            raise OSError('interrupted')
    archiver.fault=fault
    with pytest.raises(OSError):
        archiver.submit(vid,7,['A'],defer_cleanup=True)
    assert ArchiveCleanup(store).drain()==0 and source.exists()
    archiver.fault=None
    assert archiver.recover()==[]
    ArchiveCleanup(store).drain()
    assert store.video(vid)['score']==7 and not source.exists() and store.resolve(vid).exists()


def test_unchanged_directories_only_write_metadata(library,monkeypatch):
    store,archiver,vid,source=library
    archiver.folders=ArchiveFolders(tags=False,score=False)
    archiver.submit(vid,7,['A'],defer_cleanup=True)
    ArchiveCleanup(store).drain()
    before=store.query('SELECT * FROM jobs')
    def unexpected(*args):
        pytest.fail('Metadata-only save must not create probe, link, or file job')
    monkeypatch.setattr(core,'require_ntfs',unexpected)
    monkeypatch.setattr(os,'link',unexpected)
    archiver.submit(vid,9,['B'],favorite=0,defer_cleanup=True)
    assert store.query('SELECT * FROM jobs')==before
    assert store.video(vid)['score']==9 and store.video(vid)['tags']=='["B"]' and store.video(vid)['star']==0


def test_delete_includes_retired_source_and_staging_entries(library):
    store,archiver,vid,source=library
    archiver.submit(vid,7,['A','B'],defer_cleanup=True)
    retired=[Path(row['path']) for row in store.query('SELECT * FROM cleanup_jobs')]
    current=[Path(row['path']) for row in store.query('SELECT * FROM paths')]
    DeletionManager(store,recycle=lambda path:path.unlink()).submit(vid)
    assert not any(path.exists() for path in retired+current)
    assert not store.query('SELECT * FROM videos') and not LibraryRepository(store).pending_tasks('cleanup_jobs')


def test_old_database_upgrade_preserves_records_and_is_idempotent(library):
    store,archiver,vid,source=library
    before=store.video(vid)
    directory=store.directory
    store.execute('DROP TABLE cleanup_jobs')
    store.execute('PRAGMA user_version=0')
    store.db.close()
    upgraded=Store(directory)
    try:
        assert upgraded.video(vid)==before and upgraded.resolve(vid)==source
        assert upgraded.query('PRAGMA user_version')[0]['user_version']==1
        migrate(upgraded.db)
        assert upgraded.query('SELECT * FROM cleanup_jobs')==[]
    finally:
        upgraded.db.close()


def test_schema_migration_rolls_back_ddl_on_failure():
    class Interrupted(sqlite3.Connection):
        def execute(self,sql,*args):
            if sql.startswith('CREATE INDEX'):
                raise OSError('interrupted migration')
            return super().execute(sql,*args)
    connection=sqlite3.connect(':memory:',factory=Interrupted)
    with pytest.raises(OSError):
        migrate(connection)
    assert connection.execute('PRAGMA user_version').fetchone()[0]==0
    assert not connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    connection.close()
