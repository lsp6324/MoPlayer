import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication
from application.tag_drafts import TagValues
from takeover_dialog import TakeoverDialog
from test_ui_refresh import window, context_wait
from test_takeover import media, dump


def dialog(window):
    view = TakeoverDialog(window, workflow=window.takeover, folders=window.storage.folders)
    view.show()
    QApplication.processEvents()
    return view


def test_takeover_is_discoverable_and_cancelled_preview_does_not_create_records(window, tmp_path):
    menu = window.title_bar.findChild(type(window.library_view.import_button), 'settingsButton').menu()
    assert '接管已有文件夹' in [action.text() for action in menu.actions()]
    root = tmp_path / 'old'
    media(root, 'parent/child/a.mp4')
    before = dump(window.store)
    view = dialog(window)
    view.path.setText(str(root))
    view.mode.setCurrentIndex(1)
    QTest.mouseClick(view.scan, Qt.LeftButton)
    assert context_wait(lambda: not view.pending)
    assert view.model.rowCount() == 1 and view.confirm.isEnabled()
    assert view.model.data(view.model.index(0, 1)) == 'parent › child'
    view.reject()
    assert dump(window.store) == before


def test_rule_edit_invalidates_plan_and_row_selection_controls_import(window, tmp_path):
    root = tmp_path / 'old'
    paths = [media(root, 'one/a.mp4'), media(root, 'two/b.png')]
    view = dialog(window)
    view.path.setText(str(root))
    view.start_scan()
    assert context_wait(lambda: not view.pending)
    view.mode.setCurrentIndex(1)
    assert view.model.plan is None and not view.confirm.isEnabled()
    view.start_scan()
    assert context_wait(lambda: not view.pending)
    skipped = view.model.index(1, 0)
    assert view.model.setData(skipped, Qt.Unchecked, Qt.CheckStateRole)
    assert '1 项' in view.selection_count.text()
    view.submit()
    assert context_wait(lambda: view.imported)
    rows = window.store.query('SELECT * FROM videos WHERE in_library=1')
    assert len(rows) == 1 and json.loads(rows[0]['tags']) == ['one']
    assert all(path.exists() for path in paths) and not rows[0]['archived']
    view.reject()


def test_conflicts_are_excluded_until_explicit_enrollment_only_choice(window, tmp_path):
    root = tmp_path / 'old'
    media(root, 'A/shared/a.mp4')
    media(root, 'B/shared/b.mp4')
    view = dialog(window)
    view.path.setText(str(root))
    view.mode.setCurrentIndex(1)
    view.start_scan()
    assert context_wait(lambda: not view.pending)
    assert not view.confirm.isEnabled() and len(view.model.selected) == 0
    assert '父级不一致' in view.details.toPlainText()
    from PySide6.QtGui import QPalette
    assert view.model.data(view.model.index(0, 0), Qt.ForegroundRole) == window.palette().color(QPalette.PlaceholderText)
    view.conflicts.click()
    assert len(view.model.selected) == 2 and view.confirm.isEnabled()
    view.submit()
    assert context_wait(lambda: view.imported)
    rows = window.store.query('SELECT * FROM videos WHERE in_library=1')
    assert len(rows) == 2 and all(row['tags'] == '[]' for row in rows)
    assert not {'A', 'B', 'shared'}.intersection(window.store.tag_layout())
    view.reject()


def test_scan_cancel_and_close_wait_for_worker_and_never_publish_late_plan(window, tmp_path):
    root = tmp_path / 'old'
    media(root, 'file.mp4')
    queued = []
    window.takeover.dispatch = lambda work, done: queued.append((work, done))
    view = dialog(window)
    view.path.setText(str(root))
    view.start_scan()
    work, done = queued.pop()
    plan = work()
    closed = QSignalSpy(view.finished)
    view.reject()
    assert view.isVisible() and view.pending
    done(plan, None)
    assert context_wait(lambda: closed.count() == 1)
    assert len(window.store.query('SELECT * FROM videos')) == 1


def test_import_dialog_cannot_close_mid_transaction_and_failure_preserves_preview(window, tmp_path):
    root = tmp_path / 'old'
    media(root, 'file.mp4')
    view = dialog(window)
    view.path.setText(str(root))
    view.start_scan()
    assert context_wait(lambda: not view.pending)
    queued = []
    window.file_tasks.dispatch = lambda work, done: queued.append((work, done))
    view.submit()
    QTest.keyClick(view, Qt.Key_Escape)
    view.close()
    assert view.isVisible() and view.pending and not view.configuration.isEnabled()
    work, done = queued.pop()
    done(None, OSError('injected import failure'))
    assert context_wait(lambda: not view.pending)
    assert view.model.plan is not None and view.confirm.isEnabled() and 'injected' in view.status.text()
    assert window.store.query('SELECT * FROM videos WHERE in_library=1') == []
    view.reject()


def test_dirty_noncurrent_tag_draft_blocks_takeover_without_losing_intent(window, tmp_path):
    root = tmp_path / 'old'
    path = media(root, 'file.mp4')
    vid = window.store.register(path)
    draft = window.tag_drafts.open_for(vid)
    window.tag_drafts.update(vid, TagValues(['existing'], draft.values.schema))
    view = dialog(window)
    view.path.setText(str(root))
    view.start_scan()
    assert context_wait(lambda: not view.pending)
    view.submit()
    assert context_wait(lambda: not view.pending)
    assert '未保存' in view.status.text() and vid in window.tag_drafts.dirty_ids
    assert not window.catalog.video(vid)['in_library']
    view.reject()
