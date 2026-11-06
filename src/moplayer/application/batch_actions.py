"""Frozen media groups, serial classification and explicit partial results."""
from dataclasses import dataclass
from moplayer.application.operations import Operation, Outcome, Status
from moplayer.application.tag_labels import tag_path


@dataclass(frozen=True)
class BatchReport:
    targets: tuple
    completed: tuple
    failed_id: str | None = None

    @property
    def remaining(self):
        done = set(self.completed)
        return tuple(video_id for video_id in self.targets if video_id not in done)


class BatchActions:
    def __init__(self, repository, drafts, classification, deletion, *, schedule, activity_changed=lambda: None):
        self.repository, self.drafts = repository, drafts
        self.classification, self.deletion = classification, deletion
        self.schedule = schedule
        self.activity_changed = activity_changed
        self.active = None
        self.cancel_requested = False

    def cancel(self):
        if self.active is not None:
            self.cancel_requested = True

    def favorite(self, items, value, *, progress=lambda done, total: None):
        return self._run(items, lambda vid: self.classification.favorite(vid, value), progress)

    def rating(self, items, value, *, progress=lambda done, total: None):
        return self._run(items, lambda vid: self.classification.rating(vid, value), progress)

    def tags(self, items, names, mode, *, progress=lambda done, total: None):
        names = frozenset(names)
        if mode not in ('add', 'remove'):
            raise ValueError('无效批量标签操作。')
        def apply(video_id):
            values = self.repository.tag_values(video_id)
            if not names <= values.schema.keys():
                raise ValueError('所选标签已更改，请重新打开标签面板。')
            chosen = set(values.tags)
            if mode == 'add':
                chosen.update(names)
                parents = {parent for name in chosen for parent in tag_path(name, values.schema)[:-1]}
                chosen.difference_update(parents)
            else:
                chosen = {name for name in chosen if not names.intersection(tag_path(name, values.schema))}
            if chosen == set(values.tags):
                return Operation.success(video_id)
            return self.classification.apply_tags(video_id, sorted(chosen), list(values.schema.values()), prompt_score=False)
        return self._run(items, apply, progress, tags_changed=True)

    def _run(self, items, command, progress, *, tags_changed=False):
        ids = tuple(dict.fromkeys(item.video_id for item in items))
        if self.active is not None:
            return Operation.cancelled()
        operation = self.active = Operation()
        self.cancel_requested = False
        self.activity_changed()
        completed = []
        # Preserve older failed/editor drafts before modifying any selected file.
        steps = [(vid, False) for vid in ids] + [(vid, True) for vid in ids]
        index = 0
        def finish(status, error=None, failed_id=None, recoverable=False):
            self.active = None
            self.activity_changed()
            operation.finish(Outcome(status, BatchReport(ids, tuple(completed), failed_id), error, recoverable))
        def settled(outcome, video_id, applying):
            nonlocal index
            if not outcome.succeeded:
                finish(outcome.status, outcome.error, video_id, outcome.recoverable)
                return False
            if applying:
                completed.append(video_id)
                if tags_changed:
                    self.drafts.discard(video_id)
                progress(len(completed), len(ids))
            index += 1
            return True
        def pump():
            for _ in range(16):
                if index == len(steps):
                    finish(Status.SUCCEEDED)
                    return
                if self.cancel_requested:
                    finish(Status.CANCELLED)
                    return
                video_id, applying = steps[index]
                try:
                    if self.repository.video(video_id) is None:
                        raise FileNotFoundError('所选文件的软件记录已不存在。')
                    source = command(video_id) if applying else self.drafts.commit(video_id)
                except Exception as error:
                    finish(Status.FAILED, error, video_id)
                    return
                if source.pending:
                    def ready(outcome, video_id=video_id, applying=applying):
                        if settled(outcome, video_id, applying):
                            self.schedule(pump)
                    source.on_finished(ready)
                    return
                if not settled(source.outcome, video_id, applying):
                    return
            self.schedule(pump)
        progress(0, len(ids))
        self.schedule(pump)
        return operation

    def delete(self, items, *, delete_files=False, progress=lambda done, total: None):
        if self.active is not None:
            return Operation.cancelled()
        operation = self.active = Operation()
        self.cancel_requested = False
        self.activity_changed()
        ids = tuple(dict.fromkeys(item.video_id for item in items))
        try:
            source = self.deletion.delete_many(ids, delete_files=delete_files, cancelled=lambda: self.cancel_requested)
        except Exception as error:
            source = Operation.completed(Outcome(Status.FAILED, error=error))
        def completed(outcome):
            done = tuple(outcome.value or ())
            progress(len(done), len(ids))
            report = BatchReport(ids, done, next((vid for vid in ids if vid not in done), None))
            self.active = None
            self.activity_changed()
            operation.finish(Outcome(outcome.status, report, outcome.error, outcome.recoverable))
        source.on_finished(completed)
        return operation
