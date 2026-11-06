import json
from PySide6.QtCore import Qt, QItemSelectionModel, QPoint
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton
from core import Snapshot
from application.library import LibrarySelectionGroup
from batch_tag_editor import BatchTagEditor
from test_ui_refresh import window, context_wait
import pytest


def populate(window, tmp_path):
    window.thumbnails.request = lambda vid: None
    root, child = str(tmp_path), str(tmp_path / 'child')
    ids = []
    for n in range(4):
        path = tmp_path / f'{n}.mp4'
        path.write_bytes(f'video {n}'.encode())
        ids.append(window.store.register(path))
    snapshot = Snapshot(root, {root: ([child], list(zip(ids, [f'{n}.mp4' for n in range(4)]))), child: ([], [])})
    window.library_controller.adopt_snapshot(snapshot)
    QApplication.processEvents()
    return ids, snapshot


def click(view, row, modifier=Qt.NoModifier, button=Qt.LeftButton):
    index = view.model().index(row, 0)
    view.scrollTo(index)
    QApplication.processEvents()
    QTest.mouseClick(view.viewport(), button, modifier, view.visualRect(index).center())


def test_bottom_batch_switch_mouse_modifiers_and_folders_are_excluded(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    panel, listing = window.library_view, window.library_view.files
    assert panel.batch_select_button.isVisible()
    click(listing, 1)
    click(listing, 3, Qt.ControlModifier)
    assert {item.video_id for item in panel.selected_files()} == {ids[0], ids[2]}
    click(listing, 1)
    click(listing, 3, Qt.ShiftModifier)
    assert {item.video_id for item in panel.selected_files()} == set(ids[:3])
    QTest.mouseClick(panel.batch_select_button, Qt.LeftButton)
    listing.clearSelection()
    click(listing, 1)
    click(listing, 2)
    click(listing, 1)
    assert [item.video_id for item in panel.selected_files()] == [ids[1]]
    click(listing, 0)
    assert [item.video_id for item in panel.selected_files()] == [ids[1]]
    listing.setFocus()
    QTest.keyClick(listing, Qt.Key_A, Qt.ControlModifier)
    assert len(panel.selected_files()) == 4
    assert len(listing.selectionModel().selectedIndexes()) == 4
    assert '已选 4 项' in panel.batch_select_button.text()
    requested = QSignalSpy(panel.videoRequested)
    QTest.mouseDClick(listing.viewport(), Qt.LeftButton, Qt.NoModifier, listing.visualRect(listing.model().index(1, 0)).center())
    assert requested.count() == 0
    panel.show_mode('videos')
    assert not panel.batch_select_button.isVisible()
    panel.show_mode('files')
    QTest.mouseClick(panel.batch_select_button, Qt.LeftButton)
    assert len(panel.selected_files()) <= 1


def test_right_click_group_and_refresh_preserve_stable_selection(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    panel, listing = window.library_view, window.library_view.files
    panel.mediaContextRequested.disconnect(window.media_menu.open)
    requested = QSignalSpy(panel.mediaContextRequested)
    listing.selectAll()
    click(listing, 2, button=Qt.RightButton)
    panel._media_context(listing, 'files', listing.visualRect(listing.model().index(2, 0)).center())
    group = requested.at(0)[0]
    assert isinstance(group, LibrarySelectionGroup) and len(group.items) == 4
    # A refresh removes the focused selected row; other selected IDs survive.
    snapshot.excluded.add(ids[1])
    panel._sync_view(listing, lambda: listing.model().sync(snapshot, window.library_controller.details, ()))
    assert {item.video_id for item in panel.selected_files()} == {ids[0], ids[2], ids[3]}
    # Menu already holds the original identities, including the removed row.
    assert {item.video_id for item in group.items} == set(ids)
    click(listing, 1)
    click(listing, 2, button=Qt.RightButton)
    assert [item.video_id for item in panel.selected_files()] == [ids[2]]


def test_bulk_delete_confirm_defaults_to_records_and_preserves_local_bytes(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    panel = window.library_view
    panel.files.selectAll()
    window.delete_video()
    dialog = window.media_menu.batch_menu.active_dialog
    assert dialog and '4 个文件' in dialog.findChild(QLabel, 'batchStatus').text()
    status = dialog.findChild(QLabel, 'batchStatus')
    QApplication.processEvents()
    assert status.height() >= status.heightForWidth(status.width())
    assert not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked()
    QTest.mouseClick(dialog.findChild(QPushButton, 'batchDeleteConfirm'), Qt.LeftButton)
    assert context_wait(lambda: window.media_menu.batch_menu.active_dialog is None)
    assert all(window.catalog.video(vid) is None for vid in ids)
    assert [(tmp_path / f'{n}.mp4').read_bytes() for n in range(4)] == [f'video {n}'.encode() for n in range(4)]


def test_bulk_menu_shared_tag_editor_and_rating_preserve_unique_metadata(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    window.storage.enabled = False
    window.store.execute('INSERT INTO tags VALUES(?)', ('new',))
    window.store.execute('UPDATE videos SET tags=? WHERE id=?', (json.dumps(['existing']), ids[0]))
    panel = window.library_view
    panel.files.selectAll()
    group = panel.context_selection()
    menu = window.media_menu.build_menu(group)
    assert [a.text() for a in menu.actions() if not a.isSeparator() and a.isEnabled()] == ['收藏', '编辑标签', '评分', '删除']
    editor = menu.findChild(BatchTagEditor)
    assert not editor.editor.schema_editable and editor.editor.entry.isHidden()
    operation = window.batch_actions.tags(group.items, ['new'], 'add')
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded
    assert set(window.catalog.tag_values(ids[0]).tags) == {'existing', 'new'}
    assert all(window.catalog.tag_values(vid).tags == ['new'] for vid in ids[1:])
    operation = window.batch_actions.rating(group.items, 0)
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded and all(window.catalog.video(vid)['score'] == 0 for vid in ids)
    operation = window.batch_actions.favorite(group.items, True)
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded and all(window.catalog.video(vid)['star'] for vid in ids)
    assert all((tmp_path / f'{n}.mp4').exists() for n in range(4))


def test_bulk_menu_rating_waits_for_its_pending_tag_intent(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    window.storage.enabled = False
    window.library_view.files.selectAll()
    menu = window.media_menu.build_menu(window.library_view.context_selection())
    menu.popup(window.mapToGlobal(QPoint(20, 70)))
    menu.findChild(BatchTagEditor).editor.chips['existing'].click()
    from rating_editor import RatingEditor
    menu.findChild(RatingEditor).zero.click()
    assert context_wait(lambda: window.batch_actions.active is None and all(window.catalog.video(vid)['score'] == 0 for vid in ids))
    assert all(window.catalog.tag_values(vid).tags == ['existing'] for vid in ids)


def test_old_failed_target_draft_is_committed_before_bulk_change(window, tmp_path):
    from application.tag_drafts import TagValues
    ids, snapshot = populate(window, tmp_path)
    window.storage.enabled = False
    draft = window.tag_drafts.open_for(ids[1])
    window.tag_drafts.update(ids[1], TagValues(['existing'], draft.values.schema))
    window.library_view.files.selectAll()
    operation = window.batch_actions.favorite(window.library_view.selected_files(), True)
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded
    assert window.catalog.tag_values(ids[1]).tags == ['existing']
    assert all(window.catalog.video(vid)['star'] for vid in ids)


@pytest.mark.parametrize('delete_files', [True, False])
def test_bulk_delete_deduplicates_hardlink_aliases_and_freezes_mode(window, tmp_path, delete_files):
    import os
    ids, snapshot = populate(window, tmp_path)
    alias = tmp_path / 'alias.mp4'
    os.link(tmp_path / '0.mp4', alias)
    assert window.store.register(alias) == ids[0]
    snapshot.folders[str(tmp_path)][1].append((ids[0], alias.name))
    snapshot.visible_cache.clear()
    panel = window.library_view
    panel._sync_view(panel.files, lambda: panel.files.model().sync(snapshot, window.library_controller.details, ()))
    panel.files.selectAll()
    assert len(panel.selected_files()) == 4
    recycled = []
    def recycle(path):
        recycled.append(path)
        path.unlink()
    window.deleter.recycle = recycle
    operation = window.batch_actions.delete(panel.selected_files(), delete_files=delete_files)
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded and len(operation.outcome.value.completed) == 4
    assert alias.exists() != delete_files
    assert all((tmp_path / f'{n}.mp4').exists() != delete_files for n in range(4))
    assert len(recycled) == (5 if delete_files else 0)


def test_bulk_archive_favorite_uses_stable_ids_after_paths_and_rows_change(window, tmp_path):
    from application.archive_folders import ArchiveFolders
    ids, snapshot = populate(window, tmp_path)
    window.storage.root = tmp_path / 'archive'
    window.archiver.root = window.storage.root
    window.storage.folders = window.archiver.folders = ArchiveFolders(favorite=True, score=True, tags=True)
    for vid in ids:
        window.archiver.submit(vid, 4, ['existing'])
    panel = window.library_view
    panel.files.selectAll()
    group = panel.selected_files()
    operation = window.batch_actions.favorite(group, True)
    assert context_wait(lambda: not operation.pending)
    assert operation.outcome.succeeded and operation.outcome.value.completed == tuple(ids)
    for vid in ids:
        path = window.catalog.resolve(vid)
        assert '已收藏' in path.parts and path.exists()
        assert window.catalog.video(vid)['star']


def test_explicit_single_delete_target_overrides_visible_group(window, tmp_path):
    ids, snapshot = populate(window, tmp_path)
    window.library_view.files.selectAll()
    window.delete_video(ids[2])
    dialog = window.media_menu.active_dialog
    assert dialog is not None and window.media_menu.batch_menu.active_dialog is None
    assert '2.mp4' in '\n'.join(label.text() for label in dialog.findChildren(QLabel))
    dialog.reject()
