import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from media_header import MediaHeader
from theme import LIGHT_TOKENS, TOKENS
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from application.operations import Operation, Outcome, Status


@pytest.fixture
def header():
    application=QApplication.instance() or QApplication([])
    view=MediaHeader()
    view.resize(720,72)
    view.apply_colors(LIGHT_TOKENS)
    view.show()
    yield view
    view.close()


def pixel(view,x,y):
    image=view.grab().toImage()
    ratio=image.devicePixelRatio()
    return image.pixelColor(round(x*ratio),round(y*ratio))


def test_half_hearts_and_numeric_score_are_distinct_from_unrated(header):
    header.present('原名.mp4',('标签',),1,True)
    accent=QColor(LIGHT_TOKENS['accent'])
    assert pixel(header,118,51)==accent
    assert pixel(header,125,51)!=accent
    assert header.accessibleDescription()=='标签，已收藏，1 分'
    header.present('原名.mp4',(),0,False)
    assert pixel(header,118,51)!=accent and '0 分' in header.accessibleDescription()
    header.present('原名.mp4',(),None,False)
    assert '未评分' in header.accessibleDescription() and '未收藏' in header.accessibleDescription()


def test_capsules_are_before_literal_filename_and_metadata_keeps_fixed_height(header):
    header.present('8分 本来就有这些字.mp4',('教程','Python'),7,True)
    assert pixel(header,22,15)==QColor(LIGHT_TOKENS['selected'])
    assert header.accessibleName()=='8分 本来就有这些字.mp4'
    assert header.toolTip().startswith('8分 本来就有这些字.mp4')
    height=header.height()
    header.resize(340,height)
    header.present('很长的原始文件名'*30+'.mp4',tuple('长标签'+str(i) for i in range(30)),10,False)
    assert header.height()==height==72 and header.width()==340
    assert '长标签29' in header.toolTip()
    header.apply_colors(TOKENS)
    assert pixel(header,118,51)==QColor(TOKENS['accent'])


def editable(header, handler):
    header.present('原文件.mp4',('教程',),7,True)
    header.set_rename_handler(handler)
    header.set_rename_available(True)
    header.begin_edit()
    QApplication.processEvents()


def test_inline_editor_replaces_only_title_and_escape_never_submits(header):
    calls=[]
    editable(header,lambda name:calls.append(name))
    assert header.editor.isVisible() and header.editor.selectedText()=='原文件'
    assert header.editor.x()>16 and header.height()==72 and header.score==7
    QTest.keyClicks(header.editor,'new')
    QTest.keyClick(header.editor,Qt.Key_Escape)
    assert not header.editor.isVisible() and header.filename=='原文件.mp4' and not calls


def test_inline_error_preserves_draft_and_allows_retry(header):
    operation=Operation()
    editable(header,lambda name:operation)
    header.editor.setText('新文件.mp4')
    QTest.keyClick(header.editor,Qt.Key_Return)
    assert header.editor.isReadOnly()
    operation.finish(Outcome(Status.FAILED,error=FileExistsError('同名文件已存在')))
    assert header.editor.isVisible() and not header.editor.isReadOnly()
    assert header.editor.text()=='新文件.mp4' and header.error_label.isVisible()
    header.set_rename_handler(lambda name:Operation.success(name))
    QTest.keyClick(header.editor,Qt.Key_Return)
    assert not header.editor.isVisible()


def test_focus_loss_cancels_and_hidden_editor_ignores_late_result(header):
    operation=Operation()
    editable(header,lambda name:operation)
    header.editor.clearFocus()
    QApplication.processEvents()
    assert not header.editor.isVisible() and operation.pending
    header.begin_edit()
    QTest.keyClick(header.editor,Qt.Key_Return)
    header.hide()
    operation.finish(Outcome(Status.FAILED,error=OSError('late')))
    header.show()
    assert not header.editor.isVisible() and not header.error_label.isVisible()
