"""Committed markers form a persistent library without organizing files."""
import json
import sqlite3
import time

import pytest

from moplayer.core import Archiver, Store, identity
from moplayer.infrastructure.library_repository import LibraryRepository
from moplayer.infrastructure.schema import migrate


@pytest.fixture
def media(tmp_path):
    store = Store(tmp_path / 'data')
    source = tmp_path / '原目录' / '电影.mp4'
    source.parent.mkdir()
    source.write_bytes(b'membership test media')
    vid = store.register(source)
    yield store, LibraryRepository(store), vid, source
    store.db.close()


@pytest.mark.parametrize('marker', ['score', 'favorite', 'tags'])
def test_first_marker_enrolls_without_moving_or_creating_file_jobs(media, marker):
    store, repo, vid, source = media
    original_identity = identity(source)
    before = time.time() - 1
    if marker == 'score':
        repo.set_score(vid, 0)
    elif marker == 'favorite':
        repo.set_favorite(vid, True)
    else:
        store.execute('UPDATE videos SET tags=? WHERE id=?', (json.dumps(['风景']), vid))
    row = store.video(vid)
    assert row['in_library'] == 1 and not row['archived'] and row['archived_at'] is None
    assert before <= row['library_added_at'] <= time.time() + 1
    assert [item['id'] for item in repo.catalog_data()[0]] == [vid]
    assert repo.resolve(vid) == source and identity(source) == original_identity
    assert not repo.pending_tasks()
    assert len(store.query('SELECT * FROM paths WHERE id=?', (vid,))) == 1


def test_scanning_playing_and_clearing_default_markers_do_not_enroll(media):
    store, repo, vid, source = media
    store.register(source)
    repo.mark_played(vid)
    repo.progress(vid, 1234)
    repo.set_score(vid, None)
    repo.set_favorite(vid, False)
    store.execute('UPDATE videos SET tags=? WHERE id=?', (' [ ] ', vid))
    assert not repo.catalog_data()[0]
    assert store.video(vid)['library_added_at'] is None


def test_clearing_all_markers_preserves_membership_date_and_restart(media):
    store, repo, vid, source = media
    repo.set_score(vid, 0)
    added = store.video(vid)['library_added_at']
    repo.set_favorite(vid, True)
    store.execute('UPDATE videos SET tags=? WHERE id=?', ('["风景"]', vid))
    repo.set_score(vid, None)
    repo.set_favorite(vid, False)
    store.execute('UPDATE videos SET tags=? WHERE id=?', ('[]', vid))
    reopened = Store(store.directory)
    try:
        row = LibraryRepository(reopened).catalog_data()[0][0]
        assert row['id'] == vid and row['library_added_at'] == added
        assert row['score'] is None and not row['star'] and row['tag_names'] == ()
        assert not row['archived'] and reopened.resolve(vid) == source
    finally:
        reopened.db.close()


def test_marker_and_enrollment_roll_back_together(media):
    store, repo, vid, source = media
    with pytest.raises(OSError):
        with store.lock, store.db:
            store.db.execute('UPDATE videos SET score=7 WHERE id=?', (vid,))
            raise OSError('interrupted before commit')
    row = store.video(vid)
    assert row['score'] is None and not row['in_library'] and row['library_added_at'] is None
    assert not repo.catalog_data()[0] and repo.resolve(vid) == source


def test_later_archive_and_reorganization_do_not_replace_library_date(media, tmp_path):
    store, repo, vid, source = media
    repo.set_favorite(vid, True)
    added = store.video(vid)['library_added_at']
    archiver = Archiver(store, tmp_path / 'archive')
    archiver.submit(vid, 7, ['风景'], defer_cleanup=True)
    archived = store.video(vid)['archived_at']
    archiver.submit(vid, 8, ['旅行'], defer_cleanup=True)
    row = store.video(vid)
    assert row['in_library'] and row['library_added_at'] == added
    assert row['archived'] and row['archived_at'] == archived


def legacy_connection(factory=sqlite3.Connection):
    connection = sqlite3.connect(':memory:', factory=factory)
    connection.execute('CREATE TABLE videos(id TEXT PRIMARY KEY,name TEXT,score INTEGER,star INTEGER DEFAULT 0,position INTEGER DEFAULT 0,played REAL DEFAULT 0,archived INTEGER DEFAULT 0,tags TEXT DEFAULT "[]",archived_at REAL)')
    connection.execute('PRAGMA user_version=2')
    return connection


def test_upgrade_backfills_old_marked_files_keeps_unknown_dates_and_is_idempotent():
    connection = legacy_connection()
    rows = [('archived', None, 0, 1, '[]', 100), ('old', None, 0, 1, '[]', None),
            ('zero', 0, 0, 0, '[]', None), ('star', None, 1, 0, '[]', None),
            ('tag', None, 0, 0, '["风景"]', None), ('played', None, 0, 0, ' [ ] ', None)]
    connection.executemany('INSERT INTO videos(id,score,star,archived,tags,archived_at,played,position) VALUES(?,?,?,?,?,?,456,123)', rows)
    connection.commit()
    migrate(connection)
    snapshot = connection.execute('SELECT * FROM videos ORDER BY id').fetchall()
    assert connection.execute('SELECT id FROM videos WHERE in_library=0').fetchall() == [('played',)]
    assert connection.execute('SELECT library_added_at FROM videos WHERE id=?', ('archived',)).fetchone() == (100,)
    assert connection.execute('SELECT id FROM videos WHERE in_library=1 AND library_added_at IS NULL ORDER BY id').fetchall() == [('old',), ('star',), ('tag',), ('zero',)]
    assert all(row == (456, 123) for row in connection.execute('SELECT played,position FROM videos'))
    migrate(connection)
    assert connection.execute('SELECT * FROM videos ORDER BY id').fetchall() == snapshot
    connection.execute('UPDATE videos SET score=9 WHERE id="zero"')
    assert connection.execute('SELECT library_added_at FROM videos WHERE id="zero"').fetchone() == (None,)
    connection.close()


def test_membership_migration_rolls_back_rows_columns_triggers_and_version():
    class Interrupted(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'PRAGMA user_version=3':
                raise OSError('interrupted migration')
            return super().execute(sql, *args)
    connection = legacy_connection(Interrupted)
    connection.execute('INSERT INTO videos(id,score) VALUES("rated",0)')
    connection.commit()
    before = connection.execute('SELECT * FROM videos').fetchall()
    with pytest.raises(OSError):
        migrate(connection)
    assert connection.execute('PRAGMA user_version').fetchone() == (2,)
    assert connection.execute('SELECT * FROM videos').fetchall() == before
    assert not connection.execute('SELECT name FROM sqlite_master WHERE type="trigger"').fetchall()
    assert 'in_library' not in {row[1] for row in connection.execute('PRAGMA table_info(videos)')}
    connection.close()
