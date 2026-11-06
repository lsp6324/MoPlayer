"""Freeze deletion targets and coordinate preparation, cleanup and continuation."""
from application.file_results import FileAction, FileNotice, complete_file_task
from application.file_tasks import FileTaskPolicy
from application.operations import Operation, Outcome, Status


class Deletion:
    def __init__(self, tasks, library, submit, *, available, playback_target,
                 navigation_busy, mark_deleting, refresh_deleted, save, clear, start, notify, forget=None,
                 video_exists=lambda video_id: True):
        self.video_exists = video_exists
        self.tasks, self.library, self.submit = tasks, library, submit
        self.available, self.playback_target = available, playback_target
        self.navigation_busy, self.mark_deleting = navigation_busy, mark_deleting
        self.refresh_deleted, self.save, self.clear, self.start, self.notify = refresh_deleted, save, clear, start, notify
        self.forget = forget

    def delete_many(self, video_ids, *, delete_files=False, cancelled=lambda: False):
        if not self.available():
            return Operation.cancelled()
        ids = tuple(dict.fromkeys(video_ids))
        target = self.playback_target()
        playing = target.video_id in ids
        # The playing item is last: a preceding failure keeps it in place.
        order = tuple(vid for vid in ids if vid != target.video_id) + ((target.video_id,) if playing else ())
        done = []
        navigation = [Operation.success()]
        self.mark_deleting(set(ids), True)
        self.notify(FileNotice(FileAction.DELETE))
        def work():
            for video_id in order:
                if cancelled():
                    break
                if self.video_exists(video_id):
                    (self.submit if delete_files else self.forget)(video_id)
                done.append(video_id)
            return tuple(done)
        source = self.tasks.run(work, policy=FileTaskPolicy(release_media=playing))
        def reconcile(outcome):
            self.mark_deleting(set(ids), False)
            if done:
                self.refresh_deleted(set(done))
            if target.video_id in done:
                continued = self.continue_after_delete(target.context, target.location)
                navigation[0] = continued
                if not delete_files:
                    continued.on_finished(lambda result: self.library.refresh_browsing())
            else:
                if not delete_files and done:
                    self.library.refresh_browsing()
                self.save()
            status = Status.CANCELLED if outcome.succeeded and len(done) < len(ids) else outcome.status
            result = Outcome(status, tuple(done), outcome.error, outcome.recoverable)
            title = (f'已删除 {len(done)} 条记录' if not delete_files else f'已回收 {len(done)} 个文件') if outcome.succeeded else ''
            return FileNotice(FileAction.DELETE, result, len(done), receipt_title=title)
        completed = self.tasks.track(complete_file_task(source, FileAction.DELETE, reconcile, self.notify))
        operation = Operation()
        def finished(outcome):
            def navigated(result):
                operation.finish(outcome if result.succeeded else Outcome(Status.FAILED, outcome.value, result.error, outcome.recoverable))
            navigation[0].on_finished(navigated)
        completed.on_finished(finished)
        return self.tasks.track(operation)

    def delete(self, video_id, context=None, *, delete_files=True):
        if not self.available():
            return Operation.cancelled()
        target = self.playback_target()
        if video_id == target.video_id:
            context = (target.context, target.location)
        if not delete_files:
            context = context or (target.context, target.location)
            return self._submit(video_id, context, delete_files=False)
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

    def _submit(self, video_id, context, *, delete_files=True):
        playing = video_id == self.playback_target().video_id
        self.mark_deleting({video_id}, True)
        self.notify(FileNotice(FileAction.DELETE))
        source = self.tasks.run(lambda: (self.submit if delete_files else self.forget)(video_id),
                                policy=FileTaskPolicy(release_media=playing))
        def reconcile(outcome):
            self.mark_deleting({video_id}, False)
            if outcome.succeeded:
                self.refresh_deleted({video_id})
                if not playing:
                    if not delete_files:
                        self.library.refresh_browsing()
                    self.save()
                else:
                    continued = self.continue_after_delete(*context)
                    if not delete_files:
                        continued.on_finished(lambda result: self.library.refresh_browsing())
            title = ('已移至回收站' if delete_files else '已删除软件记录') if outcome.succeeded else ''
            return FileNotice(FileAction.DELETE, outcome, receipt_title=title)
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
