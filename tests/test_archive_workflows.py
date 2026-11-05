"""Portable application protocols for archive settings and favorite changes."""
from types import SimpleNamespace

from application.archive_configuration import ArchiveConfiguration
from application.archive_folders import ArchiveFolders
from application.classification import Classification
from application.file_tasks import FileTasks
from application.operations import Status


def setup():
    queue, events = [], []
    rows = {'a':dict(id='a',score=8,tags='["tag"]',star=0,archived=1),
            'b':dict(id='b',score=None,tags='[]',star=0,archived=0)}
    pending=[]
    repo=SimpleNamespace(video=rows.get, videos=lambda mode:[row for row in rows.values() if row['archived']],
                         pending_tasks=lambda:pending,
                         set_favorite=lambda vid,value: rows[vid].update(star=value))
    tasks=FileTasks(lambda work,done:queue.append((work,done)),lambda policy:events.append('begin'),
                    lambda bookmark:events.append('end'),lambda:bool(pending))
    def finish():
        work,done=queue.pop(0)
        try:
            result=work()
        except Exception as error:
            done(None,error)
        else:
            done(result,None)
    return repo,tasks,finish,events,pending


def test_configuration_refreshes_before_completion_and_preserves_failed_state():
    repo,tasks,finish,events,pending=setup()
    def submit(root,folders):
        events.append((root,folders))
        pending.append('durable batch')
        raise OSError('partial migration')
    workflow=ArchiveConfiguration(tasks,repo,submit,available=lambda:True,
                                  refresh=lambda ids:events.append(('refresh',ids)))
    policy=ArchiveFolders(False,True,True)
    result=workflow.apply('new-root',policy)
    result.on_finished(lambda outcome:events.append('finished'))
    assert result.pending
    finish()
    assert result.outcome.status is Status.FAILED and result.outcome.recoverable
    assert events.index(('refresh',('a',)))<events.index('finished')
    assert ('new-root',policy) in events
    assert workflow.apply('another',ArchiveFolders()).outcome.status is Status.CANCELLED


def classification(repo,tasks,events,folders=True,submit=None):
    return Classification(tasks,repo,lambda *args:None,lambda *args:None,
        available=lambda:True,ensure_storage=lambda:True,current_video=lambda:'a',
        refresh=lambda ids:events.append(('refresh',tuple(ids))),notify=events.append,
        favorite_folders=lambda:folders,submit_favorite=submit)


def test_favorite_folder_change_uses_task_and_does_not_commit_metadata_early():
    repo,tasks,finish,events,_=setup()
    def submit(vid,score,tags,value):
        events.append(('archive-favorite',vid,score,tags,value))
        repo.set_favorite(vid,value)
    result=classification(repo,tasks,events,submit=submit).favorite('a',True)
    assert result.pending and repo.video('a')['star']==0
    finish()
    assert result.outcome.succeeded and repo.video('a')['star']==1
    assert ('archive-favorite','a',8,['tag'],1) in events


def test_failed_favorite_archive_does_not_claim_success_or_set_flag():
    repo,tasks,finish,events,pending=setup()
    def submit(*args):
        pending.append('job')
        raise OSError('file locked')
    result=classification(repo,tasks,events,submit=submit).favorite('a',True)
    finish()
    assert result.outcome.status is Status.FAILED and result.outcome.recoverable
    assert repo.video('a')['star']==0


def test_unarchived_or_disabled_favorite_classification_is_metadata_only():
    repo,tasks,_,events,_=setup()
    assert classification(repo,tasks,events).favorite('b',True).outcome.succeeded
    assert classification(repo,tasks,events,folders=False).favorite('a',True).outcome.succeeded
    assert repo.video('a')['star']==repo.video('b')['star']==1
    assert 'begin' not in events


def test_pending_batch_blocks_favorite_metadata_changes():
    repo,tasks,_,events,pending=setup()
    pending.append('configuration migration')
    result=classification(repo,tasks,events,folders=False).favorite('a',True)
    assert result.outcome.status is Status.CANCELLED
    assert repo.video('a')['star']==0


def test_startup_original_name_restore_uses_file_task_and_refreshes_actual_rows():
    repo,tasks,finish,events,_=setup()
    repo.video('a').update(name='8分 tag movie.mp4',original_name='movie.mp4')
    def restore():
        repo.video('a')['name']='movie.mp4'
        return ['a']
    workflow=ArchiveConfiguration(tasks,repo,lambda *args:None,available=lambda:True,
                                  refresh=lambda ids:events.append(('refresh',ids)),restore_names=restore)
    result=workflow.restore_original_names()
    assert result.pending
    finish()
    assert result.outcome.succeeded and ('refresh',('a',)) in events
    assert workflow.restore_original_names().outcome.succeeded
