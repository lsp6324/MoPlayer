"""Hover controls that float above the player without changing its layout."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget
from floating_surface import FloatingSurface, owned_by, player_is_active, raise_surface


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


class RatingPanel(HoverPanel):
    def __init__(self, window, anchor):
        super().__init__(anchor, window.canvas)
        from heart_rating import HeartRating
        self.player_window = window
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
        window = self.player_window
        if not window.current or window.busy:
            return False
        self.video_id = window.current
        score = window.store.video(self.video_id)['score']
        self.hearts.set_score(score)
        self.clear.setEnabled(score is not None)
        return True

    def commit(self, score):
        vid = self.video_id
        self.dismiss()
        if vid is not None:
            self.player_window.set_rating(vid, score)

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
    def owns_active_popup(self):
        popup = QApplication.activePopupWidget()
        return popup is not None and any(owned_by(popup, panel) for panel in self.panels)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.muted = False
        self.rate = 1.0
        self.panels = []
        self.volume_button = QPushButton()
        self.volume_button.setProperty('role', 'nav')
        self.volume_button.setFixedSize(36, 36)
        self.volume_button.setCursor(Qt.PointingHandCursor)
        self.volume_button.clicked.connect(self.toggle_mute)
        self.volume_popup = HoverPanel(self.volume_button, window.canvas)
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
        self.speed_popup = HoverPanel(self.speed_button, window.canvas)
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
        window.player.audio_set_volume(80)
        self.refresh_icon()

    def add_rating(self, anchor):
        self.rating_popup = RatingPanel(self.window, anchor)
        self.panels.append(self.rating_popup)

    def add_tags(self, anchor):
        from tag_popover import TagPanel
        self.tags_popup = TagPanel(self.window, anchor)
        self.panels.append(self.tags_popup)

    def flush_pending(self):
        self.tags_popup.flush_pending()

    def refresh_icon(self):
        from ui import icon
        from theme import theme_tokens
        silent = self.muted or self.volume.value() == 0
        key = (silent, theme_tokens(self.window)['text_mid'])
        if key != getattr(self, '_volume_icon_key', None):
            self._volume_icon_key = key
            self.volume_button.setProperty('iconName', 'muted' if silent else 'volume')
            self.volume_button.setIcon(icon('muted' if silent else 'volume', key[1]))
            self.volume_button.setAccessibleName('取消静音' if silent else '静音')
        self.volume_value.setText('静音' if self.muted else f'{self.volume.value()}%')

    def toggle_mute(self):
        # Zero volume also looks muted; clicking restores the previous audible level.
        if self.volume.value() == 0:
            self.volume.setValue(getattr(self, '_audible_volume', 80))
            self.muted = False
        else:
            self.muted = not self.muted
        self.window.player.audio_set_mute(self.muted)
        self.refresh_icon()

    def set_volume(self, value):
        if value > 0:
            self._audible_volume = value
        if self.muted:
            self.window.player.audio_set_mute(False)
        self.muted = False
        self.window.player.audio_set_volume(value)
        self.refresh_icon()

    def set_rate(self, rate):
        try:
            result = self.window.player.set_rate(rate)
            if result == -1:
                raise ValueError('当前视频无法应用此播放速度。')
        except (RuntimeError, ValueError) as error:
            for value, control in self.rate_buttons.items():
                control.setChecked(value == self.rate)
            self.dismiss()
            self.window.fail(error)
            return
        self.rate = rate
        self.window.seekbar.set_playback_rate(rate)
        self.speed_button.setText(f'{rate:g}×')
        self.speed_button.setAccessibleName(f'播放速度：{rate:g} 倍')
        for value, control in self.rate_buttons.items():
            control.setChecked(value == rate)
        self.speed_popup.dismiss()

    def dismiss(self):
        visible = self.popup_visible()
        for panel in self.panels:
            panel.dismiss()
        return visible

    def popup_visible(self):
        return any(panel.isVisible() for panel in self.panels)
