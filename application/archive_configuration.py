"""Settings submission and result reconciliation; no UI or file access."""
from application.file_results import FileAction, FileNotice, complete_file_task
from application.operations import Operation, Status


class ArchiveConfiguration:
    def __init__(self, tasks, repository, submit, *, available, refresh, restore_names=lambda: [], notify=lambda notice: None):
        self.tasks, self.repository, self.submit = tasks, repository, submit
        self.restore_names = restore_names
        self.notify = notify
        self.available, self.refresh = available, refresh

    def apply(self, root, folders):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        affected = tuple(row['id'] for row in self.repository.videos('archived'))
        return self._run(lambda: self.submit(root, folders), affected)

    def restore_original_names(self):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        affected=tuple(row['id'] for row in self.repository.videos('archived')
                       if row.get('original_name') and row['name']!=row['original_name'])
        if not affected:
            return Operation.success(())
        self.notify(FileNotice(FileAction.NAMES))
        return self._run(self.restore_names,affected,FileAction.NAMES,self.notify)

    def _run(self, work, affected, action=FileAction.SETTINGS, notify=lambda notice: None):
        source = self.tasks.run(work)
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh(affected)
            return FileNotice(action, outcome, len(affected))
        return self.tasks.track(complete_file_task(source, action, reconcile, notify))
