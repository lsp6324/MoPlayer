"""Hierarchy is visible in selection controls, summaries and shared metadata."""
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog
from application.tag_labels import tag_labels, tag_label
from application.tag_drafts import TagDrafts, TagValues
from application.operations import Operation, Outcome, Status
from tag_editor import TagEditor


SCHEMA = {'风景': dict(name='风景', kind='major', parent=None, is_parent=True),
          '山川': dict(name='山川', kind='minor', parent='风景', is_parent=True),
          '雪山': dict(name='雪山', kind='minor', parent='山川', is_parent=False),
          '摄影': dict(name='摄影', kind='major', parent=None, is_parent=False)}


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    widget = TagEditor(['雪山'], SCHEMA)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_paths_are_shared_and_redundant_selected_ancestors_are_not_repeated():
    assert tag_labels(['风景', '山川', '雪山', '摄影'], SCHEMA) == ('风景 › 山川 › 雪山', '摄影')
    assert tag_label('不存在', SCHEMA) == '不存在'
    assert tag_label('风景', {'风景': {'parent': '风景'}}) == '风景'


def test_selected_descendant_is_distinct_from_explicit_parent_selection(editor):
    parent = editor.chips['风景']
    assert not parent.isChecked() and parent.property('implicitSelected')
    assert '本级未选' in parent.toolTip() and '已选子标签' in parent.toolTip()
    editor.activate('风景')
    assert editor.parent_choices['风景'].text() == '已由子标签包含'
    assert not editor.parent_choices['风景'].isEnabled()
    assert editor.chips['山川'].property('implicitSelected')
    editor.activate('山川')
    editor.activate('雪山')
    editor.parent_choices['山川'].click()
    assert editor.chosen() == ['山川'] and editor.chips.get('风景').property('implicitSelected')


def test_search_exposes_matching_child_with_path_without_changing_expansion(editor):
    assert not editor.expanded
    editor.search.setText('雪山')
    assert tuple(editor.chips) == ('雪山',)
    assert '风景 › 山川 › 雪山' in editor.chips['雪山'].text()
    assert not editor.expanded and editor.chosen() == ['雪山']
    editor.search.clear()
    assert set(editor.chips) == {'风景', '摄影'} and not editor.expanded


def test_context_menu_renames_parent_and_preserves_children_selection_and_cancel(editor, monkeypatch):
    original = deepcopy(SCHEMA)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('自然', True))
    menu = editor.build_menu('风景')
    action = next(action for action in menu.actions() if action.text() == '重命名标签…')
    action.trigger()
    assert editor.renames == {'风景': '自然'}
    assert editor.schema['山川']['parent'] == '自然' and editor.chosen() == ['雪山']
    assert SCHEMA == original
    assert editor.rename_tag('自然', '山野') and editor.renames == {'风景': '山野'}
    assert not editor.rename_tag('山野', '摄影') and '重名' in editor.hint.text()
    assert not editor.rename_tag('山野', '../非法') and editor.renames == {'风景': '山野'}
    editor.reject()
    assert SCHEMA == original


def test_new_draft_tag_rename_is_not_a_global_reference_rename(editor):
    editor.entry.setText('新标签')
    editor.add_tag()
    editor.rename_tag('新标签', '改名后的新标签')
    assert editor.renames == {} and '改名后的新标签' in editor.schema


def test_rename_mapping_survives_failed_save_and_reconciles_after_recovery():
    class Repository:
        values = TagValues(['雪山'], deepcopy(SCHEMA))
        def tag_values(self, video_id):
            return self.values.copy()
    repo, pending, sent = Repository(), Operation(), []
    drafts = TagDrafts(repo, lambda vid, values: sent.append(values.copy()) or pending, lambda: 'video', lambda: True)
    draft = drafts.open_current()
    values = draft.values.copy()
    values.schema['雪山']['name'] = '高山'
    values.schema['高山'] = values.schema.pop('雪山')
    values.tags, values.renames = ['高山'], {'雪山': '高山'}
    drafts.update('video', values)
    drafts.commit('video')
    assert sent[0].renames == {'雪山': '高山'}
    pending.finish(Outcome(Status.FAILED, error=OSError('interrupted'), recoverable=True))
    assert draft.dirty and draft.values.renames == {'雪山': '高山'}
    repo.values = TagValues(['高山'], values.schema)
    drafts.reconcile(['video'])
    assert not draft.dirty and not draft.values.renames


def test_saved_rename_rebases_a_newer_draft_to_the_committed_name():
    class Repository:
        def tag_values(self, video_id):
            return TagValues(['摄影'], {'摄影': SCHEMA['摄影']})
    first = Operation()
    drafts = TagDrafts(Repository(), lambda *_: first, lambda: 'video', lambda: True)
    draft = drafts.open_current()
    drafts.update('video', TagValues(['拍摄'], {'拍摄': dict(SCHEMA['摄影'], name='拍摄')}, {'摄影': '拍摄'}))
    drafts.commit('video')
    drafts.update('video', TagValues(['影像'], {'影像': dict(SCHEMA['摄影'], name='影像')}, {'摄影': '影像'}))
    first.finish(Outcome(Status.SUCCEEDED))
    assert draft.baseline.tags == ['拍摄'] and draft.values.tags == ['影像']
    assert draft.values.renames == {'拍摄': '影像'} and draft.dirty
