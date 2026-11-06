"""Still-image media: kind rules, decoding and the playback-area presenter."""
import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QThreadPool, Qt, QCoreApplication
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter, QVBoxLayout, QWidget

from moplayer.application.operations import Operation
from moplayer.application.playback import PlaybackStatus
from moplayer.app import Window
from moplayer.core import EXTENSIONS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, media_kind
from moplayer.gui.image_view import ImageView
from moplayer.infrastructure.image_loader import ImageLoadError, ImageLoader
from moplayer.gui.player_view import PlayerInfo, PlayerView
from moplayer.gui.theme import LIGHT_TOKENS


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def make_image(width, height, color='#336699'):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    return image


def send_wheel(widget, position, delta):
    event = QWheelEvent(position, QPointF(widget.mapToGlobal(position.toPoint())), QPoint(0, 0),
                        QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def send_mouse(widget, kind, position, buttons=Qt.LeftButton):
    event = QMouseEvent(kind, position, QPointF(widget.mapToGlobal(position.toPoint())),
                        Qt.LeftButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


# --------------------------------------------------------------------- kinds

@pytest.mark.parametrize('name, kind', [
    ('a.JPG', 'image'), ('b.png', 'image'), ('c.jpeg', 'image'), ('d.bmp', 'image'),
    ('e.webp', 'image'), ('f.gif', 'image'), ('g.TIFF', 'image'),
    ('h.mp4', 'video'), ('i.MKV', 'video'), ('no-extension', 'video'), ('k.txt', 'video'),
])
def test_media_kind_follows_the_extension(name, kind):
    assert media_kind(name) == kind


def test_still_images_join_the_existing_candidate_list():
    assert {'.mp4', '.mkv'} <= VIDEO_EXTENSIONS
    assert {'.jpg', '.png', '.webp'} <= IMAGE_EXTENSIONS
    assert not (VIDEO_EXTENSIONS & IMAGE_EXTENSIONS)
    assert EXTENSIONS == VIDEO_EXTENSIONS | IMAGE_EXTENSIONS


# -------------------------------------------------------------------- loader

def test_loader_returns_real_pixels(tmp_path, qt_app):
    path = tmp_path / 'sample.png'
    assert make_image(40, 20).save(str(path))
    result = ImageLoader().read(path)
    assert (result.width(), result.height()) == (40, 20)


def test_loader_samples_oversized_files(tmp_path, qt_app):
    path = tmp_path / 'big.png'
    assert make_image(3000, 100).save(str(path))
    result = ImageLoader(max_side=1000).read(path)
    assert max(result.width(), result.height()) == 1000
    assert result.width() == 1000 and result.height() == 33


def test_loader_reports_unreadable_files(tmp_path, qt_app):
    broken = tmp_path / 'broken.jpg'
    broken.write_bytes(b'not an image at all')
    with pytest.raises(ImageLoadError):
        ImageLoader().read(broken)
    with pytest.raises(ImageLoadError):
        ImageLoader().read(tmp_path / 'missing.jpg')


# --------------------------------------------------------------------- image

@pytest.fixture
def image_view(qt_app):
    widget = ImageView()
    widget.resize(800, 600)
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()


def test_large_image_is_fitted_and_small_image_keeps_actual_size(image_view):
    image_view.set_image(make_image(1600, 1200))
    assert image_view.has_image()
    assert image_view._scale == pytest.approx(0.5)
    image_view.set_image(make_image(200, 100))
    assert image_view._scale == pytest.approx(1.0)


def test_wheel_zoom_keeps_the_pointer_anchor(image_view):
    image_view.set_image(make_image(1600, 1200))
    anchor = QPointF(600, 200)
    before = image_view._image_point(anchor)
    send_wheel(image_view, anchor, 120)
    assert image_view._scale > 0.5
    after = image_view._image_point(anchor)
    assert after.x() == pytest.approx(before.x(), abs=0.5)
    assert after.y() == pytest.approx(before.y(), abs=0.5)


def test_wheel_zoom_never_shrinks_below_fit_or_grows_past_the_ceiling(image_view):
    image_view.set_image(make_image(1600, 1200))
    for _ in range(40):
        send_wheel(image_view, QPointF(400, 300), 120)
    assert image_view._scale == pytest.approx(image_view.MAX_SCALE)
    for _ in range(80):
        send_wheel(image_view, QPointF(400, 300), -120)
    assert image_view._scale == pytest.approx(0.5)


def test_double_click_switches_between_fit_and_actual(image_view):
    image_view.set_image(make_image(1600, 1200))
    send_mouse(image_view, QEvent.MouseButtonDblClick, QPointF(400, 300))
    assert image_view._scale == pytest.approx(1.0)
    send_mouse(image_view, QEvent.MouseButtonDblClick, QPointF(400, 300))
    assert image_view._scale == pytest.approx(0.5)


def test_dragging_pans_a_zoomed_image_and_stays_inside_the_edges(image_view):
    image_view.set_image(make_image(3200, 2400))
    image_view.zoom_at(QPointF(400, 300), 1.0)
    before = image_view._center.x()
    send_mouse(image_view, QEvent.MouseButtonPress, QPointF(400, 300))
    send_mouse(image_view, QEvent.MouseMove, QPointF(300, 300))
    send_mouse(image_view, QEvent.MouseButtonRelease, QPointF(300, 300), buttons=Qt.NoButton)
    assert image_view._center.x() > before
    for _ in range(20):
        send_mouse(image_view, QEvent.MouseButtonPress, QPointF(400, 300))
        send_mouse(image_view, QEvent.MouseMove, QPointF(4000, 300))
        send_mouse(image_view, QEvent.MouseButtonRelease, QPointF(4000, 300), buttons=Qt.NoButton)
    assert image_view._center.x() <= 3200 - 400


def test_painting_produces_non_background_pixels(image_view):
    image_view.set_image(make_image(400, 300, '#ff0000'))
    rendered = image_view.grab().toImage()
    center = rendered.pixelColor(rendered.width() // 2, rendered.height() // 2)
    assert center.red() > 200 and center.green() < 60


# -------------------------------------------------------------------- player

class Drafts:
    def commit(self, video_id):
        return Operation.success()


@pytest.fixture
def player(qt_app):
    host = QMainWindow()
    canvas = QWidget()
    host.setCentralWidget(canvas)
    layout = QVBoxLayout(canvas)
    splitter = QSplitter(Qt.Horizontal)
    layout.addWidget(splitter)
    splitter.addWidget(QWidget())
    view = PlayerView(host, canvas, splitter, Drafts(), lambda: ('frozen-id', 7))
    splitter.addWidget(view)
    host.resize(1100, 720)
    host.show()
    view.apply_theme(LIGHT_TOKENS)
    qt_app.processEvents()
    yield view
    view.shutdown()
    host.close()
    host.deleteLater()


def test_still_presentation_keeps_classification_and_disables_playback(player):
    player.present_video(PlayerInfo('图集.jpg', 5, ('旅行',), False, 'vid-1'))
    player.present_transport(PlaybackStatus.IDLE, True, False, still=True)
    assert not player.seekbar.isEnabled()
    assert not player.play_button.isEnabled()
    assert player.transport_buttons[0].isEnabled(), '图片模式仍应能用上一个'
    assert player.transport_buttons[2].isEnabled(), '图片模式仍应能用下一个'
    assert player.media_badge.text() == '图片'
    assert player.tags_button.isEnabled()
    assert player.rating_button.isEnabled()
    assert player.favorite_button.isEnabled()


def test_image_layer_is_shown_then_dropped(player):
    player.present_image(make_image(120, 80))
    assert player.image_view.isVisible()
    player.present_image(None)
    assert not player.image_view.isVisible()


# ------------------------------------------------------------------ workflow

def wait_for(predicate, app, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def window(tmp_path):
    application = QApplication.instance() or QApplication([])
    player = Window(tmp_path / 'data')
    player.timer.stop()
    player.resize(900, 580)
    player.show()
    application.processEvents()
    yield player
    player.busy = False
    player.close()
    QThreadPool.globalInstance().waitForDone()
    player.thumbnails.pool.waitForDone()
    player.store.db.close()
    player.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_mixed_directory_opens_the_image_and_keeps_zx_order(window, tmp_path, qt_app):
    folder = tmp_path / 'mixed'
    folder.mkdir()
    assert make_image(160, 120, '#cc3344').save(str(folder / 'a.png'))
    (folder / 'b.mp4').write_bytes(b'fixture that is never decoded')

    operation = window.load_folder(str(folder))
    assert wait_for(lambda: operation.outcome is not None, qt_app), '扫描没有完成'
    snapshot = operation.outcome.value.snapshot
    window.start(snapshot, (str(folder.absolute()), 0))

    assert wait_for(lambda: window.current is not None, qt_app), '图片没有打开'
    assert window.current_kind == 'image'
    assert window.catalog.video(window.current)['name'] == 'a.png'
    assert wait_for(lambda: window.player_view.image_view.has_image(), qt_app), '图片没有解码显示'
    assert window.player_view.image_view.isVisible()

    for _ in range(3):
        window.tick()
    assert window.catalog.video(window.current)['position'] == 0, '图片被写入了续播进度'
    assert window.player_view.play_button.isEnabled() is False

    window.advance(1)
    assert wait_for(lambda: window.current_kind == 'video', qt_app), 'X 没有切到视频'
    window.advance(-1)
    assert wait_for(lambda: window.current_kind == 'image', qt_app), 'Z 没有切回图片'
    assert wait_for(lambda: window.player_view.image_view.has_image(), qt_app)
