"""A playback timeline follows the pointer; it never pages or auto-repeats."""
import time
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class SeekSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setFocusPolicy(Qt.NoFocus)

    def value_at(self, point):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        span = max(1, groove.width() - handle.width())
        offset = round(point.x() - groove.x() - handle.width() / 2)
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), max(0, min(span, offset)), span, option.upsideDown)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setSliderPosition(self.value_at(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setSliderPosition(self.value_at(event.position()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderPosition(self.value_at(event.position()))
            self.setSliderDown(False)  # Emits sliderReleased once, after the final position.
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        event.ignore()


class PlaybackClock:
    """Interpolate UI time between decoder samples, without seeking the media.

    Repeated VLC timestamps must not restart the clock. Small corrections are
    spread over 400 ms; explicit seeks and state changes take effect immediately.
    Extrapolation stops if the decoder has supplied no new position for 750 ms.
    """
    def __init__(self):
        self.duration = self.anchor = self.anchor_at = self.sample_at = 0
        self.source = None
        self.running = False
        self.rate = 1.0
        self.correction = 0

    def position(self, now):
        elapsed = max(0, min(now, self.sample_at + .75) - self.anchor_at) if self.running else 0
        position = self.anchor + elapsed * self.rate * 1000
        position += self.correction * min(elapsed / .4, 1)
        return max(0, min(self.duration, position))

    def hold(self, position, duration, now):
        self.duration = max(0, duration)
        self.anchor = max(0, min(self.duration, position))
        self.anchor_at = self.sample_at = now
        self.running = False
        self.source = None
        self.correction = 0

    def sample(self, position, duration, running, rate, now):
        position = max(0, min(max(0, duration), position))
        shown = self.position(now)
        self.duration = max(0, duration)
        running = running and self.duration > 0
        if position == self.source and running == self.running:
            if rate != self.rate:
                self.anchor, self.anchor_at, self.correction = shown, now, 0
                self.rate = rate
            return
        error = position - shown
        continuous = running and self.running and abs(error) < 1500
        self.anchor = shown if continuous else position
        self.correction = max(-rate * 400, min(rate * 400, error)) if continuous else 0
        self.anchor_at = self.sample_at = now
        self.source, self.running, self.rate = position, running, rate


class PlaybackTimeline(SeekSlider):
    """Fractional, antialiased timeline; volume sliders retain direct behavior."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clock = PlaybackClock()
        self.visual_fraction = 0.0
        self._refreshing = False
        self.animation = QTimer(self)
        self.animation.setTimerType(Qt.PreciseTimer)
        self.animation.setInterval(16)
        self.animation.timeout.connect(self.refresh_frame)
        self.sliderPressed.connect(self.freeze)
        self.valueChanged.connect(self._direct_value)

    def _direct_value(self, value):
        if not self._refreshing:
            self.animation.stop()
            self.clock.hold(value / max(1, self.maximum()) * self.clock.duration,
                            self.clock.duration, time.monotonic())
            self.visual_fraction = value / max(1, self.maximum())
            self.update()

    def hold(self, position, duration):
        self.animation.stop()
        self.clock.hold(position, duration, time.monotonic())
        self.refresh_frame()

    def freeze(self):
        self.hold(self.clock.position(time.monotonic()), self.clock.duration)

    def set_playback_rate(self, rate):
        now = time.monotonic()
        self.clock.anchor = self.clock.position(now)
        self.clock.anchor_at, self.clock.rate, self.clock.correction = now, rate, 0
        self.refresh_frame()

    def synchronize(self, position, duration, running, rate):
        if self.isSliderDown():
            return
        self.clock.sample(position, duration, running, rate, time.monotonic())
        self.refresh_frame()
        if self.clock.running and self.isVisible():
            self.animation.start()
        else:
            self.animation.stop()

    def refresh_frame(self):
        position = self.clock.position(time.monotonic())
        self.visual_fraction = position / self.clock.duration if self.clock.duration else 0.0
        self._refreshing = True
        try:
            self.setValue(round(self.visual_fraction * self.maximum()))
        finally:
            self._refreshing = False
        self.update()

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_frame()
        if self.clock.running:
            self.animation.start()

    def paintEvent(self, event):
        from moplayer.gui.theme import theme_tokens
        top = self.window()
        fullscreen = top.objectName() == 'fullscreenControls'
        colors = theme_tokens(getattr(top, 'owner', top),mode='dark' if fullscreen else None)
        track = QColor(255, 255, 255, 52) if fullscreen else QColor(colors['track'])
        fill = QColor(colors['progress'])
        handle_fill = QColor('#ffffff') if fullscreen else QColor(colors['progress'])
        if self.underMouse():
            handle_fill = QColor('#f2f6ff' if fullscreen else colors['text_strong'])
        if not self.isEnabled():
            fill = handle_fill = track
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        radius = handle.width() / 2
        left, span = groove.x() + radius, max(1, groove.width() - handle.width())
        fraction = 1 - self.visual_fraction if option.upsideDown else self.visual_fraction
        x, y = left + span * fraction, self.height() / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(left, y - 2, span, 4), 2, 2)
        painter.setBrush(fill)
        start, width = (x, left + span - x) if option.upsideDown else (left, x - left)
        if width > 0:
            painter.drawRoundedRect(QRectF(start, y - 2, width, 4), 2, 2)
        painter.setPen(QPen(fill, 2 if fullscreen else 1))
        painter.setBrush(handle_fill)
        painter.drawEllipse(QRectF(x - radius + 1, y - radius + 1, 2 * radius - 2, 2 * radius - 2))
