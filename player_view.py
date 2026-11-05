"""Player widgets and presentation. Native playback commands arrive as signals.

Presentation snapshots are only for rendering; playback, persistence and file
tasks never derive their state from these widgets.
"""
from dataclasses import dataclass
from string import Template
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QAbstractButton
from PySide6.QtGui import QColor
from application.playback import PlaybackStatus
from media_header import MediaHeader
from playback_controls import PlaybackControls
from playback_options import PlaybackOptions
from seek_slider import PlaybackTimeline
from seek_notice import SeekNotice
from action_notice import ActionNotice
from video_fullscreen import VideoFullscreen
from floating_surface import owned_by
from background_region import BackgroundRegion
from image_view import ImageView
from wordmark import Wordmark
from theme import STYLE_TEMPLATE, TOKENS, colors_for
from ui import icon, label, button, format_time


@dataclass(frozen=True)
class PlayerInfo:
    name: str
    score: int | None
    tags: tuple
    starred: bool
    video_id: str | None = None


class PlayerView(QFrame):
    playRequested = Signal()
    stepRequested = Signal(int)
    seekRequested = Signal(float)
    sidebarRequested = Signal()
    fullscreenRequested = Signal()
    favoriteRequested = Signal()
    ratingRequested = Signal(str, object)
    volumeRequested = Signal(int)
    muteRequested = Signal(bool)
    rateRequested = Signal(float)
    transportRefreshRequested = Signal()

    def __init__(self, host, popup_host, splitter, drafts, rating_source, *, paint_background=None):
        super().__init__(host)
        self._info = None
        self._transport = (PlaybackStatus.IDLE, False, False, False)
        self._duration = 0
        self.normal_colors = TOKENS

        def tool(name, action, symbol):
            control = button('', lambda: action(), symbol, 'nav')
            control.setFixedSize(36, 36)
            control.setToolTip(name)
            control.setAccessibleName(name)
            return control

        self.setObjectName('playerCard')
        player = QVBoxLayout(self)
        player.setContentsMargins(0, 0, 0, 0)
        player.setSpacing(0)
        self.header = MediaHeader()
        self.header.hide()
        player.addWidget(self.header)
        self.media_badge = label('', 'badge')
        self.media_badge.hide()
        self.surface = QFrame()
        self.surface.setAttribute(Qt.WA_NativeWindow)
        self.surface.setObjectName('videoSurface')
        self.surface.setStyleSheet('QWidget#videoSurface { background:#08090b; border:none; }')
        self.surface.setMinimumSize(300, 170)
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        self.player_empty = BackgroundRegion(paint_background)
        self.player_empty.setObjectName('playerEmpty')
        self.player_empty.setAttribute(Qt.WA_StyledBackground)
        empty = QVBoxLayout(self.player_empty)
        empty.setAlignment(Qt.AlignCenter)
        empty.setSpacing(0)
        self.wordmark = Wordmark()
        empty.addWidget(self.wordmark)
        surface_layout.addWidget(self.player_empty)
        self.image_view = ImageView()
        self.image_view.hide()
        surface_layout.addWidget(self.image_view)
        player.addWidget(self.surface, 1)

        self.playback_panel = QWidget()
        self.playback_panel.setObjectName('playbackPanel')
        playback = QVBoxLayout(self.playback_panel)
        playback.setContentsMargins(14, 4, 14, 6)
        playback.setSpacing(2)
        progress = QHBoxLayout()
        progress.setSpacing(14)
        self.seekbar = PlaybackTimeline()
        self.seekbar.setRange(0, 10000)
        self.seekbar.setEnabled(False)
        self.seekbar.sliderReleased.connect(self._request_seek)
        self.seekbar.sliderMoved.connect(self.preview_seek)
        self.seekbar.setAccessibleName('播放进度')
        progress.addWidget(self.seekbar, 1)
        self.time_label = label('00:00 / 00:00', 'timecode')
        progress.addWidget(self.time_label)
        playback.addLayout(progress)
        self.control_row = PlaybackControls()
        controls = self.control_row.left_layout
        self.transport_buttons = []
        for name, symbol, action in [('上一个 · Z', 'previous', lambda: self.stepRequested.emit(-1)),
                                      ('播放 / 暂停 · 空格', 'play', self.playRequested.emit),
                                      ('下一个 · X', 'next', lambda: self.stepRequested.emit(1))]:
            control = tool(name, action, symbol)
            control.setProperty('role', 'round')
            if symbol == 'play':
                self.play_button = control
                control.setObjectName('playButton')
                control.setFixedSize(44, 44)
                control.setIconSize(QSize(22, 22))
            control.setEnabled(False)
            self.transport_buttons.append(control)
            controls.addWidget(control)
        controls = self.control_row.right_layout
        self.options = PlaybackOptions(popup_host, self, drafts, rating_source)
        controls.addWidget(self.options.volume_button)
        controls.addWidget(self.options.speed_button)
        controls.addSpacing(8)
        self.sidebar_toggle = tool('显示 / 隐藏侧栏', self.sidebarRequested.emit, 'sidebar')
        controls.addWidget(self.sidebar_toggle)
        self.fullscreen_button = tool('全屏 · Enter', self.fullscreenRequested.emit, 'full')
        controls.addWidget(self.fullscreen_button)
        self.classify_bar = self.control_row.center
        self.classify_bar.setObjectName('classifyBar')
        self.classify_buttons = []
        for text, symbol, shortcut, action in [('标签', 'tag', 'Q', self.toggle_tags),
                                              ('评分', 'heart', 'R', self.toggle_rating),
                                              ('收藏', 'star', 'W', lambda: self.favoriteRequested.emit())]:
            control = button(text, action, symbol, 'action')
            control.setToolTip(f'{text} · {shortcut}')
            control.setEnabled(False)
            self.classify_buttons.append(control)
            if symbol == 'tag':
                self.tags_button = control
                self.options.add_tags(control)
                control.setToolTip('')
            if symbol == 'heart':
                self.rating_button = control
                self.options.add_rating(control)
                control.setToolTip('')
            if symbol == 'star':
                self.favorite_button = control
                control.setCheckable(True)
            self.control_row.add_action(control)
        self.classify_bar.hide()
        playback.addWidget(self.control_row)
        player.addWidget(self.playback_panel)

        self.options.volumeRequested.connect(self.volumeRequested)
        self.options.muteRequested.connect(self.muteRequested)
        self.options.rateRequested.connect(self.rateRequested)
        self.options.ratingRequested.connect(self.ratingRequested)
        self.fullscreen = VideoFullscreen(host, self, popup_host, splitter)
        self.seek_notice = SeekNotice(self.surface)
        self.action_notice = ActionNotice(self.surface, self.fullscreen.title)
        self.fullscreenRequested.connect(self.fullscreen.toggle)

    @property
    def has_video(self):
        return self._info is not None

    def video_handle(self):
        return int(self.surface.winId())

    def present_transport(self, status, loaded, busy, *, file_busy=None, still=False):
        self._transport = status, loaded, busy, still
        file_busy = busy if file_busy is None else file_busy
        self.header.set_rename_available(loaded and not file_busy)
        for control in self.transport_buttons:
            # 图片没有播放和暂停，但仍要用上一个、下一个翻页。
            control.setEnabled(loaded and not busy and (not still or control is not self.play_button))
        for control in self.classify_buttons:
            control.setEnabled(loaded and not file_busy)
        self.seekbar.setEnabled(loaded and not busy and not still)
        if still:
            self.media_badge.setText('图片')
            self.time_label.setText('图片')
            self.seekbar.hold(0, 0)
        else:
            self.media_badge.setText({PlaybackStatus.PLAYING: '正在播放', PlaybackStatus.PAUSED: '已暂停',
                                     PlaybackStatus.ENDED: '播放结束', PlaybackStatus.IDLE: '等待播放'}.get(status, '正在加载'))
        self._render_transport()

    def _render_transport(self, force=False):
        status, loaded, busy, still = self._transport
        running = loaded and status in (PlaybackStatus.LOADING, PlaybackStatus.PLAYING)
        symbol = 'pause' if running else 'play'
        action = '暂停' if running else '重新播放' if status is PlaybackStatus.ENDED and loaded else '播放'
        tooltip = action + ' · 空格'
        self.play_button.setEnabled(loaded and not busy and not still)
        if force or self.play_button.property('iconName') != symbol or self.play_button.toolTip() != tooltip:
            self.play_button.setProperty('iconName', symbol)
            colors = self.fullscreen.colors if self.fullscreen.active else self.normal_colors
            self.play_button.setIcon(icon(symbol, colors['button_text']))
            self.play_button.setToolTip(tooltip)
            self.play_button.setAccessibleName(action)

    def present_video(self, info):
        if info is None or self._info is None or info.video_id != self._info.video_id:
            self.header.cancel_edit()
        self._info = info
        self.header.setVisible(info is not None and not self.fullscreen.active)
        values = (info.name, info.tags, info.score, info.starred) if info else ('', (), None, False)
        self.header.present(*values)
        self.fullscreen.present_video(*values)
        self.classify_bar.setVisible(info is not None)
        self.favorite_button.setChecked(bool(info and info.starred))
        self.favorite_button.setProperty('iconName', 'starFilled' if info and info.starred else 'star')
        self._favorite_icon()

    def set_rename_handler(self, handler):
        self.header.set_rename_handler(lambda name: handler(self._info.video_id, name))

    def _favorite_icon(self):
        colors = self.fullscreen.colors if self.fullscreen.active else self.normal_colors
        symbol = self.favorite_button.property('iconName') or 'star'
        self.favorite_button.setIcon(icon(symbol, colors['accent' if symbol == 'starFilled' else 'text_mid']))

    def media_loading(self):
        self.seekbar.hold(0, 0)
        self._duration = 0
        self.options.dismiss()
        self.seek_notice.clear()
        self.player_empty.hide()
        self.present_image(None)

    def present_image(self, image):
        """Show decoded still pixels, or drop the image layer for playback."""
        if image is None:
            self.image_view.clear()
            self.image_view.hide()
            return
        self.player_empty.hide()
        self.image_view.set_image(image)
        self.image_view.show()
        self.image_view.setFocus()

    def clear_media(self):
        self.present_video(None)
        self.present_transport(PlaybackStatus.IDLE, False, False)
        self.present_image(None)
        self.player_empty.show()
        self.media_badge.setText('等待播放')
        self._duration = 0
        self.seekbar.hold(0, 0)
        self.time_label.setText('00:00 / 00:00')
        self.seek_notice.clear()

    def present_progress(self, position, duration, *, playing, pending_seek):
        self._duration = duration
        if not self.seekbar.isSliderDown() and not pending_seek:
            self.time_label.setText(f'{format_time(position)} / {format_time(duration)}')
            self.seekbar.synchronize(position, duration, playing, self.options.rate)

    def freeze_progress(self):
        self.seekbar.freeze()

    def hold_position(self, target, duration):
        self._duration = duration
        self.seekbar.hold(target, duration)
        self.preview_seek(self.seekbar.value())

    def preview_seek(self, value):
        self.time_label.setText(f'{format_time(int(value / 10000 * self._duration))} / {format_time(self._duration)}')

    def _request_seek(self):
        self.seekRequested.emit(self.seekbar.value() / 10000)

    def toggle_tags(self):
        if self.tags_button.isEnabled():
            panel = self.options.tags_popup
            panel.dismiss() if panel.isVisible() else panel.open_above()

    def toggle_rating(self):
        if self.rating_button.isEnabled():
            panel = self.options.rating_popup
            panel.dismiss() if panel.isVisible() else panel.open_above()

    def handle_popup_key(self, event):
        if event.key() == Qt.Key_Escape and self.options.popup_visible():
            self.options.dismiss()
            return True
        return self.options.rating_popup.handle_key(event)

    def accept_rate(self, rate):
        self.options.accept_rate(rate)
        self.seekbar.set_playback_rate(rate)

    def reject_rate(self):
        self.options.reject_rate()

    def owns_control(self, control):
        return (owned_by(control, self) or owned_by(control, self.playback_panel) or
                any(owned_by(control, panel) for panel in self.options.panels))

    def apply_theme(self, colors):
        self.normal_colors = colors
        # 空闲区始终是深色画面，字标要用深底可读的对比，强调色仍跟随用户选择。
        dark = colors_for('dark', colors['accent_source'])
        self.wordmark.set_colors(dark['text_strong'], dark['text_faint'], dark['accent'])
        self.action_notice.set_accent(dark['accent'])
        self.update_background()
        self.header.apply_colors(colors)
        self.transportRefreshRequested.emit()
        self.fullscreen.apply_theme(colors_for('dark', colors['accent_source']))
        effective = self.fullscreen.colors if self.fullscreen.active else colors
        roots = (self, self.playback_panel, *self.options.panels)
        for root in roots:
            for control in root.findChildren(QAbstractButton):
                if control is self.play_button:
                    continue
                symbol = control.property('iconName')
                if symbol:
                    color = effective['button_text'] if control.property('role') == 'primary' else effective['text_mid']
                    control.setIcon(icon(symbol, color))
        self._favorite_icon()
        self._render_transport(force=True)
        self.control_row.adapt()
        for panel in self.options.panels:
            panel.setStyleSheet(Template(STYLE_TEMPLATE).substitute(**effective))
            panel.set_colors(effective['surface_plain'], effective['line'])
        rating = self.options.rating_popup.hearts
        rating.outline_color = QColor(effective['text_faint'])
        rating.fill_color = QColor(effective['accent'])
        rating.update()
        self.options.set_icon_color(effective['text_mid'])

    def update_background(self):
        self.player_empty.update()

    def shutdown(self):
        self.options.dismiss()
        self.seek_notice.clear()
        self.action_notice.clear()
        self.fullscreen.exit()
        self.seekbar.animation.stop()
