"""Library interaction and rendering on a private Windows desktop and data set."""
import json
from pathlib import Path
import time
import traceback
import subprocess


def run(destination):
    from verify_ui_refresh import require_private_desktop
    require_private_desktop()
    from PySide6.QtCore import Qt, QPoint, QThreadPool
    from PySide6.QtGui import QImage, QColor, QPainter, QLinearGradient
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app import Window
    from theme import apply_theme
    from runtime import BUNDLE
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = Window(output / 'data')
    window.resize(1280, 900)
    window.show()
    app.setActiveWindow(window)
    report = {'checks': []}
    window.fail = lambda error: report.setdefault('errors', []).append(str(error))

    def check(name, value):
        report['checks'].append(dict(name=name, ok=bool(value)))
        assert value, name

    def wait(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return True
            QTest.qWait(20)
        return bool(predicate())

    def screenshot(name):
        QTest.qWait(180)
        app.processEvents()
        image = window.grab()
        painter = QPainter(image)
        popup = window.library_view.catalog_panel.popup
        if popup.isVisible():
            painter.drawPixmap(popup.pos() - window.mapToGlobal(QPoint()), popup.grab())
        painter.end()
        image.save(str(output / name))

    try:
        samples = output / 'samples'
        samples.mkdir(exist_ok=True)
        names = ['山间暮色', '海岸漫步', '城市夜景', '森林深处', '雨后天光', '山间晨光', '静谧湖畔', '长长的文件名用来检查两行省略与标签和入库日期不会重叠']
        tags = ['风景', '山川', '海边', '摄影', '旅行', '夜景', '城市', '自然', '人文', '音乐', '动画', '纪录片', '电影', '短片', '壁纸', '清晨', '傍晚', '雨天', '雪景', '延时', '随手拍', '待整理', '作品集', '特别喜欢', '2026', '夏日回忆']
        ids = []
        for n, name in enumerate(names):
            image = QImage(960, 540, QImage.Format_RGB32)
            painter = QPainter(image)
            gradient = QLinearGradient(0, 0, 960, 540)
            gradient.setColorAt(0, QColor.fromHsv((n * 43 + 175) % 360, 110, 165))
            gradient.setColorAt(1, QColor.fromHsv((n * 43 + 225) % 360, 90, 65))
            painter.fillRect(image.rect(), gradient)
            painter.setPen(QColor('#f2f4f8'))
            font = painter.font()
            font.setPixelSize(40)
            painter.setFont(font)
            painter.drawText(image.rect(), Qt.AlignCenter, name)
            painter.end()
            path = samples / (name + '.png')
            image.save(str(path))
            vid = window.store.register(path)
            selected_tags = [] if n == 6 else ['山川' if n in (0, 5) else '海边' if n == 1 else tags[n % len(tags)], '摄影']
            selected_tags = list(dict.fromkeys(selected_tags))
            window.store.execute('UPDATE videos SET archived=1,score=?,star=?,tags=?,archived_at=? WHERE id=?',
                                 (None if n == 6 else n + 3, int(n % 2 == 0), json.dumps(selected_tags, ensure_ascii=False),
                                  None if n == 6 else 1793000000 + n * 86400, vid))
            ids.append(vid)
        for tag in tags:
            window.store.execute('INSERT OR REPLACE INTO tags(name) VALUES(?)', (tag,))
            window.store.execute('INSERT OR REPLACE INTO tag_layout VALUES(?,?,?)', (tag, 'minor' if tag == '山川' else 'major', '风景' if tag == '山川' else None))
        loaded = window.load_folder(str(samples))
        check('文件页载入独立样本', wait(lambda: not loaded.pending) and loaded.outcome.succeeded)
        browsing = window.library_controller.browsing
        view = window.library_view
        file_selection = view.files.model().index(1, 0)
        view.files.setCurrentIndex(file_selection)
        selected_file = file_selection.data(Qt.UserRole)
        view.show_mode('catalog')
        controller, panel = window.library_controller, view.catalog_panel
        check('库异步显示全部归档项', wait(lambda: controller.catalog_loaded and not controller.catalog_pending) and panel.list.model().rowCount() == len(ids))
        QTest.qWait(100)
        check('筛选收进浮窗并让出列表高度', not panel.popup.isVisible() and panel.list.mapTo(panel, QPoint()).y() < 110)
        check('类型使用直接按钮', set(panel.popup.kind) == {'all', 'video', 'image'})
        apply_theme(window, 'dark')
        screenshot('catalog-dark.png')
        panel.filter_button.click()
        check('统一筛选浮窗可用', wait(panel.popup.isVisible))
        panel.popup.search.setText('夏日')
        check('浮窗支持标签搜索', len(panel.popup.tags.chips) == 1)
        panel.popup.search.clear()
        panel.popup.number.setText('7')
        check('精确评分匹配真实结果', wait(lambda: not controller.catalog_pending) and controller.catalog_ids == [ids[4]])
        check('评分输入框显示当前分数', panel.popup.number.text() == '7' and panel.popup.number.width() >= 20)
        panel.popup.score_mode['gte'].click()
        check('及以上包含边界并排除未评分', wait(lambda: not controller.catalog_pending) and set(controller.catalog_ids) == {ids[4],ids[5],ids[7]})
        screenshot('catalog-tags.png')
        panel.reset_filters()
        check('重置评分完成', wait(lambda: not controller.catalog_pending))
        panel.popup.tags.chips['风景'].click()
        check('父标签包含子标签', wait(lambda: not controller.catalog_pending) and set(controller.catalog_ids) == {ids[0],ids[5]})
        panel.popup.tags.chips['摄影'].click()
        check('多选标签按交集匹配', wait(lambda: not controller.catalog_pending) and len(controller.catalog_ids) == 2)
        panel.popup.tag_mode['or'].click()
        check('切换OR匹配任一标签', wait(lambda: not controller.catalog_pending) and len(controller.catalog_ids) == 7)
        QTest.keyClick(panel.popup.search, Qt.Key_Escape)
        check('Escape关闭标签浮层', wait(lambda: not panel.popup.isVisible()))
        check('收起后显示OR摘要', '或' in ' '.join(panel.summary.chips))
        panel.reset_filters()
        check('重置恢复全部', wait(lambda: not controller.catalog_pending) and len(controller.catalog_ids) == len(ids))
        panel.list.setCurrentIndex(panel.list.model().index_for_id(ids[0]))
        original_order = tuple(controller.catalog_ids)
        panel.view_buttons['grid'].click()
        app.processEvents()
        check('网格两列并保留所选身份', panel.list.presentation == 'grid' and panel.list.currentIndex().data(Qt.UserRole) == ids[0]
              and panel.list.visualRect(panel.list.model().index(0,0)).top() == panel.list.visualRect(panel.list.model().index(1,0)).top())
        check('视图切换不查询或改变结果顺序', not controller.catalog_pending and tuple(controller.catalog_ids) == original_order)
        screenshot('catalog-grid-dark.png')
        report['grid_geometry'] = dict(viewport=panel.list.viewport().width(),cell=panel.list.gridSize().width(),
            first=tuple(panel.list.visualRect(panel.list.model().index(0,0)).getRect()),
            second=tuple(panel.list.visualRect(panel.list.model().index(1,0)).getRect()))
        check('网格异步刷新后仍保持两列', panel.list.visualRect(panel.list.model().index(0,0)).top() == panel.list.visualRect(panel.list.model().index(1,0)).top())
        panel.list.scrollTo(panel.list.currentIndex())
        QTest.qWait(100)
        index = panel.list.currentIndex()
        QTest.mouseClick(panel.list.viewport(), Qt.LeftButton, pos=panel.list.visualRect(index).center())
        check('单击只选择不播放', window.current is None)
        QTest.mouseDClick(panel.list.viewport(), Qt.LeftButton, pos=panel.list.visualRect(index).center())
        check('双击库条目实际打开图片', wait(lambda: window.current == ids[0] and window.player_view.image_view.has_image()))
        context, location = window.context, window.location
        order = list(context.folders[context.root][1])
        panel.view_buttons['list'].click()
        check('切回列表继续播放并保持队列', window.context is context and window.current == ids[0] and panel.list.presentation == 'list')
        panel.change(favorite='no', sort='added_desc')
        check('改筛选不会改变播放和冻结顺序', wait(lambda: not controller.catalog_pending) and window.current == ids[0] and context.folders[context.root][1] == order)
        check('库播放保留文件页浏览快照', controller.browsing is browsing)
        check('当前播放项可从筛选结果移出', ids[0] not in controller.catalog_ids and window.current == ids[0])
        next_location = context.step(location, 1)
        window.start(context, next_location)
        check('下一项沿冻结队列实际打开', wait(lambda: window.current == order[next_location[1]][0] and window.player_view.image_view.has_image()))
        panel.reset_filters()
        check('筛选重新查询完成', wait(lambda: not controller.catalog_pending))
        # Exercise the real deletion workflow on disposable files, no shell UI.
        from video_delete import DeletionManager
        window.deletion.submit = DeletionManager(window.store, recycle=lambda path: path.unlink()).submit
        other = next(vid for vid in controller.catalog_ids if vid not in (window.current, selected_file))
        current = window.current
        selection = controller.catalog_selection(other)
        deleted = window.deletion.delete(other, (selection.context, selection.location))
        check('删除非播放项不换片', wait(lambda: not deleted.pending and not controller.catalog_pending)
              and deleted.outcome.succeeded and window.current == current and window.player_view.image_view.has_image())
        check('删除项从库中移除', other not in controller.catalog_ids)
        missing = next(vid for vid in controller.catalog_ids if vid not in (current, selected_file))
        window.catalog.resolve(missing).unlink()
        selection = controller.catalog_selection(missing)
        window.start(selection.context, selection.location)
        check('失效文件保留当前播放和库记录', window.current == current and missing in controller.catalog_ids
              and controller.details[missing].get('unavailable'))
        report['expected_unavailable'] = report.pop('errors', [])
        apply_theme(window, 'light')
        panel.list.scrollToTop()
        screenshot('catalog-light.png')
        window.splitter.setSizes([320, 960])
        app.processEvents()
        panel.view_buttons['grid'].click()
        app.processEvents()
        check('窄侧栏工具栏不超出边界', panel.view_buttons['grid'].geometry().right() < panel.width())
        check('窄侧栏网格仍有两列', panel.list.visualRect(panel.list.model().index(0,0)).top() == panel.list.visualRect(panel.list.model().index(1,0)).top())
        screenshot('catalog-narrow.png')
        view.show_mode('files')
        check('切回文件页保留原目录', view.current_folder == browsing.root and controller.browsing is browsing)
        check('库播放保留文件页原有选择', view.files.currentIndex().data(Qt.UserRole) == selected_file)
        view.show_mode('catalog')
        panel.change(favorite='no', score='none', kind='video')
        check('无结果状态保留筛选并可重置', wait(lambda: not controller.catalog_pending)
              and panel.message.isVisible() and panel.reset.isEnabled())
        check('空网格不显示滚动条', panel.list.presentation == 'grid'
              and wait(lambda: not panel.list.verticalScrollBar().isVisible()))
        panel.reset_filters()
        check('清除无结果筛选恢复库', wait(lambda: not controller.catalog_pending) and bool(controller.catalog_ids))
        panel.list.scrollToTop()
        screenshot('catalog-final.png')
        panel.list.grab().save(str(output / 'catalog-list.png'))
        check('筛选重载保留暂不可用标记', bool(controller.details[missing].get('unavailable')))
        check('无原生播放错误', not report.get('errors'))
        # Real VLC playback verifies popup ownership above the native video child.
        image_context, image_location = window.context, window.location
        movie = samples / '筛选浮窗播放测试.mp4'
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.exists():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25','-t','20',
                        '-c:v','libx264','-threads','2','-y',str(movie)],check=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        movie_id = window.store.register(movie)
        window.store.execute('UPDATE videos SET archived=1,score=8,tags=? WHERE id=?', ('["摄影"]',movie_id))
        controller.refresh((movie_id,), window.context, catalog_changed=True)
        check('新入库视频即时进入结果', wait(lambda: not controller.catalog_pending) and movie_id in controller.catalog_ids)
        panel.change(kind='video')
        check('视频类型筛选结果正确', wait(lambda: not controller.catalog_pending) and controller.catalog_ids == [movie_id])
        selection = controller.catalog_selection(movie_id)
        window.start(selection.context, selection.location)
        check('库队列中的真实视频播放', wait(lambda: window.current == movie_id and window.player.get_time() > 400))
        handle = window.player_view.video_handle()
        panel.filter_button.click()
        check('视频播放时可打开筛选', wait(panel.popup.isVisible))
        before = window.player.get_time()
        QTest.keyClicks(panel.popup.search, 'XZ')
        check('筛选输入不触发换片且视频继续', wait(lambda: window.player.get_time() > before + 300,3) and window.current == movie_id
              and panel.popup.search.text().endswith('XZ') and window.player_view.video_handle() == handle)
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32')
        user.WindowFromPoint.argtypes = [wintypes.POINT]
        user.WindowFromPoint.restype = wintypes.HWND
        user.GetAncestor.argtypes = [wintypes.HWND,wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        point = panel.popup.mapToGlobal(QPoint(panel.popup.width()-24, panel.popup.height()//2))
        check('原生浮窗位于VLC画面之上', int(user.GetAncestor(user.WindowFromPoint(wintypes.POINT(point.x(),point.y())),2)) == int(panel.popup.winId()))
        window.showMinimized()
        app.processEvents()
        check('最小化关闭筛选浮窗', not panel.popup.isVisible())
        window.showNormal()
        app.setActiveWindow(window)
        window.start(image_context,image_location)
        check('退出视频测试后图片继续可用', wait(lambda: window.player_view.image_view.has_image()))
        panel.change(kind='all',score=7,score_mode='gte',tags=('摄影','旅行'),tag_mode='or')
        check('保存新的评分与标签规则', wait(lambda: not controller.catalog_pending))
        saved_filters = panel.filters
        saved_view = panel.list.presentation
        panel.search.setText('关闭前尚未提交的输入')
        window.close()
        check('关闭取消搜索合并计时', not panel.debounce.isActive())
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        window = Window(output / 'data')
        window.resize(1280, 900)
        window.show()
        window.restore_last_folder()
        check('重启固定回到文件页', window.library_view.mode == 'files')
        check('重启重开上次导入的文件夹', wait(lambda: window.library_view.current_folder is not None)
              and Path(window.library_view.current_folder) == samples.absolute())
        check('重启不自动播放', window.current is None)
        check('重启保留库筛选与网格视图', window.library_controller.catalog_filter == saved_filters
              and window.library_view.catalog_panel.list.presentation == saved_view)
        report['success'] = True
    except Exception:
        report['success'] = False
        report['error'] = traceback.format_exc()
    finally:
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
