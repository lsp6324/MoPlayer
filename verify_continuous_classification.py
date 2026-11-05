"""Real uninterrupted classification and deferred retirement on a private desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    from app import Window, BUNDLE
    from core import Store, Archiver, scan, identity, digest
    from application.archive_folders import ArchiveFolders
    output=Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    report=dict(desktop=require_private_desktop(),checks=[],events=[])
    ffmpeg=BUNDLE/'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
    samples=output/'samples'
    samples.mkdir()
    fixture=samples/'A.mp4'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
                    '-t','45','-c:v','libx264','-threads','2','-y',str(fixture)],check=True,capture_output=True,
                   timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    for name in ('B.mp4','C.mp4'):
        shutil.copyfile(fixture,samples/name)
    startup=output/'startup.mp4'
    shutil.copyfile(fixture,startup)
    store=Store(output/'data')
    startup_id=store.register(startup)
    Archiver(store,output/'startup-archive').submit(startup_id,5,[],defer_cleanup=True)
    store.db.close()
    application=QApplication.instance() or QApplication([])
    window=Window(output/'data')
    window.resize(1200,800)
    window.show()
    application.setActiveWindow(window)
    window.storage.save(output/'archive')
    window.archiver.root=window.storage.root
    errors=[]
    external_handle=None
    window.fail=lambda error:errors.append(str(error))
    gates=[]
    def wait(predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    def check(name,passed):
        report['checks'].append(dict(name=name,ok=bool(passed)))
        if not passed:
            raise AssertionError(name)
    def gate_at(stage):
        entered,released=threading.Event(),threading.Event()
        gates.append(released)
        def fault(state):
            if state==stage:
                entered.set()
                if not released.wait(15):
                    raise TimeoutError('verification gate timed out')
        return fault,entered,released
    def clean():
        assert wait(lambda:window.cleanup.active is None)
        operation=window.cleanup.request(force=True)
        assert wait(lambda:not operation.pending) and operation.outcome.succeeded
    manager=window.player.event_manager()
    kinds=(window.vlc.EventType.MediaPlayerStopped,window.vlc.EventType.MediaPlayerOpening,window.vlc.EventType.MediaPlayerMediaChanged)
    for kind in kinds:
        manager.event_attach(kind,lambda event:report['events'].append(str(event.type)))
    try:
        check('启动恢复清理队列且不自动播放',wait(lambda:not window.catalog.pending_tasks('cleanup_jobs'))
              and not startup.exists() and window.current is None)
        browsing=window.load_folder(str(samples))
        check('扫描三个样例',wait(lambda:not browsing.pending) and browsing.outcome.succeeded)
        context=window.library_controller.browsing
        vids=[entry[0] for entry in context.folders[str(samples)][1]]
        window.start(context,(str(samples),0))
        check('A真实播放',wait(lambda:window.player.get_time()>1000 and window.playback.resume is None))
        handle=window.player_view.video_handle()
        media=window.player.get_media().get_mrl()
        event_count=len(report['events'])
        position=window.player.get_time()
        fault,entered,released=gate_at('migrating')
        window.tag_migration.fault=fault
        operation=window.classification.apply_tags(vids[0],['教程'],[dict(name='教程',kind='major',parent=None)],prompt_score=False)
        check('保存标签时保留原媒体',wait(entered.is_set) and window.busy and not window.file_tasks.media_released
              and window.player.get_media().get_mrl()==media)
        check('保存期间视频和进度继续前进',wait(lambda:window.player.get_time()>position+600)
              and window.player_view.seekbar.isEnabled() and window.player_view.play_button.isEnabled())
        window.toggle()
        check('保存期间仍能暂停',wait(lambda:window.player.get_state()==window.vlc.State.Paused))
        before=window.player.get_time()
        window.seek(5000)
        check('保存期间暂停定位有效',wait(lambda:window.player.get_time()>=before+4500))
        paused=window.player.get_time()
        window.grab().save(str(output/'saving-live.png'))
        released.set()
        check('标签保存成功且暂停位置不变',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.player.get_state()==window.vlc.State.Paused and abs(window.player.get_time()-paused)<150)
        window.tag_migration.fault=None
        check('标签分类没有停止重新打开或切换媒体事件',len(report['events'])==event_count
              and window.player_view.video_handle()==handle and window.player.get_media().get_mrl()==media)
        check('当前原入口受保护而有效路径指向归档',fixture.exists() and window.catalog.resolve(vids[0])!=fixture
              and window.playback.protected_paths()==(str(fixture),))
        operation=window.classification.archive(vids[0],7,['教程'])
        check('评分保存成功且保持暂停和帧位置',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.player.get_state()==window.vlc.State.Paused and abs(window.player.get_time()-paused)<150)
        check('评分不触发媒体重载',len(report['events'])==event_count and window.catalog.video(vids[0])['score']==7)
        clean()
        check('当前原路径清理等待不阻塞再次评分',fixture.exists() and bool(window.catalog.pending_tasks('cleanup_jobs'))
              and not window.has_pending_file_tasks())
        fault,entered,released=gate_at('prepared')
        window.archiver.fault=fault
        operation=window.classification.archive(vids[0],8,['教程'])
        check('第二次评分进入后台文件阶段',wait(entered.is_set))
        window.start(context,(str(samples),1))
        window.start(context,(str(samples),2))
        check('保存期间选片等待提交结果',window.current==vids[0])
        released.set()
        check('评分完成后按最后一次选择播放C',wait(lambda:not operation.pending and window.current==vids[2]) and operation.outcome.succeeded)
        window.archiver.fault=None
        check('C真实解码就绪',wait(lambda:window.player.get_time()>500 and window.playback.resume is None))
        clean()
        check('离开A后清理旧入口且保留最新归档',not fixture.exists() and window.catalog.resolve(vids[0]).exists()
              and window.catalog.video(vids[0])['score']==8)
        window.archiver.folders=ArchiveFolders(tags=False,score=False)
        operation=window.classification.archive(vids[2],6,['教程'])
        check('所有目录依据关闭时初次归档成功',wait(lambda:not operation.pending) and operation.outcome.succeeded)
        events=len(report['events'])
        jobs=len(window.store.query('SELECT id FROM jobs'))
        operation=window.classification.archive(vids[2],9,[])
        check('目录不变时评分标签只更新元数据',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and len(window.store.query('SELECT id FROM jobs'))==jobs and len(report['events'])==events
              and window.catalog.video(vids[2])['score']==9 and window.catalog.video(vids[2])['tags']=='[]')
        # Exercise a real second volume when available, with a fresh disposable copy.
        cross_dir=Path(tempfile.mkdtemp(prefix='moplayer-continuous-'))
        cross=cross_dir/'跨卷.mp4'
        shutil.copyfile(samples/'B.mp4',cross)
        report['cross_volume_source']=str(cross)
        report['cross_volume_actual']=cross.stat().st_dev!=window.archiver.root.stat().st_dev
        cross_context,_=scan(cross_dir,window.store,threading.Event())
        cross_id=cross_context.folders[str(cross_dir)][1][0][0]
        window.start(cross_context,(str(cross_dir),0))
        check('跨卷样例播放就绪',wait(lambda:window.current==cross_id and window.player.get_time()>700))
        events=len(report['events'])
        entity=identity(cross)
        checksum=digest(cross)
        operation=window.classification.archive(cross_id,7,['教程'])
        check('跨卷复制校验期间不重载视频',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and len(report['events'])==events and window.player.get_time()>500)
        check('跨卷新入口内容相同并保留播放来源',digest(window.catalog.resolve(cross_id))==checksum and cross.exists()
              and (not report['cross_volume_actual'] or identity(window.catalog.resolve(cross_id))!=entity))
        clean()
        check('跨卷来源在播放期间受保护',cross.exists())
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        external_handle=kernel.CreateFileW(str(cross),0x80000000,1,None,3,0,None)
        if external_handle==ctypes.c_void_p(-1).value:
            external_handle=None
            raise ctypes.WinError(ctypes.get_last_error())
        window.clear_player()
        clean()
        check('真实外部占用使清理延后并保留错误记录',cross.exists()
              and any(row['error'] and row['path']==str(cross) for row in window.catalog.pending_tasks('cleanup_jobs')))
        operation=window.classification.archive(cross_id,9,[])
        check('外部占用的清理任务不阻止新评分',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.catalog.video(cross_id)['score']==9 and window.current is None)
        kernel.CloseHandle(external_handle)
        external_handle=None
        clean()
        check('释放媒体后跨卷旧来源自动清理',not cross.exists() and window.catalog.resolve(cross_id).exists())
        fault,entered,released=gate_at('prepared')
        window.archiver.fault=fault
        operation=window.classification.archive(vids[0],10,['教程'])
        check('关闭请求等待正在保存的分类',wait(entered.is_set) and window.isVisible())
        window.close()
        check('保存完成前窗口保持打开',window.isVisible() and operation.pending)
        released.set()
        check('保存成功后继续执行用户关闭请求',wait(lambda:not operation.pending and not window.isVisible()) and operation.outcome.succeeded)
        check('全过程没有应用错误',not errors)
        report['success']=True
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
        window.grab().save(str(output/'failure.png'))
    finally:
        if external_handle is not None:
            kernel.CloseHandle(external_handle)
        for gate in gates:
            gate.set()
        window.archiver.fault=window.tag_migration.fault=None
        wait(lambda:not window.busy)
        window.tag_drafts.discard_all()
        if window.isVisible():
            window.close()
        QThreadPool.globalInstance().waitForDone(10000)
        window.thumbnails.pool.waitForDone(10000)
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
