"""Bounded metadata heading with an optional, presentation-only inline editor."""
from pathlib import Path
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QLineEdit, QSizePolicy, QToolButton, QWidget
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
        self._rename = None
        self._available = False
        self._saving = False
        self._edit_serial = 0
        self.editor = QLineEdit(self)
        self.editor.setObjectName('filenameEditor')
        self.editor.setAccessibleName('文件名')
        self.editor.setMaxLength(1024)
        self.editor.hide()
        self.editor.installEventFilter(self)
        self.editor.returnPressed.connect(self._submit)
        self.editor.textEdited.connect(lambda: self._error(''))
        self.edit_button = QToolButton(self)
        self.edit_button.setToolTip('重命名文件')
        self.edit_button.setAccessibleName('重命名文件')
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.clicked.connect(self.begin_edit)
        self.edit_button.hide()
        self.error_label = QLabel(self)
        self.error_label.hide()

    def set_rename_handler(self, handler):
        self._rename = handler
        self._layout_editor()

    def set_rename_available(self, available):
        self._available = bool(available)
        if not available and not self._saving:
            self.cancel_edit()
        self.edit_button.setEnabled(available)

    def _title_layout(self):
        font = QFont(self.font())
        font.setPixelSize(12)
        metrics = QFontMetrics(font)
        available = max(0, self.width()-32-(32 if self._rename else 0))
        budget = max(0, min(available*.46, available-140))
        widths = [min(128,metrics.horizontalAdvance(tag)+20) for tag in self.tags]
        visible, used = [], 0
        for index,width in enumerate(widths):
            overflow = metrics.horizontalAdvance(f'+{len(widths)-index-1}')+20 if index<len(widths)-1 else 0
            if used+width+6+overflow>budget:
                break
            visible.append((self.tags[index],width))
            used += width+6
        remaining = len(self.tags)-len(visible)
        if remaining and budget>=32:
            visible.append((f'+{remaining}',metrics.horizontalAdvance(f'+{remaining}')+20))
        x = 16+sum(width+6 for _,width in visible)
        return visible, QRect(x,7,max(0,self.width()-x-16-(32 if self._rename else 0)),28)

    def _layout_editor(self):
        _, rect = self._title_layout()
        self.editor.setGeometry(rect)
        self.edit_button.setGeometry(self.width()-44,7,28,28)
        self.error_label.setGeometry(280,39,max(0,self.width()-296),24)

    def begin_edit(self):
        if not self._rename or not self._available or not self.filename or self._saving:
            return
        self._edit_serial += 1
        self.editor.setText(self.filename)
        self.editor.setReadOnly(False)
        self._error('')
        self._layout_editor()
        self.editor.show()
        self.edit_button.hide()
        self.editor.setFocus(Qt.MouseFocusReason)
        stem = Path(self.filename).stem
        self.editor.setSelection(0,len(stem.encode('utf-16-le'))//2)
        self.update()

    def cancel_edit(self):
        self._edit_serial += 1
        self._saving = False
        self.editor.hide()
        self.editor.setReadOnly(False)
        self._error('')
        self.edit_button.setVisible(bool(self._rename and self.filename and self.underMouse() and self.isVisible()))
        self.update()

    def _error(self, message):
        self.editor.setToolTip(message)
        self.error_label.setToolTip(message)
        self.error_label.setText(QFontMetrics(self.error_label.font()).elidedText(message,Qt.ElideRight,self.error_label.width()))
        self.error_label.setVisible(bool(message) and self.editor.isVisible())
        color = '#d85151' if message else self.colors['accent']
        self.editor.setStyleSheet(f'QLineEdit {{ color:{self.colors["text_strong"]}; background:{self.colors["selected"]}; border:1px solid {color}; border-radius:5px; padding:0 5px; font-size:16px; font-weight:600; }}')

    def _submit(self):
        if self._saving or not self.editor.isVisible():
            return
        serial = self._edit_serial
        self._saving = True
        self.editor.setReadOnly(True)
        self._error('')
        def completed(outcome):
            if serial != self._edit_serial:
                return
            self._saving = False
            if outcome.succeeded:
                self.cancel_edit()
            else:
                self.editor.setReadOnly(False)
                message = str(outcome.error) if outcome.error else '暂时无法重命名，请等待文件任务完成后重试。'
                if outcome.recoverable:
                    message += ' 请在“更多 → 文件任务”恢复。'
                self._error(message)
                self.editor.setFocus(Qt.OtherFocusReason)
        try:
            self._rename(self.editor.text()).on_finished(completed)
        except Exception as error:
            self._saving = False
            self.editor.setReadOnly(False)
            self._error(str(error))

    def eventFilter(self, obj, event):
        if obj is self.editor:
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                if not self._saving:
                    self.cancel_edit()
                return True
            if event.type() == QEvent.FocusOut and not self._saving:
                self.cancel_edit()
        return super().eventFilter(obj,event)

    def enterEvent(self, event):
        self.edit_button.setVisible(bool(self._rename and self.filename and not self.editor.isVisible()))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.edit_button.hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.cancel_edit()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self._layout_editor()
        super().resizeEvent(event)

    def sizeHint(self):
        return QSize(480, 72)

    def present(self, filename, tags, score, starred):
        self.filename, self.tags, self.score, self.starred = filename, tuple(tags), score, bool(starred)
        status = '已收藏' if starred else '未收藏'
        rating = '未评分' if score is None else f'{score} 分'
        self.setAccessibleName(filename or '播放器')
        self.setAccessibleDescription('，'.join((*self.tags, status, rating)))
        self.setToolTip('\n'.join((filename, ' · '.join(self.tags), status+' · '+rating)))
        self._layout_editor()
        self.update()

    def apply_colors(self, colors):
        self.colors = dict(colors)
        self.edit_button.setIcon(icon('edit',colors['text_mid'],18))
        self.edit_button.setStyleSheet('QToolButton { background:transparent; border:none; border-radius:5px; } QToolButton:hover { background:'+colors['selected']+'; }')
        self.error_label.setStyleSheet('color:#d85151; font-size:11px; background:transparent;')
        self._error(self.editor.toolTip())
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
        visible, title_rect = self._title_layout()
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
        title=QFontMetrics(font).elidedText(self.filename,Qt.ElideRight,title_rect.width())
        if not self.editor.isVisible():
            painter.drawText(title_rect,Qt.AlignVCenter|Qt.AlignLeft,title)

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
