"""Main window composition. Playback and file operations stay in app.py."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QSplitter, QSlider, QMenu)
from appearance import Appearance, BackgroundCanvas, appearance_dialog
from theme import apply_theme
from window_chrome import TitleBar
from playback_controls import PlaybackControls
from playback_options import PlaybackOptions
from seek_slider import PlaybackTimeline
from library_view import LibraryView


def build_interface(window, bundle):
    from ui import PathLabel, icon, label, button

    def tool(name, action, symbol):
        control = button('', action, symbol, 'nav')
        control.setFixedSize(36, 36)
        control.setToolTip(name)
        control.setAccessibleName(name)
        return control

    window.appearance = Appearance(window.store.directory)
    window.theme = window.appearance.theme
    window.canvas = BackgroundCanvas(window.appearance)
    window.setCentralWidget(window.canvas)
    root = QVBoxLayout(window.canvas)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    top = TitleBar()
    top.setObjectName('topBar')
    top.setFixedHeight(48)
    window.title_bar = top
    header = QHBoxLayout(top)
    header.setContentsMargins(16, 0, 0, 0)
    header.setSpacing(8)
    avatar = QLabel()
    avatar.setFixedSize(24, 24)
    avatar.setPixmap(QPixmap(str(bundle / 'assets/yunli-chibi.png')).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
    header.addWidget(avatar)
    brand = label('MoPlayer', 'brand')
    brand.setAttribute(Qt.WA_TransparentForMouseEvents)
    header.addWidget(brand)
    header.addStretch()
    appearance = tool('外观', lambda: appearance_dialog(window), 'photo')
    appearance.setObjectName('appearanceButton')
    header.addWidget(appearance)
    more = tool('更多', lambda: None, 'more')
    more.setObjectName('settingsButton')
    menu = QMenu(more)
    for text, action in [('历史文件夹', window.folder_history),
                         ('存储路径', window.storage_dialog),
                         ('系统缩略图', window.explorer_thumbnail_dialog),
                         ('文件任务', window.task_dialog), ('帮助', window.help_dialog)]:
        menu.addAction(text, action)
    more.setMenu(menu)
    header.addWidget(more)
    caption = QHBoxLayout()
    caption.setSpacing(0)
    caption.setContentsMargins(8, 0, 0, 0)
    for name, symbol, action in [('最小化', 'minimize', window.showMinimized),
                                  ('最大化', 'maximize', window.toggle_maximized),
                                  ('关闭', 'close', window.close)]:
        control = tool(name, action, symbol)
        control.setProperty('role', 'caption')
        control.setObjectName('closeWindow' if symbol == 'close' else symbol + 'Window')
        control.setFixedSize(46, 48)
        control.setIconSize(QSize(16, 16))
        control.setFocusPolicy(Qt.NoFocus)
        caption.addWidget(control)
        if symbol == 'maximize':
            window.maximize_button = control
    header.addLayout(caption)
    root.addWidget(top)

    window.splitter = QSplitter(Qt.Horizontal)
    window.splitter.setHandleWidth(6)
    window.splitter.setChildrenCollapsible(False)
    root.addWidget(window.splitter, 1)
    window.library_view = LibraryView(window.library_controller, window.thumbnails,
                                      lambda: window.current, window)
    window.splitter.addWidget(window.library_view)

    right = QFrame()
    right.setObjectName('playerCard')
    player = QVBoxLayout(right)
    player.setContentsMargins(0, 0, 0, 0)
    player.setSpacing(0)
    window.player_header = QWidget()
    info = QVBoxLayout(window.player_header)
    info.setContentsMargins(16, 8, 16, 12)
    info.setSpacing(5)
    window.now = PathLabel('')
    window.now.setObjectName('nowPlaying')
    window.metadata = PathLabel('')
    window.metadata.setObjectName('mediaMetadata')
    info.addWidget(window.now)
    info.addWidget(window.metadata)
    window.player_header.hide()
    player.addWidget(window.player_header)
    window.media_badge = label('', 'badge')
    window.media_badge.hide()
    window.surface = QFrame()
    window.surface.setAttribute(Qt.WA_NativeWindow)
    window.player.set_hwnd(int(window.surface.winId()))
    window.surface.setObjectName('videoSurface')
    window.surface.setStyleSheet('QWidget#videoSurface { background:#08090b; border:none; }')
    window.surface.setMinimumSize(300, 170)
    surface_layout = QVBoxLayout(window.surface)
    surface_layout.setContentsMargins(0, 0, 0, 0)
    window.player_empty = QWidget()
    window.player_empty.setObjectName('playerEmpty')
    window.player_empty.setAttribute(Qt.WA_StyledBackground)
    empty = QVBoxLayout(window.player_empty)
    empty.setAlignment(Qt.AlignCenter)
    empty.setSpacing(20)
    emblem = QLabel()
    emblem.setFixedSize(56, 56)
    emblem.setPixmap(icon('play', '#424a59', 48).pixmap(48, 48))
    emblem.setAlignment(Qt.AlignCenter)
    empty.addWidget(emblem, 0, Qt.AlignHCenter)
    window.empty_import = button('导入文件夹', window.library_view.choose_folder, 'plus', 'primary')
    window.empty_import.setFixedHeight(38)
    window.empty_import.setToolTip('也可将文件夹拖入左侧列表')
    empty.addWidget(window.empty_import, 0, Qt.AlignHCenter)
    surface_layout.addWidget(window.player_empty)
    player.addWidget(window.surface, 1)

    window.playback_panel = QWidget()
    window.playback_panel.setObjectName('playbackPanel')
    playback = QVBoxLayout(window.playback_panel)
    playback.setContentsMargins(14, 4, 14, 6)
    playback.setSpacing(2)
    progress = QHBoxLayout()
    progress.setSpacing(14)
    window.seekbar = PlaybackTimeline()
    window.seekbar.setRange(0, 10000)
    window.seekbar.setEnabled(False)
    window.seekbar.sliderReleased.connect(window.seek_slider)
    window.seekbar.sliderMoved.connect(window.preview_seek)
    window.seekbar.setAccessibleName('播放进度')
    progress.addWidget(window.seekbar, 1)
    window.time_label = label('00:00 / 00:00', 'timecode')
    progress.addWidget(window.time_label)
    playback.addLayout(progress)
    window.control_row = PlaybackControls()
    controls = window.control_row.left_layout
    window.transport_buttons = []
    for name, symbol, action in [('上一个 · Z', 'previous', lambda: window.advance(-1)),
                                  ('播放 / 暂停 · 空格', 'play', window.toggle),
                                  ('下一个 · X', 'next', lambda: window.advance(1))]:
        control = tool(name, action, symbol)
        control.setProperty('role', 'round')
        if symbol == 'play':
            window.play_button = control
            control.setObjectName('playButton')
            control.setFixedSize(44, 44)
            control.setIconSize(QSize(22, 22))
        control.setEnabled(False)
        window.transport_buttons.append(control)
        controls.addWidget(control)
    controls = window.control_row.right_layout
    window.playback_options = PlaybackOptions(window)
    window.volume = window.playback_options.volume
    window.volume_button = window.playback_options.volume_button
    window.speed_button = window.playback_options.speed_button
    controls.addWidget(window.volume_button)
    controls.addWidget(window.speed_button)
    controls.addSpacing(8)
    window.sidebar_toggle = tool('显示 / 隐藏侧栏', window.toggle_sidebar, 'sidebar')
    controls.addWidget(window.sidebar_toggle)
    window.fullscreen_button = tool('全屏 · Enter', window.enter_fullscreen, 'full')
    controls.addWidget(window.fullscreen_button)
    window.classify_bar = window.control_row.center
    window.classify_bar.setObjectName('classifyBar')
    window.classify_buttons = []
    for text, symbol, shortcut, action in [('标签', 'tag', 'Q', window.tags_dialog),
                                          ('评分', 'heart', 'R', window.rating_dialog),
                                          ('收藏', 'star', 'W', lambda: window.favorite(toggle=True))]:
        control = button(text, action, symbol, 'action')
        control.setToolTip(f'{text} · {shortcut}')
        control.setEnabled(False)
        window.classify_buttons.append(control)
        if symbol == 'tag':
            window.tags_button = control
            window.playback_options.add_tags(control)
            control.setToolTip('')
        if symbol == 'heart':
            window.rating_button = control
            window.playback_options.add_rating(control)
            control.setToolTip('')
        if symbol == 'star':
            window.favorite_button = control
            control.setCheckable(True)
        window.control_row.add_action(control)
    window.classify_bar.hide()
    playback.addWidget(window.control_row)
    player.addWidget(window.playback_panel)
    window.splitter.addWidget(right)
    window.splitter.setStretchFactor(1, 1)
    window.splitter.setSizes([380, 1020])
    window.statusBar().setSizeGripEnabled(False)
    window.statusBar().hide()
    apply_theme(window)
    window.sync_caption_button()
