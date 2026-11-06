"""Shared capsule and favorite drawing for titles and library cards."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor
from moplayer.gui.ui import icon


def paint_capsule(painter, rect, text, colors):
    painter.setBrush(QColor(colors['selected']))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    painter.setPen(QColor(colors['accent']))
    painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft,
                     painter.fontMetrics().elidedText(text, Qt.ElideMiddle, int(rect.width() - 20)))


def paint_favorite(painter, x, y, starred, colors):
    color = '#d39a2d' if starred else colors['text_mid']
    painter.drawPixmap(int(x), int(y + 4), icon('starFilled' if starred else 'star', color, 16).pixmap(16, 16))
    painter.setPen(QColor(colors['text_mid']))
    painter.drawText(QRectF(x + 22, y, 60, 24), Qt.AlignVCenter | Qt.AlignLeft, '已收藏' if starred else '未收藏')
