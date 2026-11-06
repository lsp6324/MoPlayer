"""Freeze a rename target and reconcile the actual record after file work."""
from moplayer.application.file_results import FileAction, FileNotice, complete_file_task
from moplayer.application.file_tasks import FileTaskPolicy
from moplayer.application.operations import Operation, Outcome, Status


class Renaming:
    def __init__(self, tasks, repository, submit, *, available, current_video, refresh, validate=lambda video_id,name: None):
        self.validate = validate
        self.tasks, self.repository, self.submit = tasks, repository, submit
        self.available, self.current_video, self.refresh = available, current_video, refresh

    def rename(self, video_id, name):
        if not self.available() or self.repository.video(video_id) is None:
            return Operation.cancelled()
        if self.repository.pending_tasks():
            return Operation.completed(Outcome(Status.FAILED,error=RuntimeError('有未完成的文件任务。'),recoverable=True))
        try:
            self.validate(video_id, name)
        except Exception as error:
            return Operation.completed(Outcome(Status.FAILED,error=error))
        source = self.tasks.run(lambda: self.submit(video_id, name),
                                policy=FileTaskPolicy(release_media=video_id == self.current_video()))
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh((video_id,))
            return FileNotice(FileAction.RENAME, outcome)
        return self.tasks.track(complete_file_task(source, FileAction.RENAME, reconcile, lambda notice: None))
