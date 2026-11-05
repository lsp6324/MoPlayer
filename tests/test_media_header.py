import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from media_header import MediaHeader
from theme import LIGHT_TOKENS, TOKENS


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
