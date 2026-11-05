"""Library widgets and item rendering consume prepared presentation data."""
from pathlib import Path
import time
from PySide6.QtCore import Qt, Signal, QAbstractItemModel, QAbstractListModel, QModelIndex, QSize, QRect, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QStyledItemDelegate, QStyle, QTreeView
from ui import format_time

THUMB_VIEW = (140, 79)
THUMB_ROW = 96
THUMB_RADIUS = 5
DETAILS_ROLE = Qt.UserRole + 1

class VideoDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails, parent, *, current_video, theme_owner):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.current_video, self.theme_owner = current_video, theme_owner

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
        painter.setBrush(QColor(colors['selected'] if selected else colors['hover'] if hovered else colors['row_bg']))
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
        row = index.data(DETAILS_ROLE) or {}
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

class VideoListModel(QAbstractListModel):
    """Stable identities survive insertions, removals and recent-list moves."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.UserRole:
            return row['id']
        if role == DETAILS_ROLE:
            return row
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return row['name']
        return None

    def index_for_id(self, video_id):
        number = next((n for n, row in enumerate(self.rows) if row['id'] == video_id), -1)
        return self.index(number, 0) if number >= 0 else QModelIndex()

    def sync(self, rows):
        wanted = {row['id'] for row in rows}
        for number in range(len(self.rows) - 1, -1, -1):
            if self.rows[number]['id'] not in wanted:
                self.beginRemoveRows(QModelIndex(), number, number)
                self.rows.pop(number)
                self.endRemoveRows()
        positions = {row['id']: n for n, row in enumerate(self.rows)}
        for number, row in enumerate(rows):
            source = positions.get(row['id'])
            if source is None:
                self.beginInsertRows(QModelIndex(), number, number)
                self.rows.insert(number, dict(row))
                self.endInsertRows()
            elif source != number:
                self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), number)
                self.rows.insert(number, self.rows.pop(source))
                self.endMoveRows()
            if source is None or source != number:
                positions.update((self.rows[n]['id'], n) for n in range(number, len(self.rows)))
            if self.rows[number] != row:
                self.rows[number] = dict(row)
                index = self.index(number, 0)
                self.dataChanged.emit(index, index)

    def notify(self, video_ids):
        ids = set(video_ids)
        for number, row in enumerate(self.rows):
            if row['id'] in ids:
                index = self.index(number, 0)
                self.dataChanged.emit(index, index)


class TreeModel(QAbstractItemModel):
    """Presentation projection; original playback indices never move.

    Visible rows are owned here so beginRemoveRows sees the old row count even
    after the application has excluded an identity from its snapshot.
    """
    def __init__(self, snapshot, details=None, parent=None):
        super().__init__(parent)
        self.root = snapshot.root
        self.children = {folder: tuple(children) for folder, (children, _) in snapshot.folders.items()}
        self.files = {folder: list(snapshot.visible_files(folder)) for folder in self.children}
        self.details = dict(details or {})
        self.nodes = {}

    def columnCount(self, parent=QModelIndex()):
        return 1

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return 1
        kind, folder, _ = parent.internalPointer()
        return len(self.children[folder]) + len(self.files[folder]) if kind == 'folder' else 0

    def _index(self, row, node):
        return self.createIndex(row, 0, self.nodes.setdefault(node, node))

    def folder_index(self, folder):
        if folder not in self.children:
            return QModelIndex()
        row = 0 if folder == self.root else self.children[str(Path(folder).parent)].index(folder)
        return self._index(row, ('folder', folder, -1))

    def index(self, row, column, parent=QModelIndex()):
        if column != 0 or row < 0 or row >= self.rowCount(parent):
            return QModelIndex()
        if not parent.isValid():
            return self.folder_index(self.root)
        folder = parent.internalPointer()[1]
        children = self.children[folder]
        if row < len(children):
            return self.folder_index(children[row])
        return self._index(row, ('video', folder, self.files[folder][row - len(children)][0]))

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        kind, folder, _ = index.internalPointer()
        if kind == 'folder' and folder == self.root:
            return QModelIndex()
        return self.folder_index(folder if kind == 'video' else str(Path(folder).parent))

    def _entry(self, index):
        _, folder, _ = index.internalPointer()
        return self.files[folder][index.row() - len(self.children[folder])][1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        kind, folder, _ = index.internalPointer()
        if role == Qt.UserRole:
            return self._entry(index)[0] if kind == 'video' else None
        if role == DETAILS_ROLE:
            return self.details.get(self._entry(index)[0], {}) if kind == 'video' else None
        if role == Qt.DisplayRole:
            return Path(folder).name if kind == 'folder' else self._entry(index)[1]
        if role == Qt.ToolTipRole:
            return folder
        if role == Qt.DecorationRole:
            style = QApplication.style()
            return style.standardIcon(style.StandardPixmap.SP_DirIcon if kind == 'folder' else style.StandardPixmap.SP_MediaPlay)
        return None

    def sync(self, snapshot, details, video_ids):
        self.details = dict(details)
        ids = set(video_ids)
        for folder in self.children:
            parent = self.folder_index(folder)
            offset = len(self.children[folder])
            visible = dict(snapshot.visible_files(folder))
            for number in range(len(self.files[folder]) - 1, -1, -1):
                original, _ = self.files[folder][number]
                if original not in visible:
                    self.beginRemoveRows(parent, offset + number, offset + number)
                    self.files[folder].pop(number)
                    self.endRemoveRows()
            for number, (original, entry) in enumerate(self.files[folder]):
                updated = visible[original]
                self.files[folder][number] = (original, updated)
                if entry != updated or updated[0] in ids:
                    index = self.index(offset + number, 0, parent)
                    self.dataChanged.emit(index, index)

    def notify(self, video_ids):
        ids = set(video_ids)
        for folder, files in self.files.items():
            parent = self.folder_index(folder)
            offset = len(self.children[folder])
            for number, (_, (vid, _)) in enumerate(files):
                if vid in ids:
                    index = self.index(offset + number, 0, parent)
                    self.dataChanged.emit(index, index)

class DropTree(QTreeView):
    dropped = Signal(str)

    def __init__(self, can_import):
        super().__init__()  # 初始化目录控件。
        self.can_import = can_import
        self.setAcceptDrops(True)
        self.setHeaderHidden(True)  # 简化目录区域。
        self.setUniformRowHeights(False)  # 视频行与文件夹分别使用委托提供的高度。
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 左侧被拖窄或目录过深时允许横向查看完整图片。
        self.setEditTriggers(QTreeView.NoEditTriggers)  # 文件名不可直接编辑。

    def _drop_path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if self.can_import(path):
                return path
        return None

    def dragEnterEvent(self, event):
        if self._drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        path = self._drop_path(event)
        if path is None:
            event.ignore()
            return
        self.dropped.emit(path)
        event.acceptProposedAction()
