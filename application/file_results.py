"""Results delivered after file workflows have reconciled application state."""
from dataclasses import dataclass
from enum import Enum
from application.operations import Operation, Outcome, Status


class FileAction(Enum):
    RENAME = 'rename'
    NAMES = 'names'
    FAVORITE = 'favorite'
    SCORE = 'score'
    SETTINGS = 'settings'
    TAGS = 'tags'
    ARCHIVE = 'archive'
    DELETE = 'delete'
    RECOVERY = 'recovery'
    NEXT = 'next'


@dataclass(frozen=True)
class PlaybackTarget:
    video_id: str | None
    context: object = None
    location: tuple | None = None


@dataclass(frozen=True)
class FileNotice:
    action: FileAction
    outcome: Outcome | None = None
    count: int = 0
    score_video: str | None = None
    continuing: bool = False
    receipt_title: str = ''
    receipt_detail: str = ''


def complete_file_task(source, action, reconcile, notify):
    """Publish completion only after reconciliation; dependent drafts wait here.

    A post-processing failure must not accidentally release a queued user action.
    Service failures retain their original recovery classification and value.
    """
    operation = Operation()
    def completed(outcome):
        try:
            notice = reconcile(outcome)
        except Exception as error:
            combined = error if outcome.error is None else RuntimeError(f'{outcome.error}\n更新应用状态失败：{error}')
            notice = FileNotice(action, Outcome(Status.FAILED, value=outcome.value,
                                               error=combined, recoverable=outcome.recoverable))
        try:
            notify(notice)
        except Exception as error:
            outcome = Outcome(Status.FAILED, value=notice.outcome.value, error=error,
                              recoverable=notice.outcome.recoverable)
        else:
            outcome = notice.outcome
        operation.finish(outcome)
    source.on_finished(completed)
    return operation
