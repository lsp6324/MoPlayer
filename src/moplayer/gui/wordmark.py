"""Empty-player wordmark: same-family weight contrast plus a play arrow.

The component only receives theme colours; it never reads playback, storage or
window state, and it paints text as vector outlines at the current DPI.
"""
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class Wordmark(QWidget):
    """Paint `▸ MoPlayer` with Mo heavy and Player light."""

    HEAVY_FAMILY = 'Bahnschrift'
    LIGHT_FAMILY = 'Bahnschrift'
    ARROW_FAMILY = 'Segoe UI'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = QColor('#1d2531')
        self._dim = QColor('#6d798b')
        self._accent = QColor('#285fbd')
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 字标不拦截播放区点击。
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(110)
        self.setToolTip('把文件夹拖进左侧列表即可开始')

    def set_colors(self, text, dim, accent):
        self._text, self._dim, self._accent = QColor(text), QColor(dim), QColor(accent)
        self.update()

    def _font_size(self):
        return max(38, min(72, int(self.width() * 0.065)))

    def sizeHint(self):
        return QSize(600, 110)

    def fonts(self):
        size = self._font_size()
        heavy = QFont(self.HEAVY_FAMILY)
        heavy.setPixelSize(size)
        heavy.setWeight(QFont.Bold)
        light = QFont(self.LIGHT_FAMILY)
        light.setPixelSize(size)
        light.setWeight(QFont.Light)
        arrow = QFont(self.ARROW_FAMILY)
        arrow.setPixelSize(int(size * 0.50))
        arrow.setWeight(QFont.DemiBold)
        return heavy, light, arrow

    def paintEvent(self, event):
        heavy, light, arrow = self.fonts()
        heavy_metrics, light_metrics = QFontMetricsF(heavy), QFontMetricsF(light)
        arrow_metrics = QFontMetricsF(arrow)
        size = heavy.pixelSize()
        gap = size * 0.09
        arrow_width = arrow_metrics.horizontalAdvance('▸')
        total = (arrow_width + gap + heavy_metrics.horizontalAdvance('Mo')
                 + light_metrics.horizontalAdvance('Player'))
        x = (self.width() - total) / 2
        baseline = (self.height() + heavy_metrics.ascent() - heavy_metrics.descent()) / 2

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(arrow)
        painter.setPen(self._accent)
        painter.drawText(QPointF(x, baseline), '▸')
        x += arrow_width + gap
        painter.setFont(heavy)
        painter.setPen(self._text)
        painter.drawText(QPointF(x, baseline), 'Mo')
        x += heavy_metrics.horizontalAdvance('Mo')
        painter.setFont(light)
        painter.setPen(self._dim)
        painter.drawText(QPointF(x, baseline), 'Player')
        painter.end()
