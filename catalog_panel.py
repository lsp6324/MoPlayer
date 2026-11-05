"""Library toolbar, filter summaries and stable list/grid presentation."""
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QSize, QPersistentModelIndex, QModelIndex, QEvent
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                               QComboBox, QListView, QAbstractItemView)
from application.catalog import CatalogFilter
from catalog_filter_popup import CatalogFilterPopup, TagChoices
from ui import label, button, icon
from theme import theme_tokens


class CatalogListView(QListView):
    """One model and selection for both layouts; changing layout never plays."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.presentation = 'list'
        self.setObjectName('sidebarList')
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.viewport().installEventFilter(self)

    def set_presentation(self, mode):
        if mode not in ('list', 'grid'):
            raise ValueError(mode)
        if mode == self.presentation:
            return False
        current = QPersistentModelIndex(self.currentIndex())
        selected = self.selectionModel() is not None and self.selectionModel().hasSelection()
        anchor = QPersistentModelIndex(self.indexAt(QPoint(1, 1)))
        self.presentation = mode
        # The bar appears only when the content actually overflows. Keeping it
        # hidden on an empty or short library matters more than freezing the
        # viewport width: update_grid() re-runs on every viewport resize, so a
        # bar that arrives later still leaves the column count at two.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setUniformItemSizes(mode == 'list')
        self.setViewMode(QListView.IconMode if mode == 'grid' else QListView.ListMode)
        self.setFlow(QListView.LeftToRight if mode == 'grid' else QListView.TopToBottom)
        self.setWrapping(mode == 'grid')
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setSpacing(0)
        self.update_grid()
        self.doItemsLayout()
        if current.isValid():
            self.setCurrentIndex(QModelIndex(current))
            if not selected:
                self.clearSelection()
        if anchor.isValid():
            self.scrollTo(QModelIndex(anchor), QAbstractItemView.PositionAtTop)
        self.viewport().update()
        return True

    def update_grid(self):
        if self.presentation == 'grid':
            # Reserve the bar's width even while it is hidden. A bar that shows
            # up right after layout would otherwise shrink the viewport below
            # the width this grid was sized for, pushing the second column onto
            # a row of its own; with the reservation two columns always fit.
            bar = self.verticalScrollBar()
            gutter = bar.sizeHint().width() if bar is not None else 0
            available = max(1, self.viewport().width() - gutter - 1)
            columns = max(1, available // 136)
            width = available // columns
            size = QSize(width, (width - 16) * 9 // 16 + 78)
        else:
            size = QSize()
        if size != self.gridSize():
            self.setGridSize(size)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_grid()

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Resize:
            self.update_grid()
        return super().eventFilter(watched, event)


class CatalogPanel(QWidget):
    filtersChanged = Signal(object)
    viewChanged = Signal(str)
    openRequested = Signal(str)
    retryRequested = Signal()

    def __init__(self, parent, *, theme_owner):
        super().__init__(parent)
        self.theme_owner = theme_owner
        self.filters, self.schema = CatalogFilter(), {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        self.search = QLineEdit()
        self.search.setAccessibleName('搜索库中的文件名')
        self.search.setPlaceholderText('搜索文件名')
        self.search.setClearButtonEnabled(True)
        toolbar.addWidget(self.search, 1)
        self.filter_button = button('筛选', self.toggle_filters, 'filters', 'rateOption')
        self.filter_button.setCheckable(True)
        self.filter_button.setStyleSheet('padding:5px 8px;')
        self.filter_button.setAccessibleName('打开库筛选浮窗')
        toolbar.addWidget(self.filter_button)
        layout.addLayout(toolbar)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(200)
        self.debounce.timeout.connect(lambda: self.change(search=self.search.text()))
        self.search.textChanged.connect(lambda: self.debounce.start())
        result_row = QHBoxLayout()
        result_row.setSpacing(4)
        self.result = label('尚未载入', 'muted')
        result_row.addWidget(self.result, 1)
        self.sort = QComboBox()
        self.sort.setAccessibleName('库排序')
        for text, value in [('名称', 'name'), ('评分从高到低', 'score'), ('最近播放', 'played'),
                            ('入库日期：新到旧', 'added_desc'), ('入库日期：旧到新', 'added_asc')]:
            self.sort.addItem(text, value)
        self.sort.setMaximumWidth(144)
        self.sort.currentIndexChanged.connect(lambda: self.change(sort=self.sort.currentData()))
        result_row.addWidget(self.sort)
        self.view_buttons = {}
        for mode, text in [('list', '列表视图'), ('grid', '网格视图')]:
            control = button('', lambda checked=False, mode=mode: self.set_view(mode), mode, 'rateOption')
            control.setCheckable(True)
            control.setFixedSize(27, 29)
            control.setStyleSheet('padding:2px;')
            control.setAccessibleName(text)
            control.setToolTip(text)
            self.view_buttons[mode] = control
            result_row.addWidget(control)
        layout.addLayout(result_row)
        self.summary = TagChoices()
        self.summary.setAccessibleName('已选库筛选条件，点击移除')
        self.summary.toggled.connect(self.remove_summary)
        self._summaries = {}
        layout.addWidget(self.summary)
        self.message = label('', 'muted')
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.message)
        self.retry = button('重新载入', self.retryRequested.emit, role='quiet')
        self.retry.hide()
        layout.addWidget(self.retry, alignment=Qt.AlignHCenter)
        self.reset = button('清除筛选', self.reset_filters, role='quiet')
        self.reset.hide()
        layout.addWidget(self.reset, alignment=Qt.AlignHCenter)
        self.list = CatalogListView(self)
        self.list.doubleClicked.connect(lambda index: self.openRequested.emit(index.data(Qt.UserRole)))
        layout.addWidget(self.list, 1)
        self.popup = CatalogFilterPopup(self)
        self.popup.changed.connect(lambda values: self.change(**values))
        self.popup.resetRequested.connect(self.reset_filters)
        self.popup.closed.connect(lambda: self.filter_button.setChecked(False))
        self.present_filter(self.filters)
        self.set_view('list', notify=False)
        self.apply_colors()

    def set_view(self, mode, *, notify=True):
        changed = self.list.set_presentation(mode)
        for key, control in self.view_buttons.items():
            control.setChecked(key == mode)
        if changed and notify:
            self.viewChanged.emit(mode)

    def change(self, **values):
        self.debounce.stop()
        values.setdefault('search', self.search.text())
        filters = self.filters.updated(**values)
        changed = filters != self.filters
        self.present_filter(filters)
        if changed:
            self.filtersChanged.emit(filters)

    def reset_filters(self):
        self.search.clear()
        self.debounce.stop()
        values = CatalogFilter(sort=self.filters.sort).to_dict()
        values['tags'] = ()
        self.change(**values)

    def present_filter(self, filters):
        self.filters = filters
        self.search.blockSignals(True)
        self.search.setText(filters.search)
        self.search.blockSignals(False)
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(filters.sort))
        self.sort.blockSignals(False)
        self.popup.present(filters, self.schema)
        self._summaries = {}
        if filters.score != 'all':
            text = '未评分' if filters.score == 'none' else f"{'≥' if filters.score_mode == 'gte' else '='} {filters.score} 分"
            self._summaries[text + ' ×'] = 'score'
        if filters.favorite != 'all':
            self._summaries[('已收藏' if filters.favorite == 'yes' else '未收藏') + ' ×'] = 'favorite'
        if filters.kind != 'all':
            self._summaries[('视频' if filters.kind == 'video' else '图片') + ' ×'] = 'kind'
        selected = (*filters.tags, *(('无标签',) if filters.untagged else ()))
        if selected:
            caption = (' 且 ' if filters.tag_mode == 'and' else ' 或 ').join(selected)
            self._summaries['标签：' + caption + ' ×'] = 'tags'
        self.summary.present(tuple(self._summaries), tuple(self._summaries))
        count = len(self._summaries)
        self.filter_button.setText(f'筛选 {count}' if count else '筛选')
        self.popup.reset.setEnabled(bool(count or filters.search))

    def remove_summary(self, caption):
        field = self._summaries.get(caption)
        if field == 'tags':
            self.change(tags=(), untagged=False)
        elif field is not None:
            self.change(**{field: 'all'})

    def present_schema(self, schema):
        if schema != self.schema:
            self.schema = schema
            self.popup.present(self.filters, schema)

    def toggle_filters(self):
        if self.popup.isVisible():
            self.popup.hide()
        else:
            self.popup.apply_colors(theme_tokens(self.theme_owner))
            self.popup.show_for(self.filter_button)
            self.filter_button.setChecked(True)

    def present_status(self, count, total, pending, error):
        self.result.setText('查询中…' if pending else f'{count} / {total} 项')
        self.popup.result.setText('查询中…' if pending else f'{count} 项符合条件')
        self.message.setText(error or ('还没有入库内容\n在文件页添加标签、评分或收藏即可入库' if not total else '没有符合条件的内容\n试试减少筛选条件'))
        self.message.setVisible(not count and not pending or bool(error))
        self.retry.setVisible(bool(error) and not pending)
        self.reset.setVisible(bool(not count and total and not pending and (self._summaries or self.filters.search)))
        self.list.setEnabled(not pending)

    def apply_colors(self):
        colors = theme_tokens(self.theme_owner)
        self.popup.apply_colors(colors)
        self.summary.apply_colors(colors)
        for mode, control in self.view_buttons.items():
            control.setIcon(icon(mode, colors['accent'] if self.list.presentation == mode else colors['text_mid']))

    def shutdown(self):
        self.debounce.stop()
        self.popup.hide()

    def hideEvent(self, event):
        self.popup.hide()
        super().hideEvent(event)
