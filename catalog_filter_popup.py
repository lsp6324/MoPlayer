"""Native library filter popup. Inputs emit values, never query storage."""
from PySide6.QtCore import Qt, Signal, QPoint, QSize, QEvent, QTimer
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout,
                               QScrollArea, QLineEdit, QSizePolicy, QPushButton, QToolButton)
from application.catalog import CatalogFilter, natural_name
from application.tag_labels import tag_label, tag_path
from heart_rating import HeartRating
from tag_flow import FlowLayout
from ui import label, button, icon


class TagChoices(QWidget):
    toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chips = {}
        self.labels = {}
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def present(self, names, selected, labels=None):
        self.labels = labels or {}
        if tuple(self.chips) != tuple(names):
            for chip in self.chips.values():
                chip.hide()
                chip.deleteLater()
            self.chips = {}
            for name in names:
                chip = button(name, lambda checked=False, name=name: self.toggled.emit(name))
                chip.setParent(self)
                chip.setCheckable(True)
                chip.setFixedHeight(28)
                chip.setToolTip(name)
                self.chips[name] = chip
        for name, chip in self.chips.items():
            chip.ensurePolished()
            chip.setChecked(name in selected)
        self.arrange()

    def arrange(self):
        width, x, y = max(1, self.width()), 0, 0
        for name, chip in self.chips.items():
            text = self.labels.get(name, name)
            size = min(width, 280, max(48, chip.fontMetrics().horizontalAdvance(text) + 28))
            if x and x + size > width:
                x, y = 0, y + 34
            chip.setGeometry(x, y, size, 28)
            chip.setText(chip.fontMetrics().elidedText(text, Qt.ElideMiddle, size - 24))
            chip.show()
            x += size + 6
        self.setFixedHeight(y + 28 if self.chips else 0)

    def apply_colors(self, colors):
        self.setStyleSheet('QPushButton { border:1px solid '+colors['line']+'; border-radius:14px; padding:0 10px; background:transparent; }'
                          'QPushButton:hover { background:'+colors['hover']+'; }'
                          'QPushButton:checked { color:'+colors['accent']+'; background:'+colors['accent_soft']+'; border-color:'+colors['accent_line']+'; }')
        for chip in self.chips.values():
            chip.ensurePolished()
        self.arrange()

    def sizeHint(self):
        return QSize(280, self.height())

    def minimumSizeHint(self):
        return QSize(0, self.height())

    def resizeEvent(self, event):
        self.arrange()
        super().resizeEvent(event)


class FilterTagChip(QPushButton):
    """Selecting a condition and opening its children are separate actions."""
    def __init__(self, choices, name, *, searchable=False):
        super().__init__()
        self.name = name
        self.label = tag_label(name, choices.schema) if searchable else name
        self.arrow = None
        self.setObjectName('filterTagChip')
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda checked=False: choices.toggled.emit(name))
        if name in choices.parents and not searchable:
            self.arrow = QToolButton(self)
            self.arrow.setObjectName('filterTagArrow')
            self.arrow.setFocusPolicy(Qt.StrongFocus)
            self.arrow.setArrowType(Qt.DownArrow if name in choices.expanded else Qt.RightArrow)
            self.arrow.setAccessibleName(('收起' if name in choices.expanded else '展开') + name + '的子标签')
            self.arrow.setToolTip(self.arrow.accessibleName())
            self.arrow.clicked.connect(lambda checked=False: choices.toggle_expanded(name))
            self.arrow.installEventFilter(self)
        self.setProperty('hasArrow', self.arrow is not None)
        self.setText(self.label)

    def sizeHint(self):
        return QSize(min(280, self.fontMetrics().horizontalAdvance(self.label) + 28 + (26 if self.arrow else 0)), 28)

    def minimumSizeHint(self):
        return QSize(0, 28)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.arrow is not None:
            self.arrow.setGeometry(max(0, self.width() - 27), 1, 26, 26)
        available = max(0, self.width() - 24 - (26 if self.arrow else 0))
        self.setText(self.fontMetrics().elidedText(self.label, Qt.ElideMiddle, available))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.arrow and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not event.isAutoRepeat():
                self.arrow.click()
            return True
        return super().eventFilter(watched, event)


class FilterTagChoices(QWidget):
    """Filter-only hierarchy; expansion never emits a filter change."""
    toggled = Signal(str)
    branchOpened = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.schema, self.chips, self.panels = {}, {}, {}
        self.parents, self.expanded = set(), set()
        self.selected, self.query, self.signature = (), '', None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.content = None

    def present(self, schema, selected, query=''):
        self.schema = {name: dict(row) for name, row in schema.items()}
        for name in selected:
            self.schema.setdefault(name, {})
        self.parents = {name for name, row in self.schema.items() if row.get('is_parent')}
        self.parents.update(row['parent'] for row in self.schema.values() if row.get('parent') in self.schema)
        self.expanded.intersection_update(self.parents)
        self.selected, self.query = tuple(selected), query.strip().casefold()
        signature = (tuple((name, row.get('parent'), name in self.parents) for name, row in self.schema.items()), self.query)
        if signature != self.signature:
            self.signature = signature
            self.rebuild()
        else:
            self.update_selection()

    def rebuild(self):
        if self.content is not None:
            self.outer.removeWidget(self.content)
            self.content.hide()
            self.content.deleteLater()
        self.content = QWidget()
        self.flow = FlowLayout(self.content)
        self.flow.setSpacing(6)
        self.chips, self.panels = {}, {}

        def populate(flow, names, ancestors=()):
            for name in sorted(names, key=natural_name):
                if self.query and self.query not in tag_label(name, self.schema).casefold():
                    continue
                chip = FilterTagChip(self, name, searchable=bool(self.query))
                flow.addWidget(chip)
                self.chips[name] = chip
                if self.query or name not in self.expanded or name in ancestors:
                    continue
                panel = QFrame()
                panel.setObjectName('filterTagBranch')
                layout = QVBoxLayout(panel)
                layout.setContentsMargins(10, 6, 6, 6)
                heading = label(tag_label(name, self.schema), 'muted')
                heading.setWordWrap(True)
                layout.addWidget(heading)
                area = QWidget()
                child_flow = FlowLayout(area)
                child_flow.setSpacing(6)
                children = [child for child, row in self.schema.items() if row.get('parent') == name]
                populate(child_flow, children, (*ancestors, name))
                layout.addWidget(area)
                if not children:
                    layout.addWidget(label('暂无子标签', 'muted'))
                flow.add_branch(chip, panel)
                self.panels[name] = panel

        roots = [name for name, row in self.schema.items() if self.query or row.get('parent') not in self.schema]
        populate(self.flow, roots)
        self.outer.addWidget(self.content)
        self.content.show()
        self.update_selection()
        self.arrange()

    def update_selection(self):
        ancestors = {ancestor for name in self.selected for ancestor in tag_path(name, self.schema)[:-1]}
        for name, chip in self.chips.items():
            chip.setChecked(name in self.selected)
            chip.setProperty('implicitSelected', name in ancestors and name not in self.selected)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            state = '本级筛选已选' if name in self.selected else '本级筛选未选；包含已选子标签' if name in ancestors else '未选'
            chip.setToolTip(tag_label(name, self.schema) + '\n' + state + ('\n选择本级可匹配本级及全部后代' if name in self.parents else '') + '\n点击选择／取消；箭头只展开')

    def toggle_expanded(self, name):
        arrow = self.chips[name].arrow
        focused = arrow is not None and arrow.hasFocus()
        self.expanded.symmetric_difference_update({name})
        self.rebuild()
        if focused and name in self.chips and self.chips[name].arrow is not None:
            self.chips[name].arrow.setFocus(Qt.OtherFocusReason)
        if name in self.expanded:
            self.branchOpened.emit(name)

    def arrange(self):
        if self.content is not None:
            self.setFixedHeight(self.flow.heightForWidth(max(1, self.width())))

    def resizeEvent(self, event):
        self.arrange()
        super().resizeEvent(event)

    def apply_colors(self, colors):
        self.setStyleSheet(
            'QPushButton#filterTagChip { color:'+colors['text']+'; border:1px solid '+colors['line']+'; border-radius:14px; padding:0; background:transparent; }'
            'QPushButton#filterTagChip[hasArrow="true"] { padding-right:26px; }'
            'QPushButton#filterTagChip:hover { background:'+colors['hover']+'; }'
            'QPushButton#filterTagChip:checked { color:'+colors['accent']+'; background:'+colors['accent_soft']+'; border-color:'+colors['accent_line']+'; }'
            'QPushButton#filterTagChip[implicitSelected="true"]:!checked { border-style:dashed; border-color:'+colors['accent_line']+'; }'
            'QToolButton#filterTagArrow { color:'+colors['text']+'; border:0; border-left:1px solid '+colors['line']+'; border-radius:0; padding:0; background:transparent; }'
            'QFrame#filterTagBranch { border:1px solid '+colors['line']+'; border-radius:7px; background:transparent; }')
        self.arrange()


class CatalogFilterPopup(QFrame):
    changed = Signal(object)
    resetRequested = Signal()
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup)
        self.setObjectName('catalogFilterPopup')
        self.filters, self.schema = CatalogFilter(), {}
        self.setAccessibleName('筛选库')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(label('筛选库', 'sectionTitle'))
        heading.addStretch()
        self.reset = button('重置', self.resetRequested.emit, role='quiet')
        self.reset.setStyleSheet('padding:3px 6px;')
        heading.addWidget(self.reset)
        close = button('', self.hide, 'close', 'nav')
        close.setFixedSize(28, 28)
        close.setToolTip('关闭筛选')
        close.setAccessibleName('关闭筛选')
        heading.addWidget(close)
        layout.addLayout(heading)
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 4, 0)
        self.body_layout.setSpacing(9)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.body_layout.addWidget(label('收藏', 'muted'))
        self.favorite = self.options(self.body_layout, [('不限', 'all'), ('已收藏', 'yes'), ('未收藏', 'no')], 'favorite')
        for value in ('yes', 'no'):
            self.favorite[value].setProperty('iconName', 'starFilled' if value == 'yes' else 'star')
        rating_heading = QHBoxLayout()
        rating_heading.addWidget(label('评分', 'muted'))
        rating_heading.addStretch()
        self.score_mode = self.options(rating_heading, [('精确', 'exact'), ('及以上', 'gte')], 'score_mode')
        self.body_layout.addLayout(rating_heading)
        rating = QHBoxLayout()
        self.hearts = HeartRating(self)
        self.hearts.chosen.connect(lambda value: self.changed.emit(dict(score=value)))
        rating.addWidget(self.hearts)
        rating.addStretch()
        self.number = QLineEdit()
        self.number.setObjectName('scoreField')
        self.number.setPlaceholderText('—')
        self.number.setFixedWidth(52)
        self.number.setMaxLength(2)
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setValidator(QIntValidator(0, 10, self))
        self.number.setToolTip('0～10 分，可直接输入；留空表示不限')
        self.number.setAccessibleName('评分筛选分数')
        self.number.textChanged.connect(self.type_score)
        rating.addWidget(self.number)
        rating.addWidget(label('分', 'muted'))
        self.body_layout.addLayout(rating)
        self.score = self.options(self.body_layout, [('不限', 'all'), ('未评分', 'none'), ('0 分', 0)], 'score')
        self.rating_text = label('', 'muted')
        self.body_layout.addWidget(self.rating_text)
        self.body_layout.addWidget(label('类型', 'muted'))
        self.kind = self.options(self.body_layout, [('全部', 'all'), ('视频', 'video'), ('图片', 'image')], 'kind')
        tags_heading = QHBoxLayout()
        self.tag_summary = label('标签', 'muted')
        tags_heading.addWidget(self.tag_summary)
        tags_heading.addStretch()
        self.tag_mode = self.options(tags_heading, [('全部 AND', 'and'), ('任一 OR', 'or')], 'tag_mode')
        self.body_layout.addLayout(tags_heading)
        tag_search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索标签')
        self.search.setAccessibleName('搜索筛选标签')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_tags)
        tag_search_row.addWidget(self.search, 1)
        self.no_tags = button('无标签', lambda checked=False: self.changed.emit(dict(untagged=checked)), role='rateOption')
        self.no_tags.setCheckable(True)
        self.no_tags.setToolTip('匹配没有设置任何标签的媒体；与所选标签使用同一 AND / OR 规则')
        self.no_tags.setStyleSheet('padding:3px 7px;')
        tag_search_row.addWidget(self.no_tags)
        self.body_layout.addLayout(tag_search_row)
        self.tags = FilterTagChoices()
        self.tags.toggled.connect(self.toggle_tag)
        self.tags.branchOpened.connect(self.reveal_tag_branch)
        self.body_layout.addWidget(self.tags)
        self.tag_description = label('', 'muted')
        self.tag_description.setWordWrap(True)
        self.body_layout.addWidget(self.tag_description)
        self.body_layout.addStretch()
        footer = QHBoxLayout()
        self.result = label('', 'muted')
        footer.addWidget(self.result)
        footer.addWidget(label('即时生效', 'muted'))
        footer.addStretch()
        done = button('完成', self.hide, role='primary')
        footer.addWidget(done)
        layout.addLayout(footer)

    def options(self, parent_layout, choices, field):
        row, controls = QHBoxLayout(), {}
        row.setSpacing(3)
        for text, value in choices:
            control = button(text, lambda checked=False, value=value: self.changed.emit({field: value}), role='rateOption')
            control.setCheckable(True)
            control.setFixedHeight(28)
            control.setStyleSheet('padding:2px 7px;')
            row.addWidget(control)
            controls[value] = control
        row.addStretch()
        parent_layout.addLayout(row)
        return controls

    def present(self, filters, schema):
        self.filters, self.schema = filters, schema
        for field in ('favorite', 'score', 'score_mode', 'kind', 'tag_mode'):
            for value, control in getattr(self, field).items():
                control.setChecked(value == getattr(filters, field))
        for control in self.score_mode.values():
            control.setEnabled(filters.score != 'none')
        self.hearts.set_score(filters.score if type(filters.score) is int else None)
        self.number.blockSignals(True)
        self.number.setText(str(filters.score) if type(filters.score) is int else '')
        self.number.blockSignals(False)
        text = '不限评分' if filters.score == 'all' else '仅未评分' if filters.score == 'none' else f'{filters.score} 分' + ('及以上' if filters.score_mode == 'gte' else '，精确匹配')
        self.rating_text.setText(text)
        self.no_tags.setChecked(filters.untagged)
        count = len(filters.tags) + int(filters.untagged)
        self.tag_summary.setText(f'标签 · 已选 {count}' if count else '标签')
        selected = (*(tag_label(name, schema) for name in filters.tags), *(('无标签',) if filters.untagged else ()))
        self.tag_description.setText(('同时包含：' if filters.tag_mode == 'and' else '包含任意一个：') + (' 且 ' if filters.tag_mode == 'and' else ' 或 ').join(selected) if selected else '未选标签时，不限制标签')
        self.refresh_tags()

    def type_score(self, text):
        """An empty field means no score condition; digits filter that many points."""
        text = text.strip()
        if not text:
            self.changed.emit(dict(score='all'))
        elif text.isdigit():
            self.changed.emit(dict(score=int(text)))

    def toggle_tag(self, name):
        tags = list(self.filters.tags)
        tags.remove(name) if name in tags else tags.append(name)
        self.changed.emit(dict(tags=tuple(tags)))

    def refresh_tags(self):
        self.tags.present(self.schema, self.filters.tags, self.search.text())

    def reveal_tag_branch(self, name):
        def reveal():
            panel = self.tags.panels.get(name)
            if not self.isVisible() or panel is None:
                return
            children = [chip for chip in self.tags.chips.values() if chip.parentWidget().parentWidget() is panel]
            self.scroll.ensureWidgetVisible(children[0] if children else panel, 0, 12)
        QTimer.singleShot(0, self, reveal)

    def show_for(self, anchor):
        available = anchor.screen().availableGeometry()
        self.resize(min(380, available.width() - 24), min(620, available.height() - 24))
        origin = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        self.move(max(available.left() + 8, min(origin.x(), available.right() - self.width() - 8)),
                  max(available.top() + 8, min(origin.y(), available.bottom() - self.height() - 8)))
        self.show()
        self.setFocus()

    def apply_colors(self, colors):
        self.setStyleSheet(
            'QFrame#catalogFilterPopup { background:'+colors['surface_plain']+'; border:1px solid '+colors['line']+'; border-radius:10px; }'
            'QFrame#catalogFilterPopup QLineEdit#scoreField { background:'+colors['surface_plain']+'; color:'+colors['text']+';'
            ' border:1px solid '+colors['line']+'; border-radius:6px; padding:2px 4px; }')
        self.hearts.fill_color, self.hearts.outline_color = QColor(colors['accent']), QColor(colors['line_strong'])
        self.hearts.update()
        self.tags.apply_colors(colors)
        self.favorite['yes'].setIcon(icon('starFilled', '#d39a2d'))
        self.favorite['no'].setIcon(icon('star', colors['text_mid']))

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)
