"""Interaction checks against real Qt controls and the remote data model.

Run with QT_QPA_PLATFORM=offscreen; native VLC composition has a separate
private-desktop check in verify_ui_refresh.py.
"""
import json
import time
from application.operations import Operation
from unittest.mock import Mock
import pytest
from PySide6.QtCore import Qt, QPoint, QEvent, QCoreApplication, QThreadPool
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window
from runtime import load_vlc
vlc = load_vlc()
from theme import apply_theme


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    player = Window(tmp_path / 'data')
    player.timer.stop()
    sample = tmp_path / 'sample.mp4'
    sample.write_bytes(b'UI metadata fixture; never decoded')
    player.current = player.store.register(sample)
    player.store.execute('UPDATE videos SET played=1 WHERE id=?', (player.current,))
    player.store.execute('INSERT INTO tags VALUES(?)', ('existing',))
    player.refresh_title()
    player.resize(900, 580)
    player.show()
    application.processEvents()
    yield player
    player.tag_drafts.discard_all()
    player.busy = False
    player.close()
    QThreadPool.globalInstance().waitForDone()
    player.thumbnails.pool.waitForDone()
    player.store.db.close()
    player.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_integrated_layout_and_quiet_feedback(window):
    assert window.theme == 'light'
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.splitter.widget(0) is window.library_view
    from PySide6.QtCore import QModelIndex
    assert window.library_view.files.itemDelegate().sizeHint(None, QModelIndex()).height() == 44
    height = window.player_view.surface.height()
    window.message('saved')
    QApplication.processEvents()
    assert not window.statusBar().isVisible()
    assert window.player_view.surface.height() == height
    assert window.player_view.control_row.center.isVisible()


@pytest.mark.parametrize('mode', ['videos', 'stars'])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_recent_and_favorite_members_render_the_same_card_as_library(window, mode, theme):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QStyleOptionViewItem
    from library_views import VideoDelegate
    apply_theme(window, theme)
    window.store.execute('INSERT INTO tags VALUES(?)', ('子标签',))
    window.store.execute('INSERT INTO tag_layout VALUES(?,?,?)', ('子标签', 'minor', 'existing'))
    window.store.execute('UPDATE videos SET tags=?,score=0,star=1 WHERE id=?',
                         (json.dumps(['子标签']), window.current))
    controller, view = window.library_controller, window.library_view
    controller.load_list(mode)
    row = controller.list_rows(mode)[0]
    assert row['in_library'] and row['tag_labels'] == ('existing › 子标签',)
    index = view.lists[mode].model().index_for_id(window.current)
    assert index.isValid()
    thumb = QPixmap(140, 79)
    thumb.fill(QColor('#836b34'))
    window.thumbnails.request = Mock(return_value=thumb)
    option = QStyleOptionViewItem()
    option.rect, option.font = QRect(0, 0, 340, 96), view.font()

    def render(delegate):
        image = QImage(340, 96, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        return image

    rich = view.catalog_panel.list.itemDelegate()
    simple = VideoDelegate(window.thumbnails, view.files, current_video=lambda: window.current, theme_owner=window)
    assert render(view.lists[mode].itemDelegate()) == render(rich)
    assert render(view.files.itemDelegate()) == render(simple)
    assert render(rich) != render(simple)
    # A metadata edit reaches the same existing row without losing selection.
    view.lists[mode].setCurrentIndex(index)
    from PySide6.QtTest import QSignalSpy
    resets = QSignalSpy(view.lists[mode].model().modelReset)
    window.store.execute('UPDATE videos SET score=9 WHERE id=?', (window.current,))
    controller.refresh([window.current])
    assert view.lists[mode].currentIndex().data(Qt.UserRole) == window.current and resets.count() == 0
    assert render(view.lists[mode].itemDelegate()) == render(rich)


def test_recent_unlisted_card_stays_simple_until_marked_and_keeps_library_style_after_clearing(window):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QStyleOptionViewItem
    controller, view = window.library_controller, window.library_view
    controller.load_list('videos')
    model = view.lists['videos'].model()
    index = model.index_for_id(window.current)
    assert not index.data(Qt.UserRole + 1)['in_library']
    thumb = QPixmap(140, 79)
    thumb.fill(Qt.black)
    window.thumbnails.request = Mock(return_value=thumb)
    option = QStyleOptionViewItem()
    option.rect, option.font = QRect(0, 0, 340, 96), view.font()

    def render(delegate):
        image = QImage(340, 96, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        return image

    recent, simple, rich = view.lists['videos'].itemDelegate(), view.files.itemDelegate(), view.catalog_panel.list.itemDelegate()
    assert render(recent) == render(simple)
    window.store.execute('UPDATE videos SET score=0 WHERE id=?', (window.current,))
    controller.refresh([window.current])
    assert render(recent) == render(rich) and render(recent) != render(simple)
    window.store.execute('UPDATE videos SET score=NULL WHERE id=?', (window.current,))
    controller.refresh([window.current])
    assert index.data(Qt.UserRole + 1)['in_library']
    assert render(recent) == render(rich) and render(recent) != render(simple)


def test_single_video_drop_loads_parent_and_plays_selected_identity_after_save(window, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from application.operations import Outcome, Status
    folder = tmp_path / '拖入 文件夹'
    folder.mkdir()
    a, b, c = [folder / name for name in ('A.mp4', 'B.MP4', 'C.mp4')]
    for path in (a, b, c):
        path.write_bytes(path.name.encode())
    chosen = window.catalog.register(c)
    window.catalog.progress(chosen, 9000)
    played = []
    window.play_path = lambda path, position, paused: played.append((path, position))
    saving = Operation()
    window.player_view.options.flush_pending = lambda: saving if saving.pending else Operation.success()
    tree = window.library_view.files
    def drop(path):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter = QDragEnterEvent(QPoint(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(tree.viewport(), enter)
        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(tree.viewport(), event)
        assert enter.isAccepted() and event.isAccepted()
    drop(b)
    drop(c)
    assert not played and not window.library_controller.scanning
    saving.finish(Outcome(Status.SUCCEEDED))
    deadline = time.monotonic() + 5
    while not played and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert played == [(c, 9000)]
    assert window.current == chosen and window.library_controller.browsing.root == str(folder)


def test_drop_rejects_invalid_payloads_and_rechecks_removed_file(window, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtTest import QSignalSpy
    tree = window.library_view.files
    signal = QSignalSpy(tree.dropped)
    video = tmp_path / 'drop.mp4'
    video.write_bytes(b'video')
    text = tmp_path / 'notes.txt'
    text.write_text('text')
    for urls in ([], [QUrl('https://example.test/video.mp4')], [QUrl.fromLocalFile(str(text))],
                 [QUrl.fromLocalFile(str(video))] * 2):
        mime = QMimeData()
        mime.setUrls(urls)
        enter = QDragEnterEvent(QPoint(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        tree.dragEnterEvent(enter)
        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        tree.dropEvent(event)
        assert not enter.isAccepted() and not event.isAccepted()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(video))])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragEnterEvent(enter)
    assert enter.isAccepted()
    video.unlink()
    event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dropEvent(event)
    assert not event.isAccepted() and signal.count() == 0


def test_failed_draft_save_prevents_dropped_video_from_replacing_current(window, tmp_path):
    from application.operations import Outcome, Status
    path = tmp_path / 'next.mp4'
    path.write_bytes(b'next')
    previous = window.current
    saving = Operation()
    window.player_view.options.flush_pending = lambda: saving
    window.import_library_path(str(path))
    saving.finish(Outcome(Status.FAILED, error=OSError('save failed')))
    QApplication.processEvents()
    assert window.current == previous and window.library_controller.browsing is None


def test_folder_browse_uses_flat_rows_and_does_not_change_playback(window, tmp_path):
    from core import Snapshot
    from library_views import FOLDER_ROLE, LOCATION_ROLE
    from PySide6.QtTest import QSignalSpy
    root, child, leaf = map(str, (tmp_path, tmp_path / 'child', tmp_path / 'child' / 'leaf'))
    snapshot = Snapshot(root, {root: ([child], [(window.current, 'root.mp4')]),
        child: ([leaf], []), leaf: ([], [(window.current, 'leaf.mp4')])})
    panel = window.library_view
    requested = QSignalSpy(panel.videoRequested)
    previous = window.current
    window.library_controller.adopt_snapshot(snapshot)
    QApplication.processEvents()
    assert panel.current_folder == root and panel.files.model().rowCount() == 2
    assert panel.folder_navigation.up.isEnabled()
    left = panel.files.visualRect(panel.files.model().index(1, 0)).left()
    for folder in (child, leaf):
        index = panel.files.model().index(0, 0)
        assert index.data(FOLDER_ROLE) == folder
        panel.files.doubleClicked.emit(index)
        QApplication.processEvents()
        assert panel.current_folder == folder
    model = panel.files.model()
    assert model.rowCount() == 1 and model.index(0, 0).data(LOCATION_ROLE) == (leaf, 0)
    assert panel.files.visualRect(model.index(0, 0)).left() == left
    assert requested.count() == 0 and window.current == previous
    panel.folder_navigation.up.click()
    assert panel.current_folder == child
    panel.show_mode('videos')
    panel.show_mode('files')
    assert panel.current_folder == child


def test_short_folder_breadcrumb_remains_readable_after_layout(window, tmp_path):
    from core import Snapshot
    from PySide6.QtWidgets import QPushButton, QStyleOptionButton, QStyle
    root = str(tmp_path.anchor + '样例')
    window.library_controller.adopt_snapshot(Snapshot(root, {root: ([], [])}))
    QApplication.processEvents()
    navigation = window.library_view.folder_navigation
    current = next(control for control in navigation.findChildren(QPushButton) if control.property('current'))
    assert current.text() == '样例'
    option = QStyleOptionButton()
    current.initStyleOption(option)
    available = current.style().subElementRect(QStyle.SE_PushButtonContents, option, current).width()
    assert current.fontMetrics().horizontalAdvance(current.text()) <= available


def test_same_named_import_folders_show_their_drive_in_breadcrumbs(window):
    from pathlib import Path
    from core import Snapshot
    from PySide6.QtWidgets import QPushButton
    navigation = window.library_view.folder_navigation
    captions = []
    for drive in ('C:', 'E:'):
        root = str(Path(drive + '/学习资料'))
        window.library_controller.adopt_snapshot(Snapshot(root, {root: ([], [])}))
        QApplication.processEvents()
        current = next(control for control in navigation.findChildren(QPushButton)
                       if control.isVisible() and control.property('current'))
        drive_button = next(control for control in navigation.findChildren(QPushButton)
                            if control.isVisible() and control.property('root'))
        captions.append(drive_button.text())
        assert drive_button.text().startswith(drive) and current.text() == '学习资料'
        assert current.toolTip() == root and navigation.up.isEnabled()
    assert captions[0] != captions[1]


def test_drive_breadcrumb_targets_disk_root_and_up_stops_only_there(window, tmp_path):
    from pathlib import Path
    from core import Snapshot
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QSignalSpy
    root = str(tmp_path / '导入目录')
    window.library_controller.adopt_snapshot(Snapshot(root, {root: ([], [])}))
    QApplication.processEvents()
    navigation = window.library_view.folder_navigation
    navigation.requested.disconnect(window.library_view.browse_folder)
    requested = QSignalSpy(navigation.requested)
    drive = next(control for control in navigation.findChildren(QPushButton)
                 if control.isVisible() and control.property('root'))
    QTest.mouseClick(drive, Qt.LeftButton)
    assert requested.at(0)[0] == Path(root).anchor
    QTest.mouseClick(navigation.up, Qt.LeftButton)
    assert requested.at(1)[0] == str(Path(root).parent)
    navigation.set_path(Path(root).anchor)
    assert not navigation.up.isEnabled()


def test_browse_outside_import_and_enter_sibling_preserves_playback_history_and_selection(window, tmp_path, monkeypatch):
    from library_views import FOLDER_ROLE
    root, sibling = tmp_path / '导入', tmp_path / '其他'
    root.mkdir()
    sibling.mkdir()
    (root / 'A.mp4').write_bytes(b'root')
    (sibling / 'B.mp4').write_bytes(b'sibling')
    deep = sibling / '深层'
    deep.mkdir()
    (deep / '不应扫描.mp4').write_bytes(b'deep')
    window.thumbnails.request = lambda vid: None
    def wait(predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        return False
    loaded = window.load_folder(str(root))
    assert wait(lambda: not loaded.pending) and loaded.outcome.succeeded
    view = window.library_view
    view.files.setCurrentIndex(view.files.model().index(0, 0))
    selected = view.files.currentIndex().data(Qt.UserRole)
    playback = (window.current, window.context, window.location)
    monkeypatch.setattr(window.library_controller.scanner, 'scan', lambda *args: pytest.fail('Navigation must not import recursively'))
    view.folder_navigation.up.click()
    assert wait(lambda: view.current_folder == str(tmp_path))
    assert set(window.library_controller.browsing.folders) == {str(tmp_path)}
    assert str(window.library_controller.last_folder()) == str(root)
    model = view.files.model()
    index = next(model.index(n, 0) for n in range(model.rowCount()) if model.index(n, 0).data(FOLDER_ROLE) == str(sibling))
    view.files.doubleClicked.emit(index)
    assert wait(lambda: view.current_folder == str(sibling))
    assert set(window.library_controller.browsing.folders) == {str(sibling)}
    assert not window.store.query('SELECT * FROM videos WHERE name=?', ('不应扫描.mp4',))
    view.browse_folder(str(root))
    assert wait(lambda: view.current_folder == str(root))
    assert view.files.currentIndex().data(Qt.UserRole) == selected
    assert (window.current, window.context, window.location) == playback
    assert str(window.library_controller.last_folder()) == str(root)


def test_inaccessible_directory_keeps_current_view_and_shows_inline_error(window, tmp_path, monkeypatch):
    from core import Snapshot
    root = str(tmp_path)
    window.library_controller.adopt_snapshot(Snapshot(root, {root: ([], [])}))
    def denied(*args):
        raise PermissionError('no access')
    monkeypatch.setattr(window.library_controller.scanner, 'directory', denied)
    window.library_view.browse_folder(str(tmp_path.parent))
    deadline = time.monotonic() + 4
    while window.library_controller.scanning and time.monotonic() < deadline:
        QTest.qWait(10)
    assert window.library_view.current_folder == root
    assert 'no access' in window.library_view.folder_error.text() and window.library_view.folder_error.isVisible()


def test_folder_return_restores_selection_scroll_and_metadata_refresh_preserves_rows(window, tmp_path):
    from core import Snapshot
    from library_views import LOCATION_ROLE
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QAbstractItemView
    window.thumbnails.request = lambda vid: None
    root, child = str(tmp_path), str(tmp_path / 'child')
    entries = []
    for n in range(50):
        path = tmp_path / f'clip-{n}.mp4'
        path.write_bytes(str(n).encode())
        entries.append((window.catalog.register(path), path.name))
    snapshot = Snapshot(root, {root: ([child], entries), child: ([], [])})
    window.library_controller.adopt_snapshot(snapshot)
    panel, view = window.library_view, window.library_view.files
    QApplication.processEvents()
    selected_key = view.model().key(view.model().index(30, 0))
    selected_location = view.model().index(30, 0).data(LOCATION_ROLE)
    view.setCurrentIndex(view.model().index(30, 0))
    view.scrollTo(view.currentIndex(), QAbstractItemView.PositionAtTop)
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 21)
    anchor_key = view.model().key(view.indexAt(QPoint(1, 1)))
    offset = view.visualRect(view.indexAt(QPoint(1, 1))).top()
    panel.browse_folder(child)
    assert panel.file_count.text() == '0 部'
    panel.browse_folder(root)
    QApplication.processEvents()
    assert view.model().key(view.currentIndex()) == selected_key
    assert view.model().key(view.indexAt(QPoint(1, 1))) == anchor_key
    assert view.visualRect(view.indexAt(QPoint(1, 1))).top() == offset
    resets = QSignalSpy(view.model().modelReset)
    vid = view.currentIndex().data(Qt.UserRole)
    window.catalog.set_score(vid, 8)
    window.library_controller.refresh([vid])
    assert view.currentIndex().data(Qt.UserRole) == vid and resets.count() == 0
    window.library_controller.exclude([vid])
    assert panel.file_count.text() == '49 部' and not view.selectionModel().hasSelection()
    assert snapshot.folders[root][1][selected_location[1]][0] == vid


def test_deep_breadcrumbs_fold_and_allow_ancestor_navigation(window, tmp_path):
    from core import Snapshot
    from PySide6.QtWidgets import QPushButton
    paths = [tmp_path]
    for n in range(8):
        paths.append(paths[-1] / f'很长的目录名称{n}')
    folders = {str(path): ([str(paths[n + 1])] if n + 1 < len(paths) else [], []) for n, path in enumerate(paths)}
    window.library_controller.adopt_snapshot(Snapshot(str(tmp_path), folders))
    panel = window.library_view
    panel.browse_folder(str(paths[-1]))
    navigation = panel.folder_navigation
    navigation.setFixedWidth(260)
    QApplication.processEvents()
    overflow = next(control for control in navigation.findChildren(QPushButton) if control.menu() and control.isVisible())
    action = next(action for action in overflow.menu().actions() if action.toolTip() == str(paths[3]))
    assert navigation.toolTip() == str(paths[-1])
    for control in navigation.findChildren(QPushButton):
        if control.isVisible():
            assert control.geometry().right() < navigation.width()
    action.trigger()
    assert panel.current_folder == str(paths[3])


def test_requested_nested_video_opens_its_directory_in_flat_browser(window, tmp_path):
    child = tmp_path / 'nested'
    child.mkdir()
    target = child / 'chosen.mp4'
    target.write_bytes(b'target')
    vid = window.catalog.register(target)
    window.play_path = lambda *args: None
    operation = window.load_folder(str(tmp_path), vid)
    deadline = time.monotonic() + 5
    while operation.pending and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert operation.outcome.succeeded and window.current == vid
    assert window.library_view.current_folder == str(child)
    assert window.library_view.files.currentIndex().data(Qt.UserRole) == vid


def test_external_directory_changes_refresh_automatically_and_keep_stable_selection(window, tmp_path):
    from PySide6.QtCore import QPersistentModelIndex
    from PySide6.QtTest import QSignalSpy
    from library_views import FOLDER_ROLE, LOCATION_ROLE
    window.thumbnails.request = lambda vid: None
    root = tmp_path / 'watched'
    root.mkdir()
    a, b = root / 'A.mp4', root / 'B.mp4'
    a.write_bytes(b'A')
    b.write_bytes(b'B')
    previous = window.current
    def wait(predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    loaded = window.load_folder(str(root))
    assert wait(lambda: not loaded.pending) and loaded.outcome.succeeded
    panel, view = window.library_view, window.library_view.files
    model = view.model()
    view.setCurrentIndex(model.index(1, 0))
    selected = QPersistentModelIndex(view.currentIndex())
    selected_id = selected.data(Qt.UserRole)
    resets = QSignalSpy(model.modelReset)
    added = root / '00.mp4'
    added.write_bytes(b'added')
    assert wait(lambda: model.rowCount() == 3)
    assert view.currentIndex().data(Qt.UserRole) == selected_id and selected.row() == 2
    assert selected.data(LOCATION_ROLE) == (str(root), 2)
    aid = model.index(1, 0).data(Qt.UserRole)
    a.rename(root / 'Z renamed.mp4')
    assert wait(lambda: model.index(2, 0).data(Qt.DisplayRole) == 'Z renamed.mp4')
    assert model.index(2, 0).data(Qt.UserRole) == aid
    added.unlink()
    assert wait(lambda: model.rowCount() == 2)
    assert selected.data(Qt.UserRole) == selected_id and selected.row() == 0
    child = root / 'child'
    child.mkdir()
    assert wait(lambda: model.index(0, 0).data(FOLDER_ROLE) == str(child))
    nested = child / 'nested.mp4'
    nested.write_bytes(b'nested')
    assert wait(lambda: bool(window.library_controller.browsing.folders[str(child)][1]))
    panel.browse_folder(str(child))
    nested.unlink()
    child.rmdir()
    assert wait(lambda: panel.current_folder == str(root))
    assert panel.file_count.text() == '2 部' and resets.count() == 0 and window.current == previous


def test_missing_import_root_clears_and_recovers_automatically(window, tmp_path):
    window.thumbnails.request = lambda vid: None
    root = tmp_path / 'disappearing'
    root.mkdir()
    clip = root / 'clip.mp4'
    clip.write_bytes(b'clip')
    def wait(predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    loaded = window.load_folder(str(root))
    assert wait(lambda: not loaded.pending)
    clip.unlink()
    root.rmdir()
    assert wait(lambda: window.library_view.files.model().rowCount() == 0)
    root.mkdir()
    clip.write_bytes(b'restored')
    assert wait(lambda: window.library_view.files.model().rowCount() == 1)
    assert window.library_view.current_folder == str(root)


def test_library_refresh_preserves_selection_and_visible_scroll_anchor(window, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QSignalSpy
    window.thumbnails.request = lambda vid: None
    ids = []
    for number in range(55):
        path = tmp_path / f'library-{number}.mp4'
        path.write_bytes(str(number).encode())
        vid = window.catalog.register(path)
        window.store.execute('UPDATE videos SET star=1,played=? WHERE id=?', (number + 10, vid))
        ids.append(vid)
    panel = window.library_view
    panel.show_mode('stars')
    view = panel.lists['stars']
    model = view.model()
    view.setCurrentIndex(model.index_for_id(ids[30]))
    view.scrollTo(model.index_for_id(ids[30]))
    QApplication.processEvents()
    view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 23)
    anchor = view.indexAt(QPoint(1, 1)).data(Qt.UserRole)
    offset = view.visualRect(model.index_for_id(anchor)).top()
    resets = QSignalSpy(model.modelReset)
    # A different video moves to the front; the selected identity and visible
    # anchor must not follow its old row number or old numeric scroll value.
    window.store.execute('UPDATE videos SET played=9999,score=8 WHERE id=?', (ids[0],))
    window.library_controller.refresh([ids[0]])
    QApplication.processEvents()
    assert view.currentIndex().data(Qt.UserRole) == ids[30]
    assert view.indexAt(QPoint(1, 1)).data(Qt.UserRole) == anchor
    assert view.visualRect(model.index_for_id(anchor)).top() == offset
    assert resets.count() == 0
    scroll = view.verticalScrollBar().value()
    panel.show_mode('videos')
    panel.show_mode('stars')
    QApplication.processEvents()
    assert view.currentIndex().data(Qt.UserRole) == ids[30]
    assert view.verticalScrollBar().value() == scroll


def test_cancel_button_cancels_all_library_work_and_ignores_late_result(window, tmp_path):
    from core import Snapshot
    tasks = []
    window.work = lambda function, ready: tasks.append((function, ready))
    window.library_controller.adopt_snapshot(Snapshot(str(tmp_path), {str(tmp_path): ([], [])}))
    previous = window.library_controller.browsing
    operation = window.load_folder('never published')
    assert window.library_view.cancel_button.isVisible()
    window.library_view.cancel_button.click()
    QApplication.processEvents()
    assert not operation.pending and not operation.outcome.succeeded
    assert not window.library_view.cancel_button.isVisible()
    tasks[0][1]((previous, [], {}), None)
    assert window.library_controller.browsing is previous


def test_favorite_button_toggles_and_shortcut_is_idempotent(window):
    window.player_view.favorite_button.click()
    assert window.store.video(window.current)['star'] == 1
    assert window.player_view.favorite_button.property('iconName') == 'starFilled'
    window.library_view.show_mode('stars')
    assert window.library_view.lists['stars'].model().rowCount() == 1
    window.player_view.favorite_button.click()
    assert window.store.video(window.current)['star'] == 0
    assert window.library_view.lists['stars'].model().rowCount() == 0
    window.favorite()
    window.favorite()
    assert window.store.video(window.current)['star'] == 1


def test_volume_and_speed_popovers(window):
    options = window.player_view.options
    window.player.audio_set_volume = Mock(wraps=window.player.audio_set_volume)
    window.player.audio_set_mute = Mock(wraps=window.player.audio_set_mute)
    assert not window.player_view.options.volume.isVisible()
    options.volume_popup.open_above()
    assert options.volume_popup.isVisible()
    window.player_view.options.volume.setValue(45)
    window.player.audio_set_volume.assert_called_with(45)
    window.player_view.options.volume_button.click()
    window.player.audio_set_mute.assert_called_with(True)
    window.player_view.options.volume_button.click()
    window.player.audio_set_mute.assert_called_with(False)
    options.speed_popup.open_above()
    assert options.speed_popup.isVisible() and not options.volume_popup.isVisible()
    options.set_rate(1.5)
    assert options.rate == 1.5 and options.rate_buttons[1.5].isChecked()


@pytest.mark.parametrize('score', [None, 0, 1, 5, 9, 10])
def test_heart_rating_saves_to_remote_metadata(window, score):
    window.rating_dialog()
    panel = window.player_view.options.rating_popup
    assert panel.isVisible() and panel.editor.hearts.width() > 0
    panel.commit(score)
    assert window.store.video(window.current)['score'] == score
    assert not panel.isVisible()
    assert not window.store.query('SELECT * FROM jobs')


def test_tag_input_native_dispatch_and_add_does_not_select(window):
    window.classification.apply_tags = Mock(return_value=Operation.success())
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    # QWindow events precede QWidget events. The hit must remain inside the
    # popover rather than dismissing it before the line edit gets focus.
    point = editor.entry.mapToGlobal(editor.entry.rect().center())
    event = QMouseEvent(QEvent.MouseButtonPress, QPoint(), point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    assert panel.contains_press(panel.windowHandle(), event)
    QTest.mouseClick(editor.entry, Qt.LeftButton)
    QTest.keyClicks(editor.entry, 'new-tag')
    assert panel.isVisible() and editor.entry.text() == 'new-tag'
    editor.add_button.click()
    assert 'new-tag' in editor.schema and 'new-tag' not in editor.chosen()
    assert not window.classification.apply_tags.called
    editor.chips['existing'].click()
    assert editor.chosen() == ['existing']
    panel.dismiss()
    window.classification.apply_tags.assert_called_once()
    assert window.classification.apply_tags.call_args.kwargs == {'prompt_score': False, 'renames': {}}
    assert window.classification.apply_tags.call_args.args[0] == window.current


def test_tag_arrow_keyboard_activation_does_not_trigger_playback(window):
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    editor.set_parent('existing', True)
    panel.activateWindow()
    editor.chips['existing'].arrow.setFocus()
    QApplication.processEvents()
    window.toggle = Mock()
    window.player_view.fullscreen.toggle = Mock()
    QTest.keyClick(editor.chips['existing'].arrow, Qt.Key_Space)
    assert editor.expanded == {'existing'}
    assert not window.toggle.called
    editor.chips['existing'].arrow.setFocus()
    QTest.keyClick(editor.chips['existing'].arrow, Qt.Key_Return)
    assert not editor.expanded and not window.toggle.called and not window.player_view.fullscreen.toggle.called
    editor.confirm_saved()
    window.classification.apply_tags = Mock(return_value=Operation.success())


def test_tag_management_multiselect_and_close_flush(window):
    window.classification.apply_tags = Mock(return_value=Operation.success())
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    editor.entry.setText('second')
    editor.add_button.click()
    editor.title.click()
    editor.chips['existing'].click()
    editor.chips['second'].click()
    assert editor.delete_selection == {'existing', 'second'}
    editor.delete_button.click()
    assert not editor.schema and not editor.chosen()
    panel.flush_pending()
    panel.dismiss()
    assert window.classification.apply_tags.call_count == 1
    assert window.classification.apply_tags.call_args.args[2] == []
    assert window.store.resolve(window.current).exists()


def test_tag_hover_leave_closes(window):
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    QApplication.sendEvent(panel, QEvent(QEvent.Leave))
    QTest.qWait(300)
    assert not panel.isVisible()


def test_seek_previews_without_stale_tick_snapback(window):
    real = window.player
    fake = Mock()
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 2000
    fake.get_state.return_value = vlc.State.Paused
    window.player = fake
    window.playback.last_save = time.monotonic()
    try:
        slider = window.player_view.seekbar
        QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(slider.width() // 2, slider.height() // 2))
        window.tick()
        assert 4500 < slider.value() < 5500
        assert fake.set_time.call_count == 0
        QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(slider.width() * 3 // 4, slider.height() // 2))
        assert fake.set_time.call_count == 1
        target = slider.value()
        window.tick()
        assert slider.value() == target
        fake.get_time.return_value = fake.set_time.call_args.args[0]
        window.tick()
        assert window.playback.pending_seek is None
    finally:
        window.player = real


@pytest.mark.parametrize(('position', 'offset', 'target'), [(5000, 5000, 10000),
    (10000, -5000, 5000), (2000, -5000, 0), (98000, 5000, 100000)])
def test_keyboard_seek_combines_notice_and_timeline_without_stale_snapback(window, position, offset, target):
    real = window.player
    fake = Mock()
    fake.get_length.return_value = 100000
    fake.get_time.return_value = position
    fake.get_state.return_value = vlc.State.Paused
    window.player = fake
    window.player_view.seek_notice.show = Mock()
    window.playback.last_save = time.monotonic()
    try:
        window.seek(offset)
        fake.set_time.assert_called_once_with(target)
        window.player_view.seek_notice.show.assert_called_once_with(position, target, 100000)
        assert window.player_view.seekbar.visual_fraction == target / 100000
        window.tick()
        assert window.player_view.seekbar.visual_fraction == target / 100000
        fake.get_time.return_value = target
        window.tick()
        assert window.playback.pending_seek is None
        assert not window.player_view.seekbar.animation.isActive()
    finally:
        window.player = real


def test_timeline_clock_keeps_moving_between_repeated_decoder_samples():
    from seek_slider import PlaybackClock
    clock = PlaybackClock()
    clock.sample(2000, 100000, True, 1, 10)
    assert clock.position(10.1) == pytest.approx(2100)
    clock.sample(2000, 100000, True, 1, 10.25)
    assert clock.position(10.4) == pytest.approx(2400)
    # A stalled decoder cannot leave the visible timeline running indefinitely.
    assert clock.position(20) == pytest.approx(2750)


def test_seek_notice_is_screen_rendered_centered_and_does_not_touch_decoder(window):
    real = window.player
    window.player = Mock()
    window.activateWindow()
    QApplication.processEvents()
    try:
        notice = window.player_view.seek_notice
        notice.show(5000, 10000, 60000)
        panel = notice.overlay
        assert panel.isVisible() and panel.owner is window and panel.isWindow()
        assert notice.text() == '00:05→00:10(01:00)\n16.7%'
        assert panel.windowFlags() & Qt.WindowTransparentForInput
        assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
        assert panel.time_label.font().pixelSize() == 20
        center = window.player_view.surface.mapToGlobal(window.player_view.surface.rect().center())
        assert abs(panel.geometry().center().x() - center.x()) <= 1
        assert panel.geometry().center().y() < center.y()
        assert window.isActiveWindow()
        assert window.player.mock_calls == []
        width = panel.width()
        window.resize(1200, 760)
        QApplication.processEvents()
        QApplication.processEvents()
        center = window.player_view.surface.mapToGlobal(window.player_view.surface.rect().center())
        assert panel.isVisible() and abs(panel.geometry().center().x() - center.x()) <= 1
        assert panel.width() == width and panel.time_label.font().pixelSize() == 20
        notice.clear()
        assert not panel.isVisible() and notice.text() == '' and not notice.timer.isActive()
    finally:
        window.player = real


def test_seek_notice_restarts_hide_deadline_for_repeated_seeks(window):
    window.activateWindow()
    QApplication.processEvents()
    notice = window.player_view.seek_notice
    notice.show(0, 5000, 60000)
    notice.timer.start(200)
    QTest.qWait(100)
    notice.show(5000, 10000, 60000)
    QTest.qWait(150)
    assert notice.overlay.isVisible() and notice.timer.remainingTime() > 1000
    assert notice.text() == '00:05→00:10(01:00)\n16.7%'
    notice.timer.start(30)
    QTest.qWait(80)
    assert not notice.overlay.isVisible() and notice.text() == ''


def test_clearing_media_removes_seek_surface_immediately(window):
    window.activateWindow()
    QApplication.processEvents()
    notice = window.player_view.seek_notice
    notice.show(5000, 10000, 60000)
    assert notice.overlay.isVisible()
    window.clear_player()
    assert not notice.overlay.isVisible() and notice.text() == ''
    assert not notice.timer.isActive()


@pytest.mark.parametrize('rate', [.5, 1, 1.5, 2])
def test_timeline_clock_speed_changes_are_continuous_and_pause_is_stable(rate):
    from seek_slider import PlaybackClock
    clock = PlaybackClock()
    clock.sample(2000, 100000, True, 1, 10)
    before = clock.position(10.2)
    clock.sample(2000, 100000, True, rate, 10.2)
    assert clock.position(10.2) == before
    assert clock.position(10.4) == pytest.approx(before + rate * 200)
    clock.sample(2400, 100000, False, rate, 10.4)
    assert clock.position(20) == 2400


def test_timeline_corrects_small_errors_without_backward_steps_and_snaps_on_seek():
    from seek_slider import PlaybackClock
    clock = PlaybackClock()
    clock.sample(2000, 100000, True, 1, 10)
    before = clock.position(10.25)
    clock.sample(2100, 100000, True, 1, 10.25)
    assert clock.position(10.25) == before
    samples = [clock.position(10.25 + i / 100) for i in range(51)]
    assert samples == sorted(samples)
    clock.hold(70000, 100000, 11)
    assert clock.position(12) == 70000
    clock.sample(70000, 100000, True, 1, 12)
    assert clock.position(12.1) == pytest.approx(70100)
    clock.sample(10000, 100000, True, 1, 12.2)
    assert clock.position(12.2) == 10000
    clock.sample(99990, 100000, True, 1, 13)
    assert clock.position(13.5) == 100000


def test_timeline_renders_fractional_progress_without_seeking_or_polling(window, monkeypatch):
    from types import SimpleNamespace
    import seek_slider
    now = [10.0]
    monkeypatch.setattr(seek_slider, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    real = window.player
    window.player = Mock()
    try:
        slider = window.player_view.seekbar
        slider.synchronize(50000, 36_000_000, True, 1)
        before_value, before_fraction = slider.value(), slider.visual_fraction
        before_image = slider.grab().toImage()
        now[0] += .1
        slider.refresh_frame()
        assert slider.value() == before_value  # Below the integer slider's resolution.
        assert slider.visual_fraction > before_fraction
        assert slider.grab().toImage() != before_image
        assert window.player.mock_calls == []
        assert not isinstance(window.player_view.options.volume, seek_slider.PlaybackTimeline)
        slider.hold(18000000, 36_000_000)
        assert slider.visual_fraction == .5 and not slider.animation.isActive()
        slider.synchronize(18000000, 36_000_000, False, 1)
        now[0] += 5
        slider.refresh_frame()
        assert slider.visual_fraction == .5
    finally:
        window.player = real


def test_fullscreen_restores_layout_and_video_handle(window):
    handle = int(window.player_view.surface.winId())
    sizes = window.splitter.sizes()
    window.player_view.fullscreen.toggle()
    QApplication.processEvents()
    full = window.player_view.fullscreen
    full.timer.stop()
    full.poll(window.canvas.mapToGlobal(QPoint(300, window.canvas.height() - 1)))
    assert full.overlay.isWindow() and full.overlay.owner is window
    assert window.player_view.playback_panel.parentWidget() is full.overlay
    assert int(window.player_view.surface.winId()) == handle
    window.player_view.fullscreen.exit()
    QApplication.processEvents()
    assert window.player_view.playback_panel.parentWidget().objectName() == 'playerCard'
    assert window.library_view.isVisible() and window.splitter.sizes() == sizes
    assert not window.statusBar().isVisible()
    apply_theme(window, 'dark')
    assert window.theme == 'dark'
    apply_theme(window, 'light')


def test_fullscreen_title_and_cursor_share_visibility_without_resizing_video(window, tmp_path):
    window.player_view.fullscreen.toggle()
    full = window.player_view.fullscreen
    full.cursor_position = lambda: window.canvas.mapToGlobal(window.canvas.rect().center())
    QApplication.processEvents()
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    original_geometry = window.player_view.surface.geometry()
    full.last_cursor, full.last_activity = center, 0
    full.poll(center)
    assert not full.overlay.isVisible() and not full.title.isVisible()
    assert full.cursor.hidden and window.player_view.surface.cursor().shape() == Qt.BlankCursor
    second = tmp_path / 'second.mp4'
    second.write_bytes(b'Isolated metadata fixture; not decoded')
    window.current = window.store.register(second)
    window.store.execute('UPDATE videos SET score=9 WHERE id=?', (window.current,))
    window.refresh_title()
    QApplication.processEvents()
    assert window.player_view.header.isHidden() and window.player_view.surface.geometry() == original_geometry
    assert full.title.filename == 'second.mp4' and not full.title.isVisible()
    full.poll(center + QPoint(1, 0))
    assert full.overlay.isVisible() and full.title.isVisible() and not full.cursor.hidden
    assert window.player_view.surface.cursor().shape() != Qt.BlankCursor
    assert abs(full.title.geometry().center().x() - center.x()) <= 1
    full.present_video('Very long video filename ' * 40 + '.mp4', (), None, False)
    assert full.title.header.toolTip().startswith('Very long video filename ') and full.title.width() <= 900
    assert window.player_view.surface.geometry() == original_geometry
    window.player_view.fullscreen.exit()
    QApplication.processEvents()
    assert window.player_view.header.isVisible() and not full.title.isVisible()


def test_fullscreen_interactions_restart_shared_idle_deadline(window, monkeypatch):
    from types import SimpleNamespace
    import video_fullscreen
    now = [100.0]
    monkeypatch.setattr(video_fullscreen, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    window.player_view.fullscreen.toggle()
    full = window.player_view.fullscreen
    full.cursor_position = lambda: window.canvas.mapToGlobal(window.canvas.rect().center())
    QApplication.processEvents()
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    full.last_cursor = center
    now[0] = 103
    full.poll(center)
    assert full.cursor.hidden
    full.poll(center + QPoint(1, 0))
    window.player_view.options.speed_popup.open_above()
    full.poll(center)
    assert full.title.isVisible() and full.overlay.isVisible() and not full.cursor.hidden
    window.player_view.options.dismiss()
    now[0] = 104
    full.poll(center)
    now[0] = 106
    full.poll(center)
    assert full.title.isVisible() and not full.cursor.hidden
    now[0] = 106.6
    full.poll(center)
    assert not full.title.isVisible() and not full.overlay.isVisible() and full.cursor.hidden
    window.activateWindow()
    QApplication.processEvents()
    full.poll(center + QPoint(1, 0))
    window.player_view.seekbar.setSliderDown(True)
    now[0] = 120
    full.poll(center)
    assert full.title.isVisible() and not full.cursor.hidden
    window.player_view.seekbar.setSliderDown(False)


def test_fullscreen_exit_restores_preexisting_video_cursor(window):
    window.player_view.surface.setCursor(Qt.CrossCursor)
    window.player_view.fullscreen.toggle()
    QApplication.processEvents()
    full = window.player_view.fullscreen
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    full.last_cursor, full.last_activity = center, 0
    full.poll(center)
    assert window.player_view.surface.cursor().shape() == Qt.BlankCursor
    window.player_view.fullscreen.exit()
    assert not full.cursor.hidden and window.player_view.surface.cursor().shape() == Qt.CrossCursor


def test_cancelled_storage_keeps_tag_draft(window):
    window.classification.apply_tags = Mock(return_value=Operation.cancelled())
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    editor.chips['existing'].click()
    panel.dismiss()
    window.player_view.toggle_tags()
    assert panel.editor is editor and editor.chosen() == ['existing']
    assert window.store.video(window.current)['tags'] == '[]'


def _capture_file_task(window):
    tasks = []
    window.work = lambda function, callback: tasks.append((function, callback))
    window.play_path = Mock()
    window.fail = Mock()
    return tasks


def _finish_file_task(tasks):
    function, completed = tasks.pop(0)
    try:
        value = function()
    except Exception as error:
        completed(None, error)
    else:
        completed(value, None)


def test_background_tag_preflight_failure_preserves_reopened_draft_and_has_no_recovery_task(window, tmp_path):
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    window.store.execute('UPDATE videos SET original_name=? WHERE id=?', ('a' * 260 + '.mp4', window.current))
    tasks = _capture_file_task(window)
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    editor.chips['existing'].click()
    panel.dismiss()
    _finish_file_task(tasks)
    window.player_view.toggle_tags()
    assert panel.editor is editor and editor.chosen() == ['existing']
    assert window.store.video(window.current)['tags'] == '[]'
    assert not window.catalog.pending_tasks()
    assert '恢复' not in str(window.fail.call_args)


def test_tag_save_continues_latest_selected_video(window, tmp_path):
    from core import Snapshot
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    original = window.current
    entries = [(original, 'sample.mp4')]
    for name in ('B.mp4', 'C.mp4'):
        path = tmp_path / name
        path.write_bytes(name.encode())
        entries.append((window.store.register(path), name))
    context = Snapshot(str(tmp_path), {str(tmp_path): ([], entries)})
    window.context, window.location = context, (str(tmp_path), 0)
    tasks = _capture_file_task(window)
    window.player_view.toggle_tags()
    window.player_view.options.tags_popup.editor.chips['existing'].click()
    window.start(context, (str(tmp_path), 1))
    window.start(context, (str(tmp_path), 2))
    assert window.current == original and len(tasks) == 1
    _finish_file_task(tasks)
    assert window.current == entries[2][0] and not tasks
    assert json.loads(window.store.video(original)['tags']) == ['existing']
    window.fail.assert_not_called()


def test_failed_tag_save_does_not_navigate_and_retry_can_continue(window, tmp_path):
    from core import Snapshot
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    original = window.current
    second = tmp_path / 'second.mp4'
    second.write_bytes(b'second')
    second_id = window.store.register(second)
    context = Snapshot(str(tmp_path), {str(tmp_path): ([], [(original, 'sample.mp4'), (second_id, 'second.mp4')])})
    window.context, window.location = context, (str(tmp_path), 0)
    window.store.execute('UPDATE videos SET original_name=? WHERE id=?', ('a' * 260 + '.mp4', original))
    tasks = _capture_file_task(window)
    window.player_view.toggle_tags()
    window.player_view.options.tags_popup.editor.chips['existing'].click()
    window.advance(1)
    _finish_file_task(tasks)
    assert window.current == original and not window.busy
    window.store.execute('UPDATE videos SET original_name=? WHERE id=?', ('sample.mp4', original))
    window.advance(1)
    _finish_file_task(tasks)
    assert window.current == second_id
    assert json.loads(window.store.video(original)['tags']) == ['existing']


def test_recovering_tag_task_confirms_existing_draft_without_submitting_it_again(window, tmp_path):
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    tasks = _capture_file_task(window)
    def fail_checkpoint(stage):
        raise OSError('interrupted batch')
    window.tag_migration.fault = fail_checkpoint
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    panel.editor.chips['existing'].click()
    panel.dismiss()
    _finish_file_task(tasks)
    assert window.catalog.pending_tasks('hierarchy_jobs')
    assert '恢复' in str(window.fail.call_args)
    window.tag_migration.fault = None
    window.recovery.retry()
    _finish_file_task(tasks)
    assert not window.catalog.pending_tasks()
    window.player_view.toggle_tags()
    assert panel.editor.chosen() == ['existing']
    panel.dismiss()
    assert not tasks and not window.busy


def test_recovering_another_archived_video_updates_its_visible_tree_name(window, tmp_path):
    from core import Snapshot
    root = str(tmp_path)
    second = tmp_path / 'legacy B.mp4'
    second.write_bytes(b'independent archive recovery fixture')
    vid = window.catalog.register(second)
    window.store.execute('UPDATE videos SET original_name=? WHERE id=?', ('B.mp4',vid))
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    window.library_controller.adopt_snapshot(Snapshot(root, {root: ([], [(vid, second.name)])}))
    tasks = _capture_file_task(window)
    def interrupted(stage):
        raise OSError('interrupted archive')
    window.archiver.fault = interrupted
    window.classification.archive(vid, 8, ['existing'])
    _finish_file_task(tasks)
    assert window.catalog.pending_tasks('jobs')
    window.archiver.fault = None
    window.recovery.retry()
    _finish_file_task(tasks)
    model = window.library_view.files.model()
    index = model.index(0, 0)
    assert not window.catalog.pending_tasks('jobs')
    assert index.data(Qt.DisplayRole) == window.catalog.video(vid)['name'] == 'B.mp4' != second.name


def test_close_waits_for_tag_commit_then_closes_its_own_window(window, tmp_path):
    window.storage.save(tmp_path / 'archive')
    window.archiver.root = tmp_path / 'archive'
    tasks = _capture_file_task(window)
    window.player_view.toggle_tags()
    window.player_view.options.tags_popup.editor.chips['existing'].click()
    assert window.close() is False
    assert window.isVisible() and len(tasks) == 1
    _finish_file_task(tasks)
    QApplication.processEvents()
    assert not window.isVisible()
    assert json.loads(window.store.video(window.current)['tags']) == ['existing']


def test_repeated_keyboard_seek_keeps_all_user_steps_before_backend_ack(window):
    real = window.player
    fake = Mock()
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 10000
    window.player = fake
    try:
        for _ in range(3):
            window.seek(5000)
        assert [call.args[0] for call in fake.set_time.call_args_list] == [15000, 20000, 25000]
        assert window.player_view.seekbar.visual_fraction == .25
    finally:
        window.player = real


def test_end_progress_remains_zero_on_later_saves_and_close(window):
    real = window.player
    fake = Mock()
    fake.get_state.return_value = vlc.State.Ended
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 99000
    window.player = fake
    window.context = Mock()
    window.context.step.return_value = None
    try:
        window.tick()
        assert window.store.video(window.current)['position'] == 0
        window.save()
        window.close()
        assert window.store.video(window.current)['position'] == 0
    finally:
        window.player = real


def test_escape_closes_editable_surface_before_leaving_fullscreen(window):
    window.player_view.fullscreen.toggle()
    QApplication.processEvents()
    window.activateWindow()
    window.player_view.fullscreen.poll(window.canvas.mapToGlobal(QPoint(300, window.canvas.height() - 1)))
    QApplication.processEvents()
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    assert panel.isVisible()
    QTest.mouseClick(panel.editor.entry, Qt.LeftButton)
    QTest.keyClick(panel.editor.entry, Qt.Key_Escape)
    assert not panel.isVisible() and window.player_view.fullscreen.active
    QTest.keyClick(window, Qt.Key_Escape)
    assert not window.player_view.fullscreen.active


def test_tag_context_menu_belongs_to_editable_surface(window):
    from PySide6.QtWidgets import QMenu
    from PySide6.QtCore import QTimer
    window.classification.apply_tags = Mock(return_value=Operation.success())
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    checks = []
    def inspect():
        menu = QApplication.activePopupWidget()
        checks.append(isinstance(menu, QMenu) and panel.isVisible())
        if menu:
            menu.close()
    QTimer.singleShot(0, inspect)
    panel.editor.menu('existing', panel.editor.mapToGlobal(QPoint(30, 30)))
    assert checks == [True] and panel.isVisible()


@pytest.mark.parametrize('cancel', [False, True])
def test_native_tag_menu_input_does_not_dismiss_or_commit(window, cancel):
    from PySide6.QtCore import QTimer
    window.classification.apply_tags = Mock(return_value=Operation.success())
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    editor = panel.editor
    observations = []
    def choose():
        menu = QApplication.activePopupWidget()
        observations.append(menu is not None and panel.isVisible())
        if menu is None:
            return
        if cancel:
            QTest.keyClick(menu.windowHandle(), Qt.Key_Escape)
        else:
            action = next(action for action in menu.actions() if action.text() == '设为父标签')
            QTest.mouseClick(menu.windowHandle(), Qt.LeftButton, pos=menu.actionGeometry(action).center())
        menu.close()
    QTimer.singleShot(0, choose)
    editor.menu('existing', editor.mapToGlobal(QPoint(30, 30)))
    assert observations == [True]
    assert panel.isVisible() and not window.classification.apply_tags.called
    assert editor.schema['existing']['is_parent'] == (not cancel)


def test_global_tag_delete_preserves_video_entities(window, tmp_path):
    from core import identity
    root = tmp_path / 'archive'
    window.storage.save(root)
    window.archiver.root = root
    second = tmp_path / 'second.mp4'
    second.write_bytes(b'second video content')
    second_id = window.store.register(second)
    ids = [window.current, second_id]
    entities = {}
    for vid in ids:
        window.archiver.submit(vid, 8, ['existing', 'keep'])
        window.store.execute('UPDATE videos SET star=1, position=12345 WHERE id=?', (vid,))
        entities[vid] = identity(window.store.resolve(vid))
    window.play_path = Mock()
    window.fail = Mock()
    window.player_view.toggle_tags()
    panel = window.player_view.options.tags_popup
    panel.editor.title.click()
    panel.editor.chips['existing'].click()
    panel.editor.delete_button.click()
    panel.dismiss()
    deadline = time.monotonic() + 8
    while window.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert not window.busy
    window.fail.assert_not_called()
    for vid in ids:
        row = window.store.video(vid)
        assert json.loads(row['tags']) == ['keep']
        assert row['star'] == 1 and row['position'] == 12345 and row['score'] == 8
        assert identity(window.store.resolve(vid)) == entities[vid]
    assert not window.store.query('SELECT * FROM deletion_jobs')
    assert 'existing' not in window.store.tag_layout()


def test_sidebar_delete_freezes_selected_id_without_playing(window, tmp_path):
    second = tmp_path / 'second.mp4'
    second.write_bytes(b'second')
    selected_id = window.store.register(second)
    window.store.execute('UPDATE videos SET star=1 WHERE id=?', (selected_id,))
    window.library_view.show_mode('stars')
    window.library_view.lists['stars'].setCurrentIndex(window.library_view.lists['stars'].model().index(0, 0))
    tasks = []
    window.work = lambda function, callback: tasks.append((function, callback))
    window.play_path = Mock()
    original = window.current
    window.delete_video()
    from PySide6.QtWidgets import QCheckBox, QDialogButtonBox
    dialog = window.media_menu.active_dialog
    assert dialog is not None and not window.busy and not tasks
    dialog.findChild(QCheckBox, 'deleteLocalFiles').setChecked(True)
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    assert window.busy and window.current == original and len(tasks) == 1
    function, ready = tasks.pop()
    # Changing selection during the scan cannot retarget the requested delete.
    window.library_view.lists['stars'].clearSelection()
    ready(function(), None)
    assert window.busy and len(tasks) == 1
    assert window.thumbnail_service.is_deleting(selected_id) and not window.thumbnail_service.is_deleting(original)
    window.play_path.assert_not_called()
    # Do not execute the queued deletion; this check only covers UI targeting.


def test_decode_failure_remains_visible_without_status_bar(window):
    original = window.player
    fake = Mock()
    fake.get_state.return_value = vlc.State.Error
    fake.get_time.return_value = 0
    fake.get_length.return_value = 0
    window.player = fake
    window.fail = Mock()
    window.playback.last_save = time.monotonic()
    try:
        window.tick()
        window.tick()
        window.fail.assert_called_once()
        assert not window.statusBar().isVisible()
    finally:
        window.player = original


def test_play_icon_survives_redraw_without_backend_transition(window):
    from ui import icon
    real = window.player
    fake = Mock()
    fake.get_state.return_value = vlc.State.Playing
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 2000
    window.player = fake
    window.playback.last_save = time.monotonic()
    expected = icon('pause', '#ffffff').pixmap(24, 24).toImage()
    try:
        window.tick()
        assert window.player_view.play_button.icon().pixmap(24, 24).toImage() == expected
        apply_theme(window, 'dark')
        # The backend remains Playing, so an ordinary tick used to skip repair.
        window.tick()
        assert window.player_view.play_button.icon().pixmap(24, 24).toImage() == expected
        window.player_view.fullscreen.toggle()
        QApplication.processEvents()
        window.tick()
        assert window.player_view.play_button.icon().pixmap(24, 24).toImage() == expected
        window.player_view.fullscreen.exit()
        QApplication.processEvents()
        window.tick()
        assert window.player_view.play_button.icon().pixmap(24, 24).toImage() == expected
    finally:
        window.player = real


@pytest.mark.parametrize('state,symbol,action', [
    (vlc.State.Opening, 'pause', '暂停'),
    (vlc.State.Buffering, 'pause', '暂停'),
    (vlc.State.Playing, 'pause', '暂停'),
    (vlc.State.Paused, 'play', '播放'),
    (vlc.State.Ended, 'play', '重新播放'),
    (vlc.State.Stopped, 'play', '播放'),
])
def test_transport_action_and_actual_icon_agree(window, state, symbol, action):
    from ui import icon
    real = window.player
    fake = Mock()
    fake.get_state.return_value = state
    window.player = fake
    try:
        # Appearance and fullscreen used to have independent rendering paths.
        for theme in ('light', 'dark', 'light'):
            apply_theme(window, theme)
            assert window.player_view.play_button.property('iconName') == symbol
            assert window.player_view.play_button.accessibleName() == action
            assert window.player_view.play_button.toolTip() == action + ' · 空格'
            assert window.player_view.play_button.icon().pixmap(24, 24).toImage() == icon(symbol, '#ffffff').pixmap(24, 24).toImage()
    finally:
        window.player = real


def test_pause_command_waits_for_state_confirmation(window):
    real = window.player
    fake = Mock()
    fake.get_state.return_value = vlc.State.Playing
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 2000
    window.player = fake
    window.playback.last_save = time.monotonic()
    try:
        window.tick()
        window.player_view.play_button.click()
        fake.pause.assert_called_once()
        assert window.player_view.play_button.property('iconName') == 'pause'
        fake.get_state.return_value = vlc.State.Paused
        window.tick()
        assert window.player_view.play_button.property('iconName') == 'play'
        window.player_view.play_button.click()
        assert fake.pause.call_count == 2
        fake.get_state.return_value = vlc.State.Playing
        window.tick()
        assert window.player_view.play_button.property('iconName') == 'pause'
    finally:
        window.player = real


def test_recent_tab_offers_confirmed_history_clearing(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    view = window.library_view
    view.show_mode('videos')
    assert view.clear_history_button.isVisible()
    assert not view.remove_favorite.isVisible()
    view.show_mode('stars')
    assert view.remove_favorite.isVisible()
    assert not view.clear_history_button.isVisible()
    view.show_mode('videos')
    assert window.library_controller.list_rows('videos'), '需要先有播放记录'

    asked = []

    def refuse(box):
        asked.append(box.text())
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, 'exec', refuse)
    window.clear_history()
    assert asked and '清空' in asked[0], '必须二次确认'
    assert window.library_controller.list_rows('videos'), '取消后不能清空'

    monkeypatch.setattr(QMessageBox, 'exec', lambda box: QMessageBox.Yes)
    window.clear_history()
    assert window.library_controller.list_rows('videos') == []


@pytest.fixture
def context_target(window, tmp_path):
    from core import Snapshot
    path = tmp_path / '右键 目标.mp4'
    path.write_bytes(b'context target')
    video_id = window.store.register(path)
    window.store.execute('UPDATE videos SET score=4,star=1,played=2,position=5000 WHERE id=?', (video_id,))
    window.thumbnails.request = lambda vid: None
    root = str(tmp_path)
    snapshot = Snapshot(root, {root: ([], [(window.current, 'sample.mp4'), (video_id, path.name)])})
    window.library_controller.adopt_snapshot(snapshot)
    return video_id, path


def context_action(window, video_id, caption):
    from application.library import LibrarySelection
    menu = window.media_menu.build_menu(LibrarySelection(video_id))
    action = next(action for action in menu.actions() if action.text() == caption)
    if action.menu() is not None:
        menu.popup(window.mapToGlobal(QPoint(40, 80)))
        menu.setActiveAction(action)
        action.menu().popup(menu.mapToGlobal(QPoint(menu.width(), menu.actionGeometry(action).top())))
    else:
        action.trigger()
    return menu


def context_wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
    return False


@pytest.mark.parametrize('mode', ['files', 'catalog', 'videos', 'stars'])
def test_all_pages_context_menu_freezes_clicked_identity_and_has_exactly_six_actions(window, context_target, mode):
    from PySide6.QtTest import QSignalSpy
    video_id, path = context_target
    panel = window.library_view
    panel.mediaContextRequested.disconnect(window.media_menu.open)
    requested = QSignalSpy(panel.mediaContextRequested)
    panel.show_mode(mode)
    view = panel.files if mode == 'files' else panel.lists[mode]
    assert context_wait(lambda: view.model().index_for_id(video_id).isValid()) if mode != 'files' else True
    model = view.model()
    index = next(model.index(n, 0) for n in range(model.rowCount()) if model.index(n, 0).data(Qt.UserRole) == video_id)
    view.scrollTo(index)
    QApplication.processEvents()
    current = window.current
    view.customContextMenuRequested.emit(view.visualRect(index).center())
    assert requested.count() == 1
    selection = requested.at(0)[0]
    assert selection.video_id == video_id and window.current == current
    menu = window.media_menu.build_menu(selection)
    actions = [action for action in menu.actions() if not action.isSeparator()]
    assert [action.text() for action in actions] == ['取消收藏', '编辑标签', '评分', '重命名', '删除', '在资源管理器中打开']
    view.clearSelection()
    actions[0].trigger()
    assert window.catalog.video(video_id)['star'] == 0 and window.current == current
    assert window.catalog.video(current)['star'] == 0


def test_context_rating_and_explorer_use_clicked_target_without_playing_it(window, context_target):
    from rating_editor import RatingEditor
    video_id, path = context_target
    current = window.current
    window.play_path = Mock()
    menu = context_action(window, video_id, '评分')
    editor = menu.findChild(RatingEditor)
    assert editor.hearts.score == 4
    assert editor.hearts.size() == window.player_view.options.rating_popup.editor.hearts.size()
    assert editor.layout().contentsMargins() == window.player_view.options.rating_popup.editor.layout().contentsMargins()
    editor.zero.click()
    assert context_wait(lambda: window.catalog.video(video_id)['score'] == 0)
    assert window.catalog.video(current)['score'] is None and not menu.isVisible()
    window.media_menu.reveal = Mock()
    context_action(window, video_id, '在资源管理器中打开')
    window.media_menu.reveal.assert_called_once_with(path)
    assert window.current == current and not window.play_path.called


def test_context_tag_failure_preserves_draft_and_reopens_in_same_embedded_style(window, context_target):
    from tag_editor import TagEditor
    from application.operations import Outcome, Status
    video_id, path = context_target
    current = window.current
    pending = Operation()
    window.classification.apply_tags = Mock(return_value=pending)
    menu = context_action(window, video_id, '编辑标签')
    editor = menu.findChild(TagEditor)
    editor.chips['existing'].click()
    assert not editor.buttons.isVisible() and not editor.footer_hint.isVisible()
    assert editor.parentWidget().size() == window.player_view.options.tags_popup.size()
    assert not window.classification.apply_tags.called
    menu.close()
    assert window.classification.apply_tags.call_args.args[0] == video_id
    pending.finish(Outcome(Status.FAILED, error=PermissionError('save failed')))
    assert window.tag_drafts.open_for(video_id).dirty and window.current == current
    window.classification.apply_tags = Mock(return_value=Operation.success())
    retry = context_action(window, video_id, '编辑标签')
    assert retry.findChild(TagEditor).chosen() == ['existing']
    retry.close()
    assert window.classification.apply_tags.call_args.args[:2] == (video_id, ['existing'])
    assert not window.tag_drafts.open_for(video_id).dirty and path.exists()


def test_context_rename_uses_original_identity_and_keeps_invalid_input_open(window, context_target):
    from PySide6.QtWidgets import QDialogButtonBox, QLineEdit
    video_id, path = context_target
    current = window.current
    window.play_path = Mock()
    context_action(window, video_id, '重命名')
    dialog = window.media_menu.active_dialog
    field = dialog.findChild(QLineEdit, 'mediaRenameField')
    controls = dialog.findChild(QDialogButtonBox)
    field.setText('invalid/name.mp4')
    controls.button(QDialogButtonBox.Save).click()
    assert dialog.isVisible() and path.exists()
    field.setText('改名后的文件.mp4')
    controls.button(QDialogButtonBox.Save).click()
    assert context_wait(lambda: window.media_menu.active_dialog is None)
    assert not path.exists() and window.catalog.resolve(video_id) == path.with_name('改名后的文件.mp4')
    assert window.catalog.video(video_id)['id'] == video_id and window.current == current and not window.play_path.called


def test_context_delete_confirmation_defaults_to_records_and_cancel_changes_nothing(window, context_target):
    from PySide6.QtWidgets import QCheckBox, QDialogButtonBox
    video_id, path = context_target
    current = window.current
    context_action(window, video_id, '删除')
    dialog = window.media_menu.active_dialog
    assert not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked()
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).click()
    assert path.exists() and window.catalog.video(video_id)['score'] == 4
    window.deleter.recycle = Mock(side_effect=AssertionError('Must keep local files'))
    context_action(window, video_id, '删除')
    dialog = window.media_menu.active_dialog
    assert not dialog.findChild(QCheckBox, 'deleteLocalFiles').isChecked()
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    assert context_wait(lambda: window.media_menu.active_dialog is None and not window.library_controller.refresh_pending)
    assert window.catalog.video(video_id) is None and path.read_bytes() == b'context target'
    assert not window.deleter.recycle.called and window.current == current
    # A retained disk file can still appear as a fresh, unmarked file-page row.
    rows = window.store.query('SELECT * FROM videos WHERE name=?', (path.name,))
    assert rows and all(row['score'] is None and row['star'] == 0 and row['tags'] == '[]' and not row['in_library'] for row in rows)


def test_context_delete_local_option_recycles_all_registered_links_only(window, context_target, tmp_path):
    import os
    from PySide6.QtWidgets import QCheckBox, QDialogButtonBox
    video_id, path = context_target
    linked = tmp_path / '另一个入口.mp4'
    os.link(path, linked)
    assert window.store.register(linked) == video_id
    recycled = tmp_path / 'recycled'
    recycled.mkdir()
    window.deleter.recycle = lambda target: target.rename(recycled / target.name)
    current = window.current
    context_action(window, video_id, '删除')
    dialog = window.media_menu.active_dialog
    dialog.findChild(QCheckBox, 'deleteLocalFiles').setChecked(True)
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    assert context_wait(lambda: window.media_menu.active_dialog is None)
    assert not path.exists() and not linked.exists() and window.catalog.video(video_id) is None
    assert len(list(recycled.iterdir())) == 2 and window.current == current



def test_context_submenu_hover_is_read_only_and_switching_retains_tag_edits(window, context_target):
    from tag_editor import TagEditor
    video_id, path = context_target
    window.classification.apply_tags = Mock(return_value=Operation.success())
    menu = context_action(window, video_id, '编辑标签')
    editor = menu.findChild(TagEditor)
    tag_action = menu.actions()[1]
    rating_action = menu.actions()[2]
    assert tag_action.menu().isVisible() and not rating_action.menu().isVisible()
    assert window.media_menu.active_dialog is None and not window.classification.apply_tags.called
    editor.chips['existing'].click()
    tag_action.menu().hide()
    rating_action.menu().popup(menu.mapToGlobal(QPoint(menu.width(), menu.actionGeometry(rating_action).top())))
    assert not window.classification.apply_tags.called
    rating_action.menu().hide()
    tag_action.menu().popup(menu.mapToGlobal(QPoint(menu.width(), menu.actionGeometry(tag_action).top())))
    assert editor.chosen() == ['existing']
    menu.close()
    assert window.classification.apply_tags.call_count == 1


def test_context_action_waits_for_current_draft_and_does_not_retarget_selection(window, context_target):
    from application.operations import Outcome, Status
    video_id, path = context_target
    pending = Operation()
    window.player_view.options.flush_pending = lambda: pending
    context_action(window, video_id, '取消收藏')
    assert window.catalog.video(video_id)['star'] == 1
    window.library_view.files.clearSelection()
    pending.finish(Outcome(Status.SUCCEEDED))
    assert window.catalog.video(video_id)['star'] == 0 and window.catalog.video(window.current)['star'] == 0


def test_file_folder_and_empty_space_do_not_open_media_menu(window, tmp_path):
    from core import Snapshot
    from PySide6.QtTest import QSignalSpy
    root, child = str(tmp_path), str(tmp_path / 'child')
    window.library_controller.adopt_snapshot(Snapshot(root, {root: ([child], []), child: ([], [])}))
    view = window.library_view
    view.mediaContextRequested.disconnect(window.media_menu.open)
    requested = QSignalSpy(view.mediaContextRequested)
    QApplication.processEvents()
    view.files.customContextMenuRequested.emit(view.files.visualRect(view.files.model().index(0, 0)).center())
    view.files.customContextMenuRequested.emit(QPoint(12, view.files.viewport().height() - 1))
    assert requested.count() == 0


@pytest.mark.parametrize('succeeded', [False, True])
def test_context_rating_waits_for_the_same_menu_tag_save_and_stops_on_failure(window, context_target, succeeded):
    from tag_editor import TagEditor
    from rating_editor import RatingEditor
    video_id, path = context_target
    window.fail = Mock()
    queued = []
    window.file_tasks.dispatch = lambda work, completed: queued.append((work, completed))
    window.classification.rating = Mock()
    menu = context_action(window, video_id, '编辑标签')
    menu.findChild(TagEditor).chips['existing'].click()
    menu.findChild(RatingEditor).zero.click()
    assert queued and not window.classification.rating.called
    work, completed = queued[0]
    completed(work() if succeeded else None, None if succeeded else PermissionError('blocked'))
    assert context_wait(lambda: not window.tag_drafts.saving)
    if succeeded:
        window.classification.rating.assert_called_once_with(video_id, 0)
        assert json.loads(window.catalog.video(video_id)['tags']) == ['existing']
    else:
        assert not window.classification.rating.called and window.tag_drafts.open_for(video_id).dirty


@pytest.mark.parametrize('accepted', [False, True])
def test_context_tag_rename_modal_finishes_before_the_closed_menu_saves(window, context_target, accepted, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from tag_editor import TagEditor
    video_id, path = context_target
    window.fail = Mock()
    menu = context_action(window, video_id, '编辑标签')
    editor = menu.findChild(TagEditor)
    editor.chips['existing'].click()
    def respond(*args):
        menu.close()
        assert window.tag_drafts.open_for(video_id).values.tags == []
        return 'changed', accepted
    monkeypatch.setattr(QInputDialog, 'getText', respond)
    editor.prompt_rename('existing')
    assert context_wait(lambda: not window.tag_drafts.saving)
    expected = 'changed' if accepted else 'existing'
    assert json.loads(window.catalog.video(video_id)['tags']) == [expected]
    assert expected in window.catalog.tag_values(video_id).schema
    assert not window.fail.called


def test_archive_settings_switch_disables_details_preserves_draft_and_cancel(window):
    from archive_settings_dialog import ArchiveSettingsDialog
    from PySide6.QtWidgets import QDialogButtonBox
    submit=Mock(return_value=Operation.success())
    dialog=ArchiveSettingsDialog(window,root=window.storage.root,folders=window.storage.folders,error='',apply=submit)
    dialog.show();QApplication.processEvents()
    path=dialog.path.text()
    dialog.favorite.setChecked(True)
    QTest.keyClick(dialog.enable_archive,Qt.Key_Space)
    assert not dialog.enable_archive.isChecked() and not dialog.path.isEnabled() and not dialog.tags.isEnabled()
    assert dialog.path.text()==path and dialog.favorite.isChecked()
    assert dialog.buttons.button(QDialogButtonBox.Save).text()=='保存'
    dialog.enable_archive.click()
    assert dialog.path.isEnabled() and dialog.favorite.isChecked()
    dialog.reject()
    assert not submit.called and window.storage.enabled


def test_disabled_archiving_keeps_tags_rating_favorite_and_all_links_in_place(window,tmp_path):
    from application.archive_folders import ArchiveFolders
    source=tmp_path/'tag-only.mp4';source.write_bytes(b'tag only file')
    video_id=window.store.register(source)
    archived=window.current
    window.archiver.submit(archived,8,['existing'])
    before=window.store.query('SELECT * FROM paths ORDER BY path')
    window.fail=Mock()
    disabling=window.archive_configuration.apply('invalid-inactive-path',ArchiveFolders(True,True,True),enabled=False)
    assert context_wait(lambda:not disabling.pending) and disabling.outcome.succeeded
    assert not window.storage.enabled
    window.classification.ensure_storage=Mock(side_effect=AssertionError('Must not ask for archive storage'))
    window.archiver.submit=Mock(side_effect=AssertionError('Must not move files'))
    for vid in (video_id,archived):
        tags=window.classification.apply_tags(vid,['existing'],list(window.store.tag_layout().values()),prompt_score=False)
        assert context_wait(lambda:not tags.pending) and tags.outcome.succeeded
        assert window.classification.rating(vid,0).outcome.succeeded
        assert window.classification.favorite(vid,True).outcome.succeeded
        row=window.catalog.video(vid)
        assert row['score']==0 and row['star']==1 and row['tags']=='["existing"]' and row['in_library']
    assert not window.store.video(video_id)['archived'] and window.store.video(archived)['archived']
    assert window.store.query('SELECT * FROM paths ORDER BY path')==before
    assert source.read_bytes()==b'tag only file' and not window.archiver.submit.called and not window.fail.called


def test_disabled_archive_save_keeps_current_media_loaded(window):
    from application.archive_folders import ArchiveFolders
    window.play_path=Mock()
    window.clear_player=Mock()
    operation=window.archive_configuration.apply('',ArchiveFolders(),enabled=False)
    assert context_wait(lambda:not operation.pending) and operation.outcome.succeeded
    assert not window.play_path.called and not window.clear_player.called


def test_disabled_explicit_archive_command_saves_metadata_without_moving(window):
    video_id=window.current
    window.storage.save(window.storage.root,enabled=False)
    before=window.store.query('SELECT * FROM paths WHERE id=?',(video_id,))
    window.archiver.submit=Mock(side_effect=AssertionError('No file archive'))
    outcome=window.classification.archive(video_id,0,['existing'],favorite=True).outcome
    assert outcome.succeeded
    video=window.catalog.video(video_id)
    assert video['score']==0 and video['star']==1 and video['tags']=='["existing"]'
    assert video['in_library'] and not video['archived']
    assert window.store.query('SELECT * FROM paths WHERE id=?',(video_id,))==before
    assert not window.archiver.submit.called
