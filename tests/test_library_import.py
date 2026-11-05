"""Real scan/identity integration without Qt or VLC."""
from threading import Event

import pytest

from core import EXTENSIONS, Store
from infrastructure.library_scanner import LibraryScanner


@pytest.fixture
def scanner(tmp_path):
    store = Store(tmp_path / 'data')
    yield LibraryScanner(store)
    store.db.close()


def test_single_video_import_preserves_identity_metadata_and_resume(scanner, tmp_path):
    folder = tmp_path / '中文 有空格'
    folder.mkdir()
    first, chosen = folder / 'A.mp4', folder / '选中.MP4'
    first.write_bytes(b'first')
    chosen.write_bytes(b'chosen')
    vid = scanner.store.register(chosen)
    scanner.store.execute('UPDATE videos SET score=7,star=1,position=12000 WHERE id=?', (vid,))
    snapshot, errors, selected = scanner.scan_import(chosen, Event())
    assert not errors and selected == vid and snapshot.root == str(folder)
    assert {name for _, name in snapshot.folders[str(folder)][1]} == {'A.mp4', '选中.MP4'}
    row = scanner.store.query('SELECT * FROM videos WHERE id=?', (vid,))[0]
    assert (row['score'], row['star'], row['position']) == (7, 1, 12000)
    assert chosen.read_bytes() == b'chosen'


def test_import_candidate_formats_share_the_existing_scanner_policy(scanner, tmp_path):
    assert scanner.can_import(tmp_path)
    for suffix in EXTENSIONS:
        path = tmp_path / ('sample' + suffix.upper())
        path.write_bytes(b'candidate')
        assert scanner.can_import(path)
    text = tmp_path / 'notes.txt'
    text.write_text('not a video')
    assert not scanner.can_import(text)
    assert not scanner.can_import(tmp_path / 'missing.mp4')
    with pytest.raises(ValueError):
        scanner.scan_import(text, Event())


def test_import_revalidates_after_drag_and_cancellation_does_not_register(scanner, tmp_path):
    path = tmp_path / 'removed.mp4'
    path.write_bytes(b'video')
    assert scanner.can_import(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        scanner.scan_import(path, Event())
    path.write_bytes(b'replaced')
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        scanner.scan_import(path, cancelled)
    assert scanner.store.query('SELECT * FROM videos') == []


def test_folder_import_keeps_recursive_browse_without_selected_video(scanner, tmp_path):
    nested = tmp_path / 'folder' / 'nested'
    nested.mkdir(parents=True)
    (nested / 'clip.webm').write_bytes(b'video')
    snapshot, errors, selected = scanner.scan_import(nested.parent, Event())
    assert not errors and selected is None
    assert snapshot.folders[str(nested)][1][0][1] == 'clip.webm'
