"""Responsive directory breadcrumbs. Only emits navigation intentions."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QMenu, QSizePolicy,
                               QStyle, QStyleOptionButton, QStylePainter)

from ui import button, label


class _PathButton(QPushButton):
    def __init__(self, name, path, current, parent, *, root=False):
        super().__init__(name, parent)
        self.setProperty('role', 'breadcrumb')
        self.setProperty('current', current)
        self.setProperty('root', root)
        self.setToolTip(path)
        self.setAccessibleName(name)
        self.elide_mode = Qt.ElideMiddle if root else Qt.ElideRight
        self.setCursor(Qt.PointingHandCursor)
        anchor_width = self.fontMetrics().horizontalAdvance(Path(path).anchor) + 16 if root else 28
        self.setMinimumWidth(max(28, min(96, anchor_width)))
        self.setMaximumWidth(160)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        available = self.style().subElementRect(QStyle.SE_PushButtonContents, option, self).width()
        option.text = self.fontMetrics().elidedText(self.text(), self.elide_mode, max(0, available))
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)


class FolderNavigation(QWidget):
    requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments = ()
        self._plan = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.up = button('', self._up, 'back', 'nav')
        self.up.setFixedSize(32, 32)
        self.up.setAccessibleName('返回上一级')
        self.up.setToolTip('返回上一级')
        self.up.setEnabled(False)
        row.addWidget(self.up)
        self.path = QHBoxLayout()
        self.path.setContentsMargins(0, 0, 0, 0)
        self.path.setSpacing(2)
        row.addLayout(self.path, 1)

    def set_path(self, folder):
        paths = []
        current = Path(folder)
        while True:
            paths.append(current)
            if current.parent == current:
                break
            current = current.parent
        self._segments = tuple((path.name or str(path), str(path)) for path in reversed(paths))
        self.setToolTip(str(folder))
        self.up.setEnabled(len(paths) > 1)
        self.up.setToolTip('返回上一级' if len(paths) > 1 else '已到磁盘根目录')
        self._plan = None
        self._reflow()

    def _up(self):
        if len(self._segments) > 1:
            self.requested.emit(self._segments[-2][1])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        if not self._segments:
            return
        available = max(0, self.width() - 36)
        widths = [min(160, self.fontMetrics().horizontalAdvance(name) + 20) for name, _ in self._segments]
        count = len(widths)
        if sum(widths) + 14 * (count - 1) <= available:
            plan = tuple(range(count))
        elif count <= 2:
            plan = tuple(range(count))
        elif widths[0] + widths[-2] + widths[-1] + 76 <= available:
            plan = (0, None, count - 2, count - 1)
        else:
            plan = (0, None, count - 1)
        if plan == self._plan:
            return
        self._plan = plan
        while self.path.count():
            item = self.path.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for number, index in enumerate(plan):
            if number:
                separator = label('›', 'muted')
                separator.setFixedWidth(10)
                self.path.addWidget(separator)
            if index is None:
                control = button('…', lambda: None, role='breadcrumb')
                control.setFixedWidth(28)
                control.setAccessibleName('展开完整路径')
                control.setToolTip('展开完整路径')
                menu = QMenu(control)
                for name, path in self._segments[:-1]:
                    action = menu.addAction(name)
                    action.setToolTip(path)
                    action.triggered.connect(lambda checked=False, target=path: self.requested.emit(target))
                control.setMenu(menu)
            else:
                name, path = self._segments[index]
                control = _PathButton(name, path, index == count - 1, self, root=index == 0)
                control.clicked.connect(lambda checked=False, target=path: self.requested.emit(target))
            self.path.addWidget(control)
        self.path.addStretch()
