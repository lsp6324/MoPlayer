"""Settings submission and result reconciliation; no UI or file access."""
from moplayer.application.file_results import FileAction, FileNotice, complete_file_task
from moplayer.application.operations import Operation, Status
from moplayer.application.file_tasks import FileTaskPolicy


class ArchiveConfiguration:
    def __init__(self, tasks, repository, submit, *, available, refresh, restore_names=lambda: [], notify=lambda notice: None,
                 archive_enabled=lambda: True):
        self.archive_enabled = archive_enabled
        self.tasks, self.repository, self.submit = tasks, repository, submit
        self.restore_names = restore_names
        self.notify = notify
        self.available, self.refresh = available, refresh

    def apply(self, root, folders, *, enabled=True):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        affected = tuple(row['id'] for row in self.repository.videos('archived')) if enabled else ()
        work = (lambda: self.submit(root, folders)) if enabled else (lambda: self.submit(root, folders, enabled=False))
        return self._run(work, affected, policy=FileTaskPolicy(release_media=enabled))

    def restore_original_names(self):
        if not self.archive_enabled():
            return Operation.success(())
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        affected=tuple(row['id'] for row in self.repository.videos('archived')
                       if row.get('original_name') and row['name']!=row['original_name'])
        if not affected:
            return Operation.success(())
        self.notify(FileNotice(FileAction.NAMES))
        return self._run(self.restore_names,affected,FileAction.NAMES,self.notify)

    def _run(self, work, affected, action=FileAction.SETTINGS, notify=lambda notice: None, *, policy=FileTaskPolicy()):
        source = self.tasks.run(work, policy=policy)
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh(affected)
            return FileNotice(action, outcome, len(affected))
        return self.tasks.track(complete_file_task(source, action, reconcile, notify))
