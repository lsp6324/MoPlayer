from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPersistentModelIndex, qInstallMessageHandler
from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
from PySide6.QtWidgets import QApplication
from core import Snapshot
from library_views import FolderModel, VideoListModel, DETAILS_ROLE, FOLDER_ROLE, LOCATION_ROLE


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_recent_model_preserves_selected_identity_across_move_remove_insert(application):
    model = VideoListModel()
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, text: messages.append(text))
    try:
        rows = [dict(id=str(n), name=f'{n}.mp4', played=n, score=None) for n in range(40)]
        model.sync(rows)
        selected = QPersistentModelIndex(model.index(20, 0))
        resets = QSignalSpy(model.modelReset)
        changed = QSignalSpy(model.dataChanged)
        rows = [dict(rows[35], score=8), *rows[:35], *rows[36:]]
        model.sync(rows)
        assert selected.data(Qt.UserRole) == '20' and selected.row() == 21
        assert changed.count() == 1 and resets.count() == 0
        rows = [dict(id='new', name='new.mp4'), *[row for row in rows if row['id'] != '3']]
        model.sync(rows)
        assert selected.data(Qt.UserRole) == '20' and model.index_for_id('new').row() == 0
        assert not model.index_for_id('3').isValid() and resets.count() == 0
        model.sync([row for row in rows if row['id'] != '20'])
        assert not selected.isValid()
        assert not [text for text in messages if 'FAIL!' in text]
    finally:
        qInstallMessageHandler(previous)


def test_large_library_sort_preserves_persistent_selection_without_reset(application):
    model = VideoListModel()
    rows = [dict(id=str(n), name=f'项目{n}.mp4') for n in range(10000)]
    model.sync(rows)
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    selected = QPersistentModelIndex(model.index(731, 0))
    resets = QSignalSpy(model.modelReset)
    model.sync(list(reversed(rows)))
    assert selected.isValid() and selected.data(Qt.UserRole) == '731' and selected.row() == 9268
    assert resets.count() == 0 and model.rowCount() == 10000


def test_folder_exclusion_preserves_original_indices_and_duplicate_id_entries(application, tmp_path):
    root, child = str(tmp_path), str(tmp_path / 'child')
    snapshot = Snapshot(root, {root: ([child], [('a', 'a.mp4'), ('b', 'b.mp4'), ('a', 'copy.mp4'), ('c', 'c.mp4')]),
                               child: ([], [('b', 'nested.mp4')])})
    details = {'c': dict(id='c', score=8)}
    model = FolderModel(snapshot, root, details)
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    child_index = QPersistentModelIndex(model.index(0, 0))
    selected = QPersistentModelIndex(model.index(4, 0))
    resets = QSignalSpy(model.modelReset)
    snapshot.excluded.add('a')
    model.sync(snapshot, details, ['a'])
    assert model.rowCount() == 3 and child_index.isValid()
    assert selected.data(Qt.UserRole) == 'c' and selected.row() == 2
    assert model.index(2, 0).data(LOCATION_ROLE) == (root, 3)
    assert selected.data(DETAILS_ROLE)['score'] == 8 and resets.count() == 0
    assert child_index.data(FOLDER_ROLE) == child and model.rowCount(child_index) == 0
    assert not child_index.parent().isValid()


def test_folder_names_change_without_reset_or_changing_logical_location(application, tmp_path):
    root = str(tmp_path)
    snapshot = Snapshot(root, {root: ([], [('a', 'before.mp4'), ('b', 'b.mp4')])})
    model = FolderModel(snapshot, root)
    selected = QPersistentModelIndex(model.index(0, 0))
    snapshot.folders[root][1][0] = ('a', 'after.mp4')
    snapshot.visible_cache.clear()
    resets, changed = QSignalSpy(model.modelReset), QSignalSpy(model.dataChanged)
    model.sync(snapshot, {'a': {'score': 9}}, ['a'])
    assert selected.data(Qt.DisplayRole) == 'after.mp4' and selected.data(Qt.UserRole) == 'a'
    assert model.index(0, 0).data(LOCATION_ROLE) == (root, 0)
    assert resets.count() == 0 and changed.count() == 1


def test_folder_model_shows_only_immediate_children_and_preserves_alias_keys(application, tmp_path):
    root, child, nested = map(str, (tmp_path, tmp_path / 'child', tmp_path / 'child' / 'nested'))
    snapshot = Snapshot(root, {root: ([child], [('a', 'A.mp4')]),
        child: ([nested], [('b', 'B.mp4'), ('b', 'alias.mp4')]), nested: ([], [('c', 'C.mp4')])})
    model = FolderModel(snapshot, root)
    assert model.rowCount() == 2 and model.data(model.index(0, 0), FOLDER_ROLE) == child
    assert model.index(1, 0).data(Qt.DisplayRole) == 'A.mp4'
    nested_model = FolderModel(snapshot, child)
    keys = [nested_model.key(nested_model.index(row, 0)) for row in (1, 2)]
    assert keys[0] != keys[1]
    assert [nested_model.index_for_key(key).row() for key in keys] == [1, 2]


def test_contents_insert_remove_and_reorder_preserve_selected_identity_and_new_location(application, tmp_path):
    root, child, new_child = str(tmp_path), str(tmp_path / 'child'), str(tmp_path / 'added')
    before = Snapshot(root, {root: ([child], [('a', 'A.mp4'), ('b', 'B.mp4'), ('c', 'C.mp4')])})
    model = FolderModel(before, root)
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    selected = QPersistentModelIndex(model.index(2, 0))
    key = model.key(model.index(2, 0))
    after = Snapshot(root, {root: ([new_child, child], [('x', '00.mp4'), ('c', 'C.mp4'), ('b', 'B.mp4')])})
    resets = QSignalSpy(model.modelReset)
    model.sync(after, {}, ())
    assert selected.data(Qt.UserRole) == 'b' and selected.row() == 4
    assert selected.data(LOCATION_ROLE) == (root, 2)
    assert model.key(model.index(4, 0)) == key and resets.count() == 0
    assert [model.index(n, 0).data(Qt.DisplayRole) for n in range(model.rowCount())] == ['added', 'child', '00.mp4', 'C.mp4', 'B.mp4']


def test_external_rename_preserves_unique_video_and_aliases_remain_distinct(application, tmp_path):
    root = str(tmp_path)
    model = FolderModel(Snapshot(root, {root: ([], [('a', 'A.mp4'), ('b', 'B.mp4'), ('b', 'alias.mp4')])}), root)
    unique = QPersistentModelIndex(model.index(0, 0))
    alias = QPersistentModelIndex(model.index(2, 0))
    model.sync(Snapshot(root, {root: ([], [('b', 'alias.mp4'), ('a', 'renamed.mp4'), ('b', 'B.mp4')])}), {}, ())
    assert unique.isValid() and unique.data(Qt.DisplayRole) == 'renamed.mp4' and unique.row() == 1
    assert alias.isValid() and alias.data(Qt.DisplayRole) == 'alias.mp4' and alias.row() == 0
    assert alias.data(LOCATION_ROLE) == (root, 0)


def test_removed_hard_link_entry_does_not_select_another_alias(application, tmp_path):
    root = str(tmp_path)
    before = Snapshot(root, {root: ([], [('a', 'A.mp4'), ('a', 'alias.mp4')])})
    model = FolderModel(before, root)
    key = model.key(model.index(0, 0))
    model.sync(Snapshot(root, {root: ([], [('a', 'alias.mp4')])}), {}, ())
    assert not model.index_for_key(key).isValid()
    assert model.rowCount() == 1 and model.index(0, 0).data(Qt.DisplayRole) == 'alias.mp4'
