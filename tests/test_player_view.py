"""Exercise the player presentation with an ordinary Qt host and no VLC/Store."""
import pytest
from PySide6.QtCore import Qt, QEvent, QCoreApplication
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter
from application.operations import Operation
from application.playback import PlaybackStatus
from player_view import PlayerView, PlayerInfo
from theme import LIGHT_TOKENS, TOKENS


class Drafts:
    def commit(self, video_id):
        return Operation.success()


@pytest.fixture
def view():
    application = QApplication.instance() or QApplication([])
    host = QMainWindow()
    canvas = QWidget()
    host.setCentralWidget(canvas)
    layout = QVBoxLayout(canvas)
    splitter = QSplitter(Qt.Horizontal)
    layout.addWidget(splitter)
    splitter.addWidget(QWidget())
    player = PlayerView(host, canvas, splitter, Drafts(), lambda: ('frozen-id', 7))
    splitter.addWidget(player)
    host.resize(1100, 720)
    host.show()
    player.apply_theme(LIGHT_TOKENS)
    application.processEvents()
    yield player
    player.shutdown()
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_player_emits_intents_and_renders_without_application_window(view):
    play, step, favorite, imports = [QSignalSpy(signal) for signal in
                                    (view.playRequested, view.stepRequested, view.favoriteRequested, view.importRequested)]
    view.present_video(PlayerInfo('示例.mp4', 7, ('标签',), True))
    view.present_transport(PlaybackStatus.PLAYING, True, False)
    view.play_button.click()
    view.transport_buttons[0].click()
    view.transport_buttons[2].click()
    view.favorite_button.click()
    view.empty_import.click()
    assert play.count() == favorite.count() == imports.count() == 1
    assert step.count() == 2 and step.at(0) == [-1] and step.at(1) == [1]
    assert view.now.text() == '示例.mp4' and view.metadata.text() == '7 分 · 标签'
    assert view.play_button.accessibleName() == '暂停'


def test_theme_and_fullscreen_keep_transport_and_video_host(view):
    from ui import icon
    view.present_video(PlayerInfo('视频.mp4', None, (), False))
    view.present_transport(PlaybackStatus.PLAYING, True, False)
    handle = view.video_handle()
    for colors in (TOKENS, LIGHT_TOKENS):
        view.apply_theme(colors)
        view.fullscreen.enter()
        assert not view.header.isVisible()
        assert view.fullscreen.title.filename == '视频.mp4'
        view.present_video(PlayerInfo('新的名称.mp4', 8, ('分类',), True))
        assert view.fullscreen.title.filename == '新的名称.mp4' and not view.header.isVisible()
        view.fullscreen.exit()
        assert view.video_handle() == handle and view.header.isVisible()
        assert view.play_button.property('iconName') == 'pause'
        assert view.play_button.icon().pixmap(24, 24).toImage() == icon('pause', '#ffffff').pixmap(24, 24).toImage()
        view.present_video(PlayerInfo('视频.mp4', None, (), False))


def test_progress_preview_and_release_only_emit_a_seek_intent(view):
    seek = QSignalSpy(view.seekRequested)
    view.present_progress(10000, 100000, playing=False, pending_seek=False)
    view.seekbar.setValue(2500)
    view.seekbar.sliderMoved.emit(2500)
    assert view.time_label.text() == '00:00:25 / 00:01:40' and seek.count() == 0
    view.seekbar.sliderReleased.emit()
    assert seek.count() == 1 and seek.at(0) == [.25]
    view.hold_position(70000, 100000)
    view.present_progress(10000, 100000, playing=True, pending_seek=True)
    assert view.seekbar.value() == 7000 and view.time_label.text() == '00:01:10 / 00:01:40'


def test_rate_changes_wait_for_backend_result(view):
    requested = QSignalSpy(view.rateRequested)
    view.options.set_rate(1.5)
    assert requested.count() == 1 and requested.at(0) == [1.5]
    assert view.options.rate == 1.0 and view.options.speed_button.text() == '1×'
    view.accept_rate(1.5)
    assert view.options.rate == 1.5 and view.options.speed_button.text() == '1.5×'
    view.options.rate_buttons[2.0].click()
    view.reject_rate()
    assert view.options.rate == 1.5 and view.options.rate_buttons[1.5].isChecked()
    assert not view.options.rate_buttons[2.0].isChecked()


def test_rating_target_is_frozen_when_panel_prepares(view):
    chosen = QSignalSpy(view.ratingRequested)
    panel = view.options.rating_popup
    assert panel.load_score()
    panel.rating_source = lambda: ('later-id', 2)
    panel.commit(9)
    assert chosen.count() == 1 and chosen.at(0) == ['frozen-id', 9]


def test_clear_and_busy_presentation_reset_or_disable_controls(view):
    view.present_video(PlayerInfo('视频.mp4', 8, ('分类',), True))
    view.present_transport(PlaybackStatus.PLAYING, True, True)
    assert not view.play_button.isEnabled() and not view.seekbar.isEnabled()
    assert all(not control.isEnabled() for control in view.classify_buttons + view.transport_buttons)
    view.present_transport(PlaybackStatus.PLAYING, True, False)
    assert all(control.isEnabled() for control in view.classify_buttons + view.transport_buttons)
    view.hold_position(12000, 60000)
    view.clear_media()
    assert view.player_empty.isVisible() and not view.header.isVisible()
    assert not view.classify_bar.isVisible() and not view.metadata.isVisible()
    assert view.now.text() == '播放器' and view.time_label.text() == '00:00 / 00:00'
    assert view.seekbar.value() == 0 and not view.favorite_button.isChecked()
