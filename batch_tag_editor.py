"""Shared tag capsules with explicit, non-destructive group intent."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QButtonGroup
from tag_editor import TagEditor


class BatchTagEditor(QWidget):
    def __init__(self, schema, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 6)
        modes = QHBoxLayout()
        self.group = QButtonGroup(self)
        for number, caption in enumerate(('添加标签', '移除标签')):
            button = QPushButton(caption)
            button.setProperty('role', 'action')
            button.setCheckable(True)
            self.group.addButton(button, number)
            modes.addWidget(button)
        self.group.button(0).setChecked(True)
        layout.addLayout(modes)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.editor = TagEditor([], schema, schema_editable=False)
        self.editor.embed()
        layout.addWidget(self.editor, 1)
        self.group.idToggled.connect(lambda number, checked: self.update_note() if checked else None)
        self.update_note()

    @property
    def mode(self):
        return 'add' if self.group.checkedId() == 0 else 'remove'

    def update_note(self):
        self.note.setText('为所选文件添加下方标签，保留其他标签。关闭菜单后应用。' if self.mode == 'add'
                          else '移除下方标签；选择父标签会同时移除其子标签。保留其他标签。关闭菜单后应用。')
