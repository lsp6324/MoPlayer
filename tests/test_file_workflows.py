"""File-result and continuation contracts, without Qt/VLC or concrete storage."""
import json
from types import SimpleNamespace
import pytest
from application.classification import Classification
from application.renaming import Renaming
from application.deletion import Deletion
from application.recovery import Recovery
from application.file_results import PlaybackTarget, FileAction
from application.file_tasks import FileTasks
from application.operations import Operation, Outcome, Status, UserActions


class Repository:
    def __init__(self):
        self.rows = {vid: dict(id=vid, name=vid, score=7, archived=1) for vid in ('a', 'b', 'c')}
        self.pending = {kind: [] for kind in ('jobs', 'hierarchy_jobs', 'deletion_jobs', 'archive_setting_jobs')}

    def video(self, vid):
        return self.rows.get(vid)

    def videos(self, mode):
        return list(self.rows.values())

    def pending_tasks(self, kind=None):
        return list(self.pending[kind]) if kind else [row for rows in self.pending.values() for row in rows]


class Harness:
    def __init__(self):
        self.repo = Repository()
        self.queue, self.notices, self.order, self.played = [], [], [], []
        self.visible = {vid: row['name'] for vid, row in self.repo.rows.items()}
        self.marked, self.deleted, self.baselines = set(), set(), set()
        self.busy, self.configured, self.restore_error = False, True, None
        self.target = PlaybackTarget('a', object(), ('original', 0))
        self.next = Operation.success(('original', 1))
        self.preparation = Operation()
        self.tasks = FileTasks(lambda work, done: self.queue.append((work, done)), self.begin, self.end,
                               lambda: bool(self.repo.pending_tasks()), prepare=lambda: self.order.append('prepare'))
        self.classification = Classification(self.tasks, self.repo, self.submit_tags, self.submit_archive,
            available=lambda: not self.busy, ensure_storage=lambda: self.configured,
            refresh=self.refresh, notify=self.notices.append)
        library = SimpleNamespace(locate_video=lambda vid: self.preparation,
                                  advance=lambda context, location, direction: self.next)
        self.deletion = Deletion(self.tasks, library, self.submit_delete,
            available=lambda: not self.busy, playback_target=lambda: self.target,
            navigation_busy=self.navigation_busy, mark_deleting=self.mark, refresh_deleted=self.remove,
            save=lambda: self.order.append('save'), clear=self.clear,
            start=lambda context, location: self.played.append((context, location)), notify=self.notices.append)
        self.recovery = Recovery(self.tasks, self.repo, SimpleNamespace(reconcile=self.confirm),
            recover_archive=lambda: [], recover_tags=lambda: [], recover_deletions=lambda: [],
            available=lambda: not self.busy, playback_target=lambda: self.target, mark_deleting=self.mark,
            refresh=self.refresh, refresh_deleted=self.remove,
            continue_after_delete=self.deletion.continue_after_delete,
            storage_ready=lambda: self.order.append('storage-ready'), notify=self.notices.append)

    def begin(self, policy):
        self.busy = True
        self.policy = policy

    def end(self, bookmark):
        self.busy = False
        if self.restore_error:
            raise self.restore_error

    def navigation_busy(self, busy):
        self.busy = busy

    def mark(self, ids, active):
        (self.marked.update if active else self.marked.difference_update)(ids)

    def refresh(self, ids):
        self.order.append('refresh')
        for vid in ids:
            if vid in self.repo.rows:
                self.visible[vid] = self.repo.rows[vid]['name']

    def remove(self, ids):
        self.deleted.update(ids)
        for vid in ids:
            self.visible.pop(vid, None)

    def confirm(self, ids):
        self.baselines.update(ids)

    def clear(self):
        self.target = PlaybackTarget(None, self.target.context, self.target.location)

    def submit_tags(self, vid, score, tags, schema):
        self.order.append(('submit-tags', vid, score, tags, schema))
        self.repo.rows[vid]['name'] = 'tagged'
        return [vid]

    def submit_archive(self, vid, score, tags):
        self.repo.rows[vid]['name'] = 'archived'

    def submit_delete(self, vid):
        del self.repo.rows[vid]

    def finish(self):
        work, done = self.queue.pop(0)
        try:
            value = work()
        except Exception as error:
            done(None, error)
        else:
            done(value, None)


def test_classification_freezes_submission_and_reconciles_before_dependent_action():
    h = Harness()
    tags, schema = ['tag'], [{'name': 'tag'}]
    operation = h.classification.apply_tags('a', tags, schema)
    tags.append('later')
    schema[0]['name'] = 'changed'
    h.repo.rows['a']['score'] = 1
    observed = []
    operation.on_finished(lambda result: observed.append(h.visible['a']))
    h.finish()
    assert operation.outcome.succeeded and observed == ['tagged']
    assert ('submit-tags', 'a', 7, ['tag'], [{'name': 'tag'}]) in h.order
    assert h.order.index('prepare') < h.order.index('refresh')
    assert h.notices[-1].score_video == 'a'


@pytest.mark.parametrize('busy,configured', [(True, True), (False, False)])
def test_cancelled_admission_does_not_submit_or_publish_success(busy, configured):
    h = Harness()
    h.busy, h.configured = busy, configured
    operation = h.classification.apply_tags('a', [], [])
    assert operation.outcome.status is Status.CANCELLED
    assert h.visible['a'] == 'a' and not h.queue and not h.notices


def test_partial_tag_failure_refreshes_actual_rows_without_prompting_score():
    h = Harness()
    def failed(*args):
        h.repo.rows['b']['name'] = 'partly committed'
        h.repo.pending['hierarchy_jobs'] = [{'plan': '{}'}]
        raise OSError('interrupted')
    h.classification.submit_tags = failed
    operation = h.classification.apply_tags('a', [], [])
    h.finish()
    assert operation.outcome.status is Status.FAILED and operation.outcome.recoverable
    assert h.visible['b'] == 'partly committed'
    assert h.notices[-1].score_video is None


def test_post_processing_failure_does_not_release_dependent_action():
    h = Harness()
    h.classification.refresh = lambda ids: (_ for _ in ()).throw(ValueError('projection failed'))
    operation = h.classification.apply_tags('a', [], [])
    h.finish()
    assert h.repo.rows['a']['name'] == 'tagged'
    assert operation.outcome.status is Status.FAILED
    assert 'projection failed' in str(h.notices[-1].outcome.error)


def test_media_restore_failure_still_refreshes_records_but_does_not_acknowledge_success():
    h = Harness()
    h.restore_error = OSError('media unavailable')
    operation = h.classification.apply_tags('a', [], [], prompt_score=False)
    h.finish()
    assert h.visible['a'] == 'tagged' and operation.outcome.status is Status.FAILED
    assert h.notices[-1].score_video is None and not h.busy


@pytest.mark.parametrize('video_id', ['a', 'b'])
def test_classification_keeps_current_media_and_updates_only_the_target(video_id):
    h = Harness()
    operation = h.classification.archive(video_id, 8, ['tag'])
    assert not h.policy.release_media
    h.finish()
    assert operation.outcome.succeeded and h.visible[video_id] == 'archived'


def test_deletion_preparation_freezes_id_and_preserves_current_media_until_success():
    h = Harness()
    context = object()
    operation = h.deletion.delete('b')
    assert h.busy and h.target.video_id == 'a'
    h.preparation.finish(Outcome(Status.SUCCEEDED, value=(context, ('chosen', 1))))
    assert h.marked == {'b'} and not h.policy.release_media
    h.finish()
    assert operation.outcome.succeeded and 'a' in h.repo.rows and 'b' not in h.repo.rows
    assert h.deleted == {'b'} and not h.marked
    assert h.played == [(context, ('original', 1))] and 'save' in h.order


def test_cancelled_deletion_preparation_releases_busy_and_does_not_delete():
    h = Harness()
    operation = h.deletion.delete('b')
    h.preparation.finish(Outcome(Status.CANCELLED))
    assert operation.outcome.status is Status.CANCELLED
    assert not h.busy and 'b' in h.visible and not h.queue and not h.played


def test_failed_delete_preserves_context_and_does_not_continue():
    h = Harness()
    original = h.target
    h.deletion.submit = lambda vid: (_ for _ in ()).throw(OSError('locked'))
    operation = h.deletion.delete('a', (original.context, original.location))
    h.finish()
    assert operation.outcome.status is Status.FAILED
    assert h.target is original and h.visible['a'] == 'a' and not h.played and not h.marked


@pytest.mark.parametrize('next_outcome', [Outcome(Status.CANCELLED), Outcome(Status.FAILED, error=OSError('scan failed'))])
def test_after_delete_navigation_failure_or_cancel_stays_stopped(next_outcome):
    h = Harness()
    h.next = Operation.completed(next_outcome)
    operation = h.deletion.delete('a', (h.target.context, h.target.location))
    h.finish()
    assert operation.outcome.succeeded and h.target.video_id is None
    assert not h.busy and not h.played and 'a' not in h.visible
    assert any(notice.action is FileAction.NEXT and notice.outcome is next_outcome for notice in h.notices)


def test_recovery_refreshes_ordinary_archive_ids_without_any_tag_plan():
    h = Harness()
    h.repo.pending['jobs'] = [{'video': 'b'}]
    def recovered():
        h.repo.rows['b']['name'] = 'recovered name'
        h.repo.pending['jobs'].clear()
        return []
    h.recovery.recover_archive = recovered
    operation = h.recovery.retry()
    h.finish()
    assert operation.outcome.succeeded and h.visible['b'] == 'recovered name'
    assert 'storage-ready' in h.order


def test_failed_recovery_refreshes_partial_commits_without_acknowledging_drafts_or_running_deletes():
    h = Harness()
    h.repo.pending['hierarchy_jobs'] = [{'plan': json.dumps({'videos': [{'video': 'b'}]})}]
    h.repo.pending['deletion_jobs'] = [{'video': 'c'}]
    def failed():
        h.repo.rows['b']['name'] = 'partially recovered'
        return ['retry failed']
    h.recovery.recover_tags = failed
    h.recovery.recover_deletions = lambda: pytest.fail('Deletion must wait for successful archive/tag recovery')
    operation = h.recovery.retry()
    h.finish()
    assert operation.outcome.status is Status.FAILED and operation.outcome.recoverable
    assert h.visible['b'] == 'partially recovered' and not h.baselines and not h.marked
    assert 'c' in h.visible and 'storage-ready' not in h.order


def test_recovery_acknowledges_existing_tag_drafts_and_continues_only_if_active_video_was_deleted():
    h = Harness()
    original = h.target
    h.repo.pending['hierarchy_jobs'] = [{'plan': json.dumps({'videos': [{'video': 'b'}]})}]
    h.repo.pending['deletion_jobs'] = [{'video': 'a'}]
    def recovered():
        h.repo.pending['hierarchy_jobs'].clear()
        return []
    def deleted():
        del h.repo.rows['a']
        h.repo.pending['deletion_jobs'].clear()
        return []
    h.recovery.recover_tags, h.recovery.recover_deletions = recovered, deleted
    operation = h.recovery.retry()
    h.finish()
    assert operation.outcome.succeeded and h.baselines == {'b'}
    assert 'a' not in h.visible and h.played == [(original.context, ('original', 1))]
    assert h.notices[-1].continuing and not h.marked


def test_settings_recovery_refreshes_frozen_batch_ids_before_deletion_recovery():
    h = Harness()
    h.repo.pending['archive_setting_jobs'] = [{'plan': json.dumps({'videos': [{'video': 'b'}]})}]
    def settings():
        h.order.append('settings-recovered')
        h.repo.rows['b']['name'] = 'new settings folder'
        h.repo.pending['archive_setting_jobs'].clear()
        return []
    h.recovery.recover_settings = settings
    h.recovery.recover_deletions = lambda: h.order.append('delete-recovered') or []
    operation = h.recovery.retry()
    h.finish()
    assert operation.outcome.succeeded
    assert h.visible['b'] == 'new settings folder'
    assert h.order.index('settings-recovered') < h.order.index('delete-recovered')
    assert 'storage-ready' in h.order


def test_recovery_restores_names_inside_the_same_media_release_cycle():
    h=Harness()
    h.repo.rows['b'].update(name='old prefix b',original_name='b')
    h.recovery.recover_deletions=lambda:h.order.append('delete-recovered') or []
    def restore():
        assert h.busy
        h.order.append('names-restored')
        h.repo.rows['b']['name']='b'
        return ['b']
    h.recovery.restore_names=restore
    operation=h.recovery.retry()
    h.finish()
    assert operation.outcome.succeeded and h.visible['b']=='b'
    assert h.order.index('delete-recovered')<h.order.index('names-restored') and not h.busy


def renaming(h, validate=lambda vid,name:None):
    def submit(vid,name):
        h.repo.rows[vid]['name']=name
        return vid
    return Renaming(h.tasks,h.repo,submit,available=lambda:not h.busy,
                    current_video=lambda:h.target.video_id,refresh=h.refresh,validate=validate)


def test_rename_freezes_identity_and_refreshes_only_after_disk_completion():
    h=Harness()
    operation=renaming(h).rename('a','renamed.mp4')
    assert operation.pending and h.visible['a']=='a' and h.policy.release_media
    h.target=PlaybackTarget('c')
    h.finish()
    assert operation.outcome.succeeded and h.visible['a']=='renamed.mp4' and h.visible['c']=='c'
    assert not h.busy


def test_rename_invalid_preflight_never_releases_media_or_starts_work():
    h=Harness()
    def invalid(vid,name):
        raise ValueError('invalid name')
    operation=renaming(h,invalid).rename('a','bad?.mp4')
    assert operation.outcome.status is Status.FAILED and not h.queue and not h.busy
    assert h.visible['a']=='a'


def test_noncurrent_rename_keeps_current_media_and_pending_tasks_require_recovery():
    h=Harness()
    operation=renaming(h).rename('b','renamed.mp4')
    assert not h.policy.release_media
    h.finish()
    assert operation.outcome.succeeded and h.visible['b']=='renamed.mp4'
    h.repo.pending['jobs']=[{'video':'b'}]
    blocked=renaming(h).rename('a','another.mp4')
    assert blocked.outcome.recoverable and not h.queue and h.visible['a']=='a'


def test_recovery_replays_rename_before_tag_batches_and_refreshes_renamed_identity():
    h=Harness()
    h.repo.pending['jobs']=[{'video':'b'}]
    def recover():
        h.order.append('rename-recovered')
        h.repo.rows['b']['name']='renamed.mp4'
        h.repo.pending['jobs'].clear()
        return []
    h.recovery.recover_renames=recover
    h.recovery.recover_tags=lambda:h.order.append('tags-recovered') or []
    operation=h.recovery.retry()
    h.finish()
    assert operation.outcome.succeeded and h.visible['b']=='renamed.mp4'
    assert h.order.index('rename-recovered')<h.order.index('tags-recovered')


def test_navigation_after_rating_waits_for_reconciliation_and_last_selection_wins():
    h=Harness()
    actions=UserActions(before_action=lambda:h.tasks.completion or Operation.success())
    operation=h.classification.archive('a',8,[])
    selected=[]
    actions.request(lambda:selected.append(('b',h.visible['a'])),lambda:Operation.success())
    actions.request(lambda:selected.append(('c',h.visible['a'])),lambda:Operation.success())
    assert not selected and not h.tasks.media_released
    h.finish()
    assert operation.outcome.succeeded and selected==[('c','archived')]
    assert h.tasks.completion is None


def test_navigation_never_continues_on_raw_io_success_if_reconciliation_failed():
    h=Harness()
    actions=UserActions(before_action=lambda:h.tasks.completion or Operation.success())
    h.classification.refresh=lambda ids:(_ for _ in ()).throw(ValueError('projection failed'))
    operation=h.classification.archive('a',8,[])
    selected=[]
    actions.request(lambda:selected.append('b'),lambda:Operation.success())
    h.finish()
    assert operation.outcome.status is Status.FAILED and not selected and h.tasks.completion is None


def test_rejected_reentrant_task_cannot_unpublish_the_running_completion():
    h=Harness()
    h.classification.available=lambda:True
    first=h.classification.archive('a',8,[])
    published=h.tasks.completion
    rejected=h.classification.archive('b',9,[])
    assert rejected.outcome.status is Status.CANCELLED and h.tasks.completion is published
    assert h.tasks.completion.pending
    h.finish()
    assert first.outcome.succeeded and h.visible['b']=='b' and h.tasks.completion is None
