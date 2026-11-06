"""Shared hover/focus behavior for player popovers; no feature dependencies."""
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QFrame, QSlider, QVBoxLayout, QWidget
from moplayer.gui.floating_surface import FloatingSurface, owned_by, player_is_active, raise_surface


class HoverPanel(FloatingSurface):
    def __init__(self, anchor, host, editable=False):
        super().__init__(host)
        self.hide()
        self.anchor = anchor
        self.editable = editable
        self.auto_close = not editable
        self.prepare = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QFrame(self)
        self.body.setObjectName('playbackPopover')
        outer.addWidget(self.body)
        self.open_timer = QTimer(self)
        self.open_timer.setSingleShot(True)
        self.open_timer.setInterval(120)
        self.open_timer.timeout.connect(self.open_above)
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.setInterval(220)
        self.close_timer.timeout.connect(self.close_if_idle)
        QApplication.instance().installEventFilter(self)

    def open_above(self):
        self.close_timer.stop()
        if (not player_is_active(self.owner) or not self.anchor.isVisible() or
                not self.anchor.isEnabled() or QApplication.activeModalWidget() or QApplication.activePopupWidget()):
            return
        for other in self.owner.findChildren(HoverPanel):
            if other is not self:
                other.dismiss()
        if self.prepare and self.prepare() is False:
            return
        self.adjustSize()
        self.position_above()
        self.show()
        raise_surface(self)

    def position_above(self):
        origin = self.anchor.mapToGlobal(QPoint())
        canvas = self.owner.canvas
        screen = QRect(canvas.mapToGlobal(QPoint()), canvas.size())
        x = max(screen.left(), min(origin.x() + (self.anchor.width() - self.width()) // 2,
                                  screen.right() - self.width() + 1))
        y = origin.y() - self.height() - 6
        if y < screen.top():
            y = origin.y() + self.anchor.height() + 6
        self.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self.position_above()

    def dismiss(self):
        self.open_timer.stop()
        self.close_timer.stop()
        self.hide()

    def close_if_idle(self):
        if not self.auto_close:
            return
        if QApplication.mouseButtons() != Qt.NoButton or any(slider.isSliderDown() for slider in self.findChildren(QSlider)):
            self.close_timer.start()
        else:
            self.hide()

    def contains_press(self, watched, event):
        # Native dispatch targets a QWindow before the corresponding QWidget.
        # Resolve it so menus/submenus retain their QObject ownership chain.
        receiver = QWidget.find(watched.winId()) if isinstance(watched, QWindow) else watched
        if isinstance(receiver, QWidget) and (receiver is self.anchor or owned_by(receiver, self)):
            return True
        if isinstance(watched, QWindow):
            # Native mouse events reach QWindow before Qt dispatches to the
            # input/button widget. Their receiver is not a QWidget.
            point = event.globalPosition().toPoint()
            if watched in (self.owner.windowHandle(), self.windowHandle(), self.anchor.window().windowHandle()):
                return (self.rect().contains(self.mapFromGlobal(point)) or
                        self.anchor.rect().contains(self.anchor.mapFromGlobal(point)))
        return False

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Show and isinstance(watched, QWidget) and (watched.isModal() or watched.windowType() == Qt.Popup) and not owned_by(watched, self):
            self.dismiss()
        if watched is self.anchor:
            if kind == QEvent.Enter:
                self.close_timer.stop()
                self.open_timer.start()
            elif kind == QEvent.Leave:
                self.open_timer.stop()
                self.close_timer.start()
            elif kind == QEvent.Hide:
                self.dismiss()
        if watched is self:
            if kind == QEvent.Enter:
                self.close_timer.stop()
            elif kind == QEvent.Leave:
                self.close_timer.start()
        if self.isVisible():
            if kind == QEvent.MouseButtonPress:
                inside = self.contains_press(watched, event)
                if not inside:
                    self.dismiss()
                elif self.editable and self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):
                    receiver = QWidget.find(watched.winId()) if isinstance(watched, QWindow) else watched
                    # A menu owns the focus until its action completes. Taking
                    # activation away from it corrupts Qt's popup restoration.
                    if not (isinstance(receiver, QWidget) and QWidget.window(receiver).windowType() == Qt.Popup):
                        self.activateWindow()
        return super().eventFilter(watched, event)
