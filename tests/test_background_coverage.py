from unittest.mock import patch
import pytest
from PySide6.QtCore import QPoint, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton
from app import Window
from appearance_dialog import AppearanceDialog
from theme import apply_theme, theme_tokens


@pytest.fixture
def scene(tmp_path):
    application=QApplication.instance() or QApplication([])
    window=Window(tmp_path/'data')
    window.resize(1100,720)
    window.show()
    window.thumbnails.request=lambda vid:None
    for number in range(2):
        sample=tmp_path/f'sample{number}.mp4'
        sample.write_bytes(b'not decoded')
        vid=window.store.register(sample)
        window.catalog.mark_played(vid)
    window.library_view.show_mode('videos')
    application.processEvents()
    images=[]
    for color in ('#e04060','#30a0e0'):
        image=QImage(1100,720,QImage.Format_RGB32)
        image.fill(QColor(color))
        path=tmp_path/(color[1:]+'.png')
        image.save(str(path))
        images.append(path)
    yield application,window,images
    window.close()
    QThreadPool.globalInstance().waitForDone()
    window.thumbnails.pool.waitForDone()
    window.store.db.close()


def samples(window):
    viewport=window.library_view.lists['videos'].viewport()
    image=window.grab().toImage()
    return tuple(image.pixelColor(viewport.mapTo(window,point)) for point in
                 (QPoint(viewport.width()-12,viewport.height()-12),QPoint(viewport.width()-12,45)))


def test_background_reaches_library_blank_space_and_unselected_video_rows(scene):
    application,window,images=scene
    window.canvas.set_background(images[0],80)
    application.processEvents()
    first=samples(window)
    window.canvas.set_background(images[1],80)
    application.processEvents()
    second=samples(window)
    assert all(a!=b for a,b in zip(first,second)),(first,second)
    assert theme_tokens(window)['backdrop']


def test_idle_background_uses_canvas_coordinates_and_keeps_video_host(scene):
    application,window,images=scene
    handle=window.player_view.video_handle()
    for mode,size in (('light',(1100,720)),('dark',(1200,800))):
        window.resize(*size)
        window.canvas.set_background(images[0],80)
        apply_theme(window,mode)
        application.processEvents()
        image=QImage(window.canvas.size(),QImage.Format_RGB32)
        painter=QPainter(image)
        window.canvas._paint_background(painter)
        painter.end()
        idle=window.player_view.player_empty
        point=QPoint(20,20)
        expected=idle.mapTo(window.canvas,point)
        assert idle.grab().toImage().pixelColor(point)==image.pixelColor(expected)
        assert window.player_view.video_handle()==handle
    window.player_view.media_loading()
    assert not window.player_view.player_empty.isVisible()
    window.player_view.clear_media()
    assert window.player_view.player_empty.isVisible() and window.player_view.video_handle()==handle


def test_cancel_preview_restores_default_library_and_idle_background(scene):
    application,window,images=scene
    before=samples(window)
    dialog=AppearanceDialog(window,window.appearance,
        preview_theme=lambda theme,accent:apply_theme(window,theme,accent),
        preview_background=window.canvas.set_background)
    dialog.show()
    with patch('appearance_dialog.QFileDialog.getOpenFileName',return_value=(str(images[0]),'PNG')):
        dialog.findChild(QPushButton,'chooseBackground').click()
    assert window.canvas.has_background and theme_tokens(window)['backdrop']
    dialog.reject()
    application.processEvents()
    assert not window.canvas.has_background and not theme_tokens(window)['backdrop']
    assert samples(window)==before
    assert window.player_view.player_empty.grab().toImage().pixelColor(20,20)==QColor('#101216')
