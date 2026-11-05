"""Reconcile durable task recovery against actual committed video records."""
import json
from application.file_results import FileAction, FileNotice, complete_file_task
from application.operations import Operation, Status


class Recovery:
    def __init__(self, tasks, repository, drafts, *, recover_archive, recover_tags,
                 recover_deletions, available, playback_target, mark_deleting,
                 refresh, refresh_deleted, continue_after_delete, storage_ready, notify, recover_settings=lambda: []):
        self.recover_settings = recover_settings
        self.tasks, self.repository, self.drafts = tasks, repository, drafts
        self.recover_archive, self.recover_tags, self.recover_deletions = recover_archive, recover_tags, recover_deletions
        self.available, self.playback_target, self.mark_deleting = available, playback_target, mark_deleting
        self.refresh, self.refresh_deleted = refresh, refresh_deleted
        self.continue_after_delete, self.storage_ready, self.notify = continue_after_delete, storage_ready, notify

    def retry(self):
        if not self.available():
            return Operation.cancelled()
        pending = {row['video'] for row in self.repository.pending_tasks('deletion_jobs')}
        plans = [json.loads(row['plan']) for row in self.repository.pending_tasks('hierarchy_jobs')]
        tag_ids = tuple(dict.fromkeys(entry['video'] for plan in plans for entry in plan['videos']))
        archive_ids = tuple(row['video'] for row in self.repository.pending_tasks('jobs'))
        settings_plans = [json.loads(row['plan']) for row in self.repository.pending_tasks('archive_setting_jobs')]
        settings_ids = tuple(entry['video'] for plan in settings_plans for entry in plan['videos'])
        affected = tuple(dict.fromkeys((*tag_ids, *archive_ids, *settings_ids)))
        playback = self.playback_target()
        self.mark_deleting(pending, True)
        self.notify(FileNotice(FileAction.RECOVERY))
        def work():
            errors = self.recover_archive() + self.recover_tags()
            if not errors:
                errors += self.recover_settings()
            if not errors:
                errors += self.recover_deletions()
            if errors:
                raise RuntimeError('\n'.join(errors))
        source = self.tasks.run(work)
        def reconcile(outcome):
            self.mark_deleting(pending, False)
            if outcome.status is Status.CANCELLED:
                return FileNotice(FileAction.RECOVERY, outcome)
            if outcome.succeeded:
                self.drafts.reconcile(vid for vid in tag_ids if self.repository.video(vid) is not None)
            if not self.repository.pending_tasks():
                self.storage_ready()
            self.refresh(affected)
            deleted = {vid for vid in pending if self.repository.video(vid) is None}
            self.refresh_deleted(deleted)
            continuing = playback.video_id in deleted
            if continuing:
                self.continue_after_delete(playback.context, playback.location)
            return FileNotice(FileAction.RECOVERY, outcome, continuing=continuing)
        return complete_file_task(source, FileAction.RECOVERY, reconcile, self.notify)
