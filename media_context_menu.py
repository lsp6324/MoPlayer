"""Stable-ID media menus and input dialogs; services own every mutation."""
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QEvent
from PySide6.QtWidgets import (QMenu, QDialog, QVBoxLayout, QLabel, QLineEdit,
                               QDialogButtonBox, QCheckBox, QMessageBox)

from application.tag_drafts import TagValues
from score_editor import ScoreEditor
from tag_editor import TagEditor


class MediaContextMenu(QObject):
    def __init__(self, parent, *, repository, drafts, classification, renaming, deletion,
                 prepare, dismiss_popups, available, reveal):
        super().__init__(parent)
        self.repository, self.drafts = repository, drafts
        self.classification, self.renaming, self.deletion = classification, renaming, deletion
        self.prepare, self.dismiss_popups = prepare, dismiss_popups
        self.available, self.reveal = available, reveal
        self.active_menu, self.active_dialog = None, None

    def open(self, selection, position):
        menu = self.build_menu(selection)
        if menu is None:
            return
        self.active_menu = menu
        try:
            menu.exec(position)
        finally:
            self.active_menu = None
            menu.deleteLater()

    def build_menu(self, selection):
        video = self.repository.video(selection.video_id)
        if video is None:
            return None
        menu = QMenu(self.parent())
        menu.setAccessibleName('媒体右键菜单')
        actions = [
            ('取消收藏' if video['star'] else '收藏', lambda: self._favorite(selection, not bool(video['star']))),
            ('编辑标签…', lambda: self._edit_tags(selection)),
            ('评分…', lambda: self._edit_rating(selection)),
            ('重命名…', lambda: self._rename(selection)),
            ('删除…', lambda: self._delete(selection)),
            ('在资源管理器中打开', lambda: self._reveal(selection)),
        ]
        for number, (caption, action) in enumerate(actions):
            if number in (3, 5):
                menu.addSeparator()
            control = menu.addAction(caption)
            control.setEnabled(number == 5 or self.available())
            control.triggered.connect(lambda checked=False, action=action: self._prepare(selection, action))
        return menu

    def confirm_delete(self, selection):
        self._prepare(selection, lambda: self._delete(selection))

    def _prepare(self, selection, action):
        # The menu captured the clicked identity, never a mutable row number.
        def ready():
            if self.repository.video(selection.video_id) is None:
                self._error('该文件的软件记录已不存在。')
                return
            self.dismiss_popups()
            action()
        self.prepare(ready)

    def _error(self, message):
        QMessageBox.warning(self.parent(), '操作未完成', message)

    def _show(self, dialog):
        self.active_dialog = dialog
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.installEventFilter(self)
        def finished(result):
            if self.active_dialog is dialog:
                self.active_dialog = None
        dialog.finished.connect(finished)
        dialog.open()

    def eventFilter(self, watched, event):
        if watched is self.active_dialog and watched.property('saving'):
            if event.type() == QEvent.Close or event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def _submit(self, dialog, command, error):
        if not self.available():
            error('文件任务正在处理，请稍后重试。')
            return
        dialog.setProperty('saving', True)
        dialog.setEnabled(False)
        try:
            operation = command()
        except Exception as failure:
            dialog.setProperty('saving', False)
            dialog.setEnabled(True)
            error(str(failure))
            return
        def completed(outcome):
            dialog.setProperty('saving', False)
            dialog.setEnabled(True)
            if outcome.succeeded:
                QDialog.accept(dialog)
            else:
                error(str(outcome.error) if outcome.error else '操作未完成，请重试。')
        operation.on_finished(completed)

    def _favorite(self, selection, value):
        if self.available():
            self.classification.favorite(selection.video_id, value)

    def _edit_tags(self, selection):
        draft = self.drafts.open_for(selection.video_id)
        if draft is None:
            return
        values = draft.values.copy()
        dialog = TagEditor(values.tags, values.schema, self.parent(),
                           baseline_schema=draft.baseline.schema, renames=values.renames,
                           target_name=self.repository.video(selection.video_id)['name'])
        dialog.enable_management(embedded=False)
        dialog.setWindowTitle('编辑标签')
        dialog.setToolTip(self.repository.video(selection.video_id)['name'])
        dialog.buttons.accepted.disconnect(dialog.accept)
        def save():
            def commit():
                self.drafts.update(selection.video_id, TagValues(dialog.chosen(), dialog.schema, dialog.renames))
                return self.drafts.commit(selection.video_id)
            self._submit(dialog, commit, dialog.message)
        dialog.buttons.accepted.connect(save)
        self._show(dialog)

    def _edit_rating(self, selection):
        def show_error(message):
            dialog.readout.setText('保存失败，请重试')
            dialog.readout.setToolTip(message)
        def choose(value):
            dialog.show_preview(None)
            self._submit(dialog, lambda: self.classification.rating(selection.video_id, value), show_error)
        dialog = ScoreEditor(self.repository.video(selection.video_id), self.parent(), submit=choose, show_name=True)
        self._show(dialog)

    def _form(self, title):
        dialog = QDialog(self.parent())
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        dialog.resize(440, 160)
        error = QLabel()
        error.setTextFormat(Qt.PlainText)
        error.setWordWrap(True)
        error.hide()
        def show_error(message):
            error.setText(message)
            error.show()
        return dialog, layout, error, show_error

    def _rename(self, selection):
        video = self.repository.video(selection.video_id)
        dialog, layout, error, show_error = self._form('重命名文件')
        field = QLineEdit(video['name'])
        field.setObjectName('mediaRenameField')
        field.setAccessibleName('新文件名')
        layout.addWidget(field)
        layout.addWidget(error)
        controls = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Save).setText('保存')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        for control in controls.buttons():
            control.setAutoDefault(False)
        layout.addWidget(controls)
        def save():
            self._submit(dialog, lambda: self.renaming.rename(selection.video_id, field.text()), show_error)
        controls.accepted.connect(save)
        field.returnPressed.connect(save)
        controls.rejected.connect(dialog.reject)
        self._show(dialog)
        field.setFocus()
        field.setSelection(0, len(Path(video['name']).stem))

    def _delete(self, selection):
        video = self.repository.video(selection.video_id)
        dialog, layout, error, show_error = self._form('删除软件记录')
        description = QLabel('从 MoPlayer 中删除“' + video['name'] + '”的标签、评分、收藏、播放记录和库记录。')
        description.setTextFormat(Qt.PlainText)
        description.setWordWrap(True)
        layout.addWidget(description)
        local = QCheckBox('同时删除本地文件（移至回收站）')
        local.setObjectName('deleteLocalFiles')
        local.setChecked(False)
        layout.addWidget(local)
        explanation = QLabel('保留的文件仍可在文件页浏览。勾选后，将回收该文件所有已登记的位置，包括分类目录中的入口。')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addWidget(error)
        controls = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        confirm = controls.button(QDialogButtonBox.Ok)
        confirm.setText('删除记录')
        for control in controls.buttons():
            control.setAutoDefault(False)
        controls.button(QDialogButtonBox.Cancel).setDefault(True)
        local.toggled.connect(lambda checked: confirm.setText('删除记录及本地文件' if checked else '删除记录'))
        layout.addWidget(controls)
        def remove():
            context = (selection.context, selection.location) if selection.context is not None else None
            self._submit(dialog, lambda: self.deletion.delete(selection.video_id, context, delete_files=local.isChecked()), show_error)
        controls.accepted.connect(remove)
        controls.rejected.connect(dialog.reject)
        self._show(dialog)

    def _reveal(self, selection):
        try:
            self.reveal(self.repository.resolve(selection.video_id))
        except (OSError, ValueError) as error:
            self._error(str(error))
