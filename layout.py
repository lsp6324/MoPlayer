"""Compose the window chrome, library and player as independent views."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QSplitter, QMenu
from appearance import Appearance, BackgroundCanvas
from appearance_dialog import AppearanceDialog
from theme import apply_theme
from window_chrome import TitleBar
from player_view import PlayerView
from library_view import LibraryView
from infrastructure.library_preferences import LibraryPreferences


def build_interface(window, bundle):
    from ui import label, button

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
    def show_appearance():
        AppearanceDialog(window,window.appearance,
            preview_theme=lambda theme,accent:apply_theme(window,theme,accent),
            preview_background=window.canvas.set_background).exec()
    appearance = tool('外观', show_appearance, 'photo')
    appearance.setObjectName('appearanceButton')
    header.addWidget(appearance)
    more = tool('更多', lambda: None, 'more')
    more.setObjectName('settingsButton')
    menu = QMenu(more)
    for text, action in [('历史文件夹', window.folder_history),
                         ('接管已有文件夹', window.takeover_dialog),
                         ('归档设置', window.storage_dialog),
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
                                      lambda: window.current, window, preferences=LibraryPreferences(window.store.directory))
    window.splitter.addWidget(window.library_view)

    window.player_view = PlayerView(window, window.canvas, window.splitter,
                                    window.tag_drafts, window.rating_value,
                                    paint_background=window.canvas.paint_region)
    window.splitter.addWidget(window.player_view)
    window.splitter.setStretchFactor(1, 1)
    window.splitter.setSizes([380, 1020])
    window.statusBar().setSizeGripEnabled(False)
    window.statusBar().hide()
    apply_theme(window)
    window.canvas.backgroundChanged.connect(lambda:apply_theme(window,window.theme,window.accent))
    window.canvas.geometryChanged.connect(window.player_view.update_background)
    window.sync_caption_button()
