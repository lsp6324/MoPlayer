"""Native group menus: frozen targets, shared editors and partial-result dialogs."""
from PySide6.QtCore import QObject, Qt, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QMenu, QWidgetAction, QFrame, QVBoxLayout, QDialog,
                               QLabel, QPushButton, QCheckBox, QMessageBox)
from moplayer.gui.batch_tag_editor import BatchTagEditor
from moplayer.gui.rating_editor import RatingEditor
from moplayer.gui.theme import theme_tokens


class BatchContextMenu(QObject):
    def __init__(self, parent, *, repository, operations, prepare, dismiss_popups, available):
        super().__init__(parent)
        self.repository, self.operations = repository, operations
        self.prepare, self.dismiss_popups, self.available = prepare, dismiss_popups, available
        self.active_menu = self.active_dialog = None

    def _prepare(self, selection, action):
        def ready():
            if any(self.repository.video(item.video_id) is None for item in selection.items):
                QMessageBox.warning(self.parent(), '操作未完成', '部分文件的软件记录已不存在，请重新选择。')
                return
            self.dismiss_popups()
            action()
        self.prepare(ready)

    def open(self, selection, position):
        def ready():
            menu = self.build_menu(selection)
            self.active_menu = menu
            try:
                menu.exec(position)
            finally:
                self.active_menu = None
                menu.deleteLater()
        self._prepare(selection, ready)

    def _content_menu(self, title, root, content, size=None):
        submenu = QMenu(title, root)
        frame = QFrame()
        frame.setObjectName('playbackPopover')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        if size:
            frame.setFixedSize(*size)
        action = QWidgetAction(submenu)
        action.setDefaultWidget(frame)
        submenu.addAction(action)
        root.addMenu(submenu)
        return submenu

    def build_menu(self, selection):
        items = selection.items
        root = QMenu(self.parent())
        root.setAccessibleName('批量媒体右键菜单')
        header = root.addAction(f'已选择 {len(items)} 个文件')
        root.addSeparator()
        def invoke(action):
            root.close()
            self._prepare(selection, action)
        favorites = root.addMenu('收藏')
        for caption, value in (('收藏所选文件', True), ('取消所选收藏', False)):
            favorites.addAction(caption).triggered.connect(
                lambda checked=False, value=value: invoke(lambda: self._run('批量收藏', selection, 'favorite', value)))
        schema = self.repository.tag_values(items[0].video_id).schema
        tags = BatchTagEditor(schema)
        self._content_menu('编辑标签', root, tags, (500, 400))
        saved = False
        def save_tags():
            nonlocal saved
            if saved:
                return
            saved = True
            names, mode = tuple(tags.editor.chosen()), tags.mode
            if names:
                self._run('批量标签', selection, 'tags', names, mode)
        root.aboutToHide.connect(save_tags)
        rating = RatingEditor()
        scores = {self.repository.video(item.video_id)['score'] for item in items}
        rating.set_score(next(iter(scores)) if len(scores) == 1 else None)
        rating.clear.setEnabled(scores != {None})
        if len(scores) > 1:
            rating.value.setText('不同评分')
        colors = theme_tokens(self.parent())
        rating.hearts.fill_color = QColor(colors['accent'])
        rating.hearts.outline_color = QColor(colors['text_faint'])
        rating.chosen.connect(lambda value: invoke(lambda: self._run('批量评分', selection, 'rating', value)))
        submenu = self._content_menu('评分', root, rating)
        submenu.aboutToHide.connect(lambda: rating.hearts.set_preview(None))
        root.addSeparator()
        root.addAction('删除').triggered.connect(lambda: invoke(lambda: self._delete(selection)))
        for action in root.actions():
            if not action.isSeparator():
                action.setEnabled(self.available())
        header.setEnabled(False)
        return root

    def confirm_delete(self, selection):
        self._prepare(selection, lambda: self._delete(selection))

    def eventFilter(self, watched, event):
        if watched is self.active_dialog and watched.property('saving'):
            if event.type() == QEvent.Close or event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def _form(self, title, count):
        dialog = QDialog(self.parent())
        dialog.setWindowTitle(title)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.installEventFilter(self)
        dialog.resize(460, 200)
        layout = QVBoxLayout(dialog)
        label = QLabel(f'已选择 {count} 个文件')
        label.setObjectName('batchStatus')
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.active_dialog = dialog
        dialog.finished.connect(lambda: self._closed(dialog))
        return dialog, layout, label

    def _closed(self, dialog):
        if self.active_dialog is dialog:
            self.active_dialog = None

    @staticmethod
    def _status(dialog, label, text):
        label.ensurePolished()
        label.setText(text)
        margins = dialog.layout().contentsMargins()
        label.setMinimumHeight(label.heightForWidth(dialog.width() - margins.left() - margins.right()))

    def _execute(self, dialog, label, stop, command):
        dialog.setProperty('saving', True)
        stop.setText('停止后续')
        def progress(done, total):
            self._status(dialog, label, f'正在处理 {done} / {total} 个文件……\n停止后会完成当前文件，保留已完成的修改。')
        def finish(outcome):
            dialog.setProperty('saving', False)
            if outcome.succeeded:
                dialog.accept()
                return
            report = outcome.value
            detail = f'已完成 {len(report.completed)} 项，剩余 {len(report.remaining)} 项。' if report else '未执行批量操作。'
            if outcome.error:
                detail += '\n' + str(outcome.error)
            if outcome.recoverable:
                detail += '\n可在“更多 → 文件任务”恢复未完成的文件任务。'
            self._status(dialog, label, detail)
            stop.setText('关闭')
        try:
            self._status(dialog, label, '正在处理所选文件……\n停止后会完成当前文件，保留已完成的修改。')
            operation = command(progress)
        except Exception as error:
            dialog.setProperty('saving', False)
            self._status(dialog, label, str(error))
            stop.setText('关闭')
            return
        operation.on_finished(finish)

    def _stop(self, dialog):
        if dialog.property('saving'):
            self.operations.cancel()
        else:
            dialog.reject()

    def _run(self, title, selection, method, *args):
        dialog, layout, label = self._form(title, len(selection.items))
        stop = QPushButton('停止后续')
        stop.clicked.connect(lambda: self._stop(dialog))
        layout.addWidget(stop)
        dialog.show()
        command = {'favorite': self.operations.favorite, 'rating': self.operations.rating, 'tags': self.operations.tags}[method]
        self._execute(dialog, label, stop, lambda progress: command(selection.items, *args, progress=progress))

    def _delete(self, selection):
        dialog, layout, label = self._form('批量删除软件记录', len(selection.items))
        names = [self.repository.video(item.video_id)['name'] for item in selection.items]
        self._status(dialog, label, f'删除所选 {len(names)} 个文件的软件记录？\n' + '\n'.join(names[:3]) + ('\n……' if len(names) > 3 else ''))
        local = QCheckBox('同时删除本地文件（移至回收站）')
        local.setObjectName('deleteLocalFiles')
        local.setChecked(False)
        layout.addWidget(local)
        note = QLabel('默认只删除标签、评分、收藏、播放和库记录，保留本地文件。勾选后将回收全部已登记位置，包括分类目录中的入口。')
        note.setWordWrap(True)
        layout.addWidget(note)
        confirm, cancel = QPushButton('删除记录'), QPushButton('取消')
        confirm.setObjectName('batchDeleteConfirm')
        for button in (confirm, cancel):
            button.setAutoDefault(False)
            layout.addWidget(button)
        cancel.setDefault(True)
        cancel.clicked.connect(lambda: self._stop(dialog))
        local.toggled.connect(lambda checked: confirm.setText('删除记录及本地文件' if checked else '删除记录'))
        def remove():
            if not self.available():
                label.setText('文件任务正在处理，请稍后重试。')
                return
            confirm.setEnabled(False)
            local.setEnabled(False)
            self._execute(dialog, label, cancel, lambda progress: self.operations.delete(selection.items, delete_files=local.isChecked(), progress=progress))
        confirm.clicked.connect(remove)
        dialog.open()
