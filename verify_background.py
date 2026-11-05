"""Visible backdrop coverage and VLC isolation on a private Windows desktop."""
import json
from pathlib import Path
import shutil
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import QPoint, QThreadPool
    from PySide6.QtGui import QColor, QImage, QPainter, QLinearGradient
    from PySide6.QtWidgets import QApplication
    from app import Window
    from runtime import BUNDLE
    from appearance import Appearance
    from theme import apply_theme, theme_tokens
    output=Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    application=QApplication.instance() or QApplication([])
    window=Window(output/'data')
    window.resize(1200,800)
    window.show()
    application.setActiveWindow(window)
    report=dict(checks=[])
    events=[]
    def check(name,passed):
        report['checks'].append(dict(name=name,ok=bool(passed)))
        assert passed,name
    def wait(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            application.processEvents()
            if predicate():
                return True
            time.sleep(.02)
        return False
    def pixel(widget,point):
        image=window.grab().toImage()
        mapped=widget.mapTo(window,point)
        ratio=image.devicePixelRatio()
        return image.pixelColor(round(mapped.x()*ratio),round(mapped.y()*ratio))
    try:
        picture=QImage(1200,800,QImage.Format_RGB32)
        painter=QPainter(picture)
        gradient=QLinearGradient(0,0,1200,800)
        gradient.setColorAt(0,QColor('#f0a0b4'))
        gradient.setColorAt(.45,QColor('#6288c8'))
        gradient.setColorAt(1,QColor('#50bfa8'))
        painter.fillRect(picture.rect(),gradient)
        painter.setPen(QColor('#d3e3f9'))
        for x in range(0,1200,80):
            painter.drawLine(x,0,x,800)
        painter.end()
        background=output/'background.png'
        picture.save(str(background))
        ffmpeg=BUNDLE/'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
        samples=output/'samples'
        samples.mkdir()
        sample=samples/'A.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
            '-t','30','-c:v','libx264','-threads','2','-y',str(sample)],check=True,capture_output=True,
            timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        for name in ('B.mp4','C.mp4'):
            shutil.copyfile(sample,samples/name)
        loaded=window.load_folder(str(samples))
        check('隔离样例扫描成功',wait(lambda:not loaded.pending) and loaded.outcome.succeeded)
        context=window.library_controller.browsing
        for vid,name in context.folders[str(samples)][1]:
            window.catalog.mark_played(vid)
        window.library_view.show_mode('videos')
        application.processEvents()
        viewport=window.library_view.lists['videos'].viewport()
        points=(QPoint(viewport.width()-12,viewport.height()-12),QPoint(viewport.width()-12,145))
        before=[pixel(viewport,point) for point in points]
        window.grab().save(str(output/'before.png'))
        handle=window.player_view.video_handle()
        window.canvas.set_background(background,80)
        application.processEvents()
        after=[pixel(viewport,point) for point in points]
        check('资料库空白区域可见背景',before[0]!=after[0])
        check('未选中视频行不再遮挡背景',before[1]!=after[1])
        idle=window.player_view.player_empty
        check('未播放区域显示背景',pixel(idle,QPoint(20,20))!=QColor('#101216'))
        check('背景透明模式只在有图片时开启',theme_tokens(window)['backdrop'])
        window.grab().save(str(output/'idle-light.png'))
        apply_theme(window,'dark')
        application.processEvents()
        check('深色主题仍显示背景',theme_tokens(window)['backdrop'] and pixel(viewport,points[0])!=after[0])
        window.grab().save(str(output/'idle-dark.png'))
        window.canvas.set_background(background,35)
        application.processEvents()
        subdued=pixel(viewport,points[0])
        window.canvas.set_background(background,80)
        application.processEvents()
        check('背景强度影响整个资料库',pixel(viewport,points[0])!=subdued)
        window.resize(1300,850)
        application.processEvents()
        check('调整窗口保持同一视频宿主与背景',window.player_view.video_handle()==handle and pixel(idle,QPoint(20,20))!=QColor('#101216'))
        window.appearance.save(background,80,'dark')
        restored=Appearance(output/'data')
        check('保存后重读背景副本及强度',restored.background.is_file() and restored.strength==80)
        for kind in (window.vlc.EventType.MediaPlayerStopped,window.vlc.EventType.MediaPlayerOpening,
                     window.vlc.EventType.MediaPlayerMediaChanged):
            window.player.event_manager().event_attach(kind,lambda event:events.append(str(event.type)))
        window.start(context,(str(samples),0))
        check('原生VLC播放正常',wait(lambda:window.player.get_time()>700))
        events.clear()
        media=window.player.get_media().get_mrl()
        check('播放后隐藏空闲背景层',not idle.isVisible())
        start=window.player.get_time()
        window.canvas.set_background(None,60)
        apply_theme(window,'light')
        application.processEvents()
        check('清除背景恢复默认面板',not theme_tokens(window)['backdrop'])
        window.canvas.set_background(restored.background,80)
        application.processEvents()
        check('播放中更换背景仍继续前进',wait(lambda:window.player.get_time()>start+300))
        window.grab().save(str(output/'playing-light.png'))
        window.player_view.fullscreen.enter()
        application.processEvents()
        check('全屏仍使用独立深色控制栏',not window.player_view.fullscreen.colors['backdrop'])
        window.player_view.fullscreen.exit()
        application.processEvents()
        check('背景与全屏不重载媒体或更换宿主',not events and window.player.get_media().get_mrl()==media and window.player_view.video_handle()==handle)
        window.clear_player()
        application.processEvents()
        check('停止后恢复空闲背景',idle.isVisible() and pixel(idle,QPoint(20,20))!=QColor('#101216'))
        report['success']=True
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
    finally:
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
