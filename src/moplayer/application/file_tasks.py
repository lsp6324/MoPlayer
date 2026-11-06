"""One admission/completion lifecycle for recoverable file operations."""
from dataclasses import dataclass

from moplayer.application.operations import Operation, Outcome, Status


@dataclass(frozen=True)
class FileTaskPolicy:
    release_media: bool = True
    cancel_navigation: bool = True


class FileTasks:
    def __init__(self, dispatch, begin, end, has_pending, prepare=lambda: None):
        self.dispatch, self.begin, self.end = dispatch, begin, end
        self.has_pending = has_pending
        self.prepare = prepare
        self.active: Operation | None = None
        self.policy = None
        self.completion = None

    def track(self, operation):
        """Navigation waits for the workflow's reconciled result, not just I/O."""
        if not operation.pending:
            return operation
        self.completion = operation
        def settled(outcome):
            if self.completion is operation:
                self.completion = None
        operation.on_finished(settled)
        return operation

    @property
    def media_released(self):
        return bool(self.active is not None and self.policy.release_media)

    def run(self, work, *, policy=FileTaskPolicy()):
        if self.active is not None:
            return Operation.cancelled()
        operation = self.active = Operation()
        self.track(operation)
        self.policy = policy
        try:
            bookmark = self.begin(policy)
        except Exception as error:
            self.active = None
            self.policy = None
            operation.finish(Outcome(Status.FAILED, error=error))
            return operation

        def completed(value, error):
            try:
                self.end(bookmark)
            except Exception as restore_error:
                error = restore_error if error is None else RuntimeError(f'{error}\n恢复播放失败：{restore_error}')
            self.active = None
            self.policy = None
            operation.finish(Outcome(Status.FAILED if error else Status.SUCCEEDED,
                                     value=value, error=error,
                                     recoverable=bool(error and self.has_pending())))

        try:
            def prepared_work():
                self.prepare()
                return work()
            self.dispatch(prepared_work, completed)
        except Exception as error:
            if operation.pending:
                completed(None, error)
            else:
                raise
        return operation
