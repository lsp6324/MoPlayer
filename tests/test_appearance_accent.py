import json
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt, QEvent, QCoreApplication, QPoint
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget, QDialog
from moplayer.gui.accent_colors import DEFAULT_ACCENT, PRESETS
from moplayer.gui.appearance import Appearance
from moplayer.gui.appearance_dialog import AppearanceDialog
from moplayer.gui.color_picker import AccentPicker
from moplayer.gui.theme import colors_for, LIGHT_TOKENS, TOKENS


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_picker_presets_and_rgb_controls_stay_in_sync(application):
    picker=AccentPicker(DEFAULT_ACCENT)
    picker.show()
    spy=QSignalSpy(picker.colorChanged)
    picker.swatches[1].click()
    assert picker.color==PRESETS[1][1] and spy.count()==1
    picker.values[0].setValue(12)
    assert picker.color=='#0c5cf6' and picker.sliders[0].value()==12
    assert not any(button.isChecked() for button in picker.swatches)
    picker.sliders[1].setValue(34)
    picker.values[2].setValue(56)
    assert picker.color=='#0c2238' and [control.value() for control in picker.values]==[12,34,56]
    QTest.mouseClick(picker.field,Qt.LeftButton,pos=QPoint(100,40))
    assert picker.color!='#0c2238' and spy.count()==5
    assert picker.readout.text().startswith(picker.color.upper())
    picker.close()


def test_hue_keeps_grayscale_selection_intent(application):
    picker=AccentPicker('#ffffff')
    picker.hue.setValue(120)
    assert picker.color=='#ffffff' and picker.hue.value()==120
    picker.show()
    QTest.mouseClick(picker.field,Qt.LeftButton,pos=QPoint(147,1))
    assert picker.color=='#00ff00'
    picker.close()


def test_rgb_value_can_be_typed_directly(application):
    picker=AccentPicker(DEFAULT_ACCENT)
    picker.show()
    editor=picker.values[0]
    editor.setFocus()
    editor.lineEdit().selectAll()
    QTest.keyClicks(editor,'200')
    QTest.keyClick(editor,Qt.Key_Return)
    assert picker.color=='#c87ce5' and picker.sliders[0].value()==200
    picker.close()


def test_old_and_invalid_accent_settings_preserve_other_preferences(tmp_path):
    appearance=Appearance(tmp_path)
    appearance.file.write_text(json.dumps(dict(theme='dark',strength=75,accent='invalid')),encoding='utf-8')
    restored=Appearance(tmp_path)
    assert (restored.theme,restored.strength,restored.accent)==('dark',75,DEFAULT_ACCENT)
    restored.file.write_text(json.dumps(dict(theme='dark',strength=75)),encoding='utf-8')
    assert Appearance(tmp_path).accent==DEFAULT_ACCENT


@pytest.mark.parametrize('finish',['reject','close','escape'])
def test_preview_cancellation_restores_saved_color_and_theme(application,tmp_path,finish):
    appearance=Appearance(tmp_path)
    appearance.save(None,60,'dark','#159f9b')
    before=appearance.file.read_bytes()
    previews=[]
    dialog=AppearanceDialog(None,appearance,preview_theme=lambda *args:previews.append(args),preview_background=lambda *args:None)
    dialog.show()
    dialog.accent_picker.set_color('#db4f96')
    dialog.themes.setCurrentIndex(dialog.themes.findData('light'))
    assert previews[-1]==('light','#db4f96') and appearance.file.read_bytes()==before
    if finish=='escape':
        QTest.keyClick(dialog,Qt.Key_Escape)
    else:
        getattr(dialog,finish)()
    assert previews[-1]==('dark','#159f9b') and appearance.file.read_bytes()==before
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


def test_save_reopen_and_failed_save_keep_exact_color_and_draft(application,tmp_path):
    appearance=Appearance(tmp_path)
    dialog=AppearanceDialog(None,appearance,preview_theme=lambda *args:None,preview_background=lambda *args:None)
    dialog.show()
    dialog.accent_picker.set_color('#0c2238')
    dialog.accept()
    assert dialog.result()==QDialog.Accepted and Appearance(tmp_path).accent=='#0c2238'
    before=appearance.file.read_bytes()
    second=AppearanceDialog(None,appearance,preview_theme=lambda *args:None,preview_background=lambda *args:None)
    second.show()
    second.accent_picker.set_color('#123456')
    with patch('moplayer.gui.appearance.os.replace',side_effect=OSError('disk full')),patch('moplayer.gui.appearance_dialog.QMessageBox.warning'):
        second.accept()
    assert second.isVisible() and second.accent_picker.color=='#123456'
    assert appearance.accent=='#0c2238' and appearance.file.read_bytes()==before
    second.reject()


def test_custom_colors_do_not_mutate_default_theme_and_survive_fullscreen(application,tmp_path):
    from moplayer.app import Window
    window=Window(tmp_path/'data')
    from moplayer.gui.theme import apply_theme
    old_light,old_dark=dict(LIGHT_TOKENS),dict(TOKENS)
    handle=window.player_view.video_handle()
    apply_theme(window,'light','#ffffff')
    dialog=AppearanceDialog(window,window.appearance,preview_theme=lambda *args:None,preview_background=lambda *args:None)
    dialog.show()
    application.processEvents()
    assert all(control.lineEdit().width()>=control.fontMetrics().horizontalAdvance('255') for control in dialog.accent_picker.values)
    dialog.reject()
    assert window.player_view.normal_colors['button_fill']=='#ffffff'
    assert window.player_view.normal_colors['button_text']=='#000000'
    assert window.player_view.fullscreen.colors['accent_source']=='#ffffff'
    assert window.player_view.fullscreen.title.header.colors['accent']==colors_for('dark','#ffffff')['accent']
    apply_theme(window,'dark','#159f9b')
    assert window.player_view.normal_colors['accent_source']=='#159f9b'
    assert window.player_view.video_handle()==handle
    assert LIGHT_TOKENS==old_light and TOKENS==old_dark
    from moplayer.gui.score_editor import ScoreEditor
    from PySide6.QtGui import QColor
    rating=ScoreEditor(dict(name='sample.mp4',score=8),window)
    rating.show()
    application.processEvents()
    assert rating.hearts[0].grab().toImage().pixelColor(24,20)==QColor(colors_for('dark','#159f9b')['accent'])
    rating.reject()
    window.close()
    window.store.db.close()
