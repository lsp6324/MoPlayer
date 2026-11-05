"""Read-only, bounded media heading shared by normal and fullscreen views."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget
from heart_rating import paint_hearts
from ui import icon


class MediaHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filename, self.tags, self.score, self.starred = '', (), None, False
        self.colors = dict(text_strong='#182c47', text_mid='#66768c', accent='#376fd4',
                           selected='#e5edfb', line='#ccd7e9')
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(480, 72)

    def present(self, filename, tags, score, starred):
        self.filename, self.tags, self.score, self.starred = filename, tuple(tags), score, bool(starred)
        status = '已收藏' if starred else '未收藏'
        rating = '未评分' if score is None else f'{score} 分'
        self.setAccessibleName(filename or '播放器')
        self.setAccessibleDescription('，'.join((*self.tags, status, rating)))
        self.setToolTip('\n'.join((filename, ' · '.join(self.tags), status+' · '+rating)))
        self.update()

    def apply_colors(self, colors):
        self.colors = dict(colors)
        self.update()

    def paintEvent(self, event):
        if not self.filename:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        available = max(0, self.width()-32)
        budget = max(0, min(available*.46, available-140))
        widths = [min(128,metrics.horizontalAdvance(tag)+20) for tag in self.tags]
        visible = []
        used = 0
        for index,width in enumerate(widths):
            overflow = metrics.horizontalAdvance(f'+{len(widths)-index-1}')+20 if index<len(widths)-1 else 0
            if used+width+6+overflow>budget:
                break
            visible.append((self.tags[index],width))
            used += width+6
        remaining=len(self.tags)-len(visible)
        if remaining and budget>=32:
            visible.append((f'+{remaining}',metrics.horizontalAdvance(f'+{remaining}')+20))
        x=16
        for text,width in visible:
            rect=QRectF(x,8,width,25)
            painter.setBrush(QColor(self.colors['selected']))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect,12,12)
            painter.setPen(QColor(self.colors['accent']))
            painter.drawText(rect.adjusted(10,0,-10,0),Qt.AlignVCenter|Qt.AlignLeft,
                             metrics.elidedText(text,Qt.ElideRight,int(width-20)))
            x+=width+6
        font.setPixelSize(16)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(self.colors['text_strong']))
        title=QFontMetrics(font).elidedText(self.filename,Qt.ElideRight,max(0,self.width()-x-16))
        painter.drawText(QRectF(x,7,max(0,self.width()-x-16),28),Qt.AlignVCenter|Qt.AlignLeft,title)

        font.setPixelSize(12)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        star_color='#d39a2d' if self.starred else self.colors['text_mid']
        painter.drawPixmap(16,43,icon('starFilled' if self.starred else 'star',star_color,16).pixmap(16,16))
        painter.setPen(QColor(self.colors['text_mid']))
        painter.drawText(QRectF(38,39,60,24),Qt.AlignVCenter|Qt.AlignLeft,'已收藏' if self.starred else '未收藏')
        paint_hearts(painter,self.score,(QRectF(112+index*22,42,18,18) for index in range(5)),
                     self.colors['accent'],self.colors['line'],1.2)
        painter.setPen(QColor(self.colors['text_mid']))
        painter.drawText(QRectF(232,39,max(0,self.width()-248),24),Qt.AlignVCenter|Qt.AlignLeft,
                         '未评分' if self.score is None else f'{self.score} 分')
