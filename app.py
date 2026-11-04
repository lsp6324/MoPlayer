import json  # 读取视频标签和诊断数据。
import logging  # 记录可追踪的运行错误。
import os  # 配置随包运行库路径。
import subprocess  # 异步调用缩略图解码程序。
import sys  # 区分源码和便携运行方式。
import threading  # 提供扫描取消信号。
import time  # 管理周期保存时间。
from collections import OrderedDict  # 限制界面缩略图内存缓存大小。
from pathlib import Path  # 处理便携数据路径。
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRunnable, QThreadPool, QAbstractItemModel, QModelIndex, QEvent, QLockFile, QSize, QRect  # 使用 Qt 事件循环、异步任务和明确缩略图尺寸。
from PySide6.QtGui import QAction, QIcon, QPixmap, QColor, QPalette, QPainter, QPainterPath, QPen  # 绘制圆角缩略图卡片与选中状态。
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTreeView, QSplitter, QSlider, QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QFrame, QStyledItemDelegate, QStyleOptionViewItem, QStyle  # 构建原生界面和大缩略图视频行。
from core import Store, Archiver, ScanRequired, scan, validate_tag, natural  # 复用经测试的核心规则与延迟扫描信号。
from video_delete import DeletionManager  # 以可恢复任务回收全部登记入口。
from tag_migration import TagMigration  # 以可恢复批次同步全局标签层级。

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent  # 数据随便携程序保存。
BUNDLE = Path(getattr(sys, '_MEIPASS', BASE))  # 定位打包资源。
VLC_DIR = BUNDLE / 'vlc' if getattr(sys, 'frozen', False) else Path('E:/tools/videoplayerenv/runtime/vlc-3.0.21')  # 源码开发与便携部署分别定位。
os.environ['PYTHON_VLC_LIB_PATH'] = str(VLC_DIR / 'libvlc.dll')  # 禁止意外加载系统其他 VLC 版本。
os.environ['PYTHON_VLC_MODULE_PATH'] = str(VLC_DIR)  # 指定 VLC 原生模块目录。
os.environ['VLC_PLUGIN_PATH'] = str(VLC_DIR / 'plugins')  # 插件全部随包加载。
DLL_HANDLE = os.add_dll_directory(str(VLC_DIR))  # 保持原生依赖搜索目录有效。
import vlc  # 在配置路径后加载成熟播放内核。

class Signals(QObject):  # 在线程间传递任务结果。
    finished = Signal(object, object)  # 同时携带返回值与异常。

class Work(QRunnable):  # 在线程池中执行阻塞操作。
    def __init__(self, function):  # 接收无参数任务函数。
        super().__init__()  # 初始化 Qt 任务对象。
        self.function, self.signals = function, Signals()  # 信号对象由界面保持引用。

    def run(self):  # 工作线程不得直接操作控件。
        try:  # 将异常转换成主线程反馈。
            result = self.function()  # 执行扫描、归档或缩略图生成。
            self.signals.finished.emit(result, None)  # 通知任务成功。
        except InterruptedError as error:  # 正常取消扫描或缩略图不当成程序故障记录。
            logging.info('后台任务已取消：%s', error)  # 保留可追踪取消状态而不刷错误堆栈。
            self.signals.finished.emit(None, error)  # 界面仍按原取消约定处理结果。
        except Exception as error:  # 保留异常到日志与界面。
            logging.exception('后台任务失败')  # 记录完整堆栈。
            self.signals.finished.emit(None, error)  # 不伪报操作成功。

class ThumbnailCache(QObject):  # 为目录、历史和收藏共用有界异步缩略图队列。
    changed = Signal()  # 缩略图完成后通知所有可见列表重绘。

    def __init__(self, window):  # 使用窗口已有的视频身份和磁盘缓存逻辑。
        super().__init__(window)  # 随主窗口管理信号生命周期。
        self.window, self.images, self.errors, self.pending = window, OrderedDict(), OrderedDict(), {}  # 共用视频 ID 并限制缓存资源。
        self.pool = QThreadPool(self)  # 与目录扫描、归档使用不同工作队列。
        self.pool.setMaxThreadCount(2)  # 最多同时启动两个 FFmpeg，避免批量解码耗尽资源。
        self.closing = False  # 退出时停止接受新缩略图请求。

    def request(self, vid):  # 绘制可见视频行时按需请求缩略图。
        if vid in self.images:  # 热缓存无需磁盘读取。
            self.images.move_to_end(vid)  # 保留最近显示的视频图片。
            return self.images[vid]  # 在 GUI 线程返回已加载的 QPixmap。
        if self.closing or self.window.busy or self.window.file_task_thumbnail_pause or vid in self.pending or vid in self.errors or len(self.pending) >= 24:  # 文件批次和快速滚动均限制新解码请求。
            return None  # 加载期间由列表绘制明确占位提示。
        job = Work(lambda: self.window.thumbnail(vid))  # 在工作线程读取缓存或生成 240×160 JPEG。
        self.pending[vid] = job  # 按稳定身份去重后台解码。
        def finished(path, error):  # 在主线程将已生成图片发布给视图。
            self.pending.pop(vid, None)  # 释放已完成任务引用和队列容量。
            if isinstance(error, InterruptedError):  # 文件任务取消的解码不能被当成视频损坏。
                if not self.closing:  # 窗口仍在使用时允许后续重试。
                    self.changed.emit()  # 忙碌状态结束后重新按需生成图片。
                return  # 不写入持久错误缓存。
            if self.closing or self.window.file_task_thumbnail_pause or vid in self.window.deleting_ids or vid in self.window.deleted_ids:  # 文件任务期间取消的旧解码结果不发布为错误缓存。
                return  # 只等待任务安全结束。
            image = QPixmap(str(path)) if not error else QPixmap()  # 仅在主线程读取完成的缓存图片。
            if image.isNull():  # 解码失败不无限重试同一坏文件。
                self.errors[vid] = str(error or '缩略图图像无效')  # 保存可显示的失败原因。
                while len(self.errors) > 256:  # 限制错误缓存长期占用。
                    self.errors.popitem(last=False)  # 释放最早的失败记录。
            else:  # 发布实际视频画面。
                self.images[vid] = image  # 同一个视频的多个入口引用同一张图片。
                while len(self.images) > 256:  # 只保留最近使用的 256 张内存图片。
                    self.images.popitem(last=False)  # 淘汰后仍可复用磁盘缓存。
            self.changed.emit()  # 重绘当前视口并继续请求尚未排队的可见视频。
        job.signals.finished.connect(finished)  # 通过 Qt 排队信号安全回到主线程。
        self.pool.start(job)  # 不在绘制过程中执行解码或大文件读取。
        return None  # 首次显示使用加载占位画布。

class VideoDelegate(QStyledItemDelegate):  # 在浏览列表直接显示至少 120×120 的视频画面。
    def __init__(self, thumbnails, parent):  # 多个视图共用同一个缩略图服务。
        super().__init__(parent)  # 由所在视图管理委托生命周期。
        self.thumbnails = thumbnails  # 保存统一缓存入口。

    def sizeHint(self, option, index):  # 按视频和文件夹分别确定行高。
        return QSize(330, 136) if index.data(Qt.UserRole) else QSize(200, 30)  # 视频留出 180×120 画面和上下边距，文件夹保持紧凑。

    def paint(self, painter, option, index):  # 自定义视频行并保留系统选择和文件夹行为。
        vid = index.data(Qt.UserRole)  # 读取稳定视频 ID，文件夹没有此角色。
        if not vid:  # 普通目录继续使用原生树样式。
            super().paint(painter, option, index)  # 保留展开收起和文件夹图标。
            return  # 不给文件夹生成视频缩略图。
        background = QStyleOptionViewItem(option)  # 复制行状态以绘制原生选中背景。
        self.initStyleOption(background, index)  # 读取当前字体、调色板和选择状态。
        background.text, background.icon = '', QIcon()  # 缩略图和文字在固定区域自行绘制。
        painter.save()  # 不将本行绘制状态泄漏到其他行。
        painter.setRenderHint(QPainter.Antialiasing)  # 平滑绘制文件选择区域和缩略图。
        card = option.rect.adjusted(1, 1, -2, -1)  # 文件列表只保留细分隔空间。
        selected = bool(option.state & QStyle.State_Selected)  # 保留鼠标和键盘选择状态。
        hovered = bool(option.state & QStyle.State_MouseOver)  # 鼠标悬停给出轻量反馈。
        painter.setPen(QPen(QColor('#9eb8df' if selected else '#eceef1'), 1))  # 普通行使用细分隔线，选中时才强调蓝色。
        painter.setBrush(QColor('#e9f0fb' if selected else '#f2f4f7' if hovered else '#ffffff'))  # 视频条目保持普通列表的状态反馈。
        painter.drawRoundedRect(card, 3, 3)  # 移除独立卡片感的大圆角。
        area = QRect(option.rect.left() + 6, option.rect.top() + 8, 180, 120)  # 实际显示尺寸固定为 180×120，不用小图标替代。
        painter.save()  # 缩略图圆角裁切不会影响右侧文字。
        clip = QPainterPath()  # 创建仅作用于缩略图的圆角路径。
        clip.addRoundedRect(area, 2, 2)  # 保持 180×120 画布，只处理细微边角。
        painter.setClipPath(clip)  # 将视频像素限制在图片卡片内。
        painter.fillRect(area, QColor('#151b25'))  # 加载和补边区域使用统一深色画布。
        image = self.thumbnails.request(vid)  # 只为正在绘制的可见视频行排队。
        if image is not None:  # 已有实际视频帧时立即显示。
            painter.drawPixmap(area, image)  # 将 240×160 缓存等比例显示为 180×120。
        else:  # 加载或失败时给出清晰状态。
            painter.setPen(QColor('#dce2ec'))  # 使用深色背景上的可读文字。
            painter.drawText(area, Qt.AlignCenter, '缩略图不可用' if vid in self.thumbnails.errors else '缩略图加载中…')  # 不用播放小图标冒充缩略图。
        painter.restore()  # 结束图片区域裁切。
        label = QRect(area.right() + 10, option.rect.top() + 12, max(40, option.rect.right() - area.right() - 16), 108)  # 在图片右侧显示文件名和列表信息。
        painter.setPen(QColor('#245ba8' if selected else '#414852'))  # 文件名使用中性深灰，选中时再强调蓝色。
        painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, str(index.data(Qt.DisplayRole)))  # 长文件名换行显示而不压缩图片。
        painter.restore()  # 还原绘制状态。

class TreeModel(QAbstractItemModel):  # 按需创建树索引，避免大量控件卡住界面。
    def __init__(self, snapshot):  # 接收已完成的异步扫描快照。
        super().__init__()  # 初始化 Qt 模型。
        self.snapshot, self.nodes = snapshot, {}  # 缓存索引对象以保持指针有效。

    def columnCount(self, parent=QModelIndex()):  # 目录浏览只需要一列。
        return 1  # 文件名占满目录区域。

    def rowCount(self, parent=QModelIndex()):  # 根据数据计算数量，不生成所有子项。
        if not parent.isValid():  # 顶层显示导入根目录。
            return 1  # 单根目录树。
        kind, folder, index = parent.internalPointer()  # 读取逻辑节点。
        return len(self.snapshot.folders[folder][0]) + len(self.snapshot.visible_files(folder)) if kind == 'folder' else 0  # 排除删除项并保留文件夹层级。

    def index(self, row, column, parent=QModelIndex()):  # 仅为当前视图需要的行建立索引。
        if column != 0 or row < 0 or row >= self.rowCount(parent):  # 拒绝无效行列。
            return QModelIndex()  # 返回空索引。
        if not parent.isValid():  # 构造根目录节点。
            node = ('folder', self.snapshot.root, -1)  # 根节点不对应视频序号。
        else:  # 构造指定目录中的子项。
            folder = parent.internalPointer()[1]  # 获得父目录路径。
            children = self.snapshot.folders[folder][0]  # 子目录排在视频之前。
            node = ('folder', children[row], -1) if row < len(children) else ('video', folder, self.snapshot.visible_files(folder)[row - len(children)][0])  # 显示行映射回未变动的原播放索引。
        node = self.nodes.setdefault(node, node)  # 保持内部指针引用稳定。
        return self.createIndex(row, column, node)  # 向 Qt 返回轻量索引。

    def parent(self, index):  # 从逻辑路径计算父索引。
        if not index.isValid():  # 空索引没有父节点。
            return QModelIndex()  # 满足 Qt 模型约定。
        kind, folder, number = index.internalPointer()  # 解析节点类型。
        if kind == 'folder' and folder == self.snapshot.root:  # 根目录没有可见父级。
            return QModelIndex()  # 限制树边界。
        parent = folder if kind == 'video' else str(Path(folder).parent)  # 文件父级是所在目录。
        row = 0 if parent == self.snapshot.root else self.snapshot.folders[str(Path(parent).parent)][0].index(parent)  # 计算父目录在祖父中的行。
        node = ('folder', parent, -1)  # 创建父目录标识。
        return self.createIndex(row, 0, self.nodes.setdefault(node, node))  # 返回引用稳定的父索引。

    def data(self, index, role=Qt.DisplayRole):  # 提供显示文字和图标。
        if not index.isValid():  # 无效索引不返回数据。
            return None  # 避免访问不存在节点。
        kind, folder, number = index.internalPointer()  # 读取节点信息。
        if role == Qt.UserRole:  # 向缩略图委托提供视频永久身份。
            return self.snapshot.folders[folder][1][number][0] if kind == 'video' else None  # 文件夹不参与缩略图队列。
        if role == Qt.DisplayRole:  # 展示文件夹名或视频原名。
            return Path(folder).name if kind == 'folder' else self.snapshot.folders[folder][1][number][1]  # 保留完整中文名称。
        if role == Qt.ToolTipRole:  # 鼠标悬停时提示逻辑原始路径。
            return folder  # 归档后该路径仍说明原播放上下文。
        if role == Qt.DecorationRole:  # 使用系统风格的轻量类型图标。
            return QApplication.style().standardIcon(QApplication.style().StandardPixmap.SP_DirIcon if kind == 'folder' else QApplication.style().StandardPixmap.SP_MediaPlay)  # 不在主线程解码视频。
        return None  # 其他角色使用默认值。

class DropTree(QTreeView):  # 将文件夹拖放限制在左侧区域。
    dropped = Signal(str)  # 向窗口发送导入路径。

    def __init__(self):  # 配置目录视图交互。
        super().__init__()  # 初始化目录控件。
        self.setAcceptDrops(True)  # 启用文件夹拖入。
        self.setHeaderHidden(True)  # 简化目录区域。
        self.setUniformRowHeights(False)  # 视频行需要 136 像素高，文件夹保持 30 像素。
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 左侧被拖窄或目录过深时允许横向查看完整图片。
        self.setEditTriggers(QTreeView.NoEditTriggers)  # 文件名不可直接编辑。

    def dragEnterEvent(self, event):  # 检查拖入对象是否为本地文件夹。
        urls = event.mimeData().urls()  # 获取系统文件拖放内容。
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).is_dir():  # 每次导入一个明确根目录。
            event.acceptProposedAction()  # 接受有效目录。

    def dragMoveEvent(self, event):  # 保持拖放区域可接受状态。
        self.dragEnterEvent(event)  # 复用同一目录验证。

    def dropEvent(self, event):  # 完成文件夹导入。
        self.dropped.emit(event.mimeData().urls()[0].toLocalFile())  # 异步扫描交给主窗口。
        event.acceptProposedAction()  # 告知系统拖放完成。

def format_time(ms):  # 将播放时间格式化为可读文本。
    seconds = max(0, ms) // 1000  # 未知时长显示零。
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'  # 支持超过一小时的视频。

class Window(QMainWindow):  # 主界面和播放协调层。
    def __init__(self, data_dir=None):  # 测试可使用隔离数据目录。
        super().__init__()  # 创建主窗口。
        self.store = Store(data_dir or BASE / 'data')  # 元数据不依赖开发环境路径。
        self.archiver = Archiver(self.store)  # 固定使用用户指定归档根目录。
        self.deleter = DeletionManager(self.store)  # 将删除阶段与元数据提交持久记账。
        self.tag_migration = TagMigration(self.store, self.archiver)  # 全局分类复用逐视频硬链接归档和恢复日志。
        self.file_task_thumbnail_pause = False  # 文件批处理期间阻止新解码器重新占用入口。
        self.thumbnail_guard, self.thumbnail_processes = threading.RLock(), {}  # 跟踪并释放目标视频的后台解码占用。
        self.deleting_ids, self.deleted_ids = set(), set()  # 阻止删除过程中及完成后的旧缩略图请求。
        self.thumbnails = ThumbnailCache(self)  # 目录树、历史和收藏统一使用异步缩略图服务。
        self.browsing, self.context, self.location, self.current = None, None, None, None  # 浏览快照与播放快照严格分离。
        self.scan_cancel, self.scan_serial, self.jobs, self.busy = threading.Event(), 0, [], False  # 管理取消和后台任务。
        self.navigation_cancel = threading.Event()  # 同级目录延迟扫描也支持取消。
        self.resume, self.resume_paused, self.last_save, self.ended = None, False, 0, False  # 维护安全重载和播放结束状态。
        self.instance = vlc.Instance('--no-video-title-show', '--no-metadata-network-access', '--no-snapshot-preview')  # 禁用网络元数据请求和视频标题浮层。
        self.player = self.instance.media_player_new()  # 创建独立播放器。
        self.player.video_set_key_input(False)  # 所有快捷键统一由应用处理。
        self.player.video_set_mouse_input(False)  # 不让内核抢占全屏与鼠标交互。
        self.setWindowTitle('MoPlayer · 本地视频与分类')  # 设置可识别的窗口标题。
        self.resize(1440, 920)  # 为品牌导航、双层控制和大缩略图保留舒适留白。
        self.setMinimumSize(1120, 760)  # 避免窗口过小造成导航和分类按钮重叠。
        from ui import build_interface  # 按独立视觉模块构建蓝色卡片布局。
        build_interface(self, DropTree, VideoDelegate, BUNDLE)  # 保留所有既有控件变量和业务回调。
        self.setWindowIcon(QIcon(str(BUNDLE / 'assets/yunli.ico')))  # 窗口与任务栏使用同一云璃 Q 版图标。
        from video_fullscreen import VideoFullscreen  # 独立管理视频全屏与控制栏浮层。
        self.video_fullscreen = VideoFullscreen(self)  # 不移动 VLC 原生播放窗口，保持解码连续。
        self.timer = QTimer(self)  # 主线程定时刷新播放器状态。
        self.timer.timeout.connect(self.tick)  # 保留既有进度和自动连播逻辑。
        self.timer.start(250)  # 每四分之一秒刷新一次。
        QApplication.instance().installEventFilter(self)  # 保留弹窗与文本输入优先的快捷键处理。
        if self.store.query('SELECT id FROM jobs WHERE state<>"done"') or self.store.query('SELECT id FROM deletion_jobs WHERE state<>"done"') or self.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"'):  # 恢复文件及全局分类任务，不恢复目录或播放。
            QTimer.singleShot(0, self.retry_jobs)  # 等界面启动后异步恢复未完成归档。

    def work(self, function, callback):  # 启动后台任务并保持信号对象存活。
        job = Work(function)  # 封装工作函数。
        self.jobs.append(job)  # 防止任务结束前被垃圾回收。
        def finished(value, error):  # 在主线程交付工作结果。
            self.jobs.remove(job)  # 释放已完成任务引用。
            callback(value, error)  # 更新界面状态。
        job.signals.finished.connect(finished)  # 使用 Qt 自动线程间排队连接。
        QThreadPool.globalInstance().start(job)  # 避免阻塞主事件循环。

    def message(self, text):  # 提供短暂、非打断式反馈。
        self.statusBar().showMessage(text, 12000)  # 保留足够阅读时间。
        logging.info(text)  # 同时记录可追踪日志。

    def fail(self, error):  # 明确报告失败而不显示成功。
        QMessageBox.warning(self, '操作未完成', str(error))  # 用户可看到真实失败原因。

    def choose_folder(self):  # 支持按钮选择目录。
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹')  # 使用系统目录选择器。
        if folder:  # 取消对话框不触发扫描。
            self.load_folder(folder)  # 复用拖放导入流程。

    def load_folder(self, folder, play_id=None):  # 替换浏览树而不改变当前播放。
        if self.busy:  # 归档期间不启动会改变当前视频的操作。
            self.message('归档处理中，请等待完成。')  # 说明暂时不可操作的原因。
            return  # 保持当前上下文。
        self.scan_cancel.set()  # 取消上一次尚未完成的扫描。
        self.scan_cancel = threading.Event()  # 每次扫描拥有独立取消对象。
        self.scan_serial += 1  # 用代次丢弃晚到的旧扫描结果。
        serial, cancel = self.scan_serial, self.scan_cancel  # 在线程启动前捕获变量。
        self.cancel_button.setEnabled(True)  # 允许用户中断扫描。
        self.message(f'正在扫描：{folder}')  # 展示扫描任务状态。
        def ready(result, error):  # 接收完整扫描快照。
            if serial != self.scan_serial:  # 旧扫描不覆盖新目录。
                return  # 丢弃过期结果。
            self.cancel_button.setEnabled(False)  # 当前扫描结束。
            if error:  # 取消或访问错误不清空旧浏览树。
                self.message(str(error))  # 显示扫描失败原因。
                return  # 保持既有播放器状态。
            self.browsing, errors = result  # 只替换浏览快照。
            self.tree.setModel(TreeModel(self.browsing))  # 按需显示新目录树。
            self.tree.expand(self.tree.model().index(0, 0))  # 默认展开导入根目录。
            self.folder_label.setText(str(folder))  # 显示当前浏览位置。
            self.file_count.setText(f'{sum(len(files) for children, files in self.browsing.folders.values())} 部')  # 同步当前目录快照中的视频数量。
            self.store.execute('INSERT OR REPLACE INTO folders VALUES(?,?)', (str(Path(folder).absolute()), time.time()))  # 历史文件夹独立记录。
            self.message(f'扫描完成，{len(self.browsing.folders)} 个目录；跳过 {len(errors)} 个无法访问的条目。')  # 给出扫描结果。
            for error_text in errors:  # 保存具体无法访问的路径。
                logging.warning(error_text)  # 可通过日志进一步诊断。
            if play_id:  # 历史或收藏明确请求恢复某个视频。
                for directory, (_, files) in self.browsing.folders.items():  # 在恢复的浏览目录内查找稳定 ID。
                    for index, (vid, name) in enumerate(files):  # 不使用同名匹配。
                        if vid == play_id:  # 找到原身份的有效入口。
                            self.start(self.browsing, (directory, index))  # 此时主动建立新的播放上下文。
                            return  # 只播放一条记录。
                self.fail('扫描后未找到原视频身份；文件可能已被移动或替换。')  # 明确处理扫描期间外部变化。
        self.work(lambda: scan(folder, self.store, cancel), ready)  # 完整递归在后台运行。

    def open_index(self, index):  # 双击文件时建立播放上下文。
        kind, folder, number = index.internalPointer()  # 从当前浏览模型读取逻辑位置。
        if kind == 'video':  # 文件夹双击由树负责展开收起。
            self.start(self.browsing, (folder, number))  # 用户主动选择才改变上下文。

    def save(self):  # 在切换和退出前保存当前进度。
        if self.current and self.resume is None and not self.busy:  # 不用重载期间的零进度覆盖已存进度。
            position = self.player.get_time()  # 获取内核毫秒时间。
            if position >= 0:  # 尚未加载的媒体时间为负数。
                self.store.progress(self.current, position)  # 更新稳定 ID 对应的进度。

    def start(self, context, location):  # 加载一个逻辑播放位置。
        if self.busy:  # 防止归档和换片同时操作文件。
            self.message('归档处理中，完成后可继续切换。')  # 显示暂时等待状态。
            return  # 不改变已有播放器。
        vid = context.folders[location[0]][1][location[1]][0]  # 根据原始上下文读取视频 ID。
        try:  # 在停止当前视频前验证目标路径。
            path = self.store.resolve(vid)  # 归档后自动使用新有效入口。
        except OSError as error:  # 丢失文件不关联同名替代品。
            self.fail(error)  # 显示明确反馈。
            return  # 保持原视频和上下文。
        self.save()  # 保存即将离开的当前视频。
        self.context, self.location, self.current = context, location, vid  # 原子切换播放上下文。
        if self.tree.currentIndex().data(Qt.UserRole) != vid:  # 自动换片后不让旧选择覆盖当前视频的删除目标。
            self.tree.clearSelection()  # 保留用户随后明确点击其他视频的优先权。
        self.store.execute('UPDATE videos SET played=? WHERE id=?', (time.time(), vid))  # 播放历史从实际打开时开始。
        self.play_path(path, self.store.video(vid)['position'], False)  # 从该视频自己的保存进度继续。
        self.refresh_title()  # 更新文件名、标签和评分。

    def play_path(self, path, position, paused):  # 统一普通加载和归档后重载。
        self.player.stop()  # 释放旧媒体及文件句柄。
        self.player_empty.hide()  # 播放开始后移除空状态文案，避免遮住真实视频。
        media = self.instance.media_new(str(path))  # 使用真实本地路径创建媒体。
        self.player.set_media(media)  # 绑定新文件入口。
        media.release()  # 播放器保留自己的媒体引用。
        self.resume, self.resume_paused, self.ended = max(0, position), paused, False  # 等待内核加载后恢复精确进度。
        self.player.play()  # 启动解码读取。

    def refresh_title(self):  # 从数据库反映真实已提交状态。
        if self.current:  # 未选中视频时不读取其他记录。
            video = self.store.video(self.current)  # 读取当前稳定 ID 元数据。
            score = '未评分' if video['score'] is None else f'{video["score"]}分'  # 区分零分与未评分。
            self.now.setText(f'{video["name"]}  ·  {score}  ·  {"、".join(json.loads(video["tags"])) or "无标签"}  {"★ 已收藏" if video["star"] else ""}')  # 显示已落盘分类。

    def tick(self):  # 主线程刷新播放状态和定期保存。
        if not self.current or self.busy:  # 空闲或归档释放句柄时不更新进度。
            return  # 避免零进度覆盖数据库。
        state, length, position = self.player.get_state(), self.player.get_length(), self.player.get_time()  # 读取内核实际状态。
        from ui import icon  # 复用统一蓝色界面图标。
        playing = state == vlc.State.Playing  # 根据真实播放状态更新可见控件。
        if getattr(self, '_visible_play_state', None) != playing:  # 仅状态改变时重绘图标。
            self.play_button.setIcon(icon('pause' if playing else 'play', '#ffffff'))  # 播放时显示暂停，暂停时显示播放。
            self._visible_play_state = playing  # 缓存最近显示状态。
        self.media_badge.setText('正在播放' if playing else '已暂停' if state == vlc.State.Paused else '播放结束' if state == vlc.State.Ended else '正在加载')  # 状态徽标反映实际播放器状态。
        if self.resume is not None and state == vlc.State.Playing and length > 0:  # 等待时长和解码准备就绪。
            self.player.set_time(min(self.resume, max(0, length - 1)))  # 恢复进度并夹紧有效范围。
            if self.resume_paused:  # 评分和标签归档前如果暂停则继续暂停。
                self.player.set_pause(1)  # 保留原播放状态。
            else:  # 目标继续播放时无需等待暂停确认。
                self.resume = None  # 普通续播只恢复一次位置。
        elif self.resume is not None and self.resume_paused and state == vlc.State.Paused:  # 暂停请求必须等内核实际确认后才算重载完成。
            self.resume = None  # 连续评分或分类不再将暂停中的短暂播放状态误判为用户意图。
        self.time_label.setText(f'{format_time(position)} / {format_time(length)}')  # 同时显示当前和总时长。
        if not self.seekbar.isSliderDown():  # 用户拖动时不抢回滑块位置。
            self.seekbar.setValue(int(max(0, position) / length * 10000) if length > 0 else 0)  # 同步实际播放比例。
        if time.monotonic() - self.last_save > 5:  # 每五秒保存一次进度。
            self.save()  # 异常退出最多损失最近一个保存周期。
            self.last_save = time.monotonic()  # 更新周期基准。
        if state == vlc.State.Ended and not self.ended:  # 自然结束只处理一次。
            self.ended = True  # 防止连续定时器重复跳转。
            self.store.progress(self.current, 0)  # 完整看完后下次从头播放。
            self.advance(1, ended=True)  # 自动连播与 X 使用相同规则。
        elif state == vlc.State.Error and not self.ended:  # 处理不能解码的候选文件。
            self.ended = True  # 错误只提示一次。
            self.message('无法解码或读取此视频，请检查文件权限、完整性和编码。')  # 扩展名不代表实际兼容。

    def advance(self, direction, ended=False):  # 按当前播放快照切换。
        if not self.current or self.busy:  # 未播放时快捷键不作用于其他记录。
            return  # 保持状态。
        try:  # 常规目录内切换直接使用已有快照。
            target = self.context.step(self.location, direction)  # 严格执行同目录及同级目录规则。
        except ScanRequired:  # 导入根的下一个同级目录需要延迟扫描。
            context, location, vid = self.context, self.location, self.current  # 固定本次请求的原始播放上下文。
            if getattr(self, 'navigation_pending', False):  # 连续按 X 不重复启动同一目标扫描。
                return  # 等待已有跨目录请求。
            self.navigation_pending = True  # 标记正在补齐播放上下文。
            self.navigation_cancel = threading.Event()  # 为本次延迟扫描创建独立取消标记。
            cancel = self.navigation_cancel  # 捕获标记避免后续导航替换引用。
            self.cancel_button.setEnabled(True)  # 大型同级目录扫描提供可见取消入口。
            self.message('正在扫描下一个同级目录；当前视频保持原状态。')  # 明确后台切换状态。
            def next_ready(next_location, error):  # 在主线程执行已准备的切换。
                self.navigation_pending = False  # 允许后续导航请求。
                self.cancel_button.setEnabled(False)  # 当前导航扫描已经结束。
                if self.busy or cancel.is_set() or self.context is not context or self.location != location or self.current != vid:  # 删除或主动换片后忽略旧请求。
                    return  # 不让晚到结果抢走新播放上下文。
                if error:  # 扫描失败保持当前视频。
                    self.message(str(error))  # 明确报告失败原因。
                elif next_location:  # 目标目录内存在可播放候选。
                    if ended:  # 自然结束时保留已清零的历史进度。
                        self.resume = 0  # 跳过旧媒体结束时间保存。
                    self.start(context, next_location)  # 仍沿用原上下文而不替换浏览树。
                else:  # 后续同级目录全部为空时停止。
                    self.message('没有后续可播放的同级目录。')  # 不向更高祖先寻找。
            self.work(lambda: context.step_loaded(location, direction, self.store, cancel), next_ready)  # 递归扫描在后台执行且可由取消按钮中断。
            return  # 等待异步目标准备完成。
        if target:  # 存在下一个或上一个逻辑视频。
            if ended:  # 防止 start 保存结束时间覆盖零进度。
                self.resume = 0  # 临时跳过旧视频进度保存。
            self.start(self.context, target)  # 浏览树改变不影响这个上下文。
        else:  # 已到规则边界。
            self.message('没有后续视频，播放已停止。' if direction > 0 and ended else '已到当前切换范围边界。')  # 不回绕播放。

    def toggle(self):  # 空格或按钮切换暂停状态。
        if self.current and not self.busy:  # 不操作空播放器或归档中的句柄。
            if self.player.get_state() == vlc.State.Ended:  # 已结束时重新从头播放。
                self.play_path(self.store.resolve(self.current), 0, False)  # 重播仍使用当前身份。
            else:  # 正常播放和暂停互相切换。
                self.player.pause()  # 由 VLC 保留当前时间。

    def seek(self, offset):  # 方向键和 A/D 共用带边界保护的毫秒跳转。
        if self.current and not self.busy and self.player.get_length() > 0:  # 只在已知有效时长时跳转。
            self.player.set_time(min(max(0, self.player.get_time() + offset), self.player.get_length()))  # 严格限制到零和总时长之间。

    def seek_slider(self):  # 将进度比例转换成媒体时间。
        if self.current and not self.busy and self.player.get_length() > 0:  # 防止无媒体时改变其他进度。
            self.player.set_time(int(self.seekbar.value() / 10000 * self.player.get_length()))  # 比例已被滑块范围限制。

    def enter_fullscreen(self):  # Enter 和按钮切换仅视频全屏。
        self.video_fullscreen.toggle()  # 目录和导航隐藏，鼠标移动时显示控制栏。

    def exit_fullscreen(self):  # Esc 恢复进入全屏前的窗口与分隔比例。
        self.video_fullscreen.exit()  # 非全屏状态下不改变用户窗口布局。

    def eventFilter(self, obj, event):  # 在应用级统一处理快捷键优先级。
        if event.type() != QEvent.KeyPress:  # 其余事件交给 Qt。
            return False  # 不干扰绘制和鼠标。
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():  # 弹窗和下拉菜单拥有最高优先级。
            return False  # Esc、Enter 和输入由弹窗自己处理。
        focus = QApplication.focusWidget()  # 获取真正接收输入的控件。
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) or isinstance(focus, QComboBox) and focus.isEditable():  # 文本编辑时所有普通键保持输入用途。
            return False  # 不触发播放、分类或跳转。
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:  # 仅将精确的 Ctrl+D 组合用于视频删除。
            if not event.isAutoRepeat():  # 长按不连续删除多个视频。
                self.delete_video()  # 根据显式选择或当前播放身份执行回收。
            return True  # 不让目录控件重复处理组合键。
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):  # 保留其他系统和编辑组合键。
            return False  # 不拦截复制粘贴等操作。
        actions = {Qt.Key_Space: self.toggle, Qt.Key_X: lambda: self.advance(1), Qt.Key_Z: lambda: self.advance(-1), Qt.Key_Left: lambda: self.seek(-5000), Qt.Key_Right: lambda: self.seek(5000), Qt.Key_A: lambda: self.seek(-5000), Qt.Key_D: lambda: self.seek(5000), Qt.Key_Return: self.enter_fullscreen, Qt.Key_Enter: self.enter_fullscreen, Qt.Key_Escape: self.exit_fullscreen, Qt.Key_Q: self.tags_dialog, Qt.Key_R: self.rating_dialog, Qt.Key_W: self.favorite}  # 左/A 后退五秒，右/D 快进五秒，组合键及输入优先。
        if event.key() in actions:  # 仅拦截已定义的按键。
            if not event.isAutoRepeat() or event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_A, Qt.Key_D):  # 四个进度键均允许长按连续跳转，其他字母不重复操作。
                actions[event.key()]()  # 在主线程执行操作。
            return True  # 避免树视图再次消费方向键。
        return False  # 其他按键保持默认行为。

    def refresh_deleted(self, vids):  # 删除后刷新浏览显示而不重排原播放索引。
        self.deleted_ids.update(vids)  # 后台旧请求不再生成已删除视频的缓存。
        for snapshot in (self.browsing, self.context):  # 浏览目录与播放上下文各自维护排除身份。
            if snapshot:  # 启动任务恢复时可能尚无目录。
                snapshot.excluded.update(vids)  # 所有已知硬链接行同时消失。
        for vid in vids:  # 清除同一身份共用的缩略图缓存。
            self.thumbnails.images.pop(vid, None)  # 释放内存图片。
            self.thumbnails.errors.pop(vid, None)  # 不保留失效错误。
            try:  # 派生缓存清理失败不应阻止已成功删除后的连播。
                (self.store.directory / 'thumbnails' / f'{vid}.jpg').unlink(missing_ok=True)  # 仅删除本应用的派生缓存。
            except OSError:  # 病毒扫描等短暂占用可留待后续缓存清理。
                logging.warning('删除后的缩略图缓存暂时无法清理：%s', vid)  # 视频文件操作成功状态仍然准确。
        if self.browsing:  # 保留导入目录和已展开层级。
            model = self.tree.model()  # 获取当前轻量树模型。
            expanded = {node[1] for node in model.nodes if node[0] == 'folder' and self.tree.isExpanded(self.folder_index(node[1]))}  # 保存用户展开的目录。
            model.beginResetModel()  # 告知视图原显示行数已经改变。
            model.endResetModel()  # 原快照视频索引仍保持有效。
            for folder in expanded:  # 恢复可见目录层级。
                self.tree.expand(self.folder_index(folder))  # 不强制重新折叠用户目录。
            self.file_count.setText(f'{sum(len(self.browsing.visible_files(folder)) for folder in self.browsing.folders)} 部')  # 数量不包含已删除视频。

    def folder_index(self, folder):  # 从浏览快照构造一个文件夹索引。
        model = self.tree.model()  # 使用当前模型的稳定节点引用。
        row = 0 if folder == self.browsing.root else self.browsing.folders[str(Path(folder).parent)][0].index(folder)  # 文件夹顺序不会随视频删除变化。
        node = ('folder', folder, -1)  # 与 TreeModel 的目录节点格式一致。
        return model.createIndex(row, 0, model.nodes.setdefault(node, node))  # 支持恢复嵌套展开状态。

    def clear_player(self):  # 删除完成后解除已不存在的视频身份。
        self.current, self.resume, self.ended = None, None, True  # 定时器不再访问已删除的数据库行。
        self.player.stop()  # 确保没有旧媒体读取。
        self.player.set_media(None)  # 释放 VLC 媒体引用及路径。
        self.player_empty.show()  # 恢复播放器空状态。
        self.now.setText('播放器')  # 不显示已删除视频的标题。
        self.media_badge.setText('等待播放')  # 没有后续视频时保持停止。
        self.seekbar.setValue(0)  # 清空旧进度。
        self.time_label.setText('00:00:00 / 00:00:00')  # 清空已删除视频的时长。
        from ui import icon  # 复用现有按钮图标。
        self.play_button.setIcon(icon('play', '#ffffff'))  # 空播放器显示播放图标。
        self._visible_play_state = False  # 保持下次状态刷新一致。

    def after_deleted_current(self, context, location):  # 使用删除前的播放上下文自动寻找下一条。
        self.clear_player()  # 在异步扫描前清除不存在的当前身份。
        self.busy = True  # 防止等待下一条时收到重复删除或切换请求。
        cancel = threading.Event()  # 允许沿用同一套可取消导航规则。
        self.navigation_cancel = cancel  # 正常退出时可取消后续扫描。
        self.cancel_button.setEnabled(True)  # 删除后的大型同级目录扫描也允许取消。
        def ready(target, error):  # 目标准备完成后回到主线程播放。
            self.busy = False  # 恢复常规操作。
            self.cancel_button.setEnabled(False)  # 目标扫描结束后恢复按钮状态。
            if error:  # 无权限等失败不伪装成正常连播。
                self.message(f'删除完成，查找下一个视频失败：{error}')  # 数据已删除的真实状态保持可见。
            elif target:  # 与 X 相同的目录边界内存在下一条。
                self.start(context, target)  # 自动播放，仍保留原来的目录顺序。
                self.message('已移入回收站，正在播放下一个视频。')  # 简短反馈成功和切换结果。
            else:  # 没有后续视频时不循环到开头。
                self.message('已移入回收站，没有下一个视频，播放已停止。')  # 明确停止原因。
        self.work(lambda: context.step_loaded(location, 1, self.store, cancel), ready)  # 跨同级目录扫描不阻塞界面。

    def stop_thumbnail_jobs(self, vids):  # 在后台释放目标文件的全部 FFmpeg 占用。
        with self.thumbnail_guard:  # 与解码进程创建使用同一个锁。
            processes = [process for vid in vids for process in self.thumbnail_processes.get(vid, set())]  # 只处理本应用启动的目标视频解码器。
            for process in processes:  # 禁止新目标进程的标志已由主线程设置。
                if process.poll() is None:  # 已结束的进程无需终止。
                    process.kill()  # 取消派生缩略图不影响用户视频数据。
        for process in processes:  # 等待操作系统关闭进程文件句柄。
            process.wait(timeout=5)  # 等待在工作线程执行，不冻结界面。

    def delete_video(self):  # Ctrl+D 优先删除明确选中的视频，否则删除当前播放视频。
        if self.busy:  # 串行执行文件任务，防止重复回收。
            self.message('文件任务正在处理，请稍候。')  # 明确当前尚未执行新删除。
            return  # 不累计危险快捷键请求。
        selected = self.tree.selectionModel().selectedIndexes() if self.tree.selectionModel() and not self.video_fullscreen.active else []  # 视频全屏不使用隐藏的旧选择。
        vid = next((index.data(Qt.UserRole) for index in selected if index.data(Qt.UserRole)), None) or self.current  # 按稳定身份选择唯一目标。
        if not vid:  # 无选择且无播放对象时不误删历史视频。
            self.message('请先选中或播放一个视频。')  # 给出操作提示。
            return  # 不创建删除任务。
        playing = vid == self.current  # 删除其他选中项时保留当前播放。
        context, location = self.context, self.location  # 固定删除前的原播放顺序。
        if not playing:  # 删除未播放的选中视频也从其目录顺序继续。
            selected_index = next(index for index in selected if index.data(Qt.UserRole) == vid)  # 查找本次明确选择的模型节点。
            _, folder, number = selected_index.internalPointer()  # 读取浏览快照的原始视频位置。
            context, location = self.browsing, (folder, number)  # 使用选中视频所在的上下文寻找下一条。
        position, paused = max(0, self.player.get_time()), self.player.get_state() != vlc.State.Playing  # 失败时可恢复当前位置和暂停状态。
        self.save()  # 先保存仍有效的播放进度。
        self.scan_cancel.set()  # 取消可能重新登记待删除路径的目录扫描。
        self.scan_serial += 1  # 旧扫描结果不再替换浏览树。
        self.navigation_cancel.set()  # 防止旧异步换片抢先切换。
        self.cancel_button.setEnabled(False)  # 当前扫描已取消。
        with self.thumbnail_guard:  # 与解码进程启动互斥。
            self.deleting_ids.add(vid)  # 禁止目标视频创建新文件占用。
        self.busy = True  # 删除期间冻结分类及换片。
        if playing:  # 仅释放待删除的当前视频。
            self.player.stop()  # 同步停止解码并释放 VLC 文件句柄。
            self.player.set_media(None)  # 解除媒体对目标路径的引用。
        self.message('正在移入回收站……')  # 不提前显示成功。
        def remove():  # 文件回收及持久提交均在后台执行。
            self.stop_thumbnail_jobs({vid})  # 先关闭本应用的缩略图文件占用。
            return self.deleter.submit(vid)  # 全部登记入口完成后才移除元数据。
        def completed(plan, error):  # 在主线程更新目录和播放状态。
            self.busy = False  # 释放当前任务状态。
            self.deleting_ids.discard(vid)  # 失败后允许继续显示原视频缩略图。
            if error:  # 文件占用或数据库失败时不跳到下一条。
                if playing:  # 尽量恢复尚存在的当前视频。
                    try:  # 多标签部分完成时仍可使用其他有效入口。
                        self.play_path(self.store.resolve(vid), position, paused)  # 删除失败保留原进度。
                    except OSError:  # 所有文件已回收但数据库尚未提交时无法重载。
                        self.clear_player()  # 保留任务日志供恢复，不访问失效身份。
                self.message(f'删除未完成：{error}；可在任务列表中重试。')  # 不因失败自动播放下一条。
                return  # 元数据继续由持久日志保护。
            self.refresh_deleted({vid})  # 成功后同步全部可见入口。
            if not playing:  # 切换到选中视频的下一条之前保存原播放器进度。
                self.save()  # 不因删除另一个文件丢失当前会话进度。
            self.after_deleted_current(context, location)  # 所有成功删除都按目标视频的原目录规则继续播放。
        self.work(remove, completed)  # 回收站和数据库操作不阻塞主线程。

    def favorite(self):  # W 只添加收藏而不切换取消。
        if self.current and not self.busy:  # 无当前视频不得误改记录。
            already = self.store.video(self.current)['star']  # 判断是否已收藏。
            self.store.execute('UPDATE videos SET star=1 WHERE id=?', (self.current,))  # 幂等设置统一收藏标记。
            self.refresh_title()  # 更新收藏状态。
            self.message('该视频已在收藏列表中。' if already else '已收藏。')  # 重复按键有简短反馈。

    def tags_dialog(self):  # Q 打开可搜索、拖动归类和确认的标签编辑器。
        if not self.current or self.busy:  # 不存在当前视频时不打开分类界面。
            return  # 避免误作用于历史记录。
        from tag_editor import TagEditor  # 按需加载层级标签界面。
        vid = self.current  # 即使自然播放结束换片，也不改变弹窗绑定身份。
        dialog = TagEditor(self.store, vid, self)  # 打开期间保留当前播放状态。
        if dialog.exec() == QDialog.Accepted:  # 所有勾选和结构变化集中确认。
            self.apply_tags(vid, dialog.chosen(), list(dialog.schema.values()))  # 成功迁移全部相关视频后再要求评分。

    def rating_dialog(self, vid=None):  # R 或标签完成回调打开十按钮整数评分界面。
        vid = vid or self.current  # 自动评分绑定原标签操作视频，不追随自然切换。
        if not vid or self.busy or not self.store.query('SELECT id FROM videos WHERE id=?', (vid,)):  # 不打开不存在或正在迁移的记录。
            return  # 不操作其他视频。
        from score_editor import ScoreEditor  # 使用直接点击的十个主评分按钮。
        dialog = ScoreEditor(self.store.video(vid), self)  # 明确显示需要评价的视频名。
        if dialog.exec() == QDialog.Accepted:  # 仅确认后持久化。
            video = self.store.video(vid)  # 获取当前归档状态。
            if video['archived']:  # 已归档评分改变必须移动全部标签入口。
                self.archive(vid, dialog.value, json.loads(video['tags']))  # 按全局层级同步路径及大类（小类）文件名。
            else:  # 未归档只保存评分等待首次 Q。
                self.store.execute('UPDATE videos SET score=? WHERE id=?', (dialog.value, vid))  # 保留未评分与零分的独立状态。
                self.refresh_title()  # 立即显示新评分。

    def refresh_names(self, vids):  # 批次完成或部分失败后显示数据库实际提交的名称。
        names = {vid: self.store.video(vid)['name'] for vid in vids if self.store.query('SELECT id FROM videos WHERE id=?', (vid,))}  # 不访问已删除身份。
        for snapshot in (self.browsing, self.context):  # 两套快照都只更新文字，不重排原序号。
            if snapshot:  # 启动恢复时可能没有目录。
                for children, files in snapshot.folders.values():  # 遍历现有显示与播放条目。
                    for number, (entry_id, entry_name) in enumerate(files):  # 使用视频身份定位全部硬链接入口。
                        if entry_id in names:  # 同一视频的多个行同步显示名称。
                            files[number] = (entry_id, names[entry_id])  # 保持原目录上下文和索引。
                snapshot.visible_cache.clear()  # 不复用旧显示名称缓存。
        self.tree.viewport().update()  # 只刷新可见区域，不折叠目录。

    def apply_tags(self, vid, tags, schema):  # 全部相关视频完成层级迁移后再弹出评分。
        self.save()  # 释放当前播放文件前保存进度。
        paused = self.resume_paused if self.resume is not None else self.player.get_state() != vlc.State.Playing  # 保留连续重载中的目标暂停状态。
        active = self.current  # 当前视频可能在标签弹窗期间自然切换。
        position = self.store.video(active)['position'] if active else 0  # 按当前会话的稳定身份恢复进度。
        self.busy, self.file_task_thumbnail_pause = True, True  # 阻止换片与新的缩略图文件占用。
        self.scan_cancel.set()  # 批量移动前取消可能登记旧路径的扫描。
        self.scan_serial += 1  # 不接收晚到的旧浏览结果。
        self.navigation_cancel.set()  # 原播放上下文仍保留，但旧异步换片请求失效。
        self.cancel_button.setEnabled(False)  # 当前没有可继续的旧扫描。
        self.player.stop()  # 全局迁移可能涉及当前视频，先释放其占用。
        self.player.set_media(None)  # 解除媒体对旧文件路径的引用。
        self.message('正在应用标签并同步相关视频，全部完成后选择评分……')  # 不提前显示成功。
        def migrate():  # 批量磁盘和数据库操作在后台执行。
            with self.thumbnail_guard:  # 安全取得本应用正在解码的身份列表。
                pending = set(self.thumbnail_processes)  # 文件任务期间新进程已被阻止。
            self.stop_thumbnail_jobs(pending)  # 取消缩略图进程，避免重命名时被本应用占用。
            return self.tag_migration.submit(vid, self.store.video(vid)['score'], tags, schema)  # 同一批次处理当前视频和所有受影响的旧视频。
        def completed(affected, error):  # 只有所有文件任务完成后才请求评分。
            self.busy, self.file_task_thumbnail_pause = False, False  # 恢复普通播放和缩略图请求。
            updated = affected or [row['id'] for row in self.store.query('SELECT id FROM videos WHERE archived=1')]  # 部分失败也反映已提交的视频名称。
            self.refresh_names(updated)  # 显示磁盘任务实际提交的状态。
            if active:  # 没有当前会话时不自动播放历史视频。
                try:  # 失败时也优先使用仍有效的来源或新入口。
                    self.play_path(self.store.resolve(active), position, paused)  # 仍沿用原播放上下文。
                except OSError as missing:  # 明确报告无法定位，不关联同名文件。
                    self.fail(missing)  # 文件日志保持可恢复。
            self.refresh_title()  # 当前视频评分和名称从数据库读取。
            if error:  # 部分完成不能进入成功后的评分流程。
                self.fail(f'{error}\n标签尚未全部应用，请在“更多 → 文件任务”恢复。')  # 明确提示批次实际状态。
            else:  # 全部相关视频均成功才弹出评分。
                self.message(f'标签已应用，已同步 {len(affected)} 个视频。')  # 成功数量来自实际批次结果。
                QTimer.singleShot(0, lambda: self.rating_dialog(vid))  # 自动弹窗仍绑定本次操作视频，而非可能换片后的当前视频。
        self.work(migrate, completed)  # 批次执行期间主界面保持响应。

    def archive(self, vid, score, tags):  # 安全释放文件后后台归档。
        self.save()  # 先保存精确播放位置。
        same = vid == self.current  # 自动连播可能在弹窗期间切换视频。
        paused = self.resume_paused if self.resume is not None else self.player.get_state() != vlc.State.Playing  # 连续分类时沿用尚未完成重载的目标暂停状态。
        position = self.store.video(self.current)['position'] if self.current else 0  # 保存需要恢复的视频进度。
        self.busy = True  # 阻止归档期间切换与进度覆盖。
        self.file_task_thumbnail_pause = True  # 评分改名也不允许后台缩略图重新占用入口。
        if same:  # 只释放正在归档视频的播放句柄。
            self.player.stop()  # VLC 占用文件时采用明确的安全重载。
            self.player.set_media(None)  # 彻底解除旧路径引用后再更新所有分类入口。
        self.message('正在归档；为释放文件句柄暂时重载，完成后恢复原进度和播放状态。')  # 说明实际执行状态。
        def done(value, error):  # 无论成功或失败都尝试恢复有效入口。
            self.busy = False  # 重新允许普通播放操作。
            self.file_task_thumbnail_pause = False  # 成功或失败后均允许重新生成派生图片。
            self.refresh_names([vid])  # 同步名称而不重新排序目录与播放上下文。
            if same:  # 只恢复本次被主动释放的视频。
                try:  # 失败任务也应有来源或新入口可播放。
                    self.play_path(self.store.resolve(vid), position, paused)  # 按稳定 ID 找到有效位置并续播。
                except OSError as restore_error:  # 无有效入口时明确显示实际问题。
                    self.fail(restore_error)  # 不伪装播放已恢复。
            self.refresh_title()  # 显示数据库实际已提交状态。
            if error:  # 失败时给出恢复入口。
                self.fail(f'{error}\n数据保留；请通过“归档任务”查看状态并重试。')  # 区分部分完成与完全成功。
            else:  # 全部旧入口清理完成才显示成功。
                self.message('归档完成；原播放顺序保持不变。')  # 告知任务真实完成。
        def submit():  # 评分移动和重命名在后台处理。
            with self.thumbnail_guard:  # 防止读取进程列表时并发增删。
                pending = set(self.thumbnail_processes)  # 新解码器已由文件任务标志禁止创建。
            self.stop_thumbnail_jobs(pending)  # 本应用不与自己争用待改名的文件。
            return self.archiver.submit(vid, score, tags)  # 始终使用已提交的全局分类结构。
        self.work(submit, done)  # 大文件复制和入口清理不阻塞界面。

    def library(self, mode):  # 显示互相独立的历史和收藏列表。
        if self.busy:  # 归档过程中不恢复其他视频。
            self.message('请等待归档完成。')  # 明确忙碌状态。
            return  # 不打开可切换视频的列表。
        dialog, layout = QDialog(self), QVBoxLayout()  # 创建列表弹窗。
        dialog.setWindowTitle({'videos': '历史视频 · 双击续播', 'folders': '历史文件夹 · 双击仅加载目录', 'stars': '收藏列表 · 双击续播'}[mode])  # 明确不同打开行为。
        dialog.resize(760, 480)  # 为完整路径和缩略图留出空间。
        dialog.setLayout(layout)  # 安装列表布局。
        listing = QListWidget()  # 创建可双击列表。
        if mode != 'folders':  # 视频历史和收藏直接逐行显示大缩略图。
            listing.setItemDelegate(VideoDelegate(self.thumbnails, listing))  # 不要求先选中记录才显示画面。
            self.thumbnails.changed.connect(listing.viewport().update)  # 异步完成后刷新当前可见列表。
        layout.addWidget(listing)  # 列表填满弹窗。
        rows = self.store.query('SELECT * FROM folders ORDER BY time DESC') if mode == 'folders' else self.store.query('SELECT * FROM videos WHERE ' + ('star=1' if mode == 'stars' else 'played>0') + ' ORDER BY played DESC')  # 独立查询三类记录。
        for row in rows:  # 为每条历史或收藏创建一行。
            item = QListWidgetItem(row['path'] if mode == 'folders' else f'{row["name"]}  ·  {format_time(row["position"])}  ·  {"未评分" if row["score"] is None else str(row["score"]) + "分"}', listing)  # 显示身份对应的进度评分。
            item.setData(Qt.UserRole, row['path'] if mode == 'folders' else row['id'])  # 视频列表以 ID 而非路径识别。
        def opened(item):  # 双击列表项执行对应恢复。
            key = item.data(Qt.UserRole)  # 读取视频 ID 或历史目录。
            try:  # 提前处理文件失效问题。
                folder = Path(key) if mode == 'folders' else self.store.resolve(key).parent  # 恢复当前有效所在目录。
                if not folder.is_dir():  # 历史目录可能已被删除。
                    raise FileNotFoundError(f'目录不存在：{folder}')  # 明确提示失效位置。
                dialog.accept()  # 关闭列表后开始扫描。
                self.load_folder(str(folder), None if mode == 'folders' else key)  # 历史文件夹绝不自动播放。
            except OSError as error:  # 缺失记录不匹配同名文件。
                QMessageBox.warning(dialog, '无法打开', str(error))  # 保留列表方便选择其他项目。
        listing.itemDoubleClicked.connect(opened)  # 双击才触发恢复。
        if mode == 'stars':  # 收藏列表提供明确取消操作。
            remove = QPushButton('取消选中视频的收藏')  # 不借用 W 作为取消开关。
            def remove_star():  # 仅取消当前列表选中条目。
                item = listing.currentItem()  # 获取选择的视频。
                if item:  # 空选择不修改记录。
                    self.store.execute('UPDATE videos SET star=0 WHERE id=?', (item.data(Qt.UserRole),))  # 收藏取消不移动文件。
                    listing.takeItem(listing.row(item))  # 从当前列表移除显示。
                    self.refresh_title()  # 同步当前视频收藏标志。
            remove.clicked.connect(remove_star)  # 绑定取消收藏操作。
            layout.addWidget(remove)  # 放置独立取消入口。
        preview = QLabel('选择视频后异步读取缓存缩略图')  # 缩略图只为实际选中记录生成。
        layout.addWidget(preview)  # 明确软件内部的预览位置。
        if mode != 'folders':  # 文件夹历史不需要视频缩略图。
            def selection():  # 为当前选择请求共享缩略图。
                item = listing.currentItem()  # 获取当前视频项。
                if not item:  # 空列表不执行解码。
                    return  # 保持初始提示。
                vid = item.data(Qt.UserRole)  # 多个硬链接入口共用视频 ID。
                def thumb_ready(path, error):  # 后台完成后只更新仍打开的弹窗。
                    if dialog.isVisible() and listing.currentItem() and listing.currentItem().data(Qt.UserRole) == vid:  # 防止晚到结果覆盖新选择。
                        if error:  # 不支持的编码显示文字而非卡死。
                            preview.setText('缩略图不可用：' + str(error))  # 与播放器兼容性分开报告。
                        else:  # 已生成的图片可安全在主线程显示。
                            from PySide6.QtGui import QPixmap  # 图片对象只在 GUI 线程构造。
                            preview.setPixmap(QPixmap(str(path)))  # 展示共享缓存图片。
                self.work(lambda: self.thumbnail(vid), thumb_ready)  # 解码和文件读取均在后台。
            listing.currentItemChanged.connect(selection)  # 选中视频才请求预览。
        dialog.exec()  # 模态窗口优先处理所有按键。

    def thumbnail(self, vid):  # 生成以稳定 ID 命名的共享缓存。
        cache = self.store.directory / 'thumbnails'  # 缓存随便携数据保存。
        cache.mkdir(exist_ok=True)  # 确保缓存目录存在。
        target = cache / f'{vid}.jpg'  # 多标签入口使用同一个缓存文件。
        if target.exists():  # 验证已有缓存满足最新尺寸要求。
            from PySide6.QtGui import QImageReader  # 仅读取图像头即可检查尺寸。
            size = QImageReader(str(target)).size()  # 不在界面线程完整解码缓存。
            if size.width() == 240 and size.height() == 160:  # 宽高均超过用户要求的 120 像素。
                return target  # 合格缓存跨多个标签入口共用。
        source = self.store.resolve(vid)  # 找到当前有效视频路径。
        ffmpeg = BUNDLE / 'ffmpeg.exe'  # 便携版内置缩略图工具。
        if not ffmpeg.exists():  # 源码运行使用隔离环境已安装的工具。
            import imageio_ffmpeg  # 仅开发环境需要该 Python 包。
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 使用包内现成二进制不在线下载。
        temporary = cache / f'{vid}-{threading.get_ident()}.jpg'  # 并发请求不共享半成品。
        command = [str(ffmpeg), '-v', 'error', '-i', str(source), '-frames:v', '1', '-vf', 'scale=240:160:force_original_aspect_ratio=decrease,pad=240:160:(ow-iw)/2:(oh-ih)/2:color=0x151b25,setsar=1', '-y', str(temporary)]  # 按原比例缩放并补边到 240×160，保证两边至少 120 像素。
        with self.thumbnail_guard:  # 进程创建与删除标志同步，避免漏掉文件占用。
            if self.file_task_thumbnail_pause or vid in self.deleting_ids or vid in self.deleted_ids:  # 文件任务已开始时不重新打开旧路径。
                raise InterruptedError('视频正在删除。')  # 由异步缓存丢弃旧请求。
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)  # 记录可取消的隐藏解码进程。
            self.thumbnail_processes.setdefault(vid, set()).add(process)  # 同一身份的并发请求全部纳入管理。
        try:  # 无论成功、超时还是删除取消都清理临时文件。
            output, errors = process.communicate(timeout=40)  # 限制坏文件的解码等待时间。
            if process.returncode:  # 被取消或解码失败时不发布半成品。
                if self.file_task_thumbnail_pause or vid in self.deleting_ids:  # 区分主动释放占用与真正的解码失败。
                    raise InterruptedError('文件任务已取消缩略图解码。')  # 允许任务结束后自动重试。
                raise OSError('缩略图解码失败或已取消。')  # 保持后台错误可见。
            with self.thumbnail_guard:  # 删除标志和缓存发布使用同一把锁。
                if self.file_task_thumbnail_pause or vid in self.deleting_ids or vid in self.deleted_ids:  # 文件任务取消的迟到结果不可重新发布。
                    raise InterruptedError('视频正在删除。')  # 不替换正式缓存。
                os.replace(temporary, target)  # 完成后原子发布缓存。
        finally:  # 释放进程、文件句柄和缓存临时文件。
            if process.poll() is None:  # 超时异常可能仍有解码进程存活。
                process.kill()  # 只结束当前缩略图子进程。
                process.communicate()  # 等待关闭原视频句柄。
            with self.thumbnail_guard:  # 与删除任务读取进程表互斥。
                self.thumbnail_processes.get(vid, set()).discard(process)  # 不保留已退出的解码器。
            temporary.unlink(missing_ok=True)  # 不积累失败产生的半成品。
        return target  # 返回可显示图片路径。

    def task_dialog(self):  # 展示真实归档阶段和失败信息。
        dialog, layout = QDialog(self), QVBoxLayout()  # 创建任务诊断窗口。
        dialog.setWindowTitle('文件任务与恢复')  # 统一展示归档和删除任务。
        dialog.resize(850, 420)  # 容纳任务标识和错误。
        dialog.setLayout(layout)  # 安装任务布局。
        text = QPlainTextEdit()  # 以只读文本展示持久任务。
        text.setReadOnly(True)  # 防止用户直接改写日志。
        text.setPlainText('\n\n'.join(f'{kind} {row["id"]}  [{row["state"]}]\n{row["error"] or "无错误"}' for table, kind in [('hierarchy_jobs', '标签结构'), ('jobs', '归档'), ('deletion_jobs', '删除')] for row in self.store.query(f'SELECT * FROM {table} ORDER BY updated DESC')) or '暂无文件任务。')  # 全局批次与逐视频任务均可诊断和恢复。
        layout.addWidget(text)  # 放置任务日志。
        retry = QPushButton('重试所有未完成任务')  # 明确执行恢复动作。
        retry.clicked.connect(lambda: (dialog.accept(), self.retry_jobs()))  # 关闭列表后异步恢复。
        layout.addWidget(retry)  # 提供可见恢复入口。
        dialog.exec()  # Esc 优先关闭当前弹窗。

    def retry_jobs(self):  # 在启动或用户要求时恢复归档。
        if self.busy:  # 禁止并发恢复。
            return  # 等待现有任务完成。
        self.save()  # 释放播放器前保存进度。
        paused = self.resume_paused if self.resume is not None else self.player.get_state() != vlc.State.Playing  # 恢复紧接重载时也保留目标播放状态。
        position = self.store.video(self.current)['position'] if self.current else 0  # 保存当前视频恢复时间。
        self.busy = True  # 恢复期间冻结切换操作。
        self.file_task_thumbnail_pause = True  # 恢复过程中不让后台解码重新占用目标。
        self.player.stop()  # 确保文件可清理和移动。
        self.player.set_media(None)  # 恢复删除任务前释放当前文件引用。
        pending = {row['video'] for row in self.store.query('SELECT video FROM deletion_jobs WHERE state<>"done"')}  # 固定本次恢复的删除身份。
        context, location = self.context, self.location  # 恢复完成后仍按原播放上下文连播。
        tag_plans = [json.loads(row['plan']) for row in self.store.query('SELECT plan FROM hierarchy_jobs WHERE state<>"done" ORDER BY updated')]  # 保存恢复完成后的名称刷新与评分目标。
        self.deleting_ids.update(pending)  # 恢复期间禁止重新生成目标缩略图。
        self.message('正在恢复未完成归档任务……')  # 提示真实恢复状态。
        def recovered(errors, error):  # 在主线程处理恢复结果。
            self.busy = False  # 恢复常规操作。
            self.file_task_thumbnail_pause = False  # 恢复完成后允许派生缩略图任务。
            self.refresh_names([entry['video'] for plan in tag_plans for entry in plan['videos']])  # 同步批次实际完成的文件名。
            self.deleting_ids.difference_update(pending)  # 失败目标允许后续正常读取。
            deleted = {vid for vid in pending if not self.store.query('SELECT id FROM videos WHERE id=?', (vid,))}  # 仅将实际提交成功的身份视为删除。
            self.refresh_deleted(deleted)  # 同步已完成的目录入口。
            if self.current in deleted:  # 当前会话删除恢复成功后也执行自动连播。
                self.after_deleted_current(context, location)  # 启动无当前视频时不会自动播放历史。
                return  # 不重载已经删除的身份。
            if self.current:  # 启动恢复不得自动播放历史视频。
                try:  # 已在播放的会话才恢复。
                    self.play_path(self.store.resolve(self.current), position, paused)  # 按稳定身份续播。
                except OSError as missing:  # 无有效入口时显示错误。
                    self.fail(missing)  # 不错误关联其他视频。
            self.refresh_title()  # 反映恢复后的实际分类。
            if error or errors:  # 任意失败保留可见诊断。
                self.fail(str(error) if error else '\n'.join(errors))  # 告知未完成任务原因。
            else:  # 全部完成后提示。
                self.message('文件任务恢复完成。')  # 不自动导入旧目录。
                if tag_plans:  # 之前明确提交的标签全部应用后仍需要评分。
                    QTimer.singleShot(0, lambda: self.rating_dialog(tag_plans[-1]['current']))  # 恢复评分不自动播放历史视频。
        def recover():  # 串行恢复归档和删除并提前释放缩略图占用。
            with self.thumbnail_guard:  # 文件恢复期间取得所有可能占用的后台进程。
                thumbnails = set(self.thumbnail_processes)  # 新任务已由恢复标志阻止启动。
            self.stop_thumbnail_jobs(thumbnails)  # 不让本应用解码器阻止恢复或改名。
            errors = self.archiver.recover() + self.tag_migration.recover()  # 先完成单视频任务，再完成全局批次。
            return errors + self.deleter.recover() if not errors else errors  # 结构迁移仍失败时保留删除任务，避免破坏安全入口。
        self.work(recover, recovered)  # 复制、校验和回收均不阻塞界面。

    def help_dialog(self):  # 显示核心交互和部署说明。
        self.message('Ctrl+D：选中视频优先，否则删除当前视频；移入回收站后自动播放下一条，末尾停止。')  # 帮助关闭后仍显示新增快捷键说明。
        QMessageBox.information(self, 'MoPlayer 使用说明', '拖入一个文件夹，双击视频播放。\n空格：播放/暂停；X/Z：下一个/上一个；左方向键/A：后退5秒；右方向键/D：快进5秒。\nEnter：切换仅视频全屏；鼠标移动显示控制栏；Esc：优先关闭弹窗，其次恢复原布局。\nQ：标签确认后归档；R：整数评分；W：仅添加收藏；Ctrl+D：移入回收站后播放下一条。\n归档根目录：E:\\我觉得是学习资料\n归档期间安全释放并重载视频，保持进度、暂停状态与原播放顺序。\n数据保存在程序旁 data 目录；启动不会恢复目录或自动播放。\n资源管理器缩略图取决于系统缩略图提供程序，详见交付说明。')  # 说明四个进度键并区分 D 与 Ctrl+D。

    def explorer_thumbnail_dialog(self):  # 为资源管理器的视频缩略图提供一次性启用与修复入口。
        if getattr(self, 'thumbnail_setup_pending', False):  # 避免同时运行多个组件配置任务。
            self.message('系统缩略图配置正在处理，请等待完成。')  # 给出真实任务状态。
            return  # 不重复下载或触发 UAC。
        dialog = QMessageBox(self)  # 启用前说明系统关联与便携运行的区别。
        dialog.setWindowTitle('资源管理器 · 视频缩略图支持')  # 明确该设置影响文件夹中的缩略图。
        dialog.setText('启用后，资源管理器会为新旧视频按需生成缩略图，并兼容 MoPlayer 默认打开方式。')  # 说明按文件类型长期生效。
        dialog.setInformativeText('使用 Icaros 3.3.6 官方便携组件，支持常见 H.264、HEVC、VP9、AV1 等编码。\n组件保存在 E:\\tools\\videoplayerenv\\plugins，首次配置可能弹出 Windows UAC。\n此功能需要单独注册系统组件；移动播放器仍可运行，但请保留上述组件目录。损坏、加密或组件不支持的文件仍可能只显示图标。')  # 给出用户需要了解的部署约束。
        enable = dialog.addButton('启用 / 修复', QMessageBox.AcceptRole)  # 用户明确选择才进行注册与下载。
        dialog.addButton('取消', QMessageBox.RejectRole)  # 取消不更改系统配置。
        dialog.exec()  # 保持对话框输入优先规则。
        if dialog.clickedButton() is not enable:  # 关闭或 Esc 均视为放弃本次操作。
            return  # 不自动安装组件。
        self.thumbnail_setup_pending = True  # 将下载与配置状态发布到界面。
        self.message('正在配置全局视频缩略图支持；如出现 Windows UAC，请确认组件注册。')  # 后台处理期间界面仍可响应。
        def completed(result, error):  # 主线程接收实际配置结果。
            self.thumbnail_setup_pending = False  # 无论结果如何都允许后续重试。
            if error:  # 不把下载、权限或注册失败显示为成功。
                self.fail(error)  # 明确显示真实原因。
            else:  # 系统组件及全部视频关联配置完成。
                self.message('全局视频缩略图支持已启用。请重新打开文件夹并使用大图标查看。')  # 不需要逐个视频手动修复。
        from setup_explorer_thumbnails import install  # 按需加载系统集成工具。
        self.work(install, completed)  # 网络、解压和 UAC 等待均不阻塞播放界面。

    def closeEvent(self, event):  # 正常退出保存进度并保护正在写入的任务。
        if getattr(self, 'thumbnail_setup_pending', False):  # 系统组件写入期间保持任务与回执完整。
            self.message('系统缩略图正在配置，请等待完成后退出。')  # 提示当前仍有明确任务。
            event.ignore()  # 不在后台提交期间关闭主进程。
            return  # 等待成功或失败回调后再退出。
        if self.busy:  # 避免正常退出打断跨卷写入。
            self.message('归档正在处理，请等待完成后退出；异常中断可在下次启动恢复。')  # 解释不能立即关闭的具体原因。
            event.ignore()  # 保持任务执行至安全状态。
            return  # 不释放数据库和播放器。
        self.scan_cancel.set()  # 取消尚未完成的扫描。
        self.navigation_cancel.set()  # 退出时同时取消同级目录延迟扫描。
        self.thumbnails.closing = True  # 停止接受新的可见行缩略图请求。
        self.save()  # 保存最后播放时间。
        self.timer.stop()  # 停止状态刷新。
        self.video_fullscreen.exit()  # 关闭浮动控件并恢复其所有权后退出。
        self.player.stop()  # 释放视频文件句柄。
        QApplication.instance().removeEventFilter(self)  # 移除应用快捷键过滤器。
        event.accept()  # 允许窗口正常关闭。

def main():  # 程序统一启动入口。
    import ctypes  # 为 Windows 任务栏设置独立的应用身份。
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MoPlayer.Desktop')  # 让任务栏使用云璃应用图标。
    app = QApplication(sys.argv)  # 初始化 Windows GUI 应用。
    app.setWindowIcon(QIcon(str(BUNDLE / 'assets/yunli.ico')))  # 为主窗口与弹窗提供统一图标。
    directory = BASE / 'data'  # 便携数据与程序保持同目录。
    try:  # 数据目录不可写时明确说明原因。
        directory.mkdir(parents=True, exist_ok=True)  # 首次启动创建数据文件夹。
        lock = QLockFile(str(directory / 'application.lock'))  # 同一数据目录仅允许一个实例写入。
        if not lock.tryLock(100):  # 防止两个进程同时归档相同视频。
            from file_open import forward  # 将外部视频请求交给已有主进程。
            if forward(directory, sys.argv[1] if len(sys.argv) > 1 else None):  # 中文和空格路径通过本地管道传输。
                return 0  # 已由现有窗口接收，不重复打开数据库。
            QMessageBox.warning(None, 'MoPlayer', '现有实例暂时无法接收文件，请稍后重试。')  # 不谎报打开成功。
            return 1  # 安全结束重复进程。
        from logging.handlers import RotatingFileHandler  # 限制日志长期占用。
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[RotatingFileHandler(directory / 'moplayer.log', maxBytes=4 * 1024 * 1024, backupCount=3, encoding='utf-8')])  # 日志全部写入便携数据目录。
        window = Window(directory)  # 创建主界面但不导入历史目录。
        window.show()  # 展示可直接操作的播放器。
        from file_open import FileOpenServer  # 加载默认应用文件接收服务。
        window.file_server = FileOpenServer(window, directory)  # 在数据库锁保护下创建唯一接收端点。
        if len(sys.argv) > 1:  # 只有用户通过文件关联明确打开时才自动播放。
            window.file_server.pending.append(sys.argv[1])  # 普通无参数启动仍不恢复目录或视频。
        result = app.exec()  # 进入原生事件循环。
        QThreadPool.globalInstance().waitForDone()  # 等待已取消的工作线程安全退出。
        window.thumbnails.pool.waitForDone()  # 等待独立缩略图池安全关闭，避免销毁运行中的 FFmpeg 任务。
        lock.unlock()  # 正常释放单实例锁。
        return result  # 返回 GUI 退出状态。
    except Exception as error:  # 启动失败给出可见提示。
        QMessageBox.critical(None, 'MoPlayer 启动失败', str(error))  # 避免无控制台便携程序静默退出。
        return 1  # 报告失败退出码。

if __name__ == '__main__':  # 仅直接运行时启动应用。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-nesting-test':  # 仅检查互斥展开、父类嵌套和删除标签。
        from verify_tag_nesting import run  # 测试使用指定目录的隔离视频和数据库。
        run(sys.argv[2])  # 不启动正常播放器或读取用户数据。
        sys.exit(0)  # 专项结束立即退出。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-cards-test':  # 仅检查新胶囊标签与半颗心评分，不运行完整回归。
        from verify_tag_cards import run  # 专项直接使用包内正式界面和隔离样例。
        run(sys.argv[2])  # 测试输出必须由调用者明确指定。
        sys.exit(0)  # 专项完成后不打开用户数据库或主窗口。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-hierarchy-test':  # 验证全局标签层级和完成后的自动按钮评分。
        from verify_tag_hierarchy import run  # 测试只使用明确指定的隔离目录。
        sys.exit(run(sys.argv[2]))  # 生成实际文件、界面截图及检查报告。
    if len(sys.argv) == 3 and sys.argv[1] == '--delete-test':  # 用隔离样例验证真实快捷键回收与自动连播。
        from verify_delete import run  # 按需加载删除验收入口。
        sys.exit(run(sys.argv[2]))  # 不使用用户的视频与元数据。
    if len(sys.argv) == 3 and sys.argv[1] == '--explorer-thumbnail-test':  # 验证系统组件及 MoPlayer 两种默认关联。
        from verify_explorer_thumbnails import run  # 按需加载全局缩略图验收。
        sys.exit(run(sys.argv[2]))  # 样例和报告写入独立目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--ui-test':  # 便携版可检查外观资源与背景设置。
        from verify_ui import run  # 按需加载外观回归检查。
        sys.exit(run(sys.argv[2]))  # 将结果保存到独立测试目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--thumbnail-test':  # 便携版可直接验证缩略图实际显示。
        from verify_thumbnails import run  # 按需加载可见缩略图回归检查。
        sys.exit(run(sys.argv[2]))  # 将截图和报告写入指定隔离目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':  # 提供便携版无开发环境的自检入口。
        from verify import run  # 按需加载验收代码。
        sys.exit(run(sys.argv[2]))  # 将测试数据写入明确指定的目录。
    sys.exit(main())  # 交付操作系统最终退出状态。

