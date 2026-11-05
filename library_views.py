"""Library widgets and item rendering consume prepared presentation data."""
from pathlib import Path
import time
from PySide6.QtCore import Qt, Signal, QAbstractItemModel, QModelIndex, QSize, QRect, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QStyledItemDelegate, QStyle, QTreeView
from ui import format_time

THUMB_VIEW = (140, 79)
THUMB_ROW = 96
THUMB_RADIUS = 5

class VideoDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails, parent, *, current_video, details, theme_owner):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.current_video, self.details, self.theme_owner = current_video, details, theme_owner

    def sizeHint(self, option, index):
        return QSize(300, THUMB_ROW) if index.data(Qt.UserRole) else QSize(180, 32)

    def paint(self, painter, option, index):
        vid = index.data(Qt.UserRole)
        if not vid:
            super().paint(painter, option, index)
            return
        from theme import theme_tokens
        colors = theme_tokens(self.theme_owner)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        playing = self.current_video() == vid
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        card = option.rect.adjusted(1, 2, -2, -2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors['selected'] if selected else colors['hover'] if hovered else colors['library_bg']))
        painter.drawRoundedRect(card, 6, 6)
        if playing:
            painter.setBrush(QColor(colors['accent']))
            painter.drawRoundedRect(QRectF(card.left(), card.top() + 12, 3, card.height() - 24), 1.5, 1.5)
        area = QRect(option.rect.left() + 10, option.rect.top() + 8, THUMB_VIEW[0], THUMB_VIEW[1])
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(area, THUMB_RADIUS, THUMB_RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(area, QColor(colors['thumb']))
        image = self.thumbnails.request(vid)
        if image is not None:
            painter.drawPixmap(area, image)
        elif vid in self.thumbnails.errors:
            painter.setPen(QColor(colors['text_dim']))
            painter.drawText(area, Qt.AlignCenter, '—')
        else:
            phase = (time.monotonic() % 1.1) / 1.1
            alpha = int(18 + 20 * (1 - abs(phase * 2 - 1)))
            painter.fillRect(area.adjusted(10, 10, -10, -10), QColor(255, 255, 255, alpha))
        painter.restore()
        if playing:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors['accent']))
            painter.drawEllipse(QRectF(area.right() - 13, area.top() + 7, 6, 6))
        row = self.details.get(vid, {})
        name = str(index.data(Qt.DisplayRole))
        text_area = QRect(area.right() + 12, area.top() + 5, max(0, option.rect.right() - area.right() - 18), 42)
        painter.setFont(option.font)
        painter.setPen(QColor(colors['text_strong'] if selected or playing else colors['text']))
        text_layout = QTextLayout(name, option.font)
        wrapping = QTextOption()
        wrapping.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        text_layout.setTextOption(wrapping)
        text_layout.beginLayout()
        first = text_layout.createLine()
        if first.isValid():
            first.setLineWidth(text_area.width())
            start_second = first.textStart() + first.textLength()
        else:
            start_second = len(name)
        text_layout.endLayout()
        if first.isValid():
            first.draw(painter, QPointF(text_area.left(), text_area.top()))
        if start_second < len(name):
            second = option.fontMetrics.elidedText(name[start_second:], Qt.ElideRight, text_area.width())
            painter.drawText(text_area.adjusted(0, option.fontMetrics.height() + 2, 0, 0), Qt.AlignLeft | Qt.AlignTop, second)
        details = []
        if row.get('position', 0) > 0:
            details.append(format_time(row['position']))
        if row.get('score') is not None:
            details.append(f"{row['score']} 分")
        if row.get('star'):
            details.append('★')
        if details:
            painter.setPen(QColor(colors['text_dim']))
            small = QFont(option.font)
            small.setPixelSize(12)
            painter.setFont(small)
            painter.drawText(QRect(text_area.left(), area.bottom() - 22, text_area.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, ' · '.join(details))
        painter.restore()

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
        return None

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
        event.acceptProposedAction()
