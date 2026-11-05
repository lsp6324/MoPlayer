"""Inline filename editing and real file tasks on an isolated Windows desktop."""
import json
from pathlib import Path
import shutil
import sys
import threading
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    from PySide6.QtCore import Qt, QThreadPool, QPoint, QEvent
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from core import Store, identity, scan
    from infrastructure.file_renaming import FileRenaming
    from app import Window
    from theme import apply_theme
    output = Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    report = dict(desktop=require_private_desktop(),checks=[])
    # Generate a silent video; never read the user's library or media.
    import subprocess
    from app import BUNDLE
    ffmpeg = BUNDLE/'ffmpeg.exe'
    if not ffmpeg.exists():
        import imageio_ffmpeg
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    fixture = output/'fixture.mp4'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
                    '-t','30','-c:v','libx264','-threads','2','-y',str(fixture)],check=True,capture_output=True,
                   timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
    pending = output/'pending.mp4'
    shutil.copyfile(fixture,pending)
    store = Store(output/'data')
    pending_id = store.register(pending)
    def interrupted(state):
        if state == 'renamed-0':
            raise OSError('simulated interrupted rename')
    try:
        FileRenaming(store,interrupted).submit(pending_id,'已恢复.mp4')
    except OSError:
        pass
    store.db.close()
    application = QApplication.instance() or QApplication([])
    window = Window(output/'data')
    window.resize(1200,800)
    window.show()
    application.setActiveWindow(window)
    errors=[]
    window.fail=errors.append
    def check(name, passed):
        report['checks'].append(dict(name=name,ok=bool(passed)))
        if not passed:
            raise AssertionError(name)
    def wait(predicate, seconds=20):
        deadline = time.monotonic()+seconds
        while time.monotonic()<deadline:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    try:
        check('启动恢复中断的重命名且不自动播放',wait(lambda:not window.busy and not window.has_pending_file_tasks())
              and window.store.resolve(pending_id).name=='已恢复.mp4' and window.current is None)
        source=output/'source'
        source.mkdir()
        original=source/'原始 名称.mp4'
        shutil.copyfile(fixture,original)
        context,_=scan(source,window.store,threading.Event())
        vid=context.folders[str(source)][1][0][0]
        window.store.execute('UPDATE videos SET score=7,star=1,tags=? WHERE id=?',('["教程"]',vid))
        window.start(context,(str(source),0))
        check('无归档设置也可播放和改名',wait(lambda:window.player.get_time()>500) and window.storage.root is None)
        header=window.player_view.header
        handle=window.player_view.video_handle()
        geometry=window.player_view.surface.geometry()
        point=QPoint(header.width()-65,20)
        application.sendEvent(header,QEnterEvent(point,point,header.mapToGlobal(point)))
        application.processEvents()
        check('标题悬停出现铅笔且不移动视频',header.edit_button.isVisible() and window.player_view.surface.geometry()==geometry)
        QTest.mouseClick(header.edit_button,Qt.LeftButton)
        check('原位输入选中不含扩展名的部分',header.editor.isVisible() and header.editor.selectedText()=='原始 名称'
              and header.editor.hasFocus() and header.editor.x()>16)
        window.grab().save(str(output/'inline-light.png'))
        QTest.keyClicks(header.editor,'draft A D X Z Q R W ')
        QTest.keyClick(header.editor,Qt.Key_Left)
        check('输入快捷键字符不换片评分或全屏',window.current==vid and window.store.video(vid)['score']==7
              and window.store.video(vid)['star']==1 and not window.player_view.fullscreen.active)
        QTest.keyClick(header.editor,Qt.Key_Escape)
        check('Esc取消没有修改磁盘',not header.editor.isVisible() and original.exists())
        header.begin_edit()
        header.editor.setText('放弃.mp4')
        window.player_view.play_button.setFocus()
        application.processEvents()
        check('点击其他位置取消未提交输入',not header.editor.isVisible() and window.store.video(vid)['name']==original.name)
        media_releases=[]
        begin=window.file_tasks.begin
        def begin_task(policy):
            media_releases.append(policy.release_media)
            return begin(policy)
        window.file_tasks.begin=begin_task
        header.begin_edit()
        header.editor.setText('坏?.mp4')
        QTest.keyClick(header.editor,Qt.Key_Return)
        check('非法名称保留输入并就地提示',wait(lambda:not window.busy and not header.editor.isReadOnly())
              and header.editor.isVisible() and header.editor.text()=='坏?.mp4' and header.error_label.isVisible())
        collision=source/'已存在.mp4'
        collision.write_bytes(b'other file')
        header.editor.setText(collision.name)
        QTest.keyClick(header.editor,Qt.Key_Return)
        check('重名不覆盖并保留输入',wait(lambda:not window.busy and not header.editor.isReadOnly())
              and header.editor.text()==collision.name and collision.read_bytes()==b'other file')
        check('无效和重名输入不会释放或重载视频',not media_releases)
        window.grab().save(str(output/'inline-error.png'))
        before=identity(original)
        header.editor.setText('新 名称.mp4')
        QTest.keyClick(header.editor,Qt.Key_Return)
        check('Enter保存成功并退出编辑',wait(lambda:not window.busy and not header.editor.isVisible())
              and window.store.video(vid)['name']=='新 名称.mp4' and not window.player_view.fullscreen.active)
        check('改名保留文件实体目录和未归档状态',identity(window.store.resolve(vid))==before
              and window.store.resolve(vid).parent==source and not window.store.video(vid)['archived'] and not original.exists())
        check('播放恢复且标题布局宿主稳定',wait(lambda:window.player.get_time()>500)
              and window.player_view.video_handle()==handle and window.player_view.surface.geometry()==geometry
              and header.starred and header.score==7 and header.tags==('教程',))
        window.grab().save(str(output/'renamed-light.png'))
        window.storage.save(output/'archive')
        window.archiver.root=window.storage.root
        operation=window.classification.archive(vid,7,['教程','Python'])
        check('改名后的归档沿用新原名',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.store.resolve(vid).name=='新 名称.mp4')
        parents={Path(row['path']).parent for row in window.store.query('SELECT * FROM paths WHERE id=?',(vid,))}
        header.begin_edit()
        header.editor.setText('归档后改名.mp4')
        QTest.keyClick(header.editor,Qt.Key_Return)
        check('归档多入口同时改名并保持目录',wait(lambda:not window.busy and not header.editor.isVisible())
              and all(Path(row['path']).name=='归档后改名.mp4' and Path(row['path']).exists() for row in window.store.query('SELECT * FROM paths WHERE id=?',(vid,)))
              and {Path(row['path']).parent for row in window.store.query('SELECT * FROM paths WHERE id=?',(vid,))}==parents)
        operation=window.classification.archive(vid,8,['教程'])
        check('后续评分归档不恢复旧名',wait(lambda:not operation.pending) and operation.outcome.succeeded
              and window.store.video(vid)['name']==window.store.video(vid)['original_name']=='归档后改名.mp4')
        apply_theme(window,'dark')
        header.begin_edit()
        window.grab().save(str(output/'inline-dark.png'))
        check('深色原位编辑保持固定高度',header.editor.isVisible() and header.height()==72 and window.player_view.video_handle()==handle)
        header.cancel_edit()
        full=window.player_view.fullscreen
        full.enter()
        check('全屏标题只读并显示新名称',wait(lambda:full.active) and not header.isVisible()
              and not full.title.header.edit_button.isVisible() and full.title.header.filename=='归档后改名.mp4')
        full.exit()
        check('退出全屏没有残留输入框',wait(lambda:header.isVisible()) and not header.editor.isVisible()
              and window.player_view.video_handle()==handle)
        check('全过程没有全局错误弹窗',not errors)
        report['success']=True
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
        window.grab().save(str(output/'failure.png'))
    finally:
        window.tag_drafts.discard_all()
        window.close()
        QThreadPool.globalInstance().waitForDone(10000)
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1


if __name__=='__main__':
    sys.exit(run(sys.argv[1]))
