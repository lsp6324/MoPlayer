"""Managed media cards consume prepared rows and share title metadata graphics."""
from PySide6.QtCore import Qt, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from library_views import DETAILS_ROLE, THUMB_VIEW, THUMB_ROW, THUMB_RADIUS
from media_badges import paint_capsule, paint_favorite
from heart_rating import paint_hearts
from theme import theme_tokens


class CatalogDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails, parent, *, current_video, theme_owner,
                 presentation=lambda: 'list', tile_size=lambda: QSize(140, 148)):
        super().__init__(parent)
        self.thumbnails, self.current_video, self.theme_owner = thumbnails, current_video, theme_owner
        self.presentation, self.tile_size = presentation, tile_size

    def sizeHint(self, option, index):
        return self.tile_size() if self.presentation() == 'grid' else QSize(300, THUMB_ROW)

    def paint(self, painter, option, index):
        row = index.data(DETAILS_ROLE)
        if not row:
            return
        colors = theme_tokens(self.theme_owner)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        playing = self.current_video() == row.get('id')
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        grid = self.presentation() == 'grid'
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors['selected'] if selected else colors['hover'] if hovered else colors['row_bg']))
        painter.drawRoundedRect(rect.adjusted(1, 2, -2, -2), 6, 6)
        thumb_width = max(1, rect.width() - 16) if grid else THUMB_VIEW[0]
        thumb = QRect(rect.left() + (8 if grid else 10), rect.top() + 8,
                      thumb_width, thumb_width * 9 // 16 if grid else THUMB_VIEW[1])
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(thumb, THUMB_RADIUS, THUMB_RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(thumb, QColor(colors['thumb']))
        image = self.thumbnails.request(row.get('id'))
        if image is not None:
            painter.drawPixmap(thumb, image)
        else:
            painter.setPen(QColor(colors['text_dim']))
            painter.drawText(thumb, Qt.AlignCenter, '图片' if row.get('kind') == 'image' else '视频')
        if row.get('unavailable'):
            background = QColor(colors['surface_dim'])
            background.setAlpha(225)
            notice = thumb.adjusted(0, thumb.height() - 19, 0, 0)
            painter.fillRect(notice, background)
            painter.setPen(QColor(colors['text']))
            small = QFont(option.font)
            small.setPixelSize(11)
            painter.setFont(small)
            painter.drawText(notice, Qt.AlignCenter, '暂不可用')
        painter.restore()
        if playing:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors['accent']))
            painter.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 10, 3, rect.height() - 20), 1.5, 1.5)
        font = QFont(option.font)
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor(colors['text_strong'] if playing or selected else colors['text']))
        left = rect.left() + 8 if grid else thumb.right() + 12
        width = max(0, rect.width() - 16 if grid else rect.right() - thumb.right() - 22)
        title_y = thumb.bottom() + 4 if grid else thumb.top() + 5
        tags_y = title_y + 25
        favorite_y = title_y + (47 if grid else 49)
        name = str(row.get('name') or '')
        metrics = painter.fontMetrics()
        painter.drawText(QRect(left, title_y, width, 22), Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(name, Qt.ElideRight, width))
        font.setPixelSize(11)
        painter.setFont(font)
        paint_favorite(painter, left, favorite_y, bool(row.get('star')), colors)
        hearts_x = left + 62
        step = max(9, min(12 if grid else 16, (width - 62) // 5))
        paint_hearts(painter, row.get('score'), (QRectF(hearts_x + n * step, favorite_y + 4, step - 1, step - 1) for n in range(5)),
                     colors['accent'], colors['line_strong'], 1)
        x, available = left, width
        tags = row.get('tag_labels') or row.get('tag_names') or ()
        for number, tag in enumerate(tags):
            rest = len(tags) - number
            reserve = painter.fontMetrics().horizontalAdvance(f'+{rest - 1}') + 26 if rest > 1 else 0
            natural_width = painter.fontMetrics().horizontalAdvance(tag) + 20
            width_tag = min(120, natural_width, available - reserve)
            if width_tag < min(48, natural_width):
                paint_capsule(painter, QRectF(x, tags_y, min(available, 42), 20), f'+{rest}', colors)
                break
            paint_capsule(painter, QRectF(x, tags_y, width_tag, 20), tag, colors)
            x, available = x + width_tag + 6, available - width_tag - 6
        painter.restore()
