"""One playback row with a centered classification group."""
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QLayout


class PlaybackControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.left = QWidget(self)
        self.center = QWidget(self)
        self.right = QWidget(self)
        self.left_layout = QHBoxLayout(self.left)
        self.center_layout = QHBoxLayout(self.center)
        self.right_layout = QHBoxLayout(self.right)
        for layout in (self.left_layout, self.center_layout, self.right_layout):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
        self.left_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.center_layout.setSpacing(4)
        self.center_layout.setAlignment(Qt.AlignCenter)
        self.right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self.grid.addWidget(self.left, 0, 0)
        self.grid.addWidget(self.center, 0, 1)
        self.grid.addWidget(self.right, 0, 2)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(2, 1)
        self.actions = []
        self._compact = None

    def minimumSizeHint(self):
        return QSize(500, 44)

    def add_action(self, control):
        control.setProperty('fullText', control.text())
        control.setAccessibleName(control.text())
        control.setFixedHeight(34)
        self.actions.append(control)
        self.center_layout.addWidget(control)

    def adapt(self):
        if not self.actions:
            return
        full_width = sum(button.fontMetrics().horizontalAdvance(button.property('fullText'))
                         + button.iconSize().width() + 32 for button in self.actions)
        full_width += self.center_layout.spacing() * (len(self.actions) - 1)
        side_width = max(self.left.sizeHint().width(), self.right.sizeHint().width())
        compact = self.width() < side_width * 2 + full_width + self.grid.horizontalSpacing() * 2
        if compact == self._compact:
            return
        self._compact = compact
        for control in self.actions:
            control.setText('' if compact else control.property('fullText'))
            if compact:
                control.setFixedWidth(34)
            else:
                control.setMinimumWidth(0)
                control.setMaximumWidth(16777215)
        self.grid.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.LayoutRequest, QEvent.Show) and hasattr(self, 'actions'):
            self.adapt()
        return result
