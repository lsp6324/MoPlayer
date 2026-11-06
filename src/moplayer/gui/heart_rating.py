"""Five vector hearts, with one point per half heart."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget


def heart_path(rect):
    path = QPainterPath(QPointF(12, 6.1))
    path.cubicTo(11.4, 6.1, 11.2, 5.4, 10.6, 4.7)
    path.cubicTo(9.4, 3.1, 7.9, 2.6, 6.1, 2.8)
    path.cubicTo(3.3, 3.1, 1.8, 5.3, 1.8, 8)
    path.cubicTo(1.8, 12.4, 5.8, 16.2, 10.7, 20.1)
    path.cubicTo(11.5, 20.75, 12.5, 20.75, 13.3, 20.1)
    path.cubicTo(18.2, 16.2, 22.2, 12.4, 22.2, 8)
    path.cubicTo(22.2, 5.3, 20.7, 3.1, 17.9, 2.8)
    path.cubicTo(16.1, 2.6, 14.6, 3.1, 13.4, 4.7)
    path.cubicTo(12.8, 5.4, 12.6, 6.1, 12, 6.1)
    path.closeSubpath()
    transform = QTransform()
    transform.translate(rect.x(), rect.y())
    transform.scale(rect.width() / 24, rect.height() / 24)
    return transform.map(path)


def paint_hearts(painter, score, rectangles, fill_color, outline_color, stroke=1.4):
    """Shared whole/half-heart drawing for editable and read-only ratings."""
    for index, rect in enumerate(rectangles):
        path = heart_path(rect)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(outline_color), stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        fraction = max(0, min(1, ((score or 0) - index * 2) / 2))
        if fraction:
            painter.save()
            painter.setClipRect(QRectF(rect.left(), rect.top(), rect.width() * fraction, rect.height()))
            painter.setBrush(QColor(fill_color))
            painter.setPen(QPen(QColor(fill_color), stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
            painter.restore()


class HeartRating(QWidget):
    chosen = Signal(object)
    previewed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(194, 36)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('评分，满分十分，每半颗爱心一分')
        self.score = None
        self.preview = None
        self.fill_color = QColor('#285fbd')
        self.outline_color = QColor('#aab3c2')
        self._pressed = False

    def set_score(self, score):
        self.score = score
        self.setAccessibleDescription('未评分' if score is None else f'{score} 分')
        self.set_preview(None)

    def set_preview(self, score):
        self.preview = score
        self.previewed.emit(self.display_score())
        self.update()

    def display_score(self):
        return self.score if self.preview is None else self.preview

    def score_at(self, x):
        x = max(0, min(self.width() - 1, x))
        index = min(4, int(x // 40))
        return index * 2 + (1 if x - index * 40 < 17 else 2)

    def mouseMoveEvent(self, event):
        self.set_preview(self.score_at(event.position().x()))

    def leaveEvent(self, event):
        self.set_preview(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.set_preview(self.score_at(event.position().x()))
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.chosen.emit(self.score_at(event.position().x()))
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        paint_hearts(painter, self.display_score(),
                     (QRectF(index * 40 + 2, 3, 30, 30) for index in range(5)),
                     self.fill_color, self.outline_color)
