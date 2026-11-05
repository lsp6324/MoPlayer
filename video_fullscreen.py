import time  # 根据真实鼠标活动控制浮层自动隐藏。
from PySide6.QtCore import QObject, QTimer, QPoint, QRect, Qt, QEvent
from PySide6.QtGui import QCursor, QColor
from PySide6.QtWidgets import QApplication, QVBoxLayout, QSlider, QWidget
from floating_surface import FloatingSurface, owned_by, player_is_active, raise_surface
from media_header import MediaHeader
from video_cursor import VideoCursor


STYLE = '''QFrame#fullscreenControls { background:transparent; border:none; }
QFrame#fullscreenControls QWidget#playbackPanel { border:none; }
QFrame#fullscreenControls QLabel { color:#e8edf5; }
QFrame#fullscreenControls QLabel[role="timecode"] { color:#c4cee0; }
QFrame#fullscreenControls QPushButton { background:transparent; border:1px solid transparent; border-radius:7px; color:#dde3ee; padding:5px 9px; }
QFrame#fullscreenControls QPushButton:hover { background:rgba(255,255,255,34); border-color:rgba(255,255,255,46); }
QFrame#fullscreenControls QPushButton:pressed { background:rgba(255,255,255,56); }
QFrame#fullscreenControls QPushButton#playButton { background:#3b6fd4; border-color:#3b6fd4; padding:8px; }
QFrame#fullscreenControls QPushButton#playButton:hover { background:#4a7ee0; border-color:#4a7ee0; }
QFrame#fullscreenControls QPushButton#speedButton { padding:0; }
QFrame#fullscreenControls QPushButton[role="action"]:checked { color:#9fc0ff; background:rgba(91,139,223,42); }
QFrame#fullscreenControls QSlider::groove:horizontal { height:4px; border-radius:2px; background:rgba(255,255,255,52); }
QFrame#fullscreenControls QSlider::sub-page:horizontal { background:#7ba7f0; border-radius:2px; }
QFrame#fullscreenControls QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0; border-radius:6px; background:#ffffff; border:2px solid #7ba7f0; }
QFrame#fullscreenControls QSlider::handle:horizontal:hover { background:#f2f6ff; border-color:#9dbcf5; }'''  # 深色浮层只影响全屏观看态，不改变普通界面。

def widgets(item):  # 递归找到纯布局中的可隐藏控件。
    if item.widget():  # 独立容器隐藏后其子控件会一起隐藏。
        return [item.widget()]  # 不逐个破坏内部可见状态。
    layout = item.layout()  # 页面标题等内容使用嵌套布局。
    return [child for index in range(layout.count()) for child in widgets(layout.itemAt(index))] if layout else []  # 忽略伸缩空白。


class FullscreenTitle(FloatingSurface):
    def __init__(self, host):
        super().__init__(host, radius=10, background=QColor(26, 30, 38, 232),
                         border=QColor(255, 255, 255, 35))
        self.setObjectName('fullscreenTitle')
        self.setWindowFlag(Qt.WindowTransparentForInput)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet('QFrame#fullscreenTitle { background:transparent; border:none; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        self.header = MediaHeader()
        self.header.apply_colors(dict(text_strong='#f2f4f8',text_mid='#c4cee0',accent='#9fc0ff',
                                      selected='#34445b',line='#8392a8'))
        layout.addWidget(self.header)

    @property
    def filename(self):
        return self.header.filename

    def present_video(self, filename, tags, score, starred):
        self.header.present(filename,tags,score,starred)

    def reposition(self, bounds):
        width = min(900, max(1, bounds.width()-64))
        self.setGeometry(bounds.x()+(bounds.width()-width)//2,
                         bounds.y()+24,width,self.sizeHint().height())

class VideoFullscreen(QObject):  # 保持视频句柄不变的全屏布局协调器。
    def __init__(self, window, view, canvas, splitter):  # 只接收明确的 UI 展示接口。
        super().__init__(window)  # 生命周期随主窗口结束。
        self.view, self.canvas, self.splitter = view, canvas, splitter
        self.window, self.active, self.hidden = window, False, []  # 与浏览和播放上下文完全独立。
        self.cursor = VideoCursor(self.view.surface)
        self.title = FullscreenTitle(self.canvas)
        self.presentation_visible = False
        self.was_interacting = False
        self.cursor_position = QCursor.pos
        self.overlay = FloatingSurface(self.canvas, radius=12,
                                       background='#20252e', border='#3d4654')
        self.overlay.hide()
        self.overlay.setObjectName('fullscreenControls')  # 为浮层提供单独样式。
        self.overlay.setFocusPolicy(Qt.NoFocus)
        self.overlay.setStyleSheet(STYLE)  # 深色浮层与视频画面形成对照。

        self.overlay_layout = QVBoxLayout(self.overlay)  # 浮层中复用同一套进度、音量和播放按钮。
        self.overlay_layout.setContentsMargins(18, 12, 18, 12)  # 留出圆角所需的内边距。
        self.geometry_cache = QRect()  # 记录上一次浮层位置，避免每轮都触发布局。
        self.timer = QTimer(self)  # 检测视频上的鼠标活动。
        self.timer.setInterval(100)  # 移动后最多约十分之一秒出现控制栏。
        self.timer.timeout.connect(self.poll)  # 全部界面操作留在 GUI 线程。
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if (self.active and event.type() == QEvent.MouseMove and
                isinstance(watched, QWidget) and owned_by(watched, self.window)):
            self.poll(event.globalPosition().toPoint())
        elif self.active and watched is self.window:
            if event.type() in (QEvent.Hide, QEvent.Close):
                self.set_presentation(False)
            elif event.type() in (QEvent.WindowDeactivate, QEvent.WindowStateChange):
                QTimer.singleShot(0, self, self.poll)
        return False

    def present_video(self, filename, tags, score, starred):
        self.title.present_video(filename,tags,score,starred)
        if self.active:
            bounds = QRect(self.canvas.mapToGlobal(QPoint()), self.canvas.size())
            self.title.reposition(bounds)
            if self.presentation_visible and filename:
                self.title.show()
                raise_surface(self.title)
            elif not filename:
                self.title.hide()

    def set_presentation(self, visible, hide_cursor=False):
        self.presentation_visible = visible
        if visible:
            self.overlay.show()
            raise_surface(self.overlay)
            if self.title.filename:
                self.title.show()
                raise_surface(self.title)
            for panel in self.view.options.panels:
                if panel.isVisible():
                    raise_surface(panel)
        else:
            self.overlay.hide()
            self.title.hide()
        self.cursor.set_hidden(hide_cursor and not visible)

    def toggle(self):  # 按 Enter 或点击同一个按钮切换模式。
        self.exit() if self.active else self.enter()  # 避免嵌套全屏与重复保存状态。

    def enter(self):  # 将视频画面铺满当前窗口所在屏幕。
        if self.active:  # 已全屏时不覆盖原始布局快照。
            return  # 保持当前状态。
        window = self.window  # 简化主窗口访问。
        self.view.options.dismiss()
        self.geometry, self.window_state = window.saveGeometry(), window.windowState()  # 恢复普通或最大化窗口。
        self.root = self.canvas.layout()  # 保存最外层卡片布局。
        self.split_sizes = self.splitter.sizes()  # 记录用户调整过的左右比例。
        self.card = self.view.surface.parentWidget()  # 保持播放器卡片及原生画面始终在原父窗口。
        self.card_layout = self.card.layout()  # 仅改变周边布局和可见性。
        self.saved_layouts = [(layout, layout.contentsMargins(), layout.spacing()) for layout in [self.root, self.card_layout]]  # 退出时逐项恢复留白。
        self.card_style, self.surface_style = self.card.styleSheet(), self.view.surface.styleSheet()  # 保存主题样式。
        self.panel_index = self.card_layout.indexOf(self.view.playback_panel)  # 记录控制栏原位置。
        self.hidden = []  # 每次进入只记录本次隐藏的可见控件。
        candidates = [widget for index in range(self.root.count()) if self.root.itemAt(index).widget() is not self.splitter for widget in widgets(self.root.itemAt(index))]  # 顶部导航及页面标题退出观看模式。
        candidates += [self.splitter.widget(0), window.statusBar()]  # 左目录和页脚在观看时隐藏。
        candidates += [widget for index in range(self.card_layout.count()) for widget in widgets(self.card_layout.itemAt(index)) if widget not in [self.view.surface, self.view.playback_panel]]  # 隐藏视频标题、分类按钮和分隔线。
        for widget in candidates:  # 只还原原来明确可见的控件。
            if not widget.isHidden():  # 不让原来主动隐藏的内容意外出现。
                self.hidden.append(widget)  # 保存恢复列表。
                widget.hide()  # 视频外的布局内容全部隐藏。
        for layout, margins, spacing in self.saved_layouts:  # 全屏移除卡片周边留白。
            layout.setContentsMargins(0, 0, 0, 0)  # 画面贴合屏幕边界。
            layout.setSpacing(0)  # 不保留隐藏分区之间的空隙。
        self.card.setStyleSheet('QFrame#playerCard{background:black;border:none;border-radius:0;}')  # 不让浅色圆角边框占据全屏画面。
        self.view.surface.setStyleSheet('QFrame#videoSurface{background:black;border:none;border-radius:0;}')  # 黑色边缘保持视频比例。
        self.overlay_layout.addWidget(self.view.playback_panel)  # 在同一主窗口内重排控制栏，视频上下文保持不变。
        self.view.playback_panel.show()
        self.view.sidebar_toggle.hide()
        self.view.fullscreen_button.setToolTip('退出全屏 · Esc')  # 全屏浮层提供明确退出入口。
        self.active = True  # 在窗口改变前发布全屏状态。
        self.title.reposition(QRect(self.canvas.mapToGlobal(QPoint()), self.canvas.size()))
        self.was_interacting = False
        self.style_popovers()
        self.last_cursor, self.last_activity = QCursor.pos(), time.monotonic()  # 首次进入暂时显示控制栏。
        self.geometry_cache = QRect()  # 全屏几何改变后必须重新定位。
        window.showFullScreen()  # 整个原生窗口承载视频，其他应用布局已隐藏。
        self.view.surface.setFocus()  # 快捷键继续作用于播放区域。
        self.timer.start()  # 视频表面的鼠标活动也能被检测。
        QTimer.singleShot(0, self.poll)  # 等全屏几何稳定后定位底部浮层。

    def poll(self, cursor=None):  # 鼠标事件立即响应，定时器只负责空闲回收。
        if not self.active:  # 退出后忽略延迟回调。
            return  # 不再次显示已关闭的浮层。
        window = self.window
        cursor = self.cursor_position() if cursor is None else cursor
        host = self.canvas
        bounds = QRect(host.mapToGlobal(QPoint()), host.size())
        inside = bounds.contains(cursor)
        if cursor != self.last_cursor and inside:  # 其他屏幕上的移动不唤出控件。
            self.last_cursor, self.last_activity = cursor, time.monotonic()  # 不依赖 视频解码器的事件转发。
        width = min(1200, max(320, host.width() - 64))
        height = self.overlay.sizeHint().height()  # 控制栏高度跟随字体及 DPI。
        target = QRect(bounds.x() + (host.width() - width) // 2,
                       bounds.bottom() - height - 23, width, height)
        if target != self.geometry_cache:  # 只有位置或尺寸变化时才重排。
            self.overlay.setGeometry(target)  # 减少无意义的重复布局。
            self.geometry_cache = target  # 记录本次结果。
        self.title.reposition(bounds)
        options = self.view.options
        own_popup = options.owns_active_popup()
        blocked = QApplication.activeModalWidget() or (QApplication.activePopupWidget() and not own_popup)
        active = player_is_active(window) or own_popup
        bottom = inside and cursor.y() >= bounds.bottom() - max(96, height + 48)
        interacting = any(slider.isSliderDown() for slider in self.view.playback_panel.findChildren(QSlider))
        over_controls = self.overlay.geometry().contains(cursor)
        held = bottom or over_controls or options.popup_visible() or interacting or own_popup
        if held or self.was_interacting:
            self.last_activity = time.monotonic()
        self.was_interacting = bool(held)
        visible = not blocked and active and (held or time.monotonic() - self.last_activity < 2.5)
        if blocked or not active:
            self.view.options.dismiss()
        self.set_presentation(visible, hide_cursor=active and not blocked and inside)

    def exit(self):  # 恢复用户进入全屏前的完整工作布局。
        if not self.active:  # 普通模式按 Esc 不改变最大化状态。
            return  # 不执行多余窗口切换。
        self.active = False  # 先阻止延迟轮询重新显示浮层。
        self.timer.stop()  # 普通模式无需监视鼠标。
        self.set_presentation(False)
        self.geometry_cache = QRect()  # 下次进入重新计算位置。
        window = self.window  # 使用原主窗口恢复控件。
        self.view.options.dismiss()
        self.card_layout.insertWidget(self.panel_index, self.view.playback_panel)  # 将同一套控件放回原位置。
        self.view.playback_panel.show()  # 控制栏恢复普通常显模式。
        self.view.sidebar_toggle.show()
        self.view.fullscreen_button.setToolTip('全屏 · Enter')  # 按钮恢复普通状态。
        self.card.setStyleSheet(self.card_style)  # 恢复用户主题卡片样式。
        self.view.surface.setStyleSheet(self.surface_style)  # 恢复普通画面圆角与边框。
        for layout, margins, spacing in self.saved_layouts:  # 逐项恢复进入前的布局参数。
            layout.setContentsMargins(margins)  # 恢复原内边距。
            layout.setSpacing(spacing)  # 恢复原分区间距。
        for widget in self.hidden:  # 恢复目录、导航、分类和页脚。
            widget.show()  # 不改变播放快照或视频身份。
        window.showNormal()  # 离开原生全屏状态。
        window.restoreGeometry(self.geometry)  # 恢复原窗口位置、屏幕和大小。
        window.setWindowState(self.window_state)  # 保留进入前的最大化状态。
        self.splitter.setSizes(self.split_sizes)  # 恢复用户拖动过的目录宽度。
        window.statusBar().hide()
        self.view.header.setVisible(bool(self.view.has_video))
        self.view.apply_theme(self.view.normal_colors)
        self.view.surface.setFocus()  # 返回视频区域继续使用原快捷键。

    def style_popovers(self):
        self.view.apply_theme(self.view.normal_colors)
