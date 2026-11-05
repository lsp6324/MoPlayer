"""Tag and archive completion rules; concrete services and UI are injected."""
import json
from copy import deepcopy
from application.file_results import FileAction, FileNotice, complete_file_task
from application.file_tasks import FileTaskPolicy
from application.operations import Operation, Outcome, Status


class Classification:
    def __init__(self, tasks, repository, submit_tags, submit_archive, *,
                 available, ensure_storage, refresh, notify,
                 favorite_folders=lambda: False, submit_favorite=None):
        self.favorite_folders, self.submit_favorite = favorite_folders, submit_favorite
        self.tasks, self.repository = tasks, repository
        self.submit_tags, self.submit_archive = submit_tags, submit_archive
        self.available, self.ensure_storage = available, ensure_storage
        self.refresh, self.notify = refresh, notify

    def apply_tags(self, video_id, tags, schema, prompt_score=True):
        tags, schema = deepcopy(tags), deepcopy(schema)
        if not self.available() or not self.ensure_storage() or not self.available():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        score = video['score']
        self.notify(FileNotice(FileAction.TAGS))
        source = self.tasks.run(lambda: self.submit_tags(video_id, score, tags, schema),
                                policy=FileTaskPolicy(release_media=False))
        def reconcile(outcome):
            if outcome.status is Status.CANCELLED:
                return FileNotice(FileAction.TAGS, outcome)
            ids = tuple(outcome.value or (row['id'] for row in self.repository.videos('archived')))
            self.refresh(ids)
            return FileNotice(FileAction.TAGS, outcome, len(ids),
                              video_id if outcome.succeeded and prompt_score else None)
        return self.tasks.track(complete_file_task(source, FileAction.TAGS, reconcile, self.notify))

    def archive(self, video_id, score, tags, *, favorite=None):
        tags = deepcopy(tags)
        if not self.available() or not self.ensure_storage() or not self.available():
            return Operation.cancelled()
        self.notify(FileNotice(FileAction.ARCHIVE))
        submit = (lambda: self.submit_archive(video_id, score, tags)) if favorite is None else (lambda: self.submit_favorite(video_id, score, tags, favorite))
        source = self.tasks.run(submit,
                                policy=FileTaskPolicy(release_media=False))
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh((video_id,))
            return FileNotice(FileAction.ARCHIVE, outcome)
        return self.tasks.track(complete_file_task(source, FileAction.ARCHIVE, reconcile, self.notify))

    def favorite(self, video_id, value):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        value = int(bool(value))
        if video['star'] == value:
            return Operation.success(video_id)
        if video['archived'] and self.favorite_folders():
            return self.archive(video_id, video['score'], json.loads(video['tags']), favorite=value)
        try:
            self.repository.set_favorite(video_id, value)
            self.refresh((video_id,))
        except Exception as error:
            outcome = Outcome(Status.FAILED, error=error)
            self.notify(FileNotice(FileAction.FAVORITE, outcome))
            return Operation.completed(outcome)
        return Operation.success(video_id)
