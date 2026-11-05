"""Library widgets and item rendering consume prepared presentation data."""
from pathlib import Path
from collections import Counter, defaultdict, deque
import time
from PySide6.QtCore import Qt, Signal, QAbstractListModel, QModelIndex, QSize, QRect, QRectF, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QStyledItemDelegate, QStyle, QListView
from ui import format_time

THUMB_VIEW = (140, 79)
THUMB_ROW = 96
THUMB_RADIUS = 5
DETAILS_ROLE = Qt.UserRole + 1
FOLDER_ROLE = Qt.UserRole + 2
LOCATION_ROLE = Qt.UserRole + 3

class VideoDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails, parent, *, current_video, theme_owner):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.current_video, self.theme_owner = current_video, theme_owner

    def sizeHint(self, option, index):
        return QSize(300, THUMB_ROW) if index.data(Qt.UserRole) else QSize(180, 44)

    def paint(self, painter, option, index):
        vid = index.data(Qt.UserRole)
        folder = index.data(FOLDER_ROLE)
        if not vid and not folder:
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
        if folder:
            area = QRect(option.rect.left() + 10, option.rect.center().y() - 10, 20, 20)
            QApplication.style().standardIcon(QStyle.SP_DirIcon).paint(painter, area)
            painter.setFont(option.font)
            painter.setPen(QColor(colors['text']))
            text_area = option.rect.adjusted(42, 0, -24, 0)
            text = option.fontMetrics.elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, text_area.width())
            painter.drawText(text_area, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.setPen(QColor(colors['text_dim']))
            painter.drawText(option.rect.adjusted(0, 0, -10, 0), Qt.AlignRight | Qt.AlignVCenter, '›')
            painter.restore()
            return
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

def _sync_rows(model, rows, key):
    """Reconcile keyed presentation rows without resetting Qt selection."""
    wanted = {key(row) for row in rows}
    for number in range(len(model.rows) - 1, -1, -1):
        if key(model.rows[number]) not in wanted:
            model.beginRemoveRows(QModelIndex(), number, number)
            model.rows.pop(number)
            model.endRemoveRows()
    positions = {key(row): n for n, row in enumerate(model.rows)}
    changed = set()
    for number, row in enumerate(rows):
        identity = key(row)
        source = positions.get(identity)
        if source is None:
            model.beginInsertRows(QModelIndex(), number, number)
            model.rows.insert(number, dict(row))
            model.endInsertRows()
        elif source != number:
            model.beginMoveRows(QModelIndex(), source, source, QModelIndex(), number)
            model.rows.insert(number, model.rows.pop(source))
            model.endMoveRows()
        if source is None or source != number:
            positions.update((key(model.rows[n]), n) for n in range(number, len(model.rows)))
        if model.rows[number] != row:
            model.rows[number] = dict(row)
            index = model.index(number, 0)
            model.dataChanged.emit(index, index)
            changed.add(identity)
    return changed


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

    def key(self, index):
        return index.data(Qt.UserRole)

    def index_for_key(self, key):
        return self.index_for_id(key)

    def sync(self, rows):
        _sync_rows(self, rows, lambda row: row['id'])

    def notify(self, video_ids):
        ids = set(video_ids)
        for number, row in enumerate(self.rows):
            if row['id'] in ids:
                index = self.index(number, 0)
                self.dataChanged.emit(index, index)


class FolderModel(QAbstractListModel):
    """Stable entry keys and snapshot locations have separate lifetimes."""
    def __init__(self, snapshot, folder, details=None, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.details = dict(details or {})
        self.rows = []
        self._snapshot = None
        self.rows = self._project(snapshot)
        self._snapshot = snapshot

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        row = self.rows[index.row()]
        if role == Qt.UserRole:
            return row['id']
        if role == FOLDER_ROLE:
            return row['folder']
        if role == LOCATION_ROLE:
            return row['location']
        if role == DETAILS_ROLE:
            return self.details.get(row['id'], {}) if row['id'] else None
        if role == Qt.DisplayRole:
            return row['name']
        if role == Qt.ToolTipRole:
            return row['folder'] or str(Path(self.folder) / row['name'])
        return None

    def key(self, index):
        if not index.isValid():
            return None
        return self.rows[index.row()]['key']

    def index_for_key(self, key):
        exact = next((n for n, row in enumerate(self.rows) if row['key'] == key), None)
        if exact is not None:
            return self.index(exact, 0)
        if key and key[0] == 'video':
            matches = [(n, row) for n, row in enumerate(self.rows) if row['id'] == key[1]]
            named = [n for n, row in matches if row['name'] == key[2]]
            if len(named) == 1:
                return self.index(named[0], 0)
        return QModelIndex()

    def index_for_location(self, location):
        return next((self.index(n, 0) for n, row in enumerate(self.rows) if row['location'] == location), QModelIndex())

    def _project(self, snapshot):
        children, _ = snapshot.folders[self.folder]
        rows = [dict(key=('folder', child), id=None, name=Path(child).name or child,
                     folder=child, location=None) for child in children]
        videos = [dict(key=('video', vid, name, number), id=vid, name=name,
                       folder=None, location=(self.folder, number))
                  for number, (vid, name) in snapshot.visible_files(self.folder)]
        unused = {row['key']: row for row in self.rows if row['id']}
        existing = defaultdict(deque)
        same_snapshot = snapshot is self._snapshot
        for row in unused.values():
            existing[(row['id'], row['location'] if same_snapshot else row['name'])].append(row)
        unmatched = []
        for row in videos:
            candidates = existing[(row['id'], row['location'] if same_snapshot else row['name'])]
            match = candidates.popleft() if candidates else None
            if match is None:
                unmatched.append(row)
            else:
                row['key'] = match['key']
                del unused[match['key']]
        remaining = defaultdict(list)
        for row in unused.values():
            remaining[row['id']].append(row)
        counts = Counter(row['id'] for row in unmatched)
        for row in unmatched:
            old = remaining[row['id']]
            # A unique identity can survive an external rename. Ambiguous hard
            # link aliases are matched by name above, never by shifted row number.
            if len(old) == counts[row['id']] == 1:
                row['key'] = old[0]['key']
        return rows + videos

    def sync(self, snapshot, details, video_ids):
        self.details = dict(details)
        changed = _sync_rows(self, self._project(snapshot), lambda row: row['key'])
        self._snapshot = snapshot
        ids = set(video_ids)
        for number, row in enumerate(self.rows):
            if row['id'] in ids and row['key'] not in changed:
                index = self.index(number, 0)
                self.dataChanged.emit(index, index)

    def notify(self, video_ids):
        ids = set(video_ids)
        for number, row in enumerate(self.rows):
            if row['id'] in ids:
                index = self.index(number, 0)
                self.dataChanged.emit(index, index)

class DropList(QListView):
    dropped = Signal(str)

    def __init__(self, can_import):
        super().__init__()
        self.can_import = can_import
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QListView.NoEditTriggers)

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
