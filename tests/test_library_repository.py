from moplayer.core import Store
from moplayer.infrastructure.library_repository import LibraryRepository


def test_metadata_snapshot_handles_large_requested_sets_and_excludes_unrelated_videos(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        with store.lock, store.db:
            store.db.executemany('INSERT INTO videos(id,name,score) VALUES(?,?,?)',
                                 [(str(i), f'video-{i}.mp4', i % 11) for i in range(1002)])
        catalog = LibraryRepository(store)
        requested = [str(i) for i in range(1001)]
        rows = catalog.video_details([*requested, '0', 'missing'])
        assert set(rows) == set(requested)
        assert rows['1000']['name'] == 'video-1000.mp4'
        assert rows['1000']['score'] == 1000 % 11
        assert catalog.video_details([]) == {}
    finally:
        store.db.close()


def test_archive_settings_batch_appears_in_pending_and_history(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        store.execute('INSERT INTO archive_setting_jobs VALUES(?,?,?,?,?)', ('settings', 'migrating', '{}', 'interrupted', 1))
        catalog = LibraryRepository(store)
        assert catalog.pending_tasks()[0]['kind'] == 'archive_setting_jobs'
        assert catalog.task_history()[0]['kind'] == 'archive_setting_jobs'
        store.execute('UPDATE archive_setting_jobs SET state="done" WHERE id="settings"')
        assert catalog.pending_tasks() == []
        assert catalog.task_history()[0]['state'] == 'done'
    finally:
        store.db.close()
