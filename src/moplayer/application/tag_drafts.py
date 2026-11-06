"""Tag drafts survive views, cancellation and failed asynchronous submissions."""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol

from moplayer.core import validate_layout
from moplayer.application.operations import Operation, Outcome, Status


@dataclass(eq=True)
class TagValues:
    tags: list[str]
    schema: dict
    renames: dict = field(default_factory=dict)

    def copy(self):
        return deepcopy(self)


@dataclass
class TagDraft:
    video_id: str
    baseline: TagValues
    values: TagValues
    operation: Operation | None = None

    @property
    def dirty(self):
        return self.values != self.baseline


class TagRepository(Protocol):
    def tag_values(self, video_id: str) -> TagValues: ...


class TagDrafts:
    def __init__(self, repository: TagRepository, submit, current_video, can_edit):
        self.repository = repository
        self.submit = submit
        self.current_video = current_video
        self.can_edit = can_edit
        self._drafts: dict[str, TagDraft] = {}

    @property
    def saving(self):
        return any(draft.operation is not None for draft in self._drafts.values())

    @property
    def dirty_ids(self):
        return tuple(video_id for video_id, draft in self._drafts.items() if draft.dirty or draft.operation is not None)

    def open_current(self):
        return self.open_for(self.current_video())

    def open_for(self, video_id):
        if not video_id or not self.can_edit():
            return None
        draft = self._drafts.get(video_id)
        if draft is None or not draft.dirty and draft.operation is None:
            values = self.repository.tag_values(video_id)
            draft = TagDraft(video_id, values.copy(), values.copy())
            self._drafts[video_id] = draft
        return draft

    def discard(self, video_id):
        draft = self._drafts.get(video_id)
        if draft is not None and draft.operation is not None:
            raise RuntimeError('Cannot discard a tag draft while it is saving')
        self._drafts.pop(video_id, None)

    def update(self, video_id, values):
        if video_id in self._drafts:
            self._drafts[video_id].values = values.copy()

    def commit(self, video_id):
        draft = self._drafts.get(video_id)
        if draft is None:
            return Operation.success()
        if draft.operation is not None:
            return draft.operation
        if not draft.dirty:
            return Operation.success()
        if not self.can_edit():
            return Operation.cancelled()
        values = draft.values.copy()
        validate_layout(list(values.schema.values()))
        operation = draft.operation = Operation()

        def completed(outcome):
            draft.operation = None
            if outcome.succeeded:
                applied = values.renames
                draft.baseline = TagValues(values.tags, values.schema)
                current = draft.values
                current.renames = {
                    applied.get(source, source): current.renames.get(source, source)
                    for source in applied.keys() | current.renames.keys()
                    if current.renames.get(source, source) in current.schema
                    and current.renames.get(source, source) != applied.get(source, source)}
            operation.finish(outcome)

        try:
            submitted = self.submit(video_id, values)
        except Exception as error:
            completed(Outcome(Status.FAILED, error=error))
        else:
            submitted.on_finished(completed)
        return operation

    def discard_all(self):
        if self.saving:
            raise RuntimeError('Cannot discard a tag draft while it is saving')
        self._drafts.clear()

    def reconcile(self, video_ids):
        """A recovered durable task may have saved a previously failed draft."""
        for video_id in set(video_ids):
            draft = self._drafts.get(video_id)
            if draft is not None and draft.operation is None:
                draft.baseline = self.repository.tag_values(video_id).copy()
                if TagValues(draft.values.tags, draft.values.schema) == draft.baseline:
                    draft.values.renames.clear()
