"""Archive settings UI and real-file workflows, restricted to a private desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication, QDialog
    from app import Window, BUNDLE
    from archive_settings_dialog import ArchiveSettingsDialog
    from application.archive_folders import ArchiveFolders
    from core import identity, scan
    from storage_settings import StorageSettings
    import threading

    output=Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    report={'desktop':require_private_desktop(),'checks':[]}
    application=QApplication.instance() or QApplication([])
    window=Window(output/'data')
    window.resize(1100,720)
    window.show()
    dialogs=[]
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
    def dialog():
        view=ArchiveSettingsDialog(window,root=window.storage.root,folders=window.storage.folders,
                                   error=window.storage.error,apply=window.archive_configuration.apply)
        dialogs.append(view)
        view.show()
        application.processEvents()
        return view
    def save(view):
        view.commit()
        view.reject()
        check('整理期间不能取消或关闭设置',view.pending and view.isVisible())
        check('设置保存完成',wait(lambda:not view.pending) and view.result()==QDialog.Accepted)
    try:
        window.fail=lambda text: (_ for _ in ()).throw(AssertionError(str(text)))
        initial=dialog()
        check('默认标签和评分勾选，收藏未勾选',initial.tags.isChecked() and initial.score.isChecked() and not initial.favorite.isChecked())
        initial.path.setText(str(output/'原归档'))
        save(initial)
        check('首次保存持久化旧兼容规则',StorageSettings(window.store.directory).folders==ArchiveFolders())

        ffmpeg=BUNDLE/'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
        source=output/'source'
        source.mkdir()
        fixture=output/'fixture.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=25',
                        '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','30','-c:v','libx264',
                        '-threads','2','-c:a','aac','-y',str(fixture)],check=True,capture_output=True,
                       timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
        ids=[]
        for name in ('收藏视频','普通视频','未归档视频'):
            path=source/(name+'.mp4')
            shutil.copyfile(fixture,path)
            ids.append(window.store.register(path))
        a,b,c=ids
        window.catalog.set_favorite(a,True)
        window.archiver.submit(a,8,['标签甲','标签乙'])
        window.archiver.submit(b,None,['标签甲'])
        entities={vid:identity(window.store.resolve(vid)) for vid in ids}
        window.store.progress(b,4321)
        window.library_controller.load_list('stars')
        window.library_controller.load_list('videos')
        context,errors=scan(window.archiver.root,window.store,threading.Event())
        folder,index=next((folder,index) for folder,(_,videos) in context.folders.items()
                          for index,(vid,_) in enumerate(videos) if vid==a)
        window.start(context,(folder,index))
        check('设置前真实视频播放',wait(lambda:window.player.get_time()>1200))
        bookmark=window.player.get_time()

        view=dialog()
        view.path.setText(str(output/'新归档'))
        view.favorite.setChecked(True)
        animation_end=time.monotonic()+.25
        wait(lambda:time.monotonic()>=animation_end)
        view.grab().save(str(output/'archive-settings.png'))
        check('目录预览按收藏评分标签排序',view.preview.text()=='目录示例：归档文件夹 / 已收藏 / 8分 / 标签 / 视频文件')
        check('设置选项按收藏评分标签排列',view.favorite.x() < view.score.x() < view.tags.x())
        save(view)
        root=window.storage.root
        check('收藏视频按收藏评分和多标签建立入口',
              {Path(row['path']).parent.relative_to(root).parts for row in window.store.query('SELECT * FROM paths WHERE id=?',(a,))}
              =={('已收藏','8分','标签甲'),('已收藏','8分','标签乙')})
        check('未评分未收藏视频使用独立层级',window.store.resolve(b).parent==root/'未收藏'/'未评分'/'标签甲')
        check('未归档视频留在原位置',window.store.resolve(c)==source/'未归档视频.mp4')
        check('全库整理保留身份和未播放视频进度',all(identity(window.store.resolve(vid))==entities[vid] for vid in ids) and window.store.video(b)['position']==4321)
        check('全库整理恢复当前播放视频与进度',window.current==a and wait(lambda:window.playback.resume is None and window.player.get_time()>=bookmark-250))
        check('全库整理保留播放顺序上下文',window.context is context and window.location==(folder,index))

        # The sidebar path uses the same workflow as the player's favorite button.
        window.remove_library_favorite(a)
        check('取消收藏启动文件任务',window.busy)
        check('取消收藏完成并同步目录',wait(lambda:not window.busy) and window.store.video(a)['star']==0
              and window.store.resolve(a).relative_to(root).parts[0]=='未收藏')
        check('收藏列表移除同一稳定ID',a not in {row['id'] for row in window.library_controller.list_rows('stars')})
        window.favorite()
        check('再次收藏完成并同步目录',wait(lambda:not window.busy) and window.store.video(a)['star']==1
              and window.store.resolve(a).relative_to(root).parts[0]=='已收藏')
        check('收藏列表恢复同一稳定ID',a in {row['id'] for row in window.library_controller.list_rows('stars')})

        cancelled=dialog()
        cancelled.tags.setChecked(False)
        cancelled.score.setChecked(False)
        cancelled.favorite.setChecked(False)
        check('全不勾选的预览直接使用根目录',cancelled.preview.text()=='目录示例：归档文件夹 / 视频文件')
        cancelled.reject()
        check('取消设置不改变有效分类规则',window.storage.folders==ArchiveFolders(True,True,True))
        flat=dialog()
        flat.tags.setChecked(False)
        flat.score.setChecked(False)
        flat.favorite.setChecked(False)
        save(flat)
        check('全部取消后已归档视频直接位于根目录',all(window.store.resolve(vid).parent==root for vid in (a,b)))
        check('合并多标签入口不复制或丢失视频',len(window.store.query('SELECT * FROM paths WHERE id=?',(a,)))==1 and identity(window.store.resolve(a))==entities[a])
        window.set_rating(a,6)
        check('关闭评分分类后评分仍有效且不增加目录',wait(lambda:not window.busy)
              and window.store.video(a)['score']==6 and window.store.resolve(a).parent==root
              and window.store.resolve(a).name=='收藏视频.mp4')
        check('关闭标签分类后原标签仍保留',set(json.loads(window.store.video(a)['tags']))=={'标签甲','标签乙'})
        old=window.store.resolve(a)
        window.favorite(toggle=True)
        check('关闭收藏分类后只更新标记',not window.busy and window.store.video(a)['star']==0 and window.store.resolve(a)==old)
        check('设置重开恢复三个未勾选项',StorageSettings(window.store.directory).folders==ArchiveFolders(False,False,False))
        window.classification.favorite(c,True)
        window.set_rating(c,3)
        check('未归档视频的评分收藏仍有效且不自动归档',not window.busy and window.store.video(c)['star']==1
              and window.store.video(c)['score']==3 and window.store.resolve(c)==source/'未归档视频.mp4')
        invalid=dialog()
        invalid.path.setText('relative-folder')
        invalid.commit()
        check('无效路径就地显示错误且保留旧设置',wait(lambda:not invalid.pending)
              and invalid.result()!=QDialog.Accepted and '完整' in invalid.status.text()
              and window.storage.root==root)
        invalid.reject()
        failed=dialog()
        failed.score.setChecked(True)
        failed.favorite.setChecked(True)
        def interrupted(state):
            if state=='migrating':
                raise OSError('隔离检查：整理中断')
        window.archive_configuration_service.fault=interrupted
        failed.commit()
        check('整理中断保留恢复入口且未确认新设置',wait(lambda:not failed.pending)
              and failed.result()!=QDialog.Accepted and '文件任务' in failed.status.text()
              and window.has_pending_file_tasks() and window.storage.folders==ArchiveFolders(False,False,False))
        check('文件任务列表包含中断的归档设置批次',any(row['kind']=='archive_setting_jobs'
              and row['state']!='done' for row in window.catalog.task_history()))
        failed.grab().save(str(output/'archive-settings-interrupted.png'))
        failed.reject()
        window.archive_configuration_service.fault=None
        recovery=window.recovery.retry()
        check('文件任务恢复继续原设置整理',wait(lambda:not recovery.pending) and recovery.outcome.succeeded
              and not window.has_pending_file_tasks() and window.storage.folders==ArchiveFolders(False,True,True))
        check('恢复后所有已归档视频匹配新目录',window.store.resolve(a).parent==root/'未收藏'/'6分'
              and window.store.resolve(b).parent==root/'未收藏'/'未评分')
        report['success']=True
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
        window.grab().save(str(output/'failure.png'))
    finally:
        for view in dialogs:
            view.reject()
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
