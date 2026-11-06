"""Archive preferences form; submits values through an application port."""
from string import Template
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)
from application.archive_folders import ArchiveFolders
from ui import ToggleSwitch
from theme import theme_tokens


class ArchiveSettingsDialog(QDialog):
    def __init__(self, parent, *, root, folders, error, apply, first_run=False, enabled=True):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setPalette(parent.palette())
        self.apply, self.pending = apply, False
        self.setWindowTitle('首次设置 · 视频归档' if first_run else '归档设置')
        self.setObjectName('archiveSettingsDialog')
        self.setMinimumWidth(600)
        self.setMaximumHeight(max(360, parent.screen().availableGeometry().height()-64))
        colors = theme_tokens(parent)
        self.setStyleSheet(Template("""
            QFrame#archiveSection { background:$surface_plain; border:1px solid $line; border-radius:10px; }
            QLabel#archiveHeading { font-size:20px; font-weight:600; }
            QLabel#archiveState { color:$text_dim; }
            QLabel:disabled { color:$disabled; }
            QLineEdit:disabled { color:$disabled; background:$surface_dim; border-color:$line_soft; }
            QCheckBox:disabled { color:$disabled; }
            QLabel#archiveFolderPreview { color:$accent; background:$accent_soft; border-radius:8px; padding:12px; }
            QLabel#archiveFolderPreview:disabled { color:$disabled; background:$surface_dim; }
        """).substitute(**colors))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel('归档设置')
        title.setObjectName('archiveHeading')
        layout.addWidget(title)
        subtitle = QLabel('管理文件的整理方式，标签、评分和收藏始终可用。')
        subtitle.setProperty('role', 'muted')
        layout.addWidget(subtitle)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(14)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        switch_card, switch_layout = self.section()
        switch_row = QHBoxLayout()
        switch_text = QVBoxLayout()
        switch_title = QLabel('启用归档')
        switch_title.setProperty('role', 'sectionTitle')
        switch_text.addWidget(switch_title)
        switch_hint = QLabel('按所选条件将文件整理到归档文件夹。')
        switch_hint.setProperty('role', 'muted')
        switch_text.addWidget(switch_hint)
        switch_row.addLayout(switch_text, 1)
        self.enable_archive = ToggleSwitch('启用归档', accent=colors['accent'], track=colors['track'], parent=self)
        self.enable_archive.setObjectName('archiveEnabled')
        self.enable_archive.setChecked(enabled)
        switch_row.addWidget(self.enable_archive)
        switch_layout.addLayout(switch_row)
        content.addWidget(switch_card)
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setObjectName('archiveState')
        content.addWidget(self.state)
        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(14)
        folder_card, folder_layout = self.section('归档文件夹')
        row = QHBoxLayout()
        self.path = QLineEdit(str(root or ''))
        self.path.setObjectName('archiveRootInput')
        self.path.setPlaceholderText('选择或输入完整文件夹路径')
        row.addWidget(self.path, 1)
        self.browse = QPushButton('选择文件夹')
        self.browse.clicked.connect(self.choose)
        row.addWidget(self.browse)
        folder_layout.addLayout(row)
        folder_hint = QLabel('归档位置需要位于可写的 NTFS 磁盘。')
        folder_hint.setProperty('role', 'muted')
        folder_layout.addWidget(folder_hint)
        details.addWidget(folder_card)
        rules_card, rules_layout = self.section('文件夹分类条件')
        rule_hint = QLabel('按勾选的条件依次建立目录。')
        rule_hint.setProperty('role', 'muted')
        rules_layout.addWidget(rule_hint)
        options = QHBoxLayout()
        options.setSpacing(28)
        self.tags = QCheckBox('标签')
        self.score = QCheckBox('评分')
        self.favorite = QCheckBox('收藏')
        for name, checkbox in (('favorite', self.favorite), ('score', self.score), ('tags', self.tags)):
            checkbox.setObjectName('archiveFolder_' + name)
            checkbox.setChecked(getattr(folders, name))
            checkbox.toggled.connect(self.update_preview)
            options.addWidget(checkbox)
        options.addStretch()
        rules_layout.addLayout(options)
        rule_note = QLabel('未勾选的层级会省略；全部不选时，直接放入归档文件夹。')
        rule_note.setProperty('role', 'muted')
        rule_note.setWordWrap(True)
        rules_layout.addWidget(rule_note)
        details.addWidget(rules_card)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setObjectName('archiveFolderPreview')
        self.path.textChanged.connect(self.update_preview)
        details.addWidget(self.preview)
        content.addWidget(self.details)
        content.addStretch()
        self.status = QLabel(error)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setVisible(bool(error))
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setProperty('role', 'primary')
        self.buttons.button(QDialogButtonBox.Cancel).setText('稍后设置' if first_run else '取消')
        self.buttons.accepted.connect(self.commit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.enable_archive.toggled.connect(self.update_preview)
        self.update_preview()
        self.resize(620, min(610, self.maximumHeight()))

    def section(self, title=None):
        card = QFrame()
        card.setObjectName('archiveSection')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        if title:
            heading = QLabel(title)
            heading.setProperty('role', 'sectionTitle')
            layout.addWidget(heading)
        return card, layout

    def values(self):
        return ArchiveFolders(self.tags.isChecked(), self.score.isChecked(), self.favorite.isChecked())

    def update_preview(self):
        enabled = self.enable_archive.isChecked()
        self.details.setEnabled(enabled and not self.pending)
        self.buttons.button(QDialogButtonBox.Save).setText('保存并整理' if enabled else '保存')
        self.state.setText('保存后整理已归档文件；未归档文件保持原位。' if enabled else
                           '归档已关闭：仅保存标记并建立库，文件保留当前位置。')
        segments = self.values().directories(8, True, [('标签',)])[0]
        self.preview.setText('目录示例：' + ' / '.join(('归档文件夹', *segments, '视频文件')))

    def choose(self):
        selected = QFileDialog.getExistingDirectory(self, '选择归档文件夹', self.path.text())
        if selected:
            self.path.setText(selected)

    def set_pending(self, pending):
        self.pending = pending
        self.enable_archive.setEnabled(not pending)
        self.buttons.setEnabled(not pending)
        self.update_preview()

    def show_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def commit(self):
        if self.pending:
            return
        root, folders, enabled = self.path.text(), self.values(), self.enable_archive.isChecked()
        self.set_pending(True)
        self.show_status('正在检查归档位置并整理已归档文件，请稍候……' if enabled else '正在保存归档设置……')
        def completed(outcome):
            self.set_pending(False)
            if outcome.succeeded:
                self.accept()
            elif outcome.error:
                suffix = '\n整理尚未完成，请关闭此窗口，在“更多 → 文件任务”中恢复。' if outcome.recoverable else ''
                self.show_status(str(outcome.error) + suffix)
            else:
                self.show_status('当前有文件任务正在进行或等待恢复，请稍后再保存。')
        try:
            operation = self.apply(root, folders) if enabled else self.apply(root, folders, enabled=False)
        except Exception as error:
            self.set_pending(False)
            self.show_status(str(error))
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
