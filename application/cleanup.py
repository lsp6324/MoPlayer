"""Throttle independent retirement work; it never owns the playback lifecycle."""
import time
from application.operations import Operation, Outcome, Status


class Cleanup:
    def __init__(self, dispatch, drain, *, available, pending, protected, clock=time.monotonic):
        self.dispatch, self.drain = dispatch, drain
        self.available, self.pending, self.protected, self.clock = available, pending, protected, clock
        self.active = None
        self.next_attempt = 0

    def request(self, *, force=False):
        if self.active is not None:
            return self.active
        if not self.available() or not self.pending() or (not force and self.clock()<self.next_attempt):
            return Operation.success(0)
        protected = tuple(self.protected())
        operation = self.active = Operation()
        self.next_attempt = self.clock()+5
        def completed(value,error):
            self.active = None
            operation.finish(Outcome(Status.FAILED if error else Status.SUCCEEDED,value=value,error=error))
        try:
            self.dispatch(lambda:self.drain(protected),completed)
        except Exception as error:
            completed(None,error)
        return operation
