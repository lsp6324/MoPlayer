"""Freeze deletion targets and coordinate preparation, cleanup and continuation."""
from application.file_results import FileAction, FileNotice, complete_file_task
from application.file_tasks import FileTaskPolicy
from application.operations import Operation, Status


class Deletion:
    def __init__(self, tasks, library, submit, *, available, playback_target,
                 navigation_busy, mark_deleting, refresh_deleted, save, clear, start, notify):
        self.tasks, self.library, self.submit = tasks, library, submit
        self.available, self.playback_target = available, playback_target
        self.navigation_busy, self.mark_deleting = navigation_busy, mark_deleting
        self.refresh_deleted, self.save, self.clear, self.start, self.notify = refresh_deleted, save, clear, start, notify

    def delete(self, video_id, context=None):
        if not self.available():
            return Operation.cancelled()
        if context is not None:
            return self._submit(video_id, context)
        operation = Operation()
        self.navigation_busy(True)
        prepared = self.library.locate_video(video_id)
        def ready(outcome):
            self.navigation_busy(False)
            if outcome.succeeded:
                self._submit(video_id, outcome.value).on_finished(operation.finish)
            else:
                try:
                    self.notify(FileNotice(FileAction.DELETE, outcome))
                finally:
                    operation.finish(outcome)
        prepared.on_finished(ready)
        return operation

    def _submit(self, video_id, context):
        playing = video_id == self.playback_target().video_id
        self.mark_deleting({video_id}, True)
        self.notify(FileNotice(FileAction.DELETE))
        source = self.tasks.run(lambda: self.submit(video_id),
                                policy=FileTaskPolicy(release_media=playing))
        def reconcile(outcome):
            self.mark_deleting({video_id}, False)
            if outcome.succeeded:
                self.refresh_deleted({video_id})
                if not playing:
                    self.save()
                else:
                    self.continue_after_delete(*context)
            return FileNotice(FileAction.DELETE, outcome)
        return self.tasks.track(complete_file_task(source, FileAction.DELETE, reconcile, self.notify))

    def continue_after_delete(self, context, location):
        self.clear()
        self.navigation_busy(True)
        operation = self.library.advance(context, location, 1)
        def ready(outcome):
            self.navigation_busy(False)
            if outcome.succeeded and outcome.value:
                self.start(context, outcome.value)
            self.notify(FileNotice(FileAction.NEXT, outcome, count=int(bool(outcome.value))))
        operation.on_finished(ready)
        return operation
