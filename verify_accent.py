"""Native appearance interaction and continuous VLC playback; private desktop only."""
import json
from pathlib import Path
import subprocess
import time
import traceback


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import Qt, QTimer, QThreadPool, QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QPushButton, QDialogButtonBox
    from PySide6.QtTest import QTest
    from app import Window
    from appearance import Appearance
    from appearance_dialog import AppearanceDialog
    from theme import colors_for
    from runtime import BUNDLE
    from ui import icon
    output=Path(destination).absolute()
    output.mkdir(parents=True,exist_ok=True)
    report=dict(checks=[])
    application=QApplication.instance() or QApplication([])
    window=Window(output/'data')
    window.resize(1200,800)
    window.show()
    application.setActiveWindow(window)
    errors=[]
    window.fail=lambda error:errors.append(str(error))
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
    try:
        ffmpeg=BUNDLE/'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe())
        samples=output/'samples'
        samples.mkdir()
        sample=samples/'强调色测试.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25',
            '-t','40','-c:v','libx264','-threads','2','-y',str(sample)],check=True,capture_output=True,
            timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        loaded=window.load_folder(str(samples))
        check('扫描隔离样例成功',wait(lambda:not loaded.pending) and loaded.outcome.succeeded)
        window.start(window.library_controller.browsing,(str(samples),0))
        check('原生VLC实际播放',wait(lambda:window.player.get_time()>700))
        handle=window.player_view.video_handle()
        mrl=window.player.get_media().get_mrl()
        manager=window.player.event_manager()
        for kind in (window.vlc.EventType.MediaPlayerStopped,window.vlc.EventType.MediaPlayerOpening,
                     window.vlc.EventType.MediaPlayerMediaChanged):
            manager.event_attach(kind,lambda event:events.append(str(event.type)))
        color='#0c8c60'
        def edit(save):
            dialog=application.activeModalWidget()
            try:
                check('外观入口打开真实设置窗口',isinstance(dialog,AppearanceDialog))
                picker=dialog.accent_picker
                picker.swatches[2].click()
                check('预设色块即时作用于播放器',window.player_view.normal_colors['button_fill']==picker.color=='#db4f96')
                QTest.mouseClick(picker.field,Qt.LeftButton,pos=QPoint(100,40))
                check('色板点击可选自定义颜色',picker.color!='#db4f96')
                for control,value in zip(picker.values,(12,140,96)):
                    control.setValue(value)
                check('RGB数值与滑块和主界面同步',picker.color==color
                      and [control.value() for control in picker.sliders]==[12,140,96]
                      and window.player_view.normal_colors['button_fill']==color)
                application.processEvents()
                check('RGB输入框能完整显示三位数',all(control.lineEdit().width()>=control.fontMetrics().horizontalAdvance('255')
                      for control in picker.values))
                dialog.themes.setCurrentIndex(dialog.themes.findData('dark'))
                check('切换深色保留调色结果',window.theme=='dark' and window.accent==color)
                if save:
                    dialog.grab().save(str(output/'appearance-dark.png'))
                dialog.themes.setCurrentIndex(dialog.themes.findData('light'))
                application.processEvents()
                button=dialog.buttons.button(QDialogButtonBox.Ok)
                check('设置适应屏幕且保存按钮保持可见',dialog.height()<=dialog.maximumHeight()
                      and dialog.rect().contains(button.mapTo(dialog,button.rect().center())))
                check('预览不会提前写入设置',not window.appearance.file.exists())
                if save:
                    dialog.grab().save(str(output/'appearance-light.png'))
                dialog.buttons.button(QDialogButtonBox.Ok if save else QDialogButtonBox.Cancel).click()
            except Exception:
                errors.append(traceback.format_exc())
                if isinstance(dialog,AppearanceDialog):
                    dialog.reject()
        entrance=window.findChild(QPushButton,'appearanceButton')
        QTimer.singleShot(0,lambda:edit(False))
        entrance.click()
        check('取消恢复默认且不保存',not errors and window.accent=='#477ce5' and not window.appearance.file.exists())
        QTimer.singleShot(0,lambda:edit(True))
        entrance.click()
        check('保存后重读保留精确RGB',not errors and Appearance(output/'data').accent==color)
        view=window.player_view
        check('普通播放按钮实际绘制自定义底色',view.play_button.grab().toImage().pixelColor(22,5)==QColor(color))
        before=window.player.get_time()
        check('外观调整后仍继续播放',wait(lambda:window.player.get_time()>before+300))
        view.fullscreen.toggle()
        application.processEvents()
        view.fullscreen.set_presentation(True)
        application.processEvents()
        check('全屏沿用同一RGB底色与深色衍生主题',view.fullscreen.colors['button_fill']==color
              and view.fullscreen.title.header.colors['accent']==colors_for('dark',color)['accent'])
        check('全屏播放按钮实际底色同步',view.play_button.grab().toImage().pixelColor(22,5)==QColor(color))
        view.fullscreen.overlay.grab().save(str(output/'fullscreen-controls.png'))
        check('播放图标使用可读前景色',view.play_button.icon().pixmap(24,24).toImage()
              ==icon('pause',colors_for('dark',color)['button_text']).pixmap(24,24).toImage())
        view.fullscreen.exit()
        application.processEvents()
        check('退出全屏仍保留强调色',view.normal_colors['button_fill']==color)
        check('外观和全屏未重载视频或改变宿主',not events and view.video_handle()==handle and window.player.get_media().get_mrl()==mrl)
        window.grab().save(str(output/'player-custom-accent.png'))
        report['success']=not errors
        report['errors']=errors
    except Exception:
        report['success']=False
        report['error']=traceback.format_exc()
    finally:
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
