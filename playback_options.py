"""Hover controls that float above the player without changing its layout."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from floating_surface import owned_by
from hover_panel import HoverPanel


class RatingPanel(HoverPanel):
    chosen = Signal(str, object)

    def __init__(self, host, anchor, rating_source):
        super().__init__(anchor, host)
        from heart_rating import HeartRating
        self.rating_source = rating_source
        self.video_id = None
        self.prepare = self.load_score
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(4)
        self.hearts = HeartRating()
        layout.addWidget(self.hearts, 0, Qt.AlignHCenter)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.zero = QPushButton('0 分')
        self.clear = QPushButton('清除')
        for control in (self.zero, self.clear):
            control.setProperty('role', 'quiet')
            control.setFixedHeight(28)
            control.setFocusPolicy(Qt.NoFocus)
            control.setCursor(Qt.PointingHandCursor)
        self.clear.setAccessibleName('清除评分')
        self.value = QLabel('— / 10')
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setFixedWidth(56)
        footer.addWidget(self.zero)
        footer.addStretch()
        footer.addWidget(self.value)
        footer.addStretch()
        footer.addWidget(self.clear)
        layout.addLayout(footer)
        self.hearts.previewed.connect(self.update_value)
        self.hearts.chosen.connect(self.commit)
        self.zero.clicked.connect(lambda: self.commit(0))
        self.clear.clicked.connect(lambda: self.commit(None))

    def update_value(self, score):
        self.value.setText('— / 10' if score is None else f'{score} / 10')

    def load_score(self):
        value = self.rating_source()
        if value is None:
            return False
        self.video_id, score = value
        self.hearts.set_score(score)
        self.clear.setEnabled(score is not None)
        return True

    def commit(self, score):
        vid = self.video_id
        self.dismiss()
        if vid is not None:
            self.chosen.emit(vid, score)

    def hideEvent(self, event):
        if hasattr(self, 'hearts'):
            self.hearts.set_preview(None)
        super().hideEvent(event)

    def handle_key(self, event):
        if not self.isVisible():
            return False
        key = event.key()
        score = self.hearts.display_score() or 0
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            score = 0 if key == Qt.Key_Home else 10 if key == Qt.Key_End else max(0, min(10, score + (1 if key == Qt.Key_Right else -1)))
            self.hearts.set_preview(score)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.commit(self.hearts.display_score())
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.commit(None)
        else:
            return False
        return True


class PlaybackOptions(QObject):
    volumeRequested = Signal(int)
    muteRequested = Signal(bool)
    rateRequested = Signal(float)
    ratingRequested = Signal(str, object)

    def owns_active_popup(self):
        popup = QApplication.activePopupWidget()
        return popup is not None and any(owned_by(popup, panel) for panel in self.panels)

    def __init__(self, host, parent, drafts, rating_source):
        super().__init__(parent)
        self.host, self.drafts, self.rating_source = host, drafts, rating_source
        self._icon_color = '#cbd2dd'
        self._volume_icon_key = None
        self._audible_volume = 80
        self.muted = False
        self.rate = 1.0
        self.panels = []
        self.volume_button = QPushButton()
        self.volume_button.setProperty('role', 'nav')
        self.volume_button.setFixedSize(36, 36)
        self.volume_button.setCursor(Qt.PointingHandCursor)
        self.volume_button.clicked.connect(self.toggle_mute)
        self.volume_popup = HoverPanel(self.volume_button, host)
        volume_layout = QHBoxLayout(self.volume_popup.body)
        volume_layout.setContentsMargins(14, 14, 14, 14)
        volume_layout.setSpacing(10)
        from seek_slider import SeekSlider
        self.volume = SeekSlider()
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedSize(144, 24)
        self.volume.setAccessibleName('音量')
        self.volume_value = QLabel('80%')
        self.volume_value.setFixedWidth(36)
        self.volume_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        volume_layout.addWidget(self.volume)
        volume_layout.addWidget(self.volume_value)
        self.volume.valueChanged.connect(self.set_volume)

        self.speed_button = QPushButton('1×')
        self.speed_button.setObjectName('speedButton')
        self.speed_button.setProperty('role', 'nav')
        self.speed_button.setFixedSize(46, 36)
        self.speed_button.setCursor(Qt.PointingHandCursor)
        self.speed_button.setAccessibleName('播放速度：1 倍')
        self.speed_popup = HoverPanel(self.speed_button, host)
        self.panels.extend((self.volume_popup, self.speed_popup))
        self.speed_button.clicked.connect(self.speed_popup.open_above)
        speed_layout = QVBoxLayout(self.speed_popup.body)
        speed_layout.setContentsMargins(6, 6, 6, 6)
        speed_layout.setSpacing(2)
        self.rate_buttons = {}
        for rate in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
            control = QPushButton(f'{rate:g}×')
            control.setProperty('role', 'rateOption')
            control.setMinimumSize(84, 30)
            control.setCheckable(True)
            control.setChecked(rate == self.rate)
            control.setCursor(Qt.PointingHandCursor)
            control.setFocusPolicy(Qt.NoFocus)
            control.clicked.connect(lambda checked=False, rate=rate: self.set_rate(rate))
            speed_layout.addWidget(control)
            self.rate_buttons[rate] = control
        self.refresh_icon()

    def add_rating(self, anchor):
        self.rating_popup = RatingPanel(self.host, anchor, self.rating_source)
        self.rating_popup.chosen.connect(self.ratingRequested)
        self.panels.append(self.rating_popup)

    def add_tags(self, anchor):
        from tag_popover import TagPanel
        self.tags_popup = TagPanel(anchor, self.host, self.drafts)
        self.panels.append(self.tags_popup)

    def flush_pending(self):
        return self.tags_popup.flush_pending()

    def refresh_icon(self):
        from ui import icon
        silent = self.muted or self.volume.value() == 0
        key = (silent, self._icon_color)
        if key != self._volume_icon_key:
            self._volume_icon_key = key
            self.volume_button.setProperty('iconName', 'muted' if silent else 'volume')
            self.volume_button.setIcon(icon('muted' if silent else 'volume', key[1]))
            self.volume_button.setAccessibleName('取消静音' if silent else '静音')
        self.volume_value.setText('静音' if self.muted else f'{self.volume.value()}%')

    def toggle_mute(self):
        # Zero volume also looks muted; clicking restores the previous audible level.
        if self.volume.value() == 0:
            self.volume.setValue(self._audible_volume)
            self.muted = False
        else:
            self.muted = not self.muted
        self.muteRequested.emit(self.muted)
        self.refresh_icon()

    def set_volume(self, value):
        if value > 0:
            self._audible_volume = value
        if self.muted:
            self.muteRequested.emit(False)
        self.muted = False
        self.volumeRequested.emit(value)
        self.refresh_icon()

    def set_icon_color(self, color):
        self._icon_color = color
        self.refresh_icon()

    def set_rate(self, rate):
        self.rateRequested.emit(rate)

    def accept_rate(self, rate):
        self.rate = rate
        self.speed_button.setText(f'{rate:g}×')
        self.speed_button.setAccessibleName(f'播放速度：{rate:g} 倍')
        for value, control in self.rate_buttons.items():
            control.setChecked(value == rate)
        self.speed_popup.dismiss()

    def reject_rate(self):
        for value, control in self.rate_buttons.items():
            control.setChecked(value == self.rate)
        self.dismiss()

    def dismiss(self):
        visible = self.popup_visible()
        for panel in self.panels:
            panel.dismiss()
        return visible

    def popup_visible(self):
        return any(panel.isVisible() for panel in self.panels)
