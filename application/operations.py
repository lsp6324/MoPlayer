"""Explicit completion results for work delivered on the application thread."""
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Status(Enum):
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True)
class Outcome:
    status: Status
    value: object = None
    error: Exception | None = None
    recoverable: bool = False

    @property
    def succeeded(self):
        return self.status is Status.SUCCEEDED


class Operation:
    """One completion, observed by drafts and their dependent user actions.

    This is a GUI-thread completion contract, not a thread pool or event loop.
    The worker adapter must deliver finish() on the application thread.
    """
    def __init__(self):
        self.outcome: Outcome | None = None
        self._observers: list[Callable[[Outcome], None]] = []

    @property
    def pending(self):
        return self.outcome is None

    def on_finished(self, observer):
        if self.pending:
            self._observers.append(observer)
        else:
            observer(self.outcome)
        return self

    def finish(self, outcome):
        if not self.pending:
            raise RuntimeError('An operation can only finish once')
        self.outcome = outcome
        observers, self._observers = self._observers, []
        first_error = None
        for observer in observers:
            try:
                observer(outcome)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    @classmethod
    def completed(cls, outcome):
        operation = cls()
        operation.finish(outcome)
        return operation

    @classmethod
    def success(cls, value=None):
        return cls.completed(Outcome(Status.SUCCEEDED, value=value))

    @classmethod
    def cancelled(cls):
        return cls.completed(Outcome(Status.CANCELLED))


class UserActions:
    """Continue a user intent only after its draft has actually committed.

    While the same commit is pending, the latest selection wins. An explicit
    close request takes precedence over selection changes until it completes.
    """
    def __init__(self, before_action=lambda: Operation.success()):
        self.before_action = before_action
        self._waiting = None
        self._action = None
        self._closing = False
        self._commit = None

    def request(self, action, commit, *, closing=False):
        if self._closing and not closing:
            return self._waiting
        self._action, self._closing = action, closing
        if self._waiting is not None:
            return self._waiting
        self._commit = commit
        operation = self._prepare()
        self._waiting = operation
        operation.on_finished(self._finished)
        return operation

    def _prepare(self):
        barrier = self.before_action()
        return self._commit() if not barrier.pending and barrier.outcome.succeeded else barrier

    def _finished(self, outcome):
        if outcome.succeeded:
            # A caller may have changed its working draft while the submitted
            # snapshot was saving. Confirm that draft before executing an intent.
            remaining = self._prepare()
            if remaining.pending:
                self._waiting = remaining
                remaining.on_finished(self._finished)
                return
            outcome = remaining.outcome
        action = self._action
        self._waiting, self._action, self._closing, self._commit = None, None, False, None
        if outcome.succeeded and action is not None:
            action()
