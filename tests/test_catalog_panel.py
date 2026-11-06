"""Real filter controls and stable list/grid identities, without media or disk."""
import pytest
from string import Template
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtTest import QSignalSpy, QTest
from application.catalog import CatalogFilter
from catalog_panel import CatalogPanel
from catalog_delegate import CatalogDelegate
from library_views import VideoListModel
from theme import STYLE_TEMPLATE, LIGHT_TOKENS


class Thumbnails:
    def request(self, video_id):
        return None


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.theme = 'light'
    host.setStyleSheet(Template(STYLE_TEMPLATE).substitute(**LIGHT_TOKENS))
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0,0,0,0)
    panel = CatalogPanel(host, theme_owner=host)
    layout.addWidget(panel)
    panel.list.setModel(VideoListModel(panel.list))
    panel.list.setItemDelegate(CatalogDelegate(Thumbnails(), panel.list, current_video=lambda:'3', theme_owner=host,
                              presentation=lambda:panel.list.presentation, tile_size=panel.list.gridSize))
    panel.list.model().sync([dict(id=str(n),name=f'山间{n}.png',kind='image',tag_names=('摄影','旅行'),score=n%11,star=n%2) for n in range(60)])
    panel.present_schema({'摄影':{},'旅行':{},'风景':{},'山川':{'parent':'风景'}})
    panel.present_status(60,60,False,None)
    panel.apply_colors()
    host.resize(340,650)
    host.show()
    app.processEvents()
    yield panel
    panel.shutdown()
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)


def test_popup_rules_emit_committed_filter_and_summary_removes_entire_group(panel):
    changes = QSignalSpy(panel.filtersChanged)
    panel.popup.number.setText('7')
    panel.popup.score_mode['gte'].click()
    panel.popup.tags.chips['摄影'].click()
    panel.popup.tags.chips['旅行'].click()
    panel.popup.tag_mode['or'].click()
    assert panel.filters.score == 7 and panel.filters.score_mode == 'gte'
    assert panel.filters.tags == ('摄影','旅行') and panel.filters.tag_mode == 'or'
    assert '≥ 7 分' in ' '.join(panel.summary.chips) and '摄影 或 旅行' in ' '.join(panel.summary.chips)
    tag_summary = next(name for name in panel.summary.chips if name.startswith('标签：'))
    panel.summary.chips[tag_summary].click()
    assert panel.filters.tags == () and panel.filters.score == 7 and changes.count() == 6


def test_reclicking_selected_condition_does_not_uncheck_it_or_requery(panel):
    changes = QSignalSpy(panel.filtersChanged)
    panel.popup.favorite['all'].click()
    assert panel.popup.favorite['all'].isChecked() and changes.count() == 0


def test_catalog_list_card_matches_other_pages_row_and_visible_thumbnail(panel):
    """Changing tabs keeps the media card scale, including the rendered image."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QStyleOptionViewItem
    from library_views import VideoDelegate

    marker = QColor('#fd07d9')
    pixmap = QPixmap(280, 158)
    pixmap.fill(marker)

    class SolidThumbnails:
        def request(self, video_id):
            return pixmap

    catalog = panel.list.itemDelegate()
    catalog.thumbnails = SolidThumbnails()
    ordinary = VideoDelegate(SolidThumbnails(), panel.list, current_video=lambda: None,
                             theme_owner=panel.window())
    index = panel.list.model().index(0, 0)
    option = QStyleOptionViewItem()
    option.font = panel.font()
    heights, bounds = [], []
    for delegate in (ordinary, catalog):
        height = delegate.sizeHint(option, index).height()
        heights.append(height)
        option.rect = QRect(0, 0, 320, height)
        image = QImage(320, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        pixels = [(x, y) for y in range(height) for x in range(160)
                  if image.pixelColor(x, y) == marker]
        assert pixels, 'the thumbnail must actually be drawn'
        bounds.append((min(x for x, y in pixels), min(y for x, y in pixels),
                       max(x for x, y in pixels), max(y for x, y in pixels)))
    assert heights[0] == heights[1]
    assert bounds[0] == bounds[1], 'the visible thumbnails must have the same size and position'


def test_view_switch_keeps_order_selection_and_filter_without_query_or_play(panel):
    panel.change(score=7,score_mode='gte',tags=('摄影',),tag_mode='or')
    changes, opens, views = QSignalSpy(panel.filtersChanged), QSignalSpy(panel.openRequested), QSignalSpy(panel.viewChanged)
    model = panel.list.model()
    panel.list.setCurrentIndex(model.index_for_id('20'))
    panel.list.scrollTo(model.index_for_id('20'))
    ids = [row['id'] for row in model.rows]
    panel.view_buttons['grid'].click()
    QApplication.processEvents()
    assert panel.list.currentIndex().data(Qt.UserRole) == '20'
    assert panel.list.visualRect(model.index(0,0)).top() == panel.list.visualRect(model.index(1,0)).top()
    panel.view_buttons['list'].click()
    QApplication.processEvents()
    assert panel.list.currentIndex().data(Qt.UserRole) == '20' and [row['id'] for row in model.rows] == ids
    assert panel.filters.score_mode == 'gte' and changes.count() == opens.count() == 0 and views.count() == 2


def test_grid_reflows_to_more_columns_without_losing_identity(panel):
    panel.set_view('grid')
    panel.list.setCurrentIndex(panel.list.model().index_for_id('10'))
    old = panel.list.gridSize().width()
    panel.window().resize(620,650)
    QApplication.processEvents()
    assert panel.list.viewport().width() // panel.list.gridSize().width() >= 4
    assert panel.list.currentIndex().data(Qt.UserRole) == '10'


def test_short_grid_keeps_two_columns_after_queued_layout_and_metadata_update(panel):
    model = panel.list.model()
    rows = model.rows[:8]
    model.sync(rows)
    panel.set_view('grid')
    QTest.qWait(80)
    model.sync([dict(row,score=9) for row in rows])
    QTest.qWait(80)
    assert panel.list.visualRect(model.index(0,0)).top() == panel.list.visualRect(model.index(1,0)).top()
    assert panel.list.visualRect(model.index(1,0)).right() < panel.list.viewport().width()


def test_tag_search_does_not_filter_media_and_reset_keeps_sort_and_view(panel):
    panel.set_view('grid')
    panel.change(search='山间',sort='added_desc',score=7,score_mode='gte',tags=('摄影','旅行'),tag_mode='or')
    changes = QSignalSpy(panel.filtersChanged)
    panel.popup.search.setText('摄影')
    assert tuple(panel.popup.tags.chips) == ('摄影',) and changes.count() == 0 and panel.filters.tags == ('摄影','旅行')
    panel.reset_filters()
    assert panel.filters == CatalogFilter(sort='added_desc') and panel.list.presentation == 'grid'


def test_hierarchy_paths_are_visible_in_filter_chips_and_summary_without_losing_typed_search(panel):
    panel.present_schema({'风景': {}, '山川': {'parent': '风景'}, '雪山': {'parent': '山川'}})
    panel.change(tags=('雪山',))
    assert set(panel.popup.tags.chips) == {'风景'}
    assert panel.popup.tags.chips['风景'].property('implicitSelected')
    assert '风景 › 山川 › 雪山' in ' '.join(panel.summary.chips)
    panel.popup.search.setText('风景')
    assert set(panel.popup.tags.chips) == {'风景', '山川', '雪山'}
    assert panel.popup.tags.chips['雪山'].text() == '风景 › 山川 › 雪山'
    panel.search.setText('尚未提交的文件名')
    panel.present_schema({'自然': {}, '山川': {'parent': '自然'}, '雪山': {'parent': '山川'}})
    assert panel.search.text() == '尚未提交的文件名'
    assert '自然 › 山川 › 雪山' in ' '.join(panel.summary.chips)


def test_filter_tag_body_selects_but_arrow_opens_below_its_row_without_filtering(panel):
    schema = {f'{n:02d}标签': {} for n in range(18)}
    schema['01子标签'] = {'parent': '01标签'}
    panel.present_schema(schema)
    panel.popup.show_for(panel.filter_button)
    QTest.qWait(40)
    choices = panel.popup.tags
    changes = QSignalSpy(panel.filtersChanged)
    origin = choices.chips['01标签'].geometry().topLeft()
    QTest.mouseClick(choices.chips['01标签'].arrow, Qt.LeftButton)
    QTest.qWait(40)
    parent, branch = choices.chips['01标签'], choices.panels['01标签']
    assert parent.geometry().topLeft() == origin and changes.count() == 0
    assert panel.filters.tags == () and '01子标签' in choices.chips
    siblings = [chip for chip in choices.chips.values() if chip.parentWidget() is parent.parentWidget()]
    assert branch.y() > max(chip.geometry().bottom() for chip in siblings if chip.y() == parent.y())
    assert min(chip.y() for chip in siblings if chip.y() > parent.y()) > branch.geometry().bottom()
    child = choices.chips['01子标签']
    assert child.mapTo(panel.popup.scroll.viewport(), child.rect().bottomLeft()).y() < panel.popup.scroll.viewport().height()
    QTest.mouseClick(parent, Qt.LeftButton)
    assert panel.filters.tags == ('01标签',) and choices.expanded == {'01标签'} and changes.count() == 1
    QTest.mouseClick(choices.chips['01标签'], Qt.LeftButton)
    assert panel.filters.tags == () and choices.expanded == {'01标签'} and changes.count() == 2
    QTest.mouseClick(choices.chips['01子标签'], Qt.LeftButton)
    assert panel.filters.tags == ('01子标签',) and choices.chips['01标签'].property('implicitSelected')
    QTest.mouseClick(choices.chips['01标签'].arrow, Qt.LeftButton)
    assert panel.filters.tags == ('01子标签',) and not choices.expanded and changes.count() == 3


def test_filter_nested_expansion_search_and_keyboard_preserve_conditions(panel):
    panel.present_schema({'风景': {}, '山川': {'parent': '风景'}, '雪山': {'parent': '山川'},
                          '摄影': {}, '设备': {'parent': '摄影'}})
    panel.change(tags=('雪山',), score=7, score_mode='gte', tag_mode='or', favorite='yes')
    before = panel.filters
    changes = QSignalSpy(panel.filtersChanged)
    panel.popup.show_for(panel.filter_button)
    choices = panel.popup.tags
    choices.chips['风景'].arrow.setFocus()
    QTest.keyClick(choices.chips['风景'].arrow, Qt.Key_Return)
    QTest.qWait(30)
    assert choices.chips['风景'].arrow.hasFocus()
    QTest.keyClick(choices.chips['山川'].arrow, Qt.Key_Space)
    choices.chips['摄影'].arrow.click()
    QTest.qWait(30)
    assert choices.panels['风景'].isAncestorOf(choices.panels['山川'])
    assert set(choices.expanded) == {'风景', '山川', '摄影'}
    assert choices.chips['雪山'].isChecked() and panel.filters == before and changes.count() == 0
    for width in (300, 380):
        panel.popup.resize(width, 600)
        QTest.qWait(30)
        for chip in choices.chips.values():
            assert chip.geometry().right() < chip.parentWidget().width()
    expanded = set(choices.expanded)
    panel.popup.search.setText('雪山')
    assert set(choices.chips) == {'雪山'} and not choices.panels
    assert choices.chips['雪山'].text() == '风景 › 山川 › 雪山'
    panel.popup.search.setText('风景')
    assert choices.chips['风景'].arrow is None
    panel.popup.search.clear()
    assert choices.expanded == expanded and '雪山' in choices.chips and '设备' in choices.chips
    assert panel.filters == before and changes.count() == 0
    panel.popup.hide()
    panel.popup.show_for(panel.filter_button)
    assert choices.expanded == expanded and panel.filters == before


def test_grid_hides_the_scrollbar_until_content_actually_overflows(panel):
    """An empty or short library must not show a scrollbar in grid view."""
    panel.set_view('grid')
    app = QApplication.instance()
    bar = panel.list.verticalScrollBar()

    def columns():
        width = panel.list.gridSize().width()
        return panel.list.viewport().width() // width if width > 0 else 0

    panel.list.model().sync([])
    QTest.qWait(60)
    assert not bar.isVisible(), 'an empty grid shows no scrollbar'
    assert columns() == 2

    panel.list.model().sync([dict(id=str(n), name=f'x{n}.png', kind='image',
                                  tag_names=(), score=None, star=0) for n in range(2)])
    QTest.qWait(60)
    assert not bar.isVisible(), 'a short grid shows no scrollbar'
    assert columns() == 2

    panel.list.model().sync([dict(id=str(n), name=f'x{n}.png', kind='image',
                                  tag_names=(), score=None, star=0) for n in range(60)])
    QTest.qWait(60)
    assert bar.isVisible(), 'overflowing content brings the scrollbar back'
    assert columns() == 2, 'the arriving scrollbar must not collapse the grid'


def test_rows_without_prepared_display_fields_still_paint(panel):
    """A row whose details lag must not abort painting and blank the list."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem
    model = panel.list.model()
    for mode in ('list', 'grid'):
        panel.set_view(mode)
        model.sync([dict(id='raw', name='未准备.png')])
        index = model.index(0, 0)
        assert index.isValid()
        image = QImage(320, 220, QImage.Format_ARGB32)
        painter = QPainter(image)
        try:
            for rect in (QRect(0, 0, 280, 86), QRect(0, 0, 160, 168)):
                option = QStyleOptionViewItem()
                option.rect = rect
                option.font = panel.font()
                panel.list.itemDelegate().paint(painter, option, index)
        finally:
            painter.end()
    assert QApplication.instance() is not None


@pytest.mark.parametrize('tag', ['风景', '摄影', 'A'])
@pytest.mark.parametrize('mode', ['list', 'grid'])
def test_short_single_tag_shows_its_name_instead_of_overflow(panel, monkeypatch, tag, mode):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem
    import catalog_delegate
    captions = []
    draw = catalog_delegate.paint_capsule
    def capture(painter, rect, text, colors):
        captions.append(text)
        draw(painter, rect, text, colors)
    monkeypatch.setattr(catalog_delegate, 'paint_capsule', capture)
    panel.set_view(mode)
    panel.list.model().sync([dict(id='short', name='电影.png', kind='image', star=0,
        score=None, tag_labels=(tag,), tag_names=(tag,))])
    rect = QRect(0, 0, 292, 96) if mode == 'list' else QRect(0, 0, 140, 148)
    image = QImage(rect.size(), QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        option = QStyleOptionViewItem()
        option.rect, option.font = rect, panel.font()
        panel.list.itemDelegate().paint(painter, option, panel.list.model().index(0, 0))
    finally:
        painter.end()
    assert captions == [tag]


def test_narrow_card_keeps_a_hierarchy_label_before_the_overflow_count(panel, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem
    import catalog_delegate
    labels = []
    draw = catalog_delegate.paint_capsule
    def capture(painter, rect, text, colors):
        labels.append((text, rect.width()))
        draw(painter, rect, text, colors)
    monkeypatch.setattr(catalog_delegate, 'paint_capsule', capture)
    panel.list.model().sync([dict(id='hierarchy', name='电影.png', kind='image', star=0,
        score=None, tag_labels=('自然风光 › 山川', '摄影'), tag_names=('山川', '摄影'))])
    image = QImage(292, 96, QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        option = QStyleOptionViewItem()
        option.rect, option.font = QRect(0, 0, 292, 96), panel.font()
        panel.list.itemDelegate().paint(painter, option, panel.list.model().index(0, 0))
    finally:
        painter.end()
    assert labels[0][0] == '自然风光 › 山川' and labels[0][1] >= 48
    assert labels[-1][0] in ('+1', '摄影')


def test_score_input_shows_and_edits_the_current_threshold():
    """The score field must show its digits and turn typing into a filter value."""
    from PySide6.QtGui import QColor, QPalette, QIntValidator
    from PySide6.QtWidgets import QWidget
    from catalog_filter_popup import CatalogFilterPopup
    from theme import theme_tokens
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.theme = 'dark'
    popup = CatalogFilterPopup(host)
    popup.apply_colors(theme_tokens(host))
    popup.present(CatalogFilter(score=7), {})
    popup.resize(360, 560)
    popup.show()
    app.processEvents()
    try:
        field = popup.number
        assert field.text() == '7'
        assert field.width() >= 20, 'the score field must give its digits room'
        assert isinstance(field.validator(), QIntValidator)

        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        def relative(color):
            return (0.2126 * channel(color.red()) + 0.7152 * channel(color.green())
                    + 0.0722 * channel(color.blue()))

        text = field.palette().color(QPalette.WindowText)
        surface = QColor(theme_tokens(host)['surface_plain'])
        lighter, darker = sorted((relative(text), relative(surface)), reverse=True)
        assert (lighter + 0.05) / (darker + 0.05) >= 4.5, 'score digits must stay readable'

        changes = QSignalSpy(popup.changed)
        field.setText('9')
        assert changes.count() == 1 and changes.at(0)[0] == dict(score=9)
        field.setText('')
        assert changes.count() == 2 and changes.at(1)[0] == dict(score='all')
    finally:
        popup.hide()
    assert app is not None
