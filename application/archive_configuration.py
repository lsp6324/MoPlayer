"""Settings submission and result reconciliation; no UI or file access."""
from application.file_results import FileAction, FileNotice, complete_file_task
from application.operations import Operation, Status


class ArchiveConfiguration:
    def __init__(self, tasks, repository, submit, *, available, refresh):
        self.tasks, self.repository, self.submit = tasks, repository, submit
        self.available, self.refresh = available, refresh

    def apply(self, root, folders):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        affected = tuple(row['id'] for row in self.repository.videos('archived'))
        source = self.tasks.run(lambda: self.submit(root, folders))
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh(affected)
            return FileNotice(FileAction.SETTINGS, outcome, len(affected))
        return complete_file_task(source, FileAction.SETTINGS, reconcile, lambda notice: None)
