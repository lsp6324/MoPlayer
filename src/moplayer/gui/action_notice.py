"""Passive two-second receipts anchored to the playback area's upper right."""
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from moplayer.gui.floating_surface import FloatingSurface, player_is_active, raise_surface


class ActionNotice(FloatingSurface):
    DURATION_MS = 2000

    def __init__(self, surface, title_obstacle):
        super().__init__(surface, radius=12, background=QColor(26, 30, 38, 238),
                         border=QColor(255, 255, 255, 35))
        self.surface, self.title_obstacle = surface, title_obstacle
        self._title = self._detail = ''
        self.setObjectName('actionNotice')
        self.setWindowFlag(Qt.WindowTransparentForInput)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet('''
            QFrame#actionNotice { background:transparent; border:none; }
            QLabel { background:transparent; border:none; font-family:"Segoe UI"; }
            QLabel#receiptTitle { color:#f2f4f8; font-size:14px; font-weight:600; }
            QLabel#receiptDetail { color:#c4cee0; font-size:12px; }
        ''')
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 18, 12)
        row.setSpacing(12)
        self.checkmark = QLabel('✓')
        self.checkmark.setFixedWidth(20)
        self.checkmark.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        row.addWidget(self.checkmark)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title_label, self.detail_label = QLabel(), QLabel()
        self.title_label.setObjectName('receiptTitle')
        self.detail_label.setObjectName('receiptDetail')
        for label in (self.title_label, self.detail_label):
            label.setTextFormat(Qt.PlainText)
            text.addWidget(label)
        row.addLayout(text, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.clear)
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self.reposition)
        surface.installEventFilter(self)
        title_obstacle.installEventFilter(self)

    def set_accent(self, color):
        self.checkmark.setStyleSheet(f'color:{QColor(color).name()}; font-size:20px; font-weight:600;')

    def present(self, title, detail=''):
        if not title or not self.surface.isVisible() or not player_is_active(self.owner):
            self.clear()
            return
        self._title, self._detail = title, detail
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)
        self.detail_label.setVisible(bool(detail))
        self.reposition()
        self.show()
        raise_surface(self)
        self.timer.start(self.DURATION_MS)

    def reposition(self):
        bounds = QRect(self.surface.mapToGlobal(QPoint()), self.surface.size())
        margin = min(24, max(0, bounds.width() // 12))
        desired = max(240, 66 + max(self.title_label.fontMetrics().horizontalAdvance(self._title),
                                  self.detail_label.fontMetrics().horizontalAdvance(self._detail)))
        width = min(360, desired, max(1, bounds.width() - margin * 2))
        text_width = max(1, width - 16 - 18 - 20 - 12)
        for label, value in ((self.title_label, self._title), (self.detail_label, self._detail)):
            label.setText(label.fontMetrics().elidedText(value, Qt.ElideRight, text_width))
            label.setFixedWidth(text_width)
        self.layout().activate()
        height = self.sizeHint().height()
        top = bounds.top() + margin
        if self.title_obstacle.isVisible():
            top = max(top, self.title_obstacle.geometry().bottom() + 16)
        top = min(top, max(bounds.top(), bounds.bottom() - height - margin + 1))
        self.setGeometry(bounds.right() - margin - width + 1, top, width, height)

    def clear(self):
        self.timer.stop()
        self.position_timer.stop()
        self.hide()

    def eventFilter(self, watched, event):
        if watched in (self.owner, self.surface, self.title_obstacle):
            kind = event.type()
            if kind in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide):
                if kind == QEvent.Hide and watched in (self.owner, self.surface):
                    self.clear()
                elif self.isVisible():
                    self.position_timer.start(0)
                return False
        return super().eventFilter(watched, event)
