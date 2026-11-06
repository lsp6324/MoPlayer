from moplayer.application.cleanup import Cleanup
from moplayer.application.operations import Status


def test_retirement_has_its_own_throttled_lifecycle_and_frozen_protected_paths():
    queue,seen=[],[]
    clock=[0]
    protected=['first.mp4']
    workflow=Cleanup(lambda work,done:queue.append((work,done)),lambda paths:seen.append(paths) or 1,
                     available=lambda:True,pending=lambda:True,protected=lambda:protected,clock=lambda:clock[0])
    first=workflow.request()
    assert workflow.request(force=True) is first and len(queue)==1
    protected[:]=['next.mp4']
    work,done=queue.pop()
    done(work(),None)
    assert first.outcome.succeeded and seen==[('first.mp4',)] and workflow.active is None
    assert not workflow.request().pending and not queue
    clock[0]=5
    next_operation=workflow.request()
    assert next_operation.pending and len(queue)==1


def test_retirement_failure_does_not_hold_admission_and_force_can_retry():
    queue=[]
    workflow=Cleanup(lambda work,done:queue.append((work,done)),lambda paths:0,
                     available=lambda:True,pending=lambda:True,protected=lambda:())
    operation=workflow.request()
    _,done=queue.pop()
    done(None,OSError('database unavailable'))
    assert operation.outcome.status is Status.FAILED and workflow.active is None
    assert workflow.request(force=True).pending
