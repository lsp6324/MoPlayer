"""Tag and archive completion rules; concrete services and UI are injected."""
import json
from copy import deepcopy
from moplayer.application.file_results import FileAction, FileNotice, complete_file_task
from moplayer.application.file_tasks import FileTaskPolicy
from moplayer.application.operations import Operation, Outcome, Status


class Classification:
    def __init__(self, tasks, repository, submit_tags, submit_archive, *,
                 available, ensure_storage, refresh, notify,
                 favorite_folders=lambda: False, submit_favorite=None,
                 archive_locations=lambda video_id: (), tags_renamed=lambda renames: None,
                 archive_enabled=lambda: True):
        self.archive_enabled = archive_enabled
        self.tags_renamed = tags_renamed
        self.archive_locations = archive_locations
        self.favorite_folders, self.submit_favorite = favorite_folders, submit_favorite
        self.tasks, self.repository = tasks, repository
        self.submit_tags, self.submit_archive = submit_tags, submit_archive
        self.available, self.ensure_storage = available, ensure_storage
        self.refresh, self.notify = refresh, notify

    def apply_tags(self, video_id, tags, schema, prompt_score=True, *, renames=None):
        tags, schema, renames = deepcopy(tags), deepcopy(schema), deepcopy(renames or {})
        if not self.available() or (self.archive_enabled() and not self.ensure_storage()) or not self.available():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        before = self._snapshot(video_id)
        schema_before = deepcopy(self.repository.tag_values(video_id).schema)
        score = video['score']
        self.notify(FileNotice(FileAction.TAGS))
        submit = (lambda: self.submit_tags(video_id, score, tags, schema, renames=renames)) if renames else (lambda: self.submit_tags(video_id, score, tags, schema))
        source = self.tasks.run(submit,
                                policy=FileTaskPolicy(release_media=False))
        def reconcile(outcome):
            if outcome.status is Status.CANCELLED:
                return FileNotice(FileAction.TAGS, outcome)
            if outcome.succeeded and renames:
                self.tags_renamed(renames)
            ids = tuple(outcome.value or (row['id'] for row in self.repository.videos('archived')))
            self.refresh(ids)
            return self._receipt(FileAction.TAGS, outcome, video_id, before, schema_before=schema_before, count=len(ids),
                                 score_video=video_id if outcome.succeeded and prompt_score else None)
        return self.tasks.track(complete_file_task(source, FileAction.TAGS, reconcile, self.notify))

    def archive(self, video_id, score, tags, *, favorite=None):
        tags = deepcopy(tags)
        if not self.archive_enabled():
            if not self.available() or self.repository.pending_tasks() or self.repository.video(video_id) is None:
                return Operation.cancelled()
            return self._save_metadata(video_id, FileAction.ARCHIVE,
                lambda: self.repository.set_classification(video_id, score, tags, favorite))
        if not self.available() or not self.ensure_storage() or not self.available():
            return Operation.cancelled()
        if self.repository.video(video_id) is None:
            return Operation.cancelled()
        before = self._snapshot(video_id)
        self.notify(FileNotice(FileAction.ARCHIVE))
        submit = (lambda: self.submit_archive(video_id, score, tags)) if favorite is None else (lambda: self.submit_favorite(video_id, score, tags, favorite))
        source = self.tasks.run(submit,
                                policy=FileTaskPolicy(release_media=False))
        def reconcile(outcome):
            if outcome.status is not Status.CANCELLED:
                self.refresh((video_id,))
            return self._receipt(FileAction.ARCHIVE, outcome, video_id, before)
        return self.tasks.track(complete_file_task(source, FileAction.ARCHIVE, reconcile, self.notify))

    def _snapshot(self, video_id):
        # This operation-local baseline never includes changing playback progress.
        return dict(self.repository.video(video_id)), frozenset(self.repository.media_directories(video_id))

    def _receipt(self, action, outcome, video_id, before, *, schema_before=None, **fields):
        title = detail = ''
        if outcome.succeeded:
            video = self.repository.video(video_id)
            if video is not None:
                previous, directories_before = before
                directories_after = frozenset(self.repository.media_directories(video_id))
                if directories_after != directories_before:
                    locations = tuple(self.archive_locations(video_id))
                    if locations:
                        title = '目录已更新' if previous['archived'] else '已归档'
                        detail = locations[0]
                        if len(locations) > 1:
                            detail += f'（共 {len(locations)} 个目录）'
                if not title:
                    tags_changed = set(json.loads(video['tags'])) != set(json.loads(previous['tags']))
                    schema_changed = (action is FileAction.TAGS and
                                      self.repository.tag_values(video_id).schema != schema_before)
                    if video['star'] != previous['star']:
                        title = '已收藏' if video['star'] else '已取消收藏'
                    elif video['score'] != previous['score']:
                        title = '评分已更新'
                    elif tags_changed or schema_changed or video['archived'] != previous['archived']:
                        title = '标签已保存'
                    if title:
                        detail = video['name']
        return FileNotice(action, outcome, receipt_title=title, receipt_detail=detail, **fields)

    def rating(self, video_id, score):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        if video['score'] == score:
            return Operation.success(video_id)
        if video['archived'] and self.archive_enabled():
            return self.archive(video_id, score, json.loads(video['tags']))
        return self._save_metadata(video_id, FileAction.SCORE,
                                   lambda: self.repository.set_score(video_id, score))

    def _save_metadata(self, video_id, action, write):
        before = None
        try:
            before = self._snapshot(video_id)
            write()
            self.refresh((video_id,))
        except Exception as error:
            outcome = Outcome(Status.FAILED, error=error)
        else:
            outcome = Outcome(Status.SUCCEEDED, value=video_id)
        return self.tasks.track(complete_file_task(Operation.completed(outcome), action,
                                lambda result: self._receipt(action, result, video_id, before), self.notify))

    def favorite(self, video_id, value):
        if not self.available() or self.repository.pending_tasks():
            return Operation.cancelled()
        video = self.repository.video(video_id)
        if video is None:
            return Operation.cancelled()
        value = int(bool(value))
        if video['star'] == value:
            return Operation.success(video_id)
        if video['archived'] and self.archive_enabled() and self.favorite_folders():
            return self.archive(video_id, video['score'], json.loads(video['tags']), favorite=value)
        return self._save_metadata(video_id, FileAction.FAVORITE,
                                   lambda: self.repository.set_favorite(video_id, value))
