"""Floating presentation of the remote tag editor and migration workflow."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QPushButton, QApplication
from playback_options import HoverPanel, owned_by
from tag_editor import TagEditor
from core import validate_layout


class TagPanel(HoverPanel):
    def __init__(self, window, anchor):
        self.editor = None
        self.baseline = None
        super().__init__(anchor, window.canvas, editable=True)
        self.player_window = window
        self.editor = None
        self.video_id = None
        self.baseline = None
        self.auto_close = True
        self.prepare = self.load_tags
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.setFixedSize(500, 360)

    def load_tags(self):
        window = self.player_window
        if not window.current or window.busy:
            return False
        if (self.editor is not None and self.video_id == window.current and
                self.baseline is not None and
                (self.editor.chosen(), self.editor.schema) != self.baseline):
            # A cancelled storage chooser must not discard the tag draft.
            return True
        if self.editor is not None:
            self.content.removeWidget(self.editor)
            self.editor.deleteLater()
        self.video_id = window.current
        self.editor = TagEditor(window.store, self.video_id, self.body)
        self.editor.setWindowFlags(Qt.Widget)
        self.editor.setAttribute(Qt.WA_TranslucentBackground, False)
        self.editor.setMinimumSize(0, 0)
        self.editor.buttons.hide()
        self.editor.footer_hint.hide()
        self.editor.enable_management()
        self.content.addWidget(self.editor)
        self.editor.show()
        self.baseline = (self.editor.chosen(), deepcopy(self.editor.schema))
        return True

    def close_if_idle(self):
        if self.editor is not None and self.editor.dragging:
            self.close_timer.start()
            return
        popup = QApplication.activePopupWidget()
        if popup is not None and owned_by(popup, self.editor):
            self.close_timer.start()
            return
        super().close_if_idle()

    def flush_pending(self):
        if self.editor is None or self.baseline is None:
            return
        tags, schema = self.editor.chosen(), deepcopy(self.editor.schema)
        if (tags, schema) == self.baseline:
            return
        window = self.player_window
        if window.busy:
            return
        try:
            validate_layout(list(schema.values()))
        except ValueError as error:
            self.editor.message(str(error))
            return
        # Snapshot before starting work: a reload/resize can hide us reentrantly.
        baseline = self.baseline
        self.baseline = (tags, schema)
        if window.apply_tags(self.video_id, tags, list(schema.values()), prompt_score=False) is False:
            self.baseline = baseline

    def hideEvent(self, event):
        self.flush_pending()
        super().hideEvent(event)
