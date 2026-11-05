"""Native library filter popup. Inputs emit values, never query storage."""
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout,
                               QScrollArea, QLineEdit, QSizePolicy)
from application.catalog import CatalogFilter, natural_name
from heart_rating import HeartRating
from ui import label, button, icon


class TagChoices(QWidget):
    toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chips = {}
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def present(self, names, selected):
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
            size = min(width, 190, max(48, chip.fontMetrics().horizontalAdvance(name) + 28))
            if x and x + size > width:
                x, y = 0, y + 34
            chip.setGeometry(x, y, size, 28)
            chip.setText(chip.fontMetrics().elidedText(name, Qt.ElideRight, size - 24))
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
        scroll = QScrollArea()
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
        self.tags = TagChoices()
        self.tags.toggled.connect(self.toggle_tag)
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
        selected = (*filters.tags, *(('无标签',) if filters.untagged else ()))
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
        search = self.search.text().casefold()
        names = sorted(set(self.schema) | set(self.filters.tags), key=natural_name)
        self.tags.present([name for name in names if search in name.casefold()], self.filters.tags)
        for name, chip in self.tags.chips.items():
            chain, seen, parent = [name], {name}, self.schema.get(name, {}).get('parent')
            while parent and parent not in seen:
                chain.insert(0, parent)
                seen.add(parent)
                parent = self.schema.get(parent, {}).get('parent')
            chip.setToolTip(' / '.join(chain) + ('\n包含子标签' if self.schema.get(name, {}).get('is_parent') else ''))

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
