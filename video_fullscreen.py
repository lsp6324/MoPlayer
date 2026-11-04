import time  # 根据真实鼠标活动控制浮层自动隐藏。
from PySide6.QtCore import QObject, Qt, QTimer, QPoint  # 在 Qt 主线程维护全屏状态。
from PySide6.QtGui import QCursor  # 即使鼠标在 VLC 原生子窗口上也能检测移动。
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QSplitter  # 复用现有播放控件并显示独立浮层。

def widgets(item):  # 递归找到纯布局中的可隐藏控件。
    if item.widget():  # 独立容器隐藏后其子控件会一起隐藏。
        return [item.widget()]  # 不逐个破坏内部可见状态。
    layout = item.layout()  # 页面标题等内容使用嵌套布局。
    return [child for index in range(layout.count()) for child in widgets(layout.itemAt(index))] if layout else []  # 忽略伸缩空白。

class VideoFullscreen(QObject):  # 保持原生视频句柄不变的全屏布局协调器。
    def __init__(self, window):  # 绑定当前播放器窗口。
        super().__init__(window)  # 生命周期随主窗口结束。
        self.window, self.active, self.hidden = window, False, []  # 与浏览和播放上下文完全独立。
        self.overlay = QFrame(window, Qt.Tool | Qt.FramelessWindowHint)  # 独立原生工具窗可覆盖 VLC 视频子窗口。
        self.overlay.setObjectName('fullscreenControls')  # 为浮层提供单独样式。
        self.overlay.setAttribute(Qt.WA_ShowWithoutActivating)  # 浮层显示不抢走快捷键焦点。
        self.overlay.setStyleSheet('QFrame#fullscreenControls{background:#f7f8fa;border:1px solid #cfd6e0;border-radius:5px;}')  # 浮层沿用紧凑的工具栏边界。
        self.overlay_layout = QVBoxLayout(self.overlay)  # 浮层中复用同一套进度、音量和播放按钮。
        self.overlay_layout.setContentsMargins(16, 12, 16, 10)  # 浮层只保留必要的点击留白。
        self.timer = QTimer(self)  # 检测原生视频上的鼠标活动。
        self.timer.setInterval(100)  # 移动后最多约十分之一秒出现控制栏。
        self.timer.timeout.connect(self.poll)  # 全部界面操作留在 GUI 线程。

    def toggle(self):  # 按 Enter 或点击同一个按钮切换模式。
        self.exit() if self.active else self.enter()  # 避免嵌套全屏与重复保存状态。

    def enter(self):  # 将视频画面铺满当前窗口所在屏幕。
        if self.active:  # 已全屏时不覆盖原始布局快照。
            return  # 保持当前状态。
        window = self.window  # 简化主窗口访问。
        self.geometry, self.window_state = window.saveGeometry(), window.windowState()  # 恢复普通或最大化窗口。
        self.root = window.canvas.layout()  # 保存最外层卡片布局。
        self.splitter = window.canvas.findChild(QSplitter)  # 复用既有可拖动分隔区域。
        self.split_sizes = self.splitter.sizes()  # 记录用户调整过的左右比例。
        self.card = window.surface.parentWidget()  # 保持播放器卡片及原生画面始终在原父窗口。
        self.card_layout = self.card.layout()  # 仅改变周边布局和可见性。
        self.saved_layouts = [(layout, layout.contentsMargins(), layout.spacing()) for layout in [self.root, self.card_layout]]  # 退出时逐项恢复留白。
        self.card_style, self.surface_style = self.card.styleSheet(), window.surface.styleSheet()  # 保存主题样式。
        self.panel_index = self.card_layout.indexOf(window.playback_panel)  # 记录控制栏原位置。
        self.hidden = []  # 每次进入只记录本次隐藏的可见控件。
        candidates = [widget for index in range(self.root.count()) if self.root.itemAt(index).widget() is not self.splitter for widget in widgets(self.root.itemAt(index))]  # 顶部导航及页面标题退出观看模式。
        candidates += [self.splitter.widget(0), window.statusBar()]  # 左目录和页脚在观看时隐藏。
        candidates += [widget for index in range(self.card_layout.count()) for widget in widgets(self.card_layout.itemAt(index)) if widget not in [window.surface, window.playback_panel]]  # 隐藏视频标题、分类按钮和分隔线。
        for widget in candidates:  # 只还原原来明确可见的控件。
            if not widget.isHidden():  # 不让原来主动隐藏的内容意外出现。
                self.hidden.append(widget)  # 保存恢复列表。
                widget.hide()  # 视频外的布局内容全部隐藏。
        for layout, margins, spacing in self.saved_layouts:  # 全屏移除卡片周边留白。
            layout.setContentsMargins(0, 0, 0, 0)  # 画面贴合屏幕边界。
            layout.setSpacing(0)  # 不保留隐藏分区之间的空隙。
        self.card.setStyleSheet('QFrame#playerCard{background:black;border:none;border-radius:0;}')  # 不让浅色圆角边框占据全屏画面。
        window.surface.setStyleSheet('QFrame#videoSurface{background:black;border:none;border-radius:0;}')  # 黑色边缘保持视频比例。
        self.overlay_layout.addWidget(window.playback_panel)  # 只移动控制栏，VLC HWND 及解码状态保持不变。
        window.fullscreen_button.setText('退出全屏')  # 全屏浮层提供明确退出入口。
        self.active = True  # 在窗口改变前发布全屏状态。
        self.last_cursor, self.last_activity = QCursor.pos(), time.monotonic()  # 首次进入暂时显示控制栏。
        window.showFullScreen()  # 整个原生窗口承载视频，其他应用布局已隐藏。
        window.surface.setFocus()  # 快捷键继续作用于播放区域。
        self.timer.start()  # 原生视频表面的鼠标活动也能被检测。
        QTimer.singleShot(0, self.poll)  # 等全屏几何稳定后定位底部浮层。

    def poll(self):  # 更新控制栏位置和自动隐藏状态。
        if not self.active:  # 退出后忽略延迟回调。
            return  # 不再次显示已关闭的浮层。
        window, cursor = self.window, QCursor.pos()  # 读取真实系统指针位置。
        if cursor != self.last_cursor:  # 仅真实移动延长显示时间。
            self.last_cursor, self.last_activity = cursor, time.monotonic()  # 不依赖 VLC 是否转发 Qt 鼠标事件。
        origin = window.mapToGlobal(QPoint(0, 0))  # 多屏幕使用主窗口实际全屏位置。
        width = min(1200, max(320, window.width() - 64))  # 浮层留出左右边距并限制超宽。
        height = self.overlay.sizeHint().height()  # 控制栏高度跟随字体及 DPI。
        self.overlay.setGeometry(origin.x() + (window.width() - width) // 2, origin.y() + window.height() - height - 24, width, height)  # 始终放在当前全屏视频的底部。
        blocked = QApplication.activeModalWidget() or QApplication.activePopupWidget()  # 标签、评分和其他弹窗保持最高优先级。
        visible = not blocked and (window.isActiveWindow() or self.overlay.isActiveWindow()) and (time.monotonic() - self.last_activity < 2.5 or self.overlay.geometry().contains(cursor))  # 切到其他软件或空闲时不让控制栏浮在桌面。
        self.overlay.setVisible(bool(visible))  # 鼠标位于控制栏上时保持可操作。

    def exit(self):  # 恢复用户进入全屏前的完整工作布局。
        if not self.active:  # 普通模式按 Esc 不改变最大化状态。
            return  # 不执行多余窗口切换。
        self.active = False  # 先阻止延迟轮询重新显示浮层。
        self.timer.stop()  # 普通模式无需监视鼠标。
        self.overlay.hide()  # 恢复布局前先隐藏独立原生浮层。
        window = self.window  # 使用原主窗口恢复控件。
        self.card_layout.insertWidget(self.panel_index, window.playback_panel)  # 将同一套控件放回原位置。
        window.playback_panel.show()  # 控制栏恢复普通常显模式。
        window.fullscreen_button.setText('全屏')  # 按钮恢复普通状态。
        self.card.setStyleSheet(self.card_style)  # 恢复用户主题卡片样式。
        window.surface.setStyleSheet(self.surface_style)  # 恢复普通画面圆角与边框。
        for layout, margins, spacing in self.saved_layouts:  # 逐项恢复进入前的布局参数。
            layout.setContentsMargins(margins)  # 恢复原内边距。
            layout.setSpacing(spacing)  # 恢复原分区间距。
        for widget in self.hidden:  # 恢复目录、导航、分类和页脚。
            widget.show()  # 不改变播放快照或视频身份。
        window.showNormal()  # 离开原生全屏状态。
        window.restoreGeometry(self.geometry)  # 恢复原窗口位置、屏幕和大小。
        window.setWindowState(self.window_state)  # 保留进入前的最大化状态。
        self.splitter.setSizes(self.split_sizes)  # 恢复用户拖动过的目录宽度。
        window.surface.setFocus()  # 返回视频区域继续使用原快捷键。
