"""Real filenames and the shared metadata heading on a private Windows desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    from PySide6.QtCore import QThreadPool, QPoint
    from PySide6.QtWidgets import QApplication
    from core import Store, Archiver, identity, scan
    from storage_settings import StorageSettings
    from app import Window,BUNDLE
    from theme import apply_theme
    output=Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    report=dict(desktop=require_private_desktop(),checks=[])
    ffmpeg=BUNDLE/'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
    fixture=output/'fixture.mp4'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
                    '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','30','-c:v','libx264',
                    '-threads','2','-c:a','aac','-y',str(fixture)],check=True,capture_output=True,
                   timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
    legacy=output/'旧归档'/'8分'/'教程'/'8分 教程 旧视频.mp4'
    legacy.parent.mkdir(parents=True)
    shutil.copyfile(fixture,legacy)
    store=Store(output/'data')
    old=store.register(legacy)
    store.execute('UPDATE videos SET archived=1,original_name=?,score=8,tags=?,star=1,position=2345 WHERE id=?',
                  ('旧视频.mp4','["教程"]',old))
    store.execute('INSERT INTO tags VALUES(?)',('教程',))
    StorageSettings(store.directory).save(output/'archive')
    entity=identity(legacy)
    pending_source=output/'pending source.mp4'
    shutil.copyfile(fixture,pending_source)
    pending_id=store.register(pending_source)
    def interrupted(stage):
        if stage=='prepared':
            raise OSError('simulate previous release interruption')
    try:
        Archiver(store,output/'old-task-root',fault=interrupted).submit(pending_id,9,['教程'])
    except OSError:
        pass
    job=store.query('SELECT * FROM jobs WHERE state<>"done"')[0]
    plan=json.loads(job['plan'])
    plan['name']='9分 教程 pending source.mp4'
    plan['targets']=[str(Path(target).with_name(plan['name'])) for target in plan['targets']]
    store.execute('UPDATE jobs SET plan=? WHERE id=?',(json.dumps(plan),job['id']))
    store.db.close()
    application=QApplication.instance() or QApplication([])
    window=Window(output/'data')
    window.resize(1200,800)
    window.show()
    errors=[]
    window.fail=errors.append
    def check(name,passed):
        report['checks'].append(dict(name=name,ok=bool(passed)))
        if not passed:
            raise AssertionError(name)
    def wait(predicate,seconds=20):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    try:
        check('升级启动自动恢复已记录的原名',wait(lambda:not window.busy and window.store.video(old)['name']=='旧视频.mp4'))
        check('旧未完成任务先重放再恢复原名',window.store.resolve(pending_id).name=='pending source.mp4'
              and window.store.resolve(pending_id).parent==output/'old-task-root'/'9分'/'教程'
              and not window.has_pending_file_tasks())
        check('恢复原名保留目录实体和非当前进度',window.store.resolve(old)==legacy.with_name('旧视频.mp4')
              and identity(window.store.resolve(old))==entity and window.store.video(old)['position']==2345)
        check('升级恢复不自动播放也不改归档根目录',window.current is None and window.storage.root==output/'archive')
        source=output/'source'
        source.mkdir()
        original=source/'示例 原名.mp4'
        shutil.copyfile(fixture,original)
        context,failures=scan(source,window.store,threading.Event())
        vid=context.folders[str(source)][1][0][0]
        window.start(context,(str(source),0))
        check('真实视频播放就绪',wait(lambda:window.player.get_time()>500))
        operation=window.classification.apply_tags(vid,['教程','Python'],
                  [dict(name=name,kind='major',parent=None) for name in ['教程','Python']],prompt_score=False)
        check('保存标签成功且保留原文件名',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.store.resolve(vid).name==original.name)
        window.set_rating(vid,7)
        check('评分只改变目录不改文件名',wait(lambda:not window.busy) and window.store.video(vid)['score']==7
              and window.store.resolve(vid).name==original.name and window.store.resolve(vid).parent.parent.name=='7分')
        window.favorite()
        header=window.player_view.header
        check('胶囊标签与文件名独立展示',header.filename==original.name and set(header.tags)=={'教程','Python'})
        check('第二行收藏文字与评分数据一致',header.starred and header.score==7 and '已收藏' in header.accessibleDescription())
        window.grab().save(str(output/'normal-light.png'))
        header.grab().save(str(output/'header-light.png'))
        geometry=window.player_view.surface.geometry()
        handle=window.player_view.video_handle()
        for score in (None,0,1,10):
            window.store.execute('UPDATE videos SET score=? WHERE id=?',(score,vid))
            window.refresh_title()
            check(f'{score}: 刷新元数据不改文件名或视频区域',header.score==score and header.filename==original.name
                  and window.player_view.surface.geometry()==geometry and window.player_view.video_handle()==handle)
        window.store.execute('UPDATE videos SET score=7 WHERE id=?',(vid,))
        window.refresh_title()
        apply_theme(window,'dark')
        header.grab().save(str(output/'header-dark.png'))
        check('深色主题保留标签收藏和半心分值',header.score==7 and header.starred and set(header.tags)=={'教程','Python'})
        apply_theme(window,'light')
        full=window.player_view.fullscreen
        full.enter()
        check('全屏进入保留同一视频宿主',wait(lambda:full.active) and window.player_view.video_handle()==handle)
        center=window.canvas.mapToGlobal(window.canvas.rect().center())
        full.poll(center)
        full.poll(center+QPoint(1,0))
        check('全屏标题共用完整元数据展示',full.title.header.filename==original.name
              and full.title.header.tags==header.tags and full.title.header.score==7 and full.title.header.starred)
        full.title.grab().save(str(output/'fullscreen-header.png'))
        window.store.execute('UPDATE videos SET star=0 WHERE id=?',(vid,))
        window.refresh_title()
        check('全屏收藏刷新不显示普通标题或缩小视频',not header.isVisible() and not full.title.header.starred
              and window.player_view.video_handle()==handle)
        full.exit()
        check('退出全屏恢复两行标题',wait(lambda:header.isVisible()) and header.height()==72 and not header.starred)
        check('全过程没有运行错误',not errors)
        report['success']=True
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
        window.grab().save(str(output/'failure.png'))
    finally:
        window.tag_drafts.discard_all()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        window.store.db.close()
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report.get('success') else 1


if __name__=='__main__':
    target=Path(sys.argv[1]).absolute()
    target.mkdir(parents=True,exist_ok=True)
    with (target/'console.txt').open('w',encoding='utf-8') as console:
        sys.stdout=sys.stderr=console
        sys.exit(run(target))
