"""First successful archive is dated; edits and old unknown dates are preserved."""
import sqlite3
import pytest
import core
from core import Store, Archiver
from infrastructure.schema import migrate


def test_upgrade_keeps_old_dates_unknown_and_preserves_rows(tmp_path):
    directory = tmp_path / 'data'
    store = Store(directory)
    media = tmp_path / 'a.mp4'
    media.write_bytes(b'media')
    vid = store.register(media)
    store.execute('UPDATE videos SET archived=1,score=7,position=123,played=456 WHERE id=?', (vid,))
    store.execute('DROP INDEX catalog_archived_at')
    store.execute('ALTER TABLE videos DROP COLUMN archived_at')
    store.execute('PRAGMA user_version=1')
    store.db.close()
    store = Store(directory)
    try:
        row = store.video(vid)
        assert row['archived_at'] is None and row['score'] == 7 and row['position'] == 123
        assert store.resolve(vid) == media
        migrate(store.db)
        assert store.query('PRAGMA user_version')[0]['user_version'] == 2
    finally:
        store.db.close()


def test_archive_dates_only_first_commit_and_not_legacy_metadata(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    media = tmp_path / 'a.mp4'
    media.write_bytes(b'media')
    vid = store.register(media)
    archiver = Archiver(store, tmp_path / 'archive')
    try:
        assert store.video(vid)['archived_at'] is None
        monkeypatch.setattr(core.time, 'time', lambda: 1234567.0)
        archiver.submit(vid, 7, ['A'], defer_cleanup=True)
        assert store.video(vid)['archived_at'] == 1234567.0
        monkeypatch.setattr(core.time, 'time', lambda: 9999999.0)
        archiver.submit(vid, 8, ['B'], defer_cleanup=True)
        assert store.video(vid)['archived_at'] == 1234567.0
        store.execute('UPDATE videos SET archived_at=NULL WHERE id=?', (vid,))
        archiver.submit(vid, 9, ['C'], defer_cleanup=True)
        assert store.video(vid)['archived_at'] is None
    finally:
        store.db.close()


def test_date_migration_rolls_back_column_and_version_on_failure():
    class Interrupted(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'PRAGMA user_version=2':
                raise OSError('interrupted')
            return super().execute(sql, *args)
    connection = sqlite3.connect(':memory:', factory=Interrupted)
    connection.execute('CREATE TABLE videos(id TEXT PRIMARY KEY,archived INTEGER)')
    connection.execute('PRAGMA user_version=1')
    connection.commit()
    with pytest.raises(OSError):
        migrate(connection)
    assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
    assert [row[1] for row in connection.execute('PRAGMA table_info(videos)')] == ['id', 'archived']
    connection.close()


@pytest.mark.parametrize('checkpoint', ['linked', 'committed'])
def test_interruption_dates_actual_commit_and_preserves_committed_replay(tmp_path, monkeypatch, checkpoint):
    store = Store(tmp_path / 'data')
    source = tmp_path / 'a.mp4'
    source.write_bytes(b'media')
    vid = store.register(source)
    archiver = Archiver(store, tmp_path / 'archive')
    try:
        monkeypatch.setattr(core.time, 'time', lambda: 100.0)
        archiver.fault = lambda stage: (_ for _ in ()).throw(OSError('interrupted')) if stage == checkpoint else None
        with pytest.raises(OSError):
            archiver.submit(vid, 7, ['A'], defer_cleanup=True)
        assert store.video(vid)['archived_at'] == (None if checkpoint == 'linked' else 100.0)
        monkeypatch.setattr(core.time, 'time', lambda: 200.0)
        archiver.fault = None
        assert archiver.recover() == []
        assert store.video(vid)['archived_at'] == (200.0 if checkpoint == 'linked' else 100.0)
    finally:
        store.db.close()
