"""Owned, per-pixel translucent surfaces above the native video window.

The compositor blends the antialiased edge. No binary window region, copied
video background, or global topmost flag is involved.
"""
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QWidget


def owned_by(widget, owner):
    while widget is not None:
        if widget is owner:
            return True
        widget = widget.parent()
    return False


def player_is_active(owner):
    return (not owner.isMinimized() and owner.isVisible() and
            owned_by(QApplication.activeWindow(), owner))


class FloatingSurface(QFrame):
    def __init__(self, host, radius=10, background='#ffffff', border='#d8dde5'):
        owner = QWidget.window(host)
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.owner = owner
        self.radius = radius
        self.background_color, self.border_color = QColor(background), QColor(border)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName('floatingSurface')
        self.owner_timer = QTimer(self)
        self.owner_timer.setSingleShot(True)
        self.owner_timer.timeout.connect(self.hide_if_inactive)
        self.owner.installEventFilter(self)
        self.hide()

    def set_colors(self, background, border):
        self.background_color, self.border_color = QColor(background), QColor(border)
        self.update()

    def hide(self):
        # An editable tool can be the active window. Hiding it must return
        # activation to the player; otherwise Qt may leave activeWindow() null
        # and the hover/fullscreen gates correctly refuse every later surface.
        restore_owner = (self.isActiveWindow() and self.owner.isVisible() and
                         not self.owner.isMinimized())
        super().hide()
        if restore_owner:
            self.owner.activateWindow()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(QPen(self.border_color, 1))
        painter.setBrush(self.background_color)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                self.radius, self.radius)

    def hide_if_inactive(self):
        # Clicking an editable surface transfers activation to an owned tool
        # window. That is still this player; switching applications is not.
        if not player_is_active(self.owner):
            self.hide()

    def changeEvent(self, event):
        super().changeEvent(event)
        # The owner is already inactive when the focus is in a tag editor.
        # Track deactivation of the tool itself when leaving the application.
        if event.type() == QEvent.WindowDeactivate:
            self.owner_timer.start(0)

    def eventFilter(self, watched, event):
        if watched is self.owner:
            kind = event.type()
            if kind in (QEvent.Hide, QEvent.Close, QEvent.Move, QEvent.Resize):
                self.hide()
            elif kind == QEvent.WindowStateChange and self.owner.isMinimized():
                self.hide()
            elif kind == QEvent.WindowDeactivate:
                self.owner_timer.start(0)
        return False


def raise_surface(surface):
    # Owned windows stay over their owner without covering other applications.
    surface.raise_()
