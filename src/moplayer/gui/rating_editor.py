"""Shared rating contents for the playback popover and media submenu."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from moplayer.gui.heart_rating import HeartRating


class RatingEditor(QWidget):
    chosen = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(4)
        self.hearts = HeartRating()
        layout.addWidget(self.hearts, 0, Qt.AlignHCenter)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.zero = QPushButton('0 分')
        self.clear = QPushButton('清除')
        for control in (self.zero, self.clear):
            control.setProperty('role', 'quiet')
            control.setFixedHeight(28)
            control.setFocusPolicy(Qt.NoFocus)
            control.setCursor(Qt.PointingHandCursor)
        self.clear.setAccessibleName('清除评分')
        self.value = QLabel('— / 10')
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setFixedWidth(56)
        footer.addWidget(self.zero)
        footer.addStretch()
        footer.addWidget(self.value)
        footer.addStretch()
        footer.addWidget(self.clear)
        layout.addLayout(footer)
        self.hearts.previewed.connect(self.update_value)
        self.hearts.chosen.connect(self.chosen)
        self.zero.clicked.connect(lambda: self.chosen.emit(0))
        self.clear.clicked.connect(lambda: self.chosen.emit(None))

    def update_value(self, score):
        self.value.setText('— / 10' if score is None else f'{score} / 10')

    def set_score(self, score):
        self.hearts.set_score(score)
        self.clear.setEnabled(score is not None)

    def handle_key(self, event):
        key = event.key()
        score = self.hearts.display_score() or 0
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            score = 0 if key == Qt.Key_Home else 10 if key == Qt.Key_End else max(0, min(10, score + (1 if key == Qt.Key_Right else -1)))
            self.hearts.set_preview(score)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.chosen.emit(self.hearts.display_score())
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.chosen.emit(None)
        else:
            return False
        return True
