"""Still-image presentation: fit/actual scaling, wheel zoom and drag panning.

Only display state lives here. The view receives pixels, keeps its own zoom and
offset, and reports nothing back to playback, storage or the window.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class ImageView(QWidget):
    """Show one still image; wheel zooms around the pointer, drag pans."""

    ZOOM_STEP = 1.25
    MAX_SCALE = 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._scale = 1.0
        self._center = QPointF()  # 图像坐标中显示在视图中心的点。
        self._auto_fit = True  # 未手动缩放时跟随视图尺寸重新适配。
        self._drag_origin = None
        self._drag_center = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)  # 自绘底色，避免父级重复填充。
        self.setFocusPolicy(Qt.StrongFocus)  # 让滚轮和键盘落到图片本身。

    # ---------------------------------------------------------------- content

    def set_image(self, image):
        self._pixmap = None if image is None else QPixmap.fromImage(image)
        self.setCursor(Qt.OpenHandCursor if self._pixmap is not None and not self._pixmap.isNull()
                       else Qt.ArrowCursor)
        self.reset_view()

    def clear(self):
        self._pixmap = None
        self._drag_origin = self._drag_center = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def has_image(self):
        return self._pixmap is not None and not self._pixmap.isNull()

    def reset_view(self):
        """Fit the whole image inside the view."""
        self._auto_fit = True
        self._scale = self._fit_scale()
        if self.has_image():
            self._center = QPointF(self._pixmap.width() / 2, self._pixmap.height() / 2)
        self.update()

    # ------------------------------------------------------------------ scale

    def _fit_scale(self):
        if not self.has_image() or self.width() <= 0 or self.height() <= 0:
            return 1.0
        fit = min(self.width() / self._pixmap.width(), self.height() / self._pixmap.height())
        return min(fit, 1.0)  # 小图保持 100%，不放大到糊。

    def zoom_at(self, point, target):
        """Zoom so the image point under *point* stays under the pointer."""
        if not self.has_image():
            return
        target = min(max(target, self._fit_scale()), self.MAX_SCALE)
        if abs(target - self._scale) < 1e-6:
            return
        focal = self._image_point(point)
        self._scale = target
        self._auto_fit = False
        view_center = QPointF(self.width() / 2, self.height() / 2)
        self._center = focal - (point - view_center) / self._scale
        self._clamp()
        self.update()

    def _image_point(self, point):
        view_center = QPointF(self.width() / 2, self.height() / 2)
        return self._center + (point - view_center) / self._scale

    def _clamp(self):
        if not self.has_image():
            return
        width, height = self._pixmap.width(), self._pixmap.height()
        half_w = self.width() / 2 / self._scale
        half_h = self.height() / 2 / self._scale
        self._center.setX(width / 2 if half_w * 2 >= width
                          else min(max(self._center.x(), half_w), width - half_w))
        self._center.setY(height / 2 if half_h * 2 >= height
                          else min(max(self._center.y(), half_h), height - half_h))

    # ----------------------------------------------------------------- events

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not self.has_image() or not delta:
            return
        self.zoom_at(event.position(), self._scale * (self.ZOOM_STEP if delta > 0 else 1 / self.ZOOM_STEP))
        event.accept()

    def mousePressEvent(self, event):
        if self.has_image() and event.button() == Qt.LeftButton:
            self._drag_origin = event.position()
            self._drag_center = QPointF(self._center)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is None:
            return
        self._center = self._drag_center - (event.position() - self._drag_origin) / self._scale
        self._auto_fit = False
        self._clamp()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._drag_origin is None:
            return
        self._drag_origin = self._drag_center = None
        if self.has_image():
            self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if not self.has_image():
            return
        self.zoom_at(event.position(), 1.0 if self._scale < 1.0 else self._fit_scale())
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.reset_view()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#08090b'))
        if not self.has_image():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scale = self._scale
        target = QRectF(self.width() / 2 - self._center.x() * scale,
                        self.height() / 2 - self._center.y() * scale,
                        self._pixmap.width() * scale, self._pixmap.height() * scale)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
