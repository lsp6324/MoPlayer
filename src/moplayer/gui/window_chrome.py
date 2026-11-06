"""Integrated titlebar. Move/resize operations are delegated to Qt's window manager."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QFrame, QMainWindow, QWidget


def corner_preference(maximized=False, fullscreen=False):
    return 1 if maximized or fullscreen else 2  # DWMWCP_DONOTROUND / DWMWCP_ROUND


def resize_edges(position, size, margin=6):
    """Logical-pixel edge detection, also valid on screens with negative origins."""
    x, y = position.x(), position.y()
    width, height = size.width(), size.height()
    edges = Qt.Edges()
    if not (0 <= x < width and 0 <= y < height):
        return edges
    if x < margin:
        edges |= Qt.LeftEdge
    elif x >= width - margin:
        edges |= Qt.RightEdge
    if y < margin:
        edges |= Qt.TopEdge
    elif y >= height - margin:
        edges |= Qt.BottomEdge
    return edges


def resize_cursor(edges):
    if edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
        return Qt.SizeFDiagCursor
    if edges in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge):
        return Qt.SizeBDiagCursor
    if edges & (Qt.LeftEdge | Qt.RightEdge):
        return Qt.SizeHorCursor
    if edges:
        return Qt.SizeVerCursor
    return Qt.ArrowCursor


class TitleBar(QFrame):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.window().isFullScreen():
            handle = self.window().windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ChromeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinMaxButtonsHint)
        self._resize_widget = None
        self.native_corner_request_ok = False

    def apply_native_corners(self):
        self.corner_preference = corner_preference(self.isMaximized(), self.isFullScreen())
        if QApplication.platformName() != 'windows':
            return False
        try:
            import ctypes
            import sys
            if sys.getwindowsversion().build < 22000:
                return False
            preference = ctypes.c_int(self.corner_preference)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(int(self.winId())), 33,
                ctypes.byref(preference), ctypes.sizeof(preference))
            self.native_corner_request_ok = result == 0
        except (AttributeError, OSError):
            self.native_corner_request_ok = False
        return self.native_corner_request_ok

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_native_corners()

    def toggle_maximized(self):
        if not self.isFullScreen():
            self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self.sync_caption_button()
            self.apply_native_corners()

    def sync_caption_button(self):
        if not hasattr(self, 'maximize_button'):
            return
        from moplayer.gui.ui import icon
        from moplayer.gui.theme import theme_tokens
        maximized = self.isMaximized()
        symbol = 'restore' if maximized else 'maximize'
        self.maximize_button.setProperty('iconName', symbol)
        self.maximize_button.setIcon(icon(symbol, theme_tokens(self)['text_mid']))
        self.maximize_button.setToolTip('还原' if maximized else '最大化')
        self.maximize_button.setAccessibleName('还原' if maximized else '最大化')

    def chrome_event_filter(self, watched, event):
        if not isinstance(watched, QWidget) or QWidget.window(watched) is not self:
            return False
        kind = event.type()
        if kind == QEvent.Show:
            watched.setMouseTracking(True)
        if kind == QEvent.Leave and self._resize_widget is watched:
            watched.unsetCursor()
            self._resize_widget = None
        if kind not in (QEvent.MouseMove, QEvent.MouseButtonPress):
            return False
        if self.isMaximized() or self.isFullScreen() or QApplication.activeModalWidget() or QApplication.activePopupWidget():
            if self._resize_widget is not None:
                self._resize_widget.unsetCursor()
                self._resize_widget = None
            return False
        position = self.mapFromGlobal(event.globalPosition().toPoint())
        edges = resize_edges(position, self.size())
        if kind == QEvent.MouseMove:
            if self._resize_widget is not None and (self._resize_widget is not watched or not edges):
                self._resize_widget.unsetCursor()
                self._resize_widget = None
            if edges:
                watched.setCursor(resize_cursor(edges))
                self._resize_widget = watched
        elif edges and event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle and handle.startSystemResize(edges):
                event.accept()
                return True
        return False
