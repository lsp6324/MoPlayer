"""Archive preferences form; submits values through an application port."""
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout)
from application.archive_folders import ArchiveFolders


class ArchiveSettingsDialog(QDialog):
    def __init__(self, parent, *, root, folders, error, apply, first_run=False):
        super().__init__(parent)
        self.apply, self.pending = apply, False
        self.setWindowTitle('首次设置 · 视频归档' if first_run else '归档设置')
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(QLabel('归档文件夹'))
        row = QHBoxLayout()
        self.path = QLineEdit(str(root or ''))
        self.path.setObjectName('archiveRootInput')
        self.path.setPlaceholderText('选择或输入完整文件夹路径')
        row.addWidget(self.path, 1)
        self.browse = QPushButton('选择文件夹')
        self.browse.clicked.connect(self.choose)
        row.addWidget(self.browse)
        layout.addLayout(row)
        layout.addWidget(QLabel('文件夹分类依据'))
        options = QHBoxLayout()
        self.tags = QCheckBox('标签')
        self.score = QCheckBox('评分')
        self.favorite = QCheckBox('收藏')
        for name in ('favorite', 'score', 'tags'):
            checkbox = {'tags': self.tags, 'score': self.score, 'favorite': self.favorite}[name]
            checkbox.setObjectName('archiveFolder_' + name)
            checkbox.setChecked(getattr(folders, name))
            checkbox.toggled.connect(self.update_preview)
            options.addWidget(checkbox)
        options.addStretch()
        layout.addLayout(options)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setObjectName('archiveFolderPreview')
        self.path.textChanged.connect(self.update_preview)
        layout.addWidget(self.preview)
        note = QLabel('仅控制文件夹分类，不影响标签、评分和收藏本身。\n'
                      '目录顺序为收藏 → 评分 → 标签，未勾选的层级会省略。\n'
                      '收藏分为“已收藏”和“未收藏”；全部不勾选时直接放入归档文件夹。\n'
                      '保存后会整理所有已归档视频，未归档的视频保持原位置。\n'
                      '归档文件夹需要位于可写的 NTFS 磁盘。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel(error)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('保存并整理')
        self.buttons.button(QDialogButtonBox.Cancel).setText('稍后设置' if first_run else '取消')
        self.buttons.accepted.connect(self.commit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.update_preview()

    def values(self):
        return ArchiveFolders(self.tags.isChecked(), self.score.isChecked(), self.favorite.isChecked())

    def update_preview(self):
        folders = self.values()
        segments = folders.directories(8, True, [('标签',)])[0]
        self.preview.setText('目录示例：' + ' / '.join(('归档文件夹', *segments, '视频文件')))

    def choose(self):
        selected = QFileDialog.getExistingDirectory(self, '选择归档文件夹', self.path.text())
        if selected:
            self.path.setText(selected)

    def set_pending(self, pending):
        self.pending = pending
        for control in (self.path, self.browse, self.tags, self.score, self.favorite, self.buttons):
            control.setEnabled(not pending)

    def commit(self):
        if self.pending:
            return
        root, folders = self.path.text(), self.values()
        self.set_pending(True)
        self.status.setText('正在检查归档位置并整理已归档视频，请稍候……')
        def completed(outcome):
            self.set_pending(False)
            if outcome.succeeded:
                self.accept()
            elif outcome.error:
                suffix = '\n整理尚未完成，请关闭此窗口，在“更多 → 文件任务”中恢复。' if outcome.recoverable else ''
                self.status.setText(str(outcome.error) + suffix)
            else:
                self.status.setText('当前有文件任务正在进行或等待恢复，请稍后再保存。')
        try:
            operation = self.apply(root, folders)
        except Exception as error:
            self.set_pending(False)
            self.status.setText(str(error))
        else:
            operation.on_finished(completed)

    def reject(self):
        if not self.pending:
            super().reject()

    def closeEvent(self, event):
        if self.pending:
            event.ignore()
        else:
            super().closeEvent(event)
