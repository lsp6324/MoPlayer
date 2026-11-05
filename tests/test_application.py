"""Application protocols run without QApplication, native VLC or a database."""
from unittest.mock import Mock

import pytest

from application.file_tasks import FileTasks
from application.operations import Operation, Outcome, Status, UserActions
from application.playback import PlaybackSession
from application.tag_drafts import TagDrafts, TagValues


def tag_values(tags=()):
    return TagValues(list(tags), {'tag': {'name': 'tag', 'kind': 'major', 'parent': None}})


@pytest.mark.parametrize('status', [Status.FAILED, Status.CANCELLED])
def test_failed_or_cancelled_commit_preserves_draft_and_cancels_dependent_action(status):
    submitted = Operation()
    drafts = TagDrafts(Mock(tag_values=lambda _: tag_values()), lambda *_: submitted, lambda: 'video', lambda: True)
    draft = drafts.open_current()
    drafts.update('video', tag_values(['tag']))
    action = Mock()
    UserActions().request(action, lambda: drafts.commit('video'))
    submitted.finish(Outcome(status, error=ValueError('not saved') if status is Status.FAILED else None))
    assert draft.dirty and draft.baseline.tags == []
    assert drafts.open_current().values.tags == ['tag']
    action.assert_not_called()


def test_only_submitted_snapshot_is_confirmed_and_draft_is_owned_by_video_id():
    submitted = Operation()
    active = ['first']
    drafts = TagDrafts(Mock(tag_values=lambda _: tag_values()), lambda *_: submitted, lambda: active[0], lambda: True)
    first = drafts.open_current()
    drafts.update('first', tag_values(['tag']))
    operation = drafts.commit('first')
    drafts.update('first', tag_values())
    active[0] = 'second'
    second = drafts.open_current()
    submitted.finish(Outcome(Status.SUCCEEDED))
    assert operation.outcome.succeeded
    assert first.dirty and first.baseline.tags == ['tag'] and first.values.tags == []
    assert second.baseline.tags == second.values.tags == []


def test_reentrant_commit_shares_one_operation():
    drafts = None
    seen = []
    submitted = Operation()
    def submit(*_):
        seen.append(drafts.commit('video'))
        return submitted
    drafts = TagDrafts(Mock(tag_values=lambda _: tag_values()), submit, lambda: 'video', lambda: True)
    drafts.open_current()
    drafts.update('video', tag_values(['tag']))
    operation = drafts.commit('video')
    assert seen == [operation]
    submitted.finish(Outcome(Status.SUCCEEDED))
    assert operation.outcome.succeeded and not drafts.saving


def test_submit_exception_is_a_failure_and_keeps_the_draft():
    drafts = TagDrafts(Mock(tag_values=lambda _: tag_values()), Mock(side_effect=OSError('cannot submit')), lambda: 'video', lambda: True)
    draft = drafts.open_current()
    drafts.update('video', tag_values(['tag']))
    operation = drafts.commit('video')
    assert operation.outcome.status is Status.FAILED and draft.dirty and not drafts.saving


def test_recovery_reconciles_persisted_values_without_overwriting_a_newer_draft():
    persisted = [tag_values()]
    submitted = Operation()
    drafts = TagDrafts(Mock(tag_values=lambda _: persisted[0]), lambda *_: submitted, lambda: 'video', lambda: True)
    draft = drafts.open_current()
    drafts.update('video', tag_values(['tag']))
    drafts.commit('video')
    submitted.finish(Outcome(Status.FAILED, error=OSError('interrupted'), recoverable=True))
    persisted[0] = tag_values(['tag'])
    drafts.reconcile(['video'])
    assert not draft.dirty
    drafts.update('video', tag_values())
    drafts.reconcile(['video'])
    assert draft.dirty and draft.values.tags == []


def test_latest_selection_runs_once_after_success():
    commit = Operation()
    actions = UserActions()
    opened = []
    actions.request(lambda: opened.append('B'), lambda: commit)
    actions.request(lambda: opened.append('C'), Mock(side_effect=AssertionError('must share the existing commit')))
    assert opened == []
    commit.finish(Outcome(Status.SUCCEEDED))
    assert opened == ['C']


def test_dependent_action_waits_for_working_draft_changed_during_submission():
    submitted = []
    def submit(*_):
        operation = Operation()
        submitted.append(operation)
        return operation
    drafts = TagDrafts(Mock(tag_values=lambda _: tag_values()), submit, lambda: 'video', lambda: True)
    drafts.open_current()
    drafts.update('video', tag_values(['tag']))
    action = Mock()
    UserActions().request(action, lambda: drafts.commit('video'))
    drafts.update('video', tag_values())
    submitted[0].finish(Outcome(Status.SUCCEEDED))
    action.assert_not_called()
    assert len(submitted) == 2
    submitted[1].finish(Outcome(Status.SUCCEEDED))
    action.assert_called_once()


def test_explicit_close_takes_precedence_over_pending_selection():
    commit = Operation()
    actions = UserActions()
    executed = []
    actions.request(lambda: executed.append('B'), lambda: commit)
    actions.request(lambda: executed.append('close'), lambda: commit, closing=True)
    actions.request(lambda: executed.append('C'), lambda: commit)
    commit.finish(Outcome(Status.SUCCEEDED))
    assert executed == ['close']


def test_completion_is_single_and_late_observers_receive_the_same_outcome():
    operation = Operation.success('result')
    seen = []
    operation.on_finished(seen.append)
    assert seen == [operation.outcome] and seen[0].value == 'result'
    with pytest.raises(RuntimeError):
        operation.finish(Outcome(Status.SUCCEEDED))


def test_view_observer_error_does_not_leave_draft_or_dependent_action_pending():
    operation = Operation()
    operation.on_finished(Mock(side_effect=ValueError('broken view')))
    delivered = []
    operation.on_finished(delivered.append)
    with pytest.raises(ValueError, match='broken view'):
        operation.finish(Outcome(Status.SUCCEEDED))
    assert delivered == [operation.outcome] and not operation.pending


@pytest.mark.parametrize('recoverable', [False, True])
def test_file_failure_restores_lifecycle_before_delivering_result(recoverable):
    queue, events = [], []
    tasks = FileTasks(lambda work, done: queue.append(done), lambda policy: events.append('begin') or 'bookmark',
                      lambda bookmark: events.append(('restore', bookmark)), lambda: recoverable)
    operation = tasks.run(lambda: None)
    operation.on_finished(lambda result: events.append(('result', result.recoverable)))
    assert tasks.active is operation
    queue.pop()(None, OSError('failure'))
    assert events == ['begin', ('restore', 'bookmark'), ('result', recoverable)]
    assert tasks.active is None and operation.outcome.status is Status.FAILED


def test_restore_failure_is_not_reported_as_success():
    queue = []
    tasks = FileTasks(lambda work, done: queue.append(done), lambda policy: None,
                      Mock(side_effect=OSError('restore failed')), lambda: False)
    operation = tasks.run(lambda: None)
    queue.pop()('service succeeded', None)
    assert operation.outcome.status is Status.FAILED
    assert str(operation.outcome.error) == 'restore failed' and tasks.active is None


def test_repeated_relative_seek_accumulates_and_can_reverse_before_acknowledgement():
    session = PlaybackSession(clock=lambda: 10)
    requested = []
    for offset in [5000, 5000, 5000, -5000]:
        _, target = session.relative_seek(10000, offset, 100000)
        requested.append(session.seek(target, 100000))
    assert requested == [15000, 20000, 25000, 20000]
    session.acknowledge(10000)
    assert session.pending_seek.position == 20000
    session.acknowledge(20000)
    assert session.pending_seek is None


def test_expired_seek_uses_backend_position_and_targets_are_bounded():
    clock = [0]
    session = PlaybackSession(clock=lambda: clock[0])
    session.seek(95000, 100000)
    clock[0] = 3
    assert session.relative_seek(10000, 5000, 100000) == (10000, 15000)
    assert session.seek(120000, 100000) == 100000
    assert session.seek(-100, 100000) == 0


def test_resume_seeks_once_and_waits_for_actual_pause_acknowledgement():
    session = PlaybackSession()
    session.begin(5000, True)
    commands = session.restore(playing=True, paused=False, duration=10000)
    assert commands.position == 5000 and commands.pause
    assert session.restore(playing=True, paused=False, duration=10000) is None
    assert session.resume.paused and session.position_to_save(0, ended=False) is None
    session.restore(playing=False, paused=True, duration=10000)
    assert session.resume is None and session.position_to_save(5000, ended=False) == 5000


def test_completed_media_stays_at_zero_until_a_new_session_starts():
    session = PlaybackSession()
    assert session.terminal(ended=True, failed=False)
    assert session.position_to_save(98000, ended=True) == 0
    assert session.position_to_save(98000, ended=False) == 0
    assert not session.terminal(ended=True, failed=False)
    session.begin(1234, False)
    session.restore(playing=True, paused=False, duration=100000)
    assert session.position_to_save(1500, ended=False) == 1500
