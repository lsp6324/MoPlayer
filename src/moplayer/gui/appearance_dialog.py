"""Appearance drafts, live preview, atomic save and cancellation restoration."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QGuiApplication
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QDialogButtonBox, QFileDialog, QMessageBox, QComboBox, QScrollArea)
from moplayer.gui.color_picker import AccentPicker


class AppearanceDialog(QDialog):
    def __init__(self, parent, appearance, *, preview_theme, preview_background):
        super().__init__(parent)
        self.appearance = appearance
        self.preview_theme, self.preview_background = preview_theme, preview_background
        self.selected_background = appearance.background
        self.setWindowTitle('外观')
        self.setObjectName('appearanceDialog')
        self.setMinimumWidth(548)
        screen = parent.screen() if parent else QGuiApplication.primaryScreen()
        self.setMaximumHeight(max(320,screen.availableGeometry().height()-64))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24,20,24,20)
        layout.setSpacing(16)
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0,0,12,0)
        content.setSpacing(14)
        scroll.setWidget(body)
        layout.addWidget(scroll,1)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel('主题'))
        self.themes = QComboBox()
        self.themes.setObjectName('themeChoice')
        self.themes.addItem('深色','dark')
        self.themes.addItem('浅色','light')
        self.themes.setCurrentIndex(self.themes.findData(appearance.theme))
        theme_row.addWidget(self.themes,1)
        content.addLayout(theme_row)
        content.addWidget(QLabel('强调色'))
        self.accent_picker = AccentPicker(appearance.accent)
        content.addWidget(self.accent_picker)
        self.themes.currentIndexChanged.connect(self._preview_theme)
        self.accent_picker.colorChanged.connect(self._preview_theme)
        content.addWidget(QLabel('背景'))
        self.preview = QLabel()
        self.preview.setObjectName('backgroundPreview')
        self.preview.setFixedSize(464,140)
        self.preview.setAlignment(Qt.AlignCenter)
        content.addWidget(self.preview)
        buttons = QHBoxLayout()
        choose = QPushButton('选择背景图')
        choose.setObjectName('chooseBackground')
        choose.setProperty('role','primary')
        reset = QPushButton('恢复默认背景')
        reset.setObjectName('resetBackground')
        choose.clicked.connect(self._select_background)
        reset.clicked.connect(self._reset_background)
        buttons.addWidget(choose)
        buttons.addWidget(reset)
        content.addLayout(buttons)
        self.strength_text = QLabel()
        content.addWidget(self.strength_text)
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setObjectName('backgroundStrength')
        self.strength.setRange(10,100)
        self.strength.setValue(appearance.strength)
        self.strength.valueChanged.connect(self._preview_background)
        content.addWidget(self.strength)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('保存')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._preview_background()
        self.resize(548,min(self.maximumHeight(),body.sizeHint().height()+100))

    def _preview_theme(self):
        self.preview_theme(self.themes.currentData(),self.accent_picker.color)

    def _preview_background(self):
        self.strength_text.setText(f'背景强度  {self.strength.value()}%')
        self.preview_background(self.selected_background,self.strength.value())
        if self.selected_background:
            pixmap = QPixmap.fromImage(self.appearance.image(self.selected_background))
            self.preview.setPixmap(pixmap.scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText('默认背景')

    def _select_background(self):
        path,_ = QFileDialog.getOpenFileName(self,'选择背景图片','','图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            try:
                self.appearance.image(path)
                self.selected_background = Path(path)
                self._preview_background()
            except (OSError,ValueError) as error:
                QMessageBox.warning(self,'背景图片无法使用',str(error))

    def _reset_background(self):
        self.selected_background = None
        self._preview_background()

    def accept(self):
        try:
            self.appearance.save(self.selected_background,self.strength.value(),
                                 self.themes.currentData(),self.accent_picker.color)
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,'外观未保存',str(error))
            return
        self.preview_background(self.appearance.background,self.appearance.strength)
        super().accept()

    def done(self, result):
        if result != QDialog.Accepted:
            self.preview_theme(self.appearance.theme,self.appearance.accent)
            self.preview_background(self.appearance.background,self.appearance.strength)
        super().done(result)
