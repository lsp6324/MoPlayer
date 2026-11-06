from types import SimpleNamespace
import pytest
from moplayer.application.batch_actions import BatchActions
from moplayer.application.library import LibrarySelection
from moplayer.application.operations import Operation, Outcome, Status, UserActions


class Harness:
    def __init__(self, count=3):
        self.queue, self.applied, self.committed, self.discarded = [], [], [], []
        self.schema = {name: dict(name=name, parent=parent) for name, parent in
                       [('parent', None), ('child', 'parent'), ('other', None), ('new', None)]}
        self.tags = {str(n): ['child', 'other'] if n % 2 else ['other'] for n in range(count)}
        self.fail_id, self.pending = None, None
        self.repository = SimpleNamespace(video=lambda vid: {} if vid in self.tags else None,
            tag_values=lambda vid: SimpleNamespace(tags=self.tags[vid], schema=self.schema))
        self.drafts = SimpleNamespace(commit=self.commit, discard=self.discarded.append)
        self.classification = SimpleNamespace(favorite=self.apply, rating=self.apply, apply_tags=self.apply_tags)
        self.batch = BatchActions(self.repository, self.drafts, self.classification, None, schedule=self.queue.append)
        self.items = tuple(LibrarySelection(vid) for vid in self.tags)

    def commit(self, vid):
        self.committed.append(vid)
        return Operation.success()

    def apply(self, vid, value):
        self.applied.append((vid, value))
        if vid == self.fail_id:
            return Operation.completed(Outcome(Status.FAILED, error=OSError('injected'), recoverable=True))
        return self.pending or Operation.success()

    def apply_tags(self, vid, tags, schema, **options):
        self.tags[vid] = tags
        return self.apply(vid, tags)

    def drain(self):
        while self.queue:
            self.queue.pop(0)()


@pytest.mark.parametrize('mode,names,expected', [
    ('add', ['new'], {'0': {'other', 'new'}, '1': {'child', 'other', 'new'}}),
    ('remove', ['parent'], {'0': {'other'}, '1': {'other'}}),
    ('add', ['parent'], {'0': {'parent', 'other'}, '1': {'child', 'other'}}),
])
def test_batch_tag_intent_preserves_individual_tags_and_parent_branch(mode, names, expected):
    h = Harness(2)
    result = h.batch.tags(h.items, names, mode)
    h.drain()
    assert result.outcome.succeeded
    assert {vid: set(tags) for vid, tags in h.tags.items()} == expected
    assert result.outcome.value.completed == ('0', '1')
    assert h.discarded == ['0', '1']


def test_batch_failure_stops_remaining_frozen_ids_and_reports_recoverability():
    h = Harness()
    h.fail_id = '1'
    result = h.batch.rating(h.items + (h.items[0],), 8)
    h.drain()
    assert result.outcome.status is Status.FAILED and result.outcome.recoverable
    assert result.outcome.value.completed == ('0',)
    assert result.outcome.value.remaining == ('1', '2')
    assert result.outcome.value.failed_id == '1'
    assert h.applied == [('0', 8), ('1', 8)]
    assert h.committed == ['0', '1', '2']
    assert h.batch.active is None


def test_async_batch_is_action_barrier_and_cancels_only_after_current_item():
    h = Harness()
    h.pending = Operation()
    result = h.batch.favorite(h.items, True)
    h.drain()
    actions = []
    user = UserActions(before_action=lambda: h.batch.active or Operation.success())
    user.request(lambda: actions.append('navigate'), Operation.success)
    assert not actions and result.pending
    assert h.batch.rating(h.items, 4).outcome.status is Status.CANCELLED
    h.batch.cancel()
    h.pending.finish(Outcome(Status.SUCCEEDED))
    h.drain()
    assert result.outcome.status is Status.CANCELLED
    assert result.outcome.value.completed == ('0',)
    assert result.outcome.value.remaining == ('1', '2')
    assert not actions and h.applied == [('0', True)]


def test_large_synchronous_batch_yields_without_recursion_and_completes():
    h = Harness(1200)
    result = h.batch.rating(h.items, None)
    h.queue.pop(0)()
    assert result.pending and h.queue
    h.drain()
    assert result.outcome.succeeded and len(result.outcome.value.completed) == 1200


def test_deleted_target_and_renamed_tag_are_not_retargeted():
    h = Harness()
    result = h.batch.tags(h.items, ['new'], 'add')
    del h.schema['new']
    h.drain()
    assert result.outcome.status is Status.FAILED and h.applied == []
    result = h.batch.favorite(h.items, True)
    del h.tags['1']
    h.drain()
    assert result.outcome.status is Status.FAILED and h.applied == []
