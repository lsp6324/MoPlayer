"""Screen-resolution seek feedback above the native video surface."""
from PySide6.QtCore import QObject, QTimer, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout
from floating_surface import FloatingSurface, player_is_active, raise_surface


def short_time(milliseconds):
    seconds = max(0, int(milliseconds)) // 1000
    return (f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
            if seconds >= 3600 else f'{seconds // 60:02}:{seconds % 60:02}')


def notice_text(before, after, total):
    return f'{short_time(before)}→{short_time(after)}({short_time(total)})\n{after / total * 100:.1f}%'


class SeekSurface(FloatingSurface):
    def __init__(self, surface):
        super().__init__(surface, radius=12, background=QColor(26, 30, 38, 232),
                         border=QColor(255, 255, 255, 35))
        self.surface = surface
        self.setObjectName('seekNotice')
        self.setWindowFlag(Qt.WindowTransparentForInput)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName('播放跳转进度')
        self.setStyleSheet('''
            QFrame#seekNotice { background:transparent; border:none; }
            QLabel { background:transparent; border:none; font-family:"Segoe UI"; }
            QLabel#seekTime { color:#f2f4f8; font-size:20px; font-weight:600; }
            QLabel#seekPercent { color:#c4cee0; font-size:14px; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(4)
        self.time_label = QLabel()
        self.time_label.setObjectName('seekTime')
        self.percent_label = QLabel()
        self.percent_label.setObjectName('seekPercent')
        for label in (self.time_label, self.percent_label):
            label.setAlignment(Qt.AlignCenter)
            label.setTextFormat(Qt.PlainText)
            layout.addWidget(label)
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self.reposition)
        surface.installEventFilter(self)

    def reposition(self):
        bounds = QRect(self.surface.mapToGlobal(QPoint()), self.surface.size())
        width = min(self.sizeHint().width(), max(1, bounds.width() - 24))
        height = self.sizeHint().height()
        top = min(max(16, round(bounds.height() * .12)), max(0, bounds.height() - height - 16))
        self.setGeometry(bounds.x() + (bounds.width() - width) // 2,
                         bounds.y() + top, width, height)

    def eventFilter(self, watched, event):
        # Passive feedback follows the video layout instead of dismissing on resize.
        if watched is self.owner or watched is getattr(self, 'surface', None):
            if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show):
                if self.isVisible():
                    self.position_timer.start(0)
                return False
            if watched is getattr(self, 'surface', None) and event.type() == QEvent.Hide:
                self.hide()
        return super().eventFilter(watched, event)


class SeekNotice(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.overlay = SeekSurface(window.surface)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.clear)

    def text(self):
        return (self.overlay.time_label.text() + '\n' + self.overlay.percent_label.text()
                if self.overlay.time_label.text() else '')

    def show(self, before, after, total):
        if total <= 0 or not self.window.surface.isVisible() or not player_is_active(self.window):
            self.clear()
            return
        times, percentage = notice_text(before, after, total).split('\n')
        self.overlay.time_label.setText(times)
        self.overlay.percent_label.setText(percentage)
        self.overlay.layout().activate()
        self.overlay.reposition()
        self.overlay.show()
        raise_surface(self.overlay)
        self.timer.start(1600)

    def clear(self):
        self.timer.stop()
        self.overlay.hide()
        self.overlay.time_label.clear()
        self.overlay.percent_label.clear()
