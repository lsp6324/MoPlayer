"""Interaction checks against real Qt controls and the remote data model.

Run with QT_QPA_PLATFORM=offscreen; native VLC composition has a separate
private-desktop check in verify_ui_refresh.py.
"""
import json
import time
from unittest.mock import Mock
import pytest
from PySide6.QtCore import Qt, QPoint, QEvent, QCoreApplication, QThreadPool
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import Window, vlc
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
    player.playback_options.tags_popup.baseline = None
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
    assert window.splitter.widget(0) is window.sidebar
    from PySide6.QtCore import QModelIndex
    assert window.tree.itemDelegate().sizeHint(None, QModelIndex()).height() == 32
    height = window.surface.height()
    window.message('saved')
    QApplication.processEvents()
    assert not window.statusBar().isVisible()
    assert window.surface.height() == height
    assert window.control_row.center.isVisible()


def test_favorite_button_toggles_and_shortcut_is_idempotent(window):
    window.favorite_button.click()
    assert window.store.video(window.current)['star'] == 1
    assert window.favorite_button.property('iconName') == 'starFilled'
    window.show_sidebar('stars')
    assert window.sidebar_list.count() == 1
    window.favorite_button.click()
    assert window.store.video(window.current)['star'] == 0
    assert window.sidebar_list.count() == 0
    window.favorite()
    window.favorite()
    assert window.store.video(window.current)['star'] == 1


def test_volume_and_speed_popovers(window):
    options = window.playback_options
    window.player.audio_set_volume = Mock(wraps=window.player.audio_set_volume)
    window.player.audio_set_mute = Mock(wraps=window.player.audio_set_mute)
    assert not window.volume.isVisible()
    options.volume_popup.open_above()
    assert options.volume_popup.isVisible()
    window.volume.setValue(45)
    window.player.audio_set_volume.assert_called_with(45)
    window.volume_button.click()
    window.player.audio_set_mute.assert_called_with(True)
    window.volume_button.click()
    window.player.audio_set_mute.assert_called_with(False)
    options.speed_popup.open_above()
    assert options.speed_popup.isVisible() and not options.volume_popup.isVisible()
    options.set_rate(1.5)
    assert options.rate == 1.5 and options.rate_buttons[1.5].isChecked()


@pytest.mark.parametrize('score', [None, 0, 1, 5, 9, 10])
def test_heart_rating_saves_to_remote_metadata(window, score):
    window.rating_dialog()
    panel = window.playback_options.rating_popup
    assert panel.isVisible() and panel.hearts.width() > 0
    panel.commit(score)
    assert window.store.video(window.current)['score'] == score
    assert not panel.isVisible()
    assert not window.store.query('SELECT * FROM jobs')


def test_tag_input_native_dispatch_and_add_does_not_select(window):
    window.apply_tags = Mock()
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    assert not window.apply_tags.called
    editor.chips['existing'].click()
    assert editor.chosen() == ['existing']
    panel.dismiss()
    window.apply_tags.assert_called_once()
    assert window.apply_tags.call_args.kwargs == {'prompt_score': False}
    assert window.apply_tags.call_args.args[0] == window.current


def test_tag_management_multiselect_and_close_flush(window):
    window.apply_tags = Mock()
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    assert window.apply_tags.call_count == 1
    assert window.apply_tags.call_args.args[2] == []
    assert window.store.resolve(window.current).exists()


def test_tag_hover_leave_closes(window):
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    window.last_save = time.monotonic()
    try:
        slider = window.seekbar
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
        assert window._pending_seek is None
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
    window.seek_notice.show = Mock()
    window.last_save = time.monotonic()
    try:
        window.seek(offset)
        fake.set_time.assert_called_once_with(target)
        window.seek_notice.show.assert_called_once_with(position, target, 100000)
        assert window.seekbar.visual_fraction == target / 100000
        window.tick()
        assert window.seekbar.visual_fraction == target / 100000
        fake.get_time.return_value = target
        window.tick()
        assert window._pending_seek is None
        assert not window.seekbar.animation.isActive()
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
        notice = window.seek_notice
        notice.show(5000, 10000, 60000)
        panel = notice.overlay
        assert panel.isVisible() and panel.owner is window and panel.isWindow()
        assert notice.text() == '00:05→00:10(01:00)\n16.7%'
        assert panel.windowFlags() & Qt.WindowTransparentForInput
        assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
        assert panel.time_label.font().pixelSize() == 20
        center = window.surface.mapToGlobal(window.surface.rect().center())
        assert abs(panel.geometry().center().x() - center.x()) <= 1
        assert panel.geometry().center().y() < center.y()
        assert window.isActiveWindow()
        assert window.player.mock_calls == []
        width = panel.width()
        window.resize(1200, 760)
        QApplication.processEvents()
        QApplication.processEvents()
        center = window.surface.mapToGlobal(window.surface.rect().center())
        assert panel.isVisible() and abs(panel.geometry().center().x() - center.x()) <= 1
        assert panel.width() == width and panel.time_label.font().pixelSize() == 20
        notice.clear()
        assert not panel.isVisible() and notice.text() == '' and not notice.timer.isActive()
    finally:
        window.player = real


def test_seek_notice_restarts_hide_deadline_for_repeated_seeks(window):
    window.activateWindow()
    QApplication.processEvents()
    notice = window.seek_notice
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
    notice = window.seek_notice
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
        slider = window.seekbar
        slider.synchronize(50000, 36_000_000, True, 1)
        before_value, before_fraction = slider.value(), slider.visual_fraction
        before_image = slider.grab().toImage()
        now[0] += .1
        slider.refresh_frame()
        assert slider.value() == before_value  # Below the integer slider's resolution.
        assert slider.visual_fraction > before_fraction
        assert slider.grab().toImage() != before_image
        assert window.player.mock_calls == []
        assert not isinstance(window.volume, seek_slider.PlaybackTimeline)
        slider.hold(18000000, 36_000_000)
        assert slider.visual_fraction == .5 and not slider.animation.isActive()
        slider.synchronize(18000000, 36_000_000, False, 1)
        now[0] += 5
        slider.refresh_frame()
        assert slider.visual_fraction == .5
    finally:
        window.player = real


def test_fullscreen_restores_layout_and_video_handle(window):
    handle = int(window.surface.winId())
    sizes = window.splitter.sizes()
    window.enter_fullscreen()
    QApplication.processEvents()
    full = window.video_fullscreen
    full.timer.stop()
    full.poll(window.canvas.mapToGlobal(QPoint(300, window.canvas.height() - 1)))
    assert full.overlay.isWindow() and full.overlay.owner is window
    assert window.playback_panel.parentWidget() is full.overlay
    assert int(window.surface.winId()) == handle
    window.exit_fullscreen()
    QApplication.processEvents()
    assert window.playback_panel.parentWidget().objectName() == 'playerCard'
    assert window.sidebar.isVisible() and window.splitter.sizes() == sizes
    assert not window.statusBar().isVisible()
    apply_theme(window, 'dark')
    assert window.theme == 'dark'
    apply_theme(window, 'light')


def test_fullscreen_title_and_cursor_share_visibility_without_resizing_video(window, tmp_path):
    window.enter_fullscreen()
    full = window.video_fullscreen
    full.cursor_position = lambda: window.canvas.mapToGlobal(window.canvas.rect().center())
    QApplication.processEvents()
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    original_geometry = window.surface.geometry()
    full.last_cursor, full.last_activity = center, 0
    full.poll(center)
    assert not full.overlay.isVisible() and not full.title.isVisible()
    assert full.cursor.hidden and window.surface.cursor().shape() == Qt.BlankCursor
    second = tmp_path / 'second.mp4'
    second.write_bytes(b'Isolated metadata fixture; not decoded')
    window.current = window.store.register(second)
    window.store.execute('UPDATE videos SET score=9 WHERE id=?', (window.current,))
    window.refresh_title()
    QApplication.processEvents()
    assert window.player_header.isHidden() and window.surface.geometry() == original_geometry
    assert full.title.filename == 'second.mp4' and not full.title.isVisible()
    full.poll(center + QPoint(1, 0))
    assert full.overlay.isVisible() and full.title.isVisible() and not full.cursor.hidden
    assert window.surface.cursor().shape() != Qt.BlankCursor
    assert abs(full.title.geometry().center().x() - center.x()) <= 1
    full.set_title('Very long video filename ' * 40 + '.mp4')
    assert '…' in full.title.label.text() and full.title.width() <= 900
    assert window.surface.geometry() == original_geometry
    window.exit_fullscreen()
    QApplication.processEvents()
    assert window.player_header.isVisible() and not full.title.isVisible()


def test_fullscreen_interactions_restart_shared_idle_deadline(window, monkeypatch):
    from types import SimpleNamespace
    import video_fullscreen
    now = [100.0]
    monkeypatch.setattr(video_fullscreen, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    window.enter_fullscreen()
    full = window.video_fullscreen
    full.cursor_position = lambda: window.canvas.mapToGlobal(window.canvas.rect().center())
    QApplication.processEvents()
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    full.last_cursor = center
    now[0] = 103
    full.poll(center)
    assert full.cursor.hidden
    full.poll(center + QPoint(1, 0))
    window.playback_options.speed_popup.open_above()
    full.poll(center)
    assert full.title.isVisible() and full.overlay.isVisible() and not full.cursor.hidden
    window.playback_options.dismiss()
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
    window.seekbar.setSliderDown(True)
    now[0] = 120
    full.poll(center)
    assert full.title.isVisible() and not full.cursor.hidden
    window.seekbar.setSliderDown(False)


def test_fullscreen_exit_restores_preexisting_video_cursor(window):
    window.surface.setCursor(Qt.CrossCursor)
    window.enter_fullscreen()
    QApplication.processEvents()
    full = window.video_fullscreen
    full.timer.stop()
    center = window.canvas.mapToGlobal(window.canvas.rect().center())
    full.last_cursor, full.last_activity = center, 0
    full.poll(center)
    assert window.surface.cursor().shape() == Qt.BlankCursor
    window.exit_fullscreen()
    assert not full.cursor.hidden and window.surface.cursor().shape() == Qt.CrossCursor


def test_cancelled_storage_keeps_tag_draft(window):
    window.apply_tags = Mock(return_value=False)
    window.tags_dialog()
    panel = window.playback_options.tags_popup
    editor = panel.editor
    editor.chips['existing'].click()
    panel.dismiss()
    window.tags_dialog()
    assert panel.editor is editor and editor.chosen() == ['existing']
    assert window.store.video(window.current)['tags'] == '[]'


def test_escape_closes_editable_surface_before_leaving_fullscreen(window):
    window.enter_fullscreen()
    QApplication.processEvents()
    window.activateWindow()
    window.video_fullscreen.poll(window.canvas.mapToGlobal(QPoint(300, window.canvas.height() - 1)))
    QApplication.processEvents()
    window.tags_dialog()
    panel = window.playback_options.tags_popup
    assert panel.isVisible()
    QTest.mouseClick(panel.editor.entry, Qt.LeftButton)
    QTest.keyClick(panel.editor.entry, Qt.Key_Escape)
    assert not panel.isVisible() and window.video_fullscreen.active
    QTest.keyClick(window, Qt.Key_Escape)
    assert not window.video_fullscreen.active


def test_tag_context_menu_belongs_to_editable_surface(window):
    from PySide6.QtWidgets import QMenu
    from PySide6.QtCore import QTimer
    window.apply_tags = Mock()
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    window.apply_tags = Mock()
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    assert panel.isVisible() and not window.apply_tags.called
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
    window.tags_dialog()
    panel = window.playback_options.tags_popup
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
    window.show_sidebar('stars')
    window.sidebar_list.setCurrentRow(0)
    tasks = []
    window.work = lambda function, callback: tasks.append((function, callback))
    window.play_path = Mock()
    original = window.current
    window.delete_video()
    assert window.busy and window.current == original and len(tasks) == 1
    function, ready = tasks.pop()
    # Changing selection during the scan cannot retarget the requested delete.
    window.sidebar_list.clearSelection()
    ready(function(), None)
    assert window.busy and len(tasks) == 1
    assert selected_id in window.deleting_ids and original not in window.deleting_ids
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
    window.last_save = time.monotonic()
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
    window.last_save = time.monotonic()
    expected = icon('pause', '#ffffff').pixmap(24, 24).toImage()
    try:
        window.tick()
        assert window.play_button.icon().pixmap(24, 24).toImage() == expected
        apply_theme(window, 'dark')
        # The backend remains Playing, so an ordinary tick used to skip repair.
        window.tick()
        assert window.play_button.icon().pixmap(24, 24).toImage() == expected
        window.enter_fullscreen()
        QApplication.processEvents()
        window.tick()
        assert window.play_button.icon().pixmap(24, 24).toImage() == expected
        window.exit_fullscreen()
        QApplication.processEvents()
        window.tick()
        assert window.play_button.icon().pixmap(24, 24).toImage() == expected
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
            assert window.play_button.property('iconName') == symbol
            assert window.play_button.accessibleName() == action
            assert window.play_button.toolTip() == action + ' · 空格'
            assert window.play_button.icon().pixmap(24, 24).toImage() == icon(symbol, '#ffffff').pixmap(24, 24).toImage()
    finally:
        window.player = real


def test_pause_command_waits_for_state_confirmation(window):
    real = window.player
    fake = Mock()
    fake.get_state.return_value = vlc.State.Playing
    fake.get_length.return_value = 100000
    fake.get_time.return_value = 2000
    window.player = fake
    window.last_save = time.monotonic()
    try:
        window.tick()
        window.play_button.click()
        fake.pause.assert_called_once()
        assert window.play_button.property('iconName') == 'pause'
        fake.get_state.return_value = vlc.State.Paused
        window.tick()
        assert window.play_button.property('iconName') == 'play'
        window.play_button.click()
        assert fake.pause.call_count == 2
        fake.get_state.return_value = vlc.State.Playing
        window.tick()
        assert window.play_button.property('iconName') == 'pause'
    finally:
        window.player = real
