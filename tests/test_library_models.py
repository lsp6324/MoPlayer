from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPersistentModelIndex, qInstallMessageHandler
from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy
from PySide6.QtWidgets import QApplication
from core import Snapshot
from library_views import TreeModel, VideoListModel, DETAILS_ROLE


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


def test_tree_exclusion_preserves_original_indices_and_duplicate_id_entries(application, tmp_path):
    root, child = str(tmp_path), str(tmp_path / 'child')
    snapshot = Snapshot(root, {root: ([child], [('a', 'a.mp4'), ('b', 'b.mp4'), ('a', 'copy.mp4'), ('c', 'c.mp4')]),
                               child: ([], [('b', 'nested.mp4')])})
    details = {'c': dict(id='c', score=8)}
    model = TreeModel(snapshot, details)
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    root_index = model.index(0, 0)
    child_index = QPersistentModelIndex(model.index(0, 0, root_index))
    selected = QPersistentModelIndex(model.index(4, 0, root_index))
    resets = QSignalSpy(model.modelReset)
    snapshot.excluded.add('a')
    model.sync(snapshot, details, ['a'])
    assert model.rowCount(root_index) == 3 and child_index.isValid()
    assert selected.data(Qt.UserRole) == 'c' and selected.row() == 2
    assert model.index(2, 0, root_index).internalPointer()[2] == 3
    assert selected.data(DETAILS_ROLE)['score'] == 8 and resets.count() == 0
    assert model.parent(model.index(0, 0, child_index)) == child_index


def test_tree_names_change_without_reset_or_changing_logical_location(application, tmp_path):
    root = str(tmp_path)
    snapshot = Snapshot(root, {root: ([], [('a', 'before.mp4'), ('b', 'b.mp4')])})
    model = TreeModel(snapshot)
    parent = model.index(0, 0)
    selected = QPersistentModelIndex(model.index(0, 0, parent))
    snapshot.folders[root][1][0] = ('a', 'after.mp4')
    snapshot.visible_cache.clear()
    resets, changed = QSignalSpy(model.modelReset), QSignalSpy(model.dataChanged)
    model.sync(snapshot, {'a': {'score': 9}}, ['a'])
    assert selected.data(Qt.DisplayRole) == 'after.mp4' and selected.data(Qt.UserRole) == 'a'
    assert model.index(0, 0, parent).internalPointer() == ('video', root, 0)
    assert resets.count() == 0 and changed.count() == 1
