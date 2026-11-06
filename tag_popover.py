"""Tag editing view; draft ownership and submission live in the application."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QApplication, QAbstractButton

from application.operations import Operation, Outcome, Status
from application.tag_drafts import TagValues
from floating_surface import owned_by
from hover_panel import HoverPanel
from tag_editor import TagEditor


class TagPanel(HoverPanel):
    def __init__(self, anchor, host, drafts):
        self.editor = None
        self.video_id = None
        self.drafts = drafts
        super().__init__(anchor, host, editable=True)
        self.auto_close = True
        self.prepare = self.load_tags
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.setFixedSize(500, 360)

    def capture(self):
        if self.editor is not None:
            self.drafts.update(self.video_id, TagValues(self.editor.chosen(), self.editor.schema, self.editor.renames))

    def load_tags(self):
        self.capture()
        draft = self.drafts.open_current()
        if draft is None:
            return False
        if self.editor is not None and self.video_id == draft.video_id and draft.dirty:
            return True
        if self.editor is not None:
            self.content.removeWidget(self.editor)
            self.editor.deleteLater()
        self.video_id = draft.video_id
        self.editor = TagEditor(draft.values.tags, draft.values.schema, self.body)
        self.editor.setWindowFlags(Qt.Widget)
        self.editor.setAttribute(Qt.WA_TranslucentBackground, False)
        self.editor.setMinimumSize(0, 0)
        self.editor.buttons.hide()
        self.editor.footer_hint.hide()
        self.editor.enable_management()
        self.content.addWidget(self.editor)
        self.editor.show()
        return True

    def close_if_idle(self):
        if self.editor is not None and self.editor.dragging:
            self.close_timer.start()
            return
        popup = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if popup is not None and owned_by(popup, self.editor):
            self.close_timer.start()
            return
        super().close_if_idle()

    def handle_key(self, event):
        focus = QApplication.focusWidget()
        if (self.isVisible() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter)
                and isinstance(focus, QAbstractButton) and owned_by(focus, self.editor)):
            if not event.isAutoRepeat():
                focus.click()
            return True
        return False

    def flush_pending(self):
        self.capture()
        try:
            operation = self.drafts.commit(self.video_id)
        except ValueError as error:
            self.editor.message(str(error))
            return Operation.completed(Outcome(Status.FAILED, error=error))
        editor = self.editor
        if operation.pending and editor is not None:
            editor.setEnabled(False)
        def completed(outcome):
            if editor is not None and self.editor is editor:
                editor.setEnabled(True)
                if outcome.succeeded:
                    editor.confirm_saved()
        operation.on_finished(completed)
        return operation

    def hideEvent(self, event):
        self.flush_pending()
        super().hideEvent(event)
