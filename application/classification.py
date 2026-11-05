"""Tag and archive completion rules; concrete services and UI are injected."""
from copy import deepcopy
from application.file_results import FileAction, FileNotice, complete_file_task
from application.file_tasks import FileTaskPolicy
from application.operations import Operation, Status


class Classification:
    def __init__(self, tasks, repository, submit_tags, submit_archive, *,
                 available, ensure_storage, current_video, refresh, notify):
        self.tasks, self.repository = tasks, repository
        self.submit_tags, self.submit_archive = submit_tags, submit_archive
        self.available, self.ensure_storage = available, ensure_storage
        self.current_video, self.refresh, self.notify = current_video, refresh, notify

    def apply_tags(self, video_id, tags, schema, prompt_score=True):
        tags, schema = deepcopy(tags), deepcopy(schema)
        if not self.available() or not self.ensure_storage() or not self.available():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        score = video['score']
        self.notify(FileNotice(FileAction.TAGS))
        source = self.tasks.run(lambda: self.submit_tags(video_id, score, tags, schema))
        def reconcile(outcome):
            if outcome.status is Status.CANCELLED:
                return FileNotice(FileAction.TAGS, outcome)
            ids = tuple(outcome.value or (row['id'] for row in self.repository.videos('archived')))
            self.refresh(ids)
            return FileNotice(FileAction.TAGS, outcome, len(ids),
                              video_id if outcome.succeeded and prompt_score else None)
        return complete_file_task(source, FileAction.TAGS, reconcile, self.notify)

    def archive(self, video_id, score, tags):
        tags = deepcopy(tags)
        if not self.available() or not self.ensure_storage() or not self.available():
            return Operation.cancelled()
        self.notify(FileNotice(FileAction.ARCHIVE))
        source = self.tasks.run(lambda: self.submit_archive(video_id, score, tags),
                                policy=FileTaskPolicy(release_media=video_id == self.current_video()))
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh((video_id,))
            return FileNotice(FileAction.ARCHIVE, outcome)
        return complete_file_task(source, FileAction.ARCHIVE, reconcile, self.notify)
