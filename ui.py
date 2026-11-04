from PySide6.QtCore import Qt, QSize, QPointF  # 设置统一布局尺寸和矢量图标坐标。
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF  # 绘制一致的细线界面图标。
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSplitter, QSlider, QMenu  # 构建紧凑的桌面工具栏与播放器工作区。
from appearance import Appearance, BackgroundCanvas, appearance_dialog  # 接入持久化背景和外观弹窗。

STYLE = '''
QMainWindow { background:#eef0f3; } /* 使用中性灰作为窗口底色。 */
QWidget { font-family:"Microsoft YaHei UI"; font-size:12px; color:#30353c; background:transparent; } /* 统一功能文字的字号和对比度。 */
QDialog,QMessageBox { background:#f8f9fb; } /* 对话框使用稳定浅色底板。 */
QFrame#topBar { background:rgba(250,251,252,245); border-bottom:1px solid #d7dce3; } /* 工具栏使用直线边界，不再做悬浮品牌卡片。 */
QFrame#libraryCard,QFrame#playerCard { background:rgba(255,255,255,240); border:1px solid #d7dce3; border-radius:4px; } /* 两个功能区以细边框区分，减少装饰。 */
QLabel[role="brand"] { font-family:"Segoe UI"; font-size:14px; font-weight:600; color:#272c33; } /* 应用名称收回到普通工具栏尺度。 */
QLabel[role="sectionTitle"] { font-size:12px; font-weight:600; color:#343a43; } /* 分区标题只承担功能识别。 */
QLabel[role="muted"] { color:#777f8a; font-size:11px; } /* 次要信息采用中性灰。 */
QLabel[role="badge"] { color:#707984; padding:0 4px; font-size:11px; } /* 数量和播放状态改为普通文字，不使用胶囊底板。 */
QLabel#nowPlaying { font-size:12px; color:#424a54; } /* 文件名保持单行，不挤占画面。 */
QLabel#directoryPath { color:#7a828d; font-size:11px; padding:3px 0; } /* 路径用次要层级显示。 */
QPushButton { border:1px solid #d5dbe3; border-radius:4px; background:#fff; padding:6px 10px; color:#424a54; } /* 普通按钮使用桌面工具常见的紧凑尺寸。 */
QPushButton:hover { border-color:#aebbd0; background:#f0f4fa; color:#245ba8; } /* 悬停反馈保持克制。 */
QPushButton:pressed { background:#e1e9f5; border-color:#8fa7cb; } /* 按下时明确反馈操作。 */
QPushButton:disabled { color:#b1b6bf; background:#f5f6f8; border-color:#e6e9ee; } /* 禁用控件不与主要内容竞争。 */
QPushButton[role="primary"] { background:#2f66bd; color:white; border:1px solid #2f66bd; } /* 蓝色仅强调导入和播放等主要操作。 */
QPushButton[role="primary"]:hover { background:#2559ac; border-color:#2559ac; } /* 主按钮悬停加深。 */
QPushButton[role="nav"] { background:transparent; border-color:transparent; padding:6px 9px; color:#505a68; } /* 导航与设置使用平面工具栏按钮。 */
QPushButton[role="nav"]:hover { background:#e7edf5; color:#245ba8; } /* 功能按钮悬停才显示底色。 */
QPushButton[role="round"] { border-radius:4px; padding:7px; background:transparent; border-color:transparent; } /* 前后切换改为紧凑的方形图标按钮。 */
QPushButton#playButton { border-radius:5px; padding:8px; background:#2f66bd; border:1px solid #2f66bd; } /* 播放按钮采用单一蓝色强调。 */
QPushButton#playButton:hover { background:#2559ac; } /* 播放按钮保留直接反馈。 */
QPushButton[role="action"] { background:transparent; border:1px solid transparent; color:#505a68; border-radius:4px; padding:5px 8px; } /* 分类操作使用次级工具按钮。 */
QPushButton[role="action"]:hover { background:#e9eff7; border-color:#d4deec; } /* 分类按钮悬停时才强调。 */
QPushButton[role="quiet"] { border-color:transparent; background:transparent; color:#7a828e; padding:4px 6px; font-size:11px; } /* 扫描取消保持较低视觉权重。 */
QTreeView#libraryTree { border:none; outline:none; background:transparent; padding:0; selection-background-color:transparent; } /* 目录卡片内部由缩略图委托绘制行背景。 */
QTreeView#libraryTree::branch { background:transparent; } /* 展开箭头周边不出现不协调底色。 */
QListWidget { border:1px solid #d7dce3; background:#fff; border-radius:4px; padding:4px; outline:none; } /* 历史和收藏沿用普通文件列表的边界。 */
QLineEdit,QComboBox,QPlainTextEdit,QTextEdit { background:#fff; border:1px solid #cfd6e0; border-radius:4px; padding:7px; selection-background-color:#2f66bd; } /* 输入控件使用一致的紧凑边框。 */
QLineEdit:focus,QComboBox:focus { border-color:#74a2f6; } /* 输入焦点以蓝色边框明确展示。 */
QComboBox::drop-down { border:none; width:26px; } /* 下拉按钮避免原生粗糙分隔。 */
QComboBox QAbstractItemView { background:white; selection-background-color:#e8f1ff; selection-color:#255ab0; } /* 下拉列表保持蓝白配色。 */
QSlider::groove:horizontal { height:5px; border-radius:2px; background:#e4ecf9; } /* 进度和音量滑轨更细腻。 */
QSlider::sub-page:horizontal { background:#4081f4; border-radius:2px; } /* 已播放区域使用品牌蓝色。 */
QSlider::handle:horizontal { width:12px; height:12px; margin:-5px 0; border-radius:7px; background:white; border:2px solid #4081f4; } /* 进度拖动点有清晰边界。 */
QScrollBar:vertical { background:transparent; width:6px; margin:3px 0; } /* 目录滚动条减少视觉噪声。 */
QScrollBar::handle:vertical { background:#cad8ee; min-height:28px; border-radius:3px; } /* 滚动滑块使用低饱和度蓝灰。 */
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; } /* 隐藏多余滚动箭头。 */
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; } /* 滑块外轨道透明。 */
QScrollBar:horizontal { background:transparent; height:6px; } /* 窄侧栏时仍允许横向浏览。 */
QScrollBar::handle:horizontal { background:#cad8ee; min-width:28px; border-radius:3px; } /* 水平滑块保持同样视觉语言。 */
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; } /* 不额外增加横向按钮。 */
QSplitter::handle { background:transparent; width:7px; } /* 左右功能区之间保留窄的可拖动间距。 */
QSplitter::handle:hover { background:rgba(84,136,235,35); border-radius:5px; } /* 拖动分隔处悬停才提示可调整。 */
QStatusBar { background:#eef0f3; color:#727b88; font-size:10px; min-height:20px; padding:0 10px 2px; } /* 状态栏只显示实际任务和操作反馈。 */
QStatusBar::item { border:none; } /* 去除原生状态栏边框。 */
QLabel#backgroundPreview { background:#eef1f5; border:1px solid #d5dce5; border-radius:4px; color:#727b88; } /* 背景预览不添加额外装饰。 */
QMenu { background:#fff; border:1px solid #cfd6df; padding:4px; } /* 低频功能集中到标准菜单中。 */
QMenu::item { padding:7px 24px 7px 12px; } /* 菜单保持清晰可点击的行高。 */
QMenu::item:selected { background:#e8eff9; color:#245ba8; } /* 菜单选择使用同一蓝色反馈。 */
QToolTip { background:#233a61; color:#fff; border:none; padding:7px; } /* 快捷键提示保持简洁可读。 */
'''  # 所有视觉样式集中维护，不影响业务逻辑。

def icon(name, color='#6984ac', size=24):  # 绘制统一的圆角细线图标。
    pixmap = QPixmap(size * 2, size * 2)  # 用双倍像素保证高 DPI 下清晰。
    pixmap.fill(Qt.transparent)  # 保留背景透明。
    painter = QPainter(pixmap)  # 在图标画布上绘制。
    painter.setRenderHint(QPainter.Antialiasing)  # 平滑图标线条。
    painter.scale(size * 2 / 24, size * 2 / 24)  # 将标准 24 单位坐标映射到目标分辨率。
    painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # 使用统一线宽和圆角端点。
    paths = {  # 用清晰的线段描述常用操作图标。
        'folder': [[(3, 7), (9, 7), (11, 9), (21, 9), (21, 20), (3, 20), (3, 7)], [(3, 7), (3, 5), (9, 5), (11, 7), (20, 7)]],  # 文件夹轮廓。
        'history': [[(4, 10), (4, 4), (1, 7)], [(12, 7), (12, 12), (16, 14)]],  # 历史时钟指针与返回箭头。
        'star': [[(12, 3), (15, 9), (22, 10), (17, 15), (18, 22), (12, 18), (6, 22), (7, 15), (2, 10), (9, 9), (12, 3)]],  # 收藏五角星。
        'tag': [[(3, 4), (12, 4), (22, 14), (14, 22), (3, 11), (3, 4)]],  # 标签吊牌轮廓。
        'score': [[(5, 19), (5, 13)], [(12, 19), (12, 5)], [(19, 19), (19, 9)]],  # 评分柱形标记。
        'photo': [[(3, 4), (21, 4), (21, 20), (3, 20), (3, 4)], [(3, 17), (9, 11), (13, 15), (16, 12), (21, 17)]],  # 自定义背景图标。
        'full': [[(8, 3), (3, 3), (3, 8)], [(16, 3), (21, 3), (21, 8)], [(3, 16), (3, 21), (8, 21)], [(16, 21), (21, 21), (21, 16)]],  # 视频全屏使用四角展开图标。
        'volume': [[(3, 9), (7, 9), (12, 5), (12, 19), (7, 15), (3, 15), (3, 9)], [(16, 8), (18, 12), (16, 16)], [(19, 5), (22, 12), (19, 19)]],  # 音量扬声器。
        'plus': [[(12, 5), (12, 19)], [(5, 12), (19, 12)]],  # 导入按钮加号。
        'tasks': [[(9, 6), (21, 6)], [(9, 12), (21, 12)], [(9, 18), (21, 18)], [(3, 6), (4, 7), (6, 4)], [(3, 12), (4, 13), (6, 10)], [(3, 18), (4, 19), (6, 16)]],  # 归档任务列表。
        'help': [[(9, 8), (10, 6), (14, 6), (16, 8), (15, 10), (12, 12), (12, 14)], [(12, 18), (12, 18.2)]],  # 帮助问号。
        'pause': [[(8, 6), (8, 18)], [(16, 6), (16, 18)]],  # 暂停双竖线。
        'previous': [[(5, 6), (5, 18)], [(18, 5), (8, 12), (18, 19), (18, 5)]],  # 上一个视频。
        'next': [[(19, 6), (19, 18)], [(6, 5), (16, 12), (6, 19), (6, 5)]],  # 下一个视频。
    }  # 结束统一图标路径表。
    if name == 'play':  # 播放使用实心三角形突出主要控制。
        painter.setBrush(QColor(color))  # 填充与线条相同的颜色。
        painter.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))  # 适当右移以获得视觉居中。
    for points in paths.get(name, []):  # 绘制当前图标的各条折线。
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))  # 根据标准坐标生成平滑线条。
    if name in ('history', 'help'):  # 时钟和帮助图标补充外圆。
        painter.drawEllipse(QPointF(12, 12), 9, 9)  # 使用一致的圆形外框。
    if name in ('photo', 'tag'):  # 图片和标签补充小圆细节。
        painter.drawEllipse(QPointF(16, 8) if name == 'photo' else QPointF(7, 8), 1.1, 1.1)  # 标注太阳或吊牌孔洞。
    painter.end()  # 结束画布绘制。
    pixmap.setDevicePixelRatio(2)  # 让 Qt 按高 DPI 图标显示。
    return QIcon(pixmap)  # 返回所有按钮可共享的矢量风格图标。

def label(text, role=None):  # 创建具有语义样式的文字标签。
    result = QLabel(text)  # 设置用户可见文案。
    if role:  # 样式按角色统一管理。
        result.setProperty('role', role)  # 让 QSS 应用对应层级。
    return result  # 供布局直接使用。

def button(text, callback, symbol=None, role=None):  # 创建一致的操作按钮。
    result = QPushButton(text)  # 提供可读操作名称。
    result.setCursor(Qt.PointingHandCursor)  # 悬停时提示可点击。
    if role:  # 仅主要和特殊按钮声明角色。
        result.setProperty('role', role)  # 使用统一的颜色和圆角样式。
    if symbol:  # 图标与文字保持一致间距。
        result.setIcon(icon(symbol, '#ffffff' if role == 'primary' else '#6d8db9'))  # 主按钮使用白色图标。
        result.setIconSize(QSize(17, 17))  # 导航和次级按钮统一图标大小。
    result.clicked.connect(callback)  # 不改变原有业务回调。
    return result  # 返回可进一步调整的控件。

class PathLabel(QLabel):  # 路径过长时省略显示而不挤压卡片布局。
    def __init__(self, text):  # 保留完整路径用于提示。
        super().__init__()  # 初始化标签。
        self.full_text = text  # 缓存完整文本。
        self.setMinimumWidth(0)  # 允许左右分隔线正常缩小目录区域。
        self.setObjectName('directoryPath')  # 使用路径专属次级样式。
        self.setText(text)  # 首次展示文案。

    def setText(self, text):  # 兼容原扫描完成后的路径更新。
        self.full_text = text  # 保存未裁切路径。
        self.setToolTip(text)  # 悬停可查看完整路径。
        super().setText(self.fontMetrics().elidedText(text, Qt.ElideMiddle, max(80, self.width())))  # 在中间省略保留盘符与末级名称。

    def resizeEvent(self, event):  # 左侧宽度改变后重新计算路径显示。
        super().resizeEvent(event)  # 保持 Qt 标签正常布局。
        self.setText(self.full_text)  # 不改变真实浏览路径。

def build_interface(window, tree_class, delegate_class, bundle):  # 在不改变播放规则的前提下重组全部界面布局。
    window.appearance = Appearance(window.store.directory)  # 载入便携外观配置。
    window.canvas = BackgroundCanvas(window.appearance)  # 主背景独立于视频输出。
    window.setCentralWidget(window.canvas)  # 安装可自定义背景的中央容器。
    window.setStyleSheet(STYLE)  # 一次应用完整蓝白主题。
    layout = QVBoxLayout(window.canvas)  # 顶部导航、页面标题与主工作区纵向排布。
    layout.setContentsMargins(8, 0, 8, 4)  # 将空间优先留给目录和视频。
    layout.setSpacing(8)  # 工具栏与工作区保持紧凑分隔。
    top = QFrame()  # 创建品牌与导航卡片。
    top.setObjectName('topBar')  # 顶部使用半透明白色样式。
    top_layout = QHBoxLayout(top)  # 品牌、导航和外观入口横向排列。
    top_layout.setContentsMargins(8, 7, 8, 7)  # 工具栏只保留必要点击空间。
    top_layout.setSpacing(4)  # 同类操作靠近排列。
    avatar = QLabel()  # 将生成的云璃图标作为品牌识别。
    avatar.setFixedSize(28, 28)  # 应用图标退到普通工具栏大小。
    avatar.setPixmap(QPixmap(str(bundle / 'assets/yunli-chibi.png')).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))  # 保留用户指定的角色图标。
    top_layout.addWidget(avatar)  # 头像位于品牌左侧。
    top_layout.addWidget(label('MoPlayer', 'brand'))  # 仅保留名称，不添加品牌口号。
    top_layout.addSpacing(22)  # 应用名称与常用功能形成一个明确分组。
    for text, symbol, action in [('历史视频', 'history', lambda: window.library('videos')), ('历史文件夹', 'folder', lambda: window.library('folders')), ('收藏列表', 'star', lambda: window.library('stars'))]:  # 保留所有历史和收藏独立入口。
        top_layout.addWidget(button(text, action, symbol, 'nav'))  # 使用轻量文字导航。
    top_layout.addStretch()  # 常用浏览功能靠左，设置功能靠右。
    appearance = button('外观', lambda: appearance_dialog(window), 'photo')  # 提供明确的自定义背景入口。
    appearance.setObjectName('appearanceButton')  # 便于自动化验收外观设置入口。
    top_layout.addWidget(appearance)  # 放在导航右侧的可见位置。
    more = QPushButton('更多')  # 低频功能不长期占据主工具栏。
    more.setProperty('role', 'nav')  # 与外观按钮保持相同层级。
    menu = QMenu(more)  # 使用普通桌面菜单容纳系统与维护操作。
    for text, action in [('系统缩略图', window.explorer_thumbnail_dialog), ('文件任务', window.task_dialog), ('使用帮助', window.help_dialog)]:  # 提供缩略图、归档与删除恢复及帮助入口。
        menu.addAction(text, action)  # 点击菜单项仍执行原有逻辑。
    more.setMenu(menu)  # 菜单打开时沿用弹出层优先的快捷键规则。
    top_layout.addWidget(more)  # 将维护菜单放在工具栏末端。
    layout.addWidget(top)  # 顶部品牌与导航占独立一行。
    splitter = QSplitter(Qt.Horizontal)  # 保留用户可拖动的左右分隔线。
    splitter.setHandleWidth(8)  # 使用窄分隔条控制目录宽度。
    splitter.setChildrenCollapsible(False)  # 避免将任一区域完全收起。
    layout.addWidget(splitter, 1)  # 主工作区使用剩余窗口高度。
    left = QFrame()  # 左侧独立目录卡片。
    left.setObjectName('libraryCard')  # 应用半透明白色卡片样式。
    left.setMinimumWidth(280)  # 保证大缩略图和横向滚动仍然可用。
    left_layout = QVBoxLayout(left)  # 目录标题、路径、树视图、页脚纵向排布。
    left_layout.setContentsMargins(10, 10, 10, 6)  # 目录区不使用过厚内边距。
    left_layout.setSpacing(7)  # 标题和路径保持紧凑。
    library_head = QHBoxLayout()  # 标题与导入按钮各占两端。
    library_head.addWidget(label('文件', 'sectionTitle'))  # 目录分区只使用功能名称。
    window.file_count = label('0 部', 'badge')  # 显示本次浏览快照的视频条目数。
    library_head.addWidget(window.file_count)  # 数量与标题靠近。
    library_head.addStretch()  # 导入按钮推到右侧。
    library_head.addWidget(button('导入文件夹', window.choose_folder, 'plus', 'primary'))  # 导入成为左侧唯一主要操作。
    left_layout.addLayout(library_head)  # 添加目录卡片标题行。
    window.folder_label = PathLabel('未打开文件夹')  # 启动状态使用直接说明。
    left_layout.addWidget(window.folder_label)  # 路径说明保持单行。
    window.tree = tree_class()  # 使用既有拖放目录树逻辑。
    window.tree.setObjectName('libraryTree')  # 应用无边框目录样式。
    window.tree.setItemDelegate(delegate_class(window.thumbnails, window.tree))  # 保留 180×120 可见视频缩略图。
    window.thumbnails.changed.connect(window.tree.viewport().update)  # 异步图片完成时仅重绘视口。
    window.tree.dropped.connect(window.load_folder)  # 导入规则保持不变。
    window.tree.doubleClicked.connect(window.open_index)  # 仍然双击视频才开始播放。
    left_layout.addWidget(window.tree, 1)  # 树视图占据主要浏览高度。
    footer = QHBoxLayout()  # 次要提示和取消扫描放在卡片底部。
    footer.addWidget(label('可拖入文件夹', 'muted'))  # 仅提示不明显的导入方式。
    footer.addStretch()  # 将取消操作推到右侧。
    window.cancel_button = button('取消扫描', lambda: (window.scan_cancel.set(), window.navigation_cancel.set()), role='quiet')  # 保留两种扫描的取消能力。
    window.cancel_button.setEnabled(False)  # 没有扫描时保持弱化禁用状态。
    footer.addWidget(window.cancel_button)  # 取消不再占据整行空间。
    left_layout.addLayout(footer)  # 完成左侧目录卡片。
    splitter.addWidget(left)  # 左侧目录保持独立区域。
    right = QFrame()  # 右侧播放器整体作为一个主卡片。
    right.setObjectName('playerCard')  # 统一圆角边框。
    right_layout = QVBoxLayout(right)  # 标题、画面、进度、控制、分类按用途分层。
    right_layout.setContentsMargins(10, 8, 10, 6)  # 缩小视频周围的非内容空间。
    right_layout.setSpacing(8)  # 文件名、画面和控制栏紧凑排列。
    player_head = QHBoxLayout()  # 当前视频信息与状态位于画面上方。
    window.now = PathLabel('播放器')  # 当前文件名使用可省略的单行文本。
    window.now.setObjectName('nowPlaying')  # 当前媒体名称使用强调字体。
    player_head.addWidget(window.now, 1)  # 文件名占主要横向空间，省去重复标题。
    window.media_badge = label('等待播放', 'badge')  # 显示当前实际播放状态。
    player_head.addWidget(window.media_badge)  # 状态徽标靠右。
    right_layout.addLayout(player_head)  # 视频标题位于画面之上。
    window.surface = QFrame()  # 保留独立 VLC 原生播放窗口。
    window.surface.setObjectName('videoSurface')  # 区分主题背景与真实视频输出。
    window.surface.setStyleSheet('QFrame#videoSurface{background:#17191d;border:none;border-radius:0;}')  # 视频窗口采用无圆角的中性深色画布。
    window.surface.setMinimumSize(320, 230)  # 不牺牲核心播放区域。
    window.surface.setAttribute(Qt.WA_NativeWindow)  # 提供真正 Windows HWND 给 VLC。
    window.surface.setFocusPolicy(Qt.StrongFocus)  # 保留视频区域键盘操作。
    surface_layout = QVBoxLayout(window.surface)  # 在未播放时显示居中空状态。
    window.player_empty = QWidget()  # 空状态单独隐藏，不遮挡真正播放画面。
    empty_layout = QVBoxLayout(window.player_empty)  # 图标、标题和说明纵向居中。
    empty_layout.setAlignment(Qt.AlignCenter)  # 空状态内容聚焦在画面中央。
    empty_layout.setSpacing(10)  # 空状态只保留简短操作提示。
    emblem = label('▶')  # 使用简单播放标记表达观看入口。
    emblem.setAlignment(Qt.AlignCenter)  # 标记在圆形画布中央。
    emblem.setFixedSize(42, 42)  # 空状态播放符号保持较低视觉权重。
    emblem.setStyleSheet('color:#737982;font-size:27px;')  # 不绘制装饰圆环或发光底板。
    empty_layout.addWidget(emblem, 0, Qt.AlignHCenter)  # 图标居中显示。
    empty_title = label('未打开视频')  # 只说明当前播放状态。
    empty_title.setAlignment(Qt.AlignCenter)  # 文案与图标居中对齐。
    empty_title.setStyleSheet('color:#a4aab2;font-size:13px;')  # 不把空状态放大成宣传标题。
    empty_layout.addWidget(empty_title)  # 添加空状态标题。
    empty_note = label('从左侧选择视频，双击开始播放')  # 保持操作指引明确。
    empty_note.setAlignment(Qt.AlignCenter)  # 说明同样居中。
    empty_note.setStyleSheet('color:#6f7680;font-size:11px;')  # 操作提示保持次要层级。
    empty_layout.addWidget(empty_note)  # 添加播放入口说明。
    surface_layout.addWidget(window.player_empty, 1)  # 空状态填充画面容器。
    right_layout.addWidget(window.surface, 1)  # 真实视频画面占最大空间。
    window.player.set_hwnd(int(window.surface.winId()))  # 将 VLC 输出绑定到同一个原生窗口。
    window.playback_panel = QWidget()  # 播放控件可在全屏时移入独立浮动栏。
    playback_layout = QVBoxLayout(window.playback_panel)  # 将进度和播放控制组成一个整体。
    playback_layout.setContentsMargins(0, 0, 0, 0)  # 普通模式沿用卡片已有留白。
    playback_layout.setSpacing(6)  # 缩小两层播放控件的间隔。
    progress = QHBoxLayout()  # 时间信息与进度条在同一轻量行。
    progress.setSpacing(14)  # 进度和时间之间留出间隔。
    window.seekbar = QSlider(Qt.Horizontal)  # 保留原有可拖动播放进度。
    window.seekbar.setRange(0, 10000)  # 使用相对比例支持长视频。
    window.seekbar.sliderReleased.connect(window.seek_slider)  # 仍在松开滑块时跳转。
    progress.addWidget(window.seekbar, 1)  # 进度条自适应剩余宽度。
    window.time_label = label('00:00:00 / 00:00:00', 'muted')  # 当前与总时间始终可见。
    window.time_label.setStyleSheet('font-family:"Segoe UI";font-size:11px;color:#8091aa;')  # 时间数字使用紧凑字体。
    progress.addWidget(window.time_label)  # 时间放在进度条右侧。
    playback_layout.addLayout(progress)  # 进度紧邻视频画面。
    controls = QHBoxLayout()  # 播放、音量与全屏组成第一层控制。
    controls.setSpacing(5)  # 前后切换与播放按钮形成紧凑的一组。
    for text, name, callback in [('上一个 Z', 'previous', lambda: window.advance(-1)), ('播放 / 暂停 · 空格', 'play', window.toggle), ('下一个 X', 'next', lambda: window.advance(1))]:  # 保留所有原播放快捷键对应操作。
        control = button('', callback, name, 'round')  # 核心控制使用图标，不挤满文字按钮。
        control.setAccessibleName(text)  # 保持辅助功能可识别操作。
        control.setToolTip(text)  # 鼠标悬停显示快捷键。
        control.setFixedSize(36, 36)  # 前后切换采用统一的工具按钮尺寸。
        if name == 'play':  # 播放暂停按钮居中且更醒目。
            control.setObjectName('playButton')  # 绑定蓝色强调样式。
            control.setFixedSize(40, 36)  # 主操作以颜色而非夸张尺寸强调。
            control.setIcon(icon('play', '#ffffff'))  # 蓝色圆按钮内使用白色图标。
            control.setIconSize(QSize(23, 23))  # 播放图标适合较大按钮。
            window.play_button = control  # 状态刷新时可切换播放与暂停图标。
        controls.addWidget(control)  # 按上一个、播放、下一个排列。
    controls.addStretch()  # 音量和全屏归到右侧辅助区域。
    volume_icon = QLabel()  # 用小扬声器标记音量区。
    volume_icon.setPixmap(icon('volume').pixmap(18, 18))  # 不占用较长“音量”按钮宽度。
    controls.addWidget(volume_icon)  # 放置音量图标。
    volume = QSlider(Qt.Horizontal)  # 保留音量滑块。
    volume.setRange(0, 100)  # 使用百分比范围。
    volume.setValue(80)  # 默认音量仍为 80%。
    volume.setFixedWidth(90)  # 音量使用适中固定宽度。
    volume.setToolTip('音量')  # 鼠标悬停可识别用途。
    volume.valueChanged.connect(window.player.audio_set_volume)  # 保留原 VLC 音量操作。
    window.player.audio_set_volume(80)  # 同步初始实际音量。
    controls.addWidget(volume)  # 放置音量滑轨。
    controls.addSpacing(10)  # 将全屏与音量稍作分隔。
    window.fullscreen_button = button('全屏', window.enter_fullscreen, 'full', 'nav')  # 同一按钮负责进入和退出视频全屏。
    controls.addWidget(window.fullscreen_button)  # 全屏操作始终位于播放控制右侧。
    playback_layout.addLayout(controls)  # 第一层只保留播放相关控件。
    right_layout.addWidget(window.playback_panel)  # 普通模式播放控件保持原来的位置。
    line = QFrame()  # 用细线分隔播放与分类操作。
    line.setFixedHeight(1)  # 避免厚重横线。
    line.setStyleSheet('background:#e5e8ed;')  # 使用中性分隔线区分播放与文件操作。
    right_layout.addWidget(line)  # 添加功能分组分隔线。
    classify = QHBoxLayout()  # 第二层专注边看边分类。
    classify.setSpacing(10)  # 分类按钮留出足够间隔。
    classify.addWidget(label('分类', 'muted'))  # 使用功能名称，不添加宣传文案。
    classify.addStretch()  # 分类操作统一靠右排列。
    for text, symbol, action in [('标签  Q', 'tag', window.tags_dialog), ('评分  R', 'score', window.rating_dialog), ('收藏  W', 'star', window.favorite)]:  # 保持原有 Q/R/W 规则。
        classify.addWidget(button(text, action, symbol, 'action'))  # 使用蓝色轻量胶囊按钮。
    right_layout.addLayout(classify)  # 分类层与播放层分开，不再挤在同一排。
    splitter.addWidget(right)  # 安装右侧主播放器卡片。
    splitter.setSizes([380, 1020])  # 保留大缩略图所需宽度并优先扩大播放区域。
    window.statusBar().showMessage('就绪')  # 状态栏只显示实际状态，不重复堆放快捷键。
