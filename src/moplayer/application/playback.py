"""Playback intent and persistence rules, independent of VLC and Qt."""
from dataclasses import dataclass
from enum import Enum
import time


class PlaybackStatus(Enum):
    IDLE = 'idle'
    LOADING = 'loading'
    PLAYING = 'playing'
    PAUSED = 'paused'
    ENDED = 'ended'
    ERROR = 'error'


@dataclass(frozen=True)
class ResumeTarget:
    position: int
    paused: bool


@dataclass(frozen=True)
class PendingSeek:
    position: int
    deadline: float


@dataclass(frozen=True)
class RestoreCommands:
    position: int
    pause: bool


class PlaybackSession:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.resume: ResumeTarget | None = None
        self.pending_seek: PendingSeek | None = None
        self.terminal_handled = False
        self.completed = False
        self.last_save = 0
        self._restore_requested = False
        self.source = None

    def begin(self, position, paused, *, source=None):
        self.source = source
        self.resume = ResumeTarget(max(0, position), paused)
        self.pending_seek = None
        self.terminal_handled = self.completed = self._restore_requested = False

    def clear(self):
        self.release_source()
        self.resume = self.pending_seek = None
        self.terminal_handled = True
        self.completed = self._restore_requested = False

    def release_source(self):
        self.source = None

    def protected_paths(self):
        return (self.source,) if self.source is not None else ()

    def paused_intent(self, backend_paused):
        return self.resume.paused if self.resume is not None else backend_paused

    def save_due(self):
        return self.clock() - self.last_save > 5

    def saved(self):
        self.last_save = self.clock()

    def restore(self, *, playing, paused, duration):
        if self.resume is None:
            return None
        if paused and self.resume.paused and self._restore_requested:
            self.resume = None
        elif playing and duration > 0 and not self._restore_requested:
            commands = RestoreCommands(min(self.resume.position, max(0, duration - 1)), self.resume.paused)
            self._restore_requested = True
            if not self.resume.paused:
                self.resume = None
            return commands
        return None

    def seek(self, target, duration):
        target = min(max(0, int(target)), max(0, duration))
        self.pending_seek = PendingSeek(target, self.clock() + 2)
        return target

    def relative_seek(self, reported_position, offset, duration):
        pending = self.pending_seek
        before = pending.position if pending and self.clock() <= pending.deadline else reported_position
        before = min(max(0, before), duration)
        return before, min(max(0, before + offset), duration)

    def acknowledge(self, position):
        pending = self.pending_seek
        if pending and (abs(position - pending.position) < 1000 or self.clock() > pending.deadline):
            self.pending_seek = None

    def terminal(self, *, ended, failed):
        if self.terminal_handled or not (ended or failed):
            return False
        self.terminal_handled = True
        self.completed = ended
        return True

    def position_to_save(self, reported_position, *, ended):
        if self.resume is not None:
            return None
        if ended or self.completed:
            return 0
        return reported_position if reported_position >= 0 else None
