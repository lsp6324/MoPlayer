"""A painted idle region above a native video host; no media or settings access."""
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget


class BackgroundRegion(QWidget):
    def __init__(self, paint_background=None, parent=None):
        super().__init__(parent)
        self.paint_background = paint_background

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.paint_background is None:
            painter.fillRect(self.rect(),QColor('#101216'))
        else:
            self.paint_background(painter,self)
