from core import Store
from infrastructure.library_repository import LibraryRepository


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
