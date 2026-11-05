"""Self-contained preset swatches, saturation/value field, hue and RGB controls."""
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient, QPalette
from PySide6.QtWidgets import (QWidget, QToolButton, QLabel, QSlider, QSpinBox,
                               QVBoxLayout, QHBoxLayout, QGridLayout)
from accent_colors import PRESETS, normalize_color, rgb, contrast


class SwatchButton(QToolButton):
    def __init__(self, name, color, parent=None):
        super().__init__(parent)
        self.color = color
        self.setCheckable(True)
        self.setFixedSize(32,32)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f'{name} · {color.upper()}')
        self.setAccessibleName(name + '强调色')
        self.setObjectName('accentPreset_' + color[1:])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        text = self.palette().color(QPalette.Text)
        painter.setPen(QPen(text if self.isChecked() or self.hasFocus() else Qt.transparent,1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(1.5,1.5,29,29))
        painter.setPen(QPen(QColor(128,128,128,80),1))
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(QRectF(5,5,22,22))
        if self.isChecked():
            ink = '#ffffff' if contrast(self.color,'#ffffff') >= contrast(self.color,'#000000') else '#000000'
            painter.setPen(QPen(QColor(ink),2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            painter.drawPolyline([QPointF(11,16),QPointF(14.5,19.5),QPointF(21,12.5)])


class ColorField(QWidget):
    colorChanged = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color, self.hue = QColor('#477ce5'), 0.62
        self.setFixedSize(148,112)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName('自定义颜色：饱和度和明度')
        self.setObjectName('accentColorField')

    def present(self, color, hue):
        self.color, self.hue = QColor(color), hue
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        area = QRectF(self.rect()).adjusted(1,1,-1,-1)
        horizontal = QLinearGradient(area.topLeft(),area.topRight())
        horizontal.setColorAt(0,QColor('white'))
        horizontal.setColorAt(1,QColor.fromHsvF(self.hue,1,1))
        painter.fillRect(area,horizontal)
        vertical = QLinearGradient(area.topLeft(),area.bottomLeft())
        vertical.setColorAt(0,QColor(0,0,0,0))
        vertical.setColorAt(1,QColor('black'))
        painter.fillRect(area,vertical)
        point = QPointF(area.left()+self.color.saturationF()*area.width(),
                        area.top()+(1-self.color.valueF())*area.height())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor('black'),3))
        painter.drawEllipse(point,4,4)
        painter.setPen(QPen(QColor('white'),1.5))
        painter.drawEllipse(point,4,4)

    def _select(self, point):
        saturation = max(0,min(1,(point.x()-1)/max(1,self.width()-2)))
        value = 1-max(0,min(1,(point.y()-1)/max(1,self.height()-2)))
        self.colorChanged.emit(QColor.fromHsvF(self.hue,saturation,value))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            self._select(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._select(event.position())
            event.accept()

    def keyPressEvent(self, event):
        shifts = {Qt.Key_Left:(-.01,0),Qt.Key_Right:(.01,0),Qt.Key_Up:(0,.01),Qt.Key_Down:(0,-.01)}
        if event.key() in shifts:
            ds,dv = shifts[event.key()]
            self.colorChanged.emit(QColor.fromHsvF(self.hue,max(0,min(1,self.color.saturationF()+ds)),
                                                  max(0,min(1,self.color.valueF()+dv))))
            event.accept()
        else:
            super().keyPressEvent(event)


class AccentPicker(QWidget):
    colorChanged = Signal(str)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color, self._hue = normalize_color(color), .62
        self.setObjectName('accentPicker')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(10)
        presets = QHBoxLayout()
        presets.setSpacing(9)
        self.swatches = []
        for name,value in PRESETS:
            button = SwatchButton(name,value,self)
            button.clicked.connect(lambda checked=False,value=value:self.set_color(value))
            presets.addWidget(button)
            self.swatches.append(button)
        presets.addStretch()
        layout.addLayout(presets)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.field = ColorField(self)
        self.field.colorChanged.connect(lambda value:self.set_color(value.name()))
        row.addWidget(self.field)
        self.hue = QSlider(Qt.Vertical)
        self.hue.setObjectName('accentHue')
        self.hue.setAccessibleName('色相')
        self.hue.setRange(0,359)
        self.hue.setInvertedAppearance(True)
        self.hue.setFixedSize(18,112)
        self.hue.setStyleSheet('QSlider::groove:vertical { width:12px; border-radius:3px; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ff0000,stop:0.167 #ffff00,stop:0.333 #00ff00,stop:0.5 #00ffff,stop:0.667 #0000ff,stop:0.833 #ff00ff,stop:1 #ff0000); } QSlider::handle:vertical { height:5px; margin:0 -3px; background:white; border:1px solid #444444; border-radius:2px; } QSlider::sub-page:vertical,QSlider::add-page:vertical { background:transparent; }')
        self.hue.valueChanged.connect(self._set_hue)
        row.addWidget(self.hue)
        channels = QGridLayout()
        channels.setHorizontalSpacing(8)
        channels.setVerticalSpacing(6)
        self.sliders, self.values = [], []
        for index,name in enumerate(('R','G','B')):
            label = QLabel(name)
            slider, value = QSlider(Qt.Horizontal), QSpinBox()
            slider.setRange(0,255)
            value.setRange(0,255)
            value.setStyleSheet('QSpinBox::up-button,QSpinBox::down-button { width:0; height:0; border:none; }')
            value.setFixedWidth(60)
            value.setKeyboardTracking(False)
            slider.setObjectName('accent'+name+'Slider')
            value.setObjectName('accent'+name+'Value')
            slider.setAccessibleName(name+'颜色分量')
            value.setAccessibleName(name+'颜色数值')
            slider.valueChanged.connect(lambda amount,index=index:self._set_channel(index,amount))
            value.valueChanged.connect(lambda amount,index=index:self._set_channel(index,amount))
            channels.addWidget(label,index,0)
            channels.addWidget(slider,index,1)
            channels.addWidget(value,index,2)
            self.sliders.append(slider)
            self.values.append(value)
        channels.setColumnStretch(1,1)
        row.addLayout(channels,1)
        layout.addLayout(row)
        self.readout = QLabel()
        self.readout.setObjectName('accentRgbReadout')
        layout.addWidget(self.readout)
        self.set_color(self._color,emit=False)

    @property
    def color(self):
        return self._color

    def set_color(self, color, *, emit=True):
        color = normalize_color(color)
        changed = color != self._color
        self._color = color
        value = QColor(color)
        if value.hsvHueF() >= 0:
            self._hue = value.hsvHueF()
        for control,amount in zip(self.sliders+self.values,list(rgb(color))*2):
            with QSignalBlocker(control):
                control.setValue(amount)
        with QSignalBlocker(self.hue):
            self.hue.setValue(round(self._hue*360))
        for swatch in self.swatches:
            swatch.setChecked(swatch.color == color)
        self.field.present(value,self._hue)
        self.readout.setText(f'{color.upper()}    RGB {value.red()}, {value.green()}, {value.blue()}')
        self.setAccessibleDescription(self.readout.text())
        if emit and changed:
            self.colorChanged.emit(color)

    def _set_channel(self, index, value):
        channels = list(rgb(self._color))
        channels[index] = value
        self.set_color('#'+''.join(f'{amount:02x}' for amount in channels))

    def _set_hue(self, value):
        self._hue = value/360
        current = QColor(self._color)
        self.set_color(QColor.fromHsvF(self._hue,current.saturationF(),current.valueF()).name())
