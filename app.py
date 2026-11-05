import json  # 读取视频标签和诊断数据。
import logging  # 记录可追踪的运行错误。
import sys  # 区分源码和便携运行方式。
import threading  # 提供扫描取消信号。
import time  # 管理周期保存时间。
from pathlib import Path  # 处理便携数据路径。
if len(sys.argv) == 3 and sys.argv[1] in ('--ui-refresh-test', '--seek-notice-test'):
    # A windowed EXE has no stderr; keep explicit test failures reviewable.
    _test_output = Path(sys.argv[2]).absolute()
    _test_output.mkdir(parents=True, exist_ok=True)
    _test_console = (_test_output / 'console.txt').open('w', encoding='utf-8')
    sys.stdout = sys.stderr = _test_console
    import faulthandler
    faulthandler.enable(file=_test_console)
from PySide6.QtCore import Qt, QTimer, QThreadPool, QEvent, QLockFile
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QVBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QDialog, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QAbstractSpinBox, QTextEdit, QPlainTextEdit
from background_work import Work
from thumbnail_cache import ThumbnailCache
from library_views import DropTree, TreeModel, VideoDelegate
from infrastructure.thumbnails import ThumbnailService
from ui import format_time
from application.operations import Operation, UserActions
from application.tag_drafts import TagDrafts
from application.playback import PlaybackSession
from application.file_tasks import FileTasks, FileTaskPolicy
from infrastructure.library_repository import LibraryRepository
from core import Store, Archiver, ScanRequired, scan
from video_delete import DeletionManager  # 以可恢复任务回收全部登记入口。
from tag_migration import TagMigration  # 以可恢复批次同步全局标签层级。
from storage_settings import StorageSettings, StorageDialog  # 加载每位用户独立的存储路径与设置窗口。

from runtime import BASE, BUNDLE, create_player


from window_chrome import ChromeWindow

class Window(ChromeWindow):  # 主界面和播放协调层。
    def __init__(self, data_dir=None):  # 测试可使用隔离数据目录。
        super().__init__()  # 创建主窗口。
        self.store = Store(data_dir or BASE / 'data')  # 元数据不依赖开发环境路径。
        self.catalog = LibraryRepository(self.store)
        self.storage = StorageSettings(self.store.directory)  # 首次运行没有默认归档目录。
        self.legacy_storage_recovery = self.storage.root is None and self.has_pending_file_tasks()  # 旧版本未完成任务先沿用其原路径恢复。
        from core import ARCHIVE_ROOT  # 旧固定路径只供旧版本已提交任务兼容恢复。
        self.archiver = Archiver(self.store, ARCHIVE_ROOT if self.legacy_storage_recovery else self.storage.root)  # 正常新安装不再依赖 E 盘。
        self.deleter = DeletionManager(self.store)  # 将删除阶段与元数据提交持久记账。
        self.tag_migration = TagMigration(self.store, self.archiver)  # 全局分类复用逐视频硬链接归档和恢复日志。
        self.video_details = {}
        self.thumbnail_service = ThumbnailService(self.store.directory, self.catalog.resolve, BUNDLE)
        self.thumbnails = ThumbnailCache(self.thumbnail_service, lambda: self.busy, self)
        self.browsing, self.context, self.location, self.current = None, None, None, None  # 浏览快照与播放快照严格分离。
        self.scan_cancel, self.scan_serial, self.jobs, self.busy = threading.Event(), 0, [], False  # 管理取消和后台任务。
        self.navigation_cancel = threading.Event()  # 同级目录延迟扫描也支持取消。
        self.playback = PlaybackSession()
        self.user_actions = UserActions()
        self.tag_drafts = TagDrafts(self.catalog,
            lambda vid, values: self.apply_tags(vid, values.tags, list(values.schema.values()), prompt_score=False),
            lambda: self.current, lambda: not self.busy)
        self.file_tasks = FileTasks(lambda function, callback: self.work(function, callback),
                                    self._begin_file_task, self._end_file_task, self.has_pending_file_tasks)
        self.vlc, self.instance, self.player = create_player()
        self.setWindowTitle('MoPlayer · 本地视频与分类')  # 设置可识别的窗口标题。
        self.resize(1440, 920)  # 为品牌导航、双层控制和大缩略图保留舒适留白。
        self.setMinimumSize(900, 580)  # 避免窗口过小造成导航和分类按钮重叠。
        from layout import build_interface  # 按独立视觉模块构建蓝色卡片布局。
        build_interface(self, DropTree, VideoDelegate, BUNDLE)  # 保留所有既有控件变量和业务回调。
        self.setWindowIcon(QIcon(str(BUNDLE / 'assets/yunli.ico')))  # 窗口与任务栏使用同一云璃 Q 版图标。
        from video_fullscreen import VideoFullscreen  # 独立管理视频全屏与控制栏浮层。
        self.video_fullscreen = VideoFullscreen(self)  # 不移动 VLC 原生播放窗口，保持解码连续。
        from seek_notice import SeekNotice
        self.seek_notice = SeekNotice(self)  # 独立浮层按界面分辨率绘制，普通和全屏共用。
        self.timer = QTimer(self)  # 主线程定时刷新播放器状态。
        self.timer.timeout.connect(self.tick)  # 保留既有进度和自动连播逻辑。
        self.timer.start(250)  # 每四分之一秒刷新一次。
        QApplication.instance().installEventFilter(self)  # 保留弹窗与文本输入优先的快捷键处理。
        if self.has_pending_file_tasks():
            QTimer.singleShot(0, self.retry_jobs)  # 等界面启动后异步恢复未完成归档。

    def work(self, function, callback):  # 启动后台任务并保持信号对象存活。
        job = Work(function)  # 封装工作函数。
        self.jobs.append(job)  # 防止任务结束前被垃圾回收。
        def finished(value, error):  # 在主线程交付工作结果。
            self.jobs.remove(job)  # 释放已完成任务引用。
            callback(value, error)  # 更新界面状态。
        job.signals.finished.connect(finished)  # 使用 Qt 自动线程间排队连接。
        QThreadPool.globalInstance().start(job)  # 避免阻塞主事件循环。

    def message(self, text):  # 提供短暂、非打断式反馈。
        # Routine feedback stays in the log; errors still use fail().
        self.statusBar().hide()  # 保留足够阅读时间。
        logging.info(text)  # 同时记录可追踪日志。

    def fail(self, error):  # 明确报告失败而不显示成功。
        QMessageBox.warning(self, '操作未完成', str(error))  # 用户可看到真实失败原因。

    def choose_folder(self):  # 支持按钮选择目录。
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹')  # 使用系统目录选择器。
        if folder:  # 取消对话框不触发扫描。
            self.load_folder(folder)  # 复用拖放导入流程。

    def has_pending_file_tasks(self):  # 未完成文件意图必须先按原目标恢复。
        return bool(self.catalog.pending_tasks())  # 仅查询内部固定表名。

    def storage_dialog(self, first_run=False):  # 右上角设置与首次引导共用入口。
        if self.busy or self.has_pending_file_tasks():  # 不在文件任务执行或等待恢复时更改目标根目录。
            self.message('请先等待文件任务完成，或通过“更多 → 文件任务”恢复，再设置存储路径。')  # 保留原任务位置。
            return False  # 不切换正在使用的归档器。
        return StorageDialog(self, first_run).exec() == QDialog.Accepted  # 取消不保存路径。

    def initialize_storage(self):  # 正常启动时只在未配置情况下弹出首次设置。
        if self.storage.root is not None:  # 已配置用户不被重复打扰。
            return  # 不扫描或移动任何视频。
        if self.busy:  # 旧版已提交任务的恢复先完成。
            QTimer.singleShot(300, self.initialize_storage)  # 让后台任务继续，不阻塞主界面。
            return  # 稍后再显示首次设置。
        self.storage_dialog(first_run=True)  # 可以稍后设置，浏览与播放仍可用。

    def ensure_storage(self):  # 归档操作前保证用户已明确选择目录。
        if self.archiver.root is not None and not self.legacy_storage_recovery:  # 包括测试注入的独立归档器。
            return True  # 已配置时不重复弹窗。
        return self.storage_dialog(first_run=True)  # 稍后设置会取消本次归档操作。

    def load_folder(self, folder, play_id=None):  # 替换浏览树而不改变当前播放。
        if self.busy:  # 归档期间不启动会改变当前视频的操作。
            self.message('归档处理中，请等待完成。')  # 说明暂时不可操作的原因。
            return  # 保持当前上下文。
        self.scan_cancel.set()  # 取消上一次尚未完成的扫描。
        self.scan_cancel = threading.Event()  # 每次扫描拥有独立取消对象。
        self.scan_serial += 1  # 用代次丢弃晚到的旧扫描结果。
        serial, cancel = self.scan_serial, self.scan_cancel  # 在线程启动前捕获变量。
        self.cancel_button.setEnabled(True)  # 允许用户中断扫描。
        self.message(f'正在扫描：{folder}')  # 展示扫描任务状态。
        def ready(result, error):  # 接收完整扫描快照。
            if serial != self.scan_serial:  # 旧扫描不覆盖新目录。
                return  # 丢弃过期结果。
            self.cancel_button.setEnabled(False)  # 当前扫描结束。
            if error:  # 取消或访问错误不清空旧浏览树。
                (self.message if isinstance(error, InterruptedError) else self.fail)(str(error))
                return  # 保持既有播放器状态。
            self.browsing, errors = result  # 只替换浏览快照。
            ids = (vid for _, files in self.browsing.folders.values() for vid, _ in files)
            self.video_details.update(self.catalog.video_details(ids))
            self.tree.setModel(TreeModel(self.browsing))  # 按需显示新目录树。
            self.tree.expand(self.tree.model().index(0, 0))  # 默认展开导入根目录。
            self.folder_label.setText(str(folder))  # 显示当前浏览位置。
            self.file_count.setText(f'{sum(len(files) for children, files in self.browsing.folders.values())} 部')  # 同步当前目录快照中的视频数量。
            self.catalog.remember_folder(folder)  # 历史文件夹独立记录。
            self.message(f'扫描完成，{len(self.browsing.folders)} 个目录；跳过 {len(errors)} 个无法访问的条目。')  # 给出扫描结果。
            for error_text in errors:  # 保存具体无法访问的路径。
                logging.warning(error_text)  # 可通过日志进一步诊断。
            if play_id:  # 历史或收藏明确请求恢复某个视频。
                for directory, (_, files) in self.browsing.folders.items():  # 在恢复的浏览目录内查找稳定 ID。
                    for index, (vid, name) in enumerate(files):  # 不使用同名匹配。
                        if vid == play_id:  # 找到原身份的有效入口。
                            self.start(self.browsing, (directory, index))  # 此时主动建立新的播放上下文。
                            return  # 只播放一条记录。
                self.fail('扫描后未找到原视频身份；文件可能已被移动或替换。')  # 明确处理扫描期间外部变化。
        self.work(lambda: scan(folder, self.store, cancel), ready)  # 完整递归在后台运行。

    def open_index(self, index):  # 双击文件时建立播放上下文。
        kind, folder, number = index.internalPointer()  # 从当前浏览模型读取逻辑位置。
        if kind == 'video':  # 文件夹双击由树负责展开收起。
            self.start(self.browsing, (folder, number))  # 用户主动选择才改变上下文。

    def save(self):
        if self.current and not self.busy:
            position = self.playback.position_to_save(
                self.player.get_time(), ended=self.player.get_state() == self.vlc.State.Ended)
            if position is not None:
                self.catalog.progress(self.current, position)
            if self.current in self.video_details:
                self.video_details[self.current]['position'] = position

    def start(self, context, location):
        if self.busy and not self.tag_drafts.saving:
            self.message('文件任务正在处理，请稍候。')
            return
        self.user_actions.request(lambda: self._start(context, location), self.playback_options.flush_pending)

    def _start(self, context, location):
        vid = context.folders[location[0]][1][location[1]][0]
        try:
            path = self.catalog.resolve(vid)
        except OSError as error:
            self.fail(error)
            return
        self.save()
        self.context, self.location, self.current = context, location, vid
        if self.tree.currentIndex().data(Qt.UserRole) != vid:
            self.tree.clearSelection()
        self.catalog.mark_played(vid)
        self.play_path(path, self.catalog.video(vid)['position'], False)
        self.refresh_title()

    def play_path(self, path, position, paused):
        self.playback.begin(position, paused)
        self.seekbar.hold(0, 0)
        self.playback_options.dismiss()
        self.seek_notice.clear()
        self.player.stop()
        self.player_empty.hide()
        media = self.instance.media_new(str(path))
        self.player.set_media(media)
        media.release()
        self.player.play()
        self.sync_play_button()

    def sync_play_button(self, state=None, force=False):
        """The transport button has one rendering path, driven by VLC state."""
        from ui import icon
        if state is None:
            state = self.player.get_state() if self.current else self.vlc.State.NothingSpecial
        running = bool(self.current) and state in (self.vlc.State.Opening, self.vlc.State.Buffering, self.vlc.State.Playing)
        symbol = 'pause' if running else 'play'
        action = '暂停' if running else '重新播放' if state == self.vlc.State.Ended and self.current else '播放'
        tooltip = action + ' · 空格'
        self.play_button.setEnabled(bool(self.current) and not self.busy)
        if (force or self.play_button.property('iconName') != symbol or
                self.play_button.toolTip() != tooltip):
            self.play_button.setProperty('iconName', symbol)
            self.play_button.setIcon(icon(symbol, '#ffffff'))
            self.play_button.setToolTip(tooltip)
            self.play_button.setAccessibleName(action)

    def refresh_title(self):
        from ui import icon
        from theme import theme_tokens
        video = self.catalog.video(self.current) if self.current else None
        fullscreen = getattr(self, 'video_fullscreen', None)
        self.player_header.setVisible(bool(video) and not (fullscreen and fullscreen.active))
        if fullscreen:
            fullscreen.set_title(video['name'] if video else '')
        active = bool(video) and not self.busy
        self.classify_bar.setVisible(bool(video))
        for button in self.transport_buttons + self.classify_buttons:
            button.setEnabled(active)
        self.seekbar.setEnabled(active)
        self.favorite_button.setChecked(bool(video and video['star']))
        symbol = 'starFilled' if video and video['star'] else 'star'
        self.favorite_button.setProperty('iconName', symbol)
        self.favorite_button.setIcon(icon(symbol, theme_tokens(self)['accent' if symbol == 'starFilled' else 'text_mid']))
        if video:
            self.now.setText(video['name'])
            details = ([f"{video['score']} 分"] if video['score'] is not None else []) + json.loads(video['tags'])
            self.metadata.setText(' · '.join(details))
            self.metadata.setVisible(bool(details))
            self.video_details[self.current] = video
        self.tree.viewport().update()
        self.show_sidebar(self.sidebar_mode)

    def show_sidebar(self, mode):
        self.sidebar_mode = mode
        for key, tab in self.sidebar_tabs.items():
            tab.setChecked(key == mode)
        self.library_stack.setCurrentIndex(0 if mode == 'files' else 1)
        self.folder_label.setVisible(mode == 'files')
        self.file_count.setVisible(mode == 'files')
        self.remove_favorite.setVisible(mode == 'stars')
        if mode == 'files':
            return
        scroll = self.sidebar_list.verticalScrollBar().value()
        current = self.sidebar_list.currentItem()
        selected = current.data(Qt.UserRole) if current else None
        self.sidebar_list.clear()
        for row in self.catalog.videos(mode):
            self.video_details[row['id']] = row
            item = QListWidgetItem(row['name'], self.sidebar_list)
            item.setData(Qt.UserRole, row['id'])
            item.setToolTip(row['name'])
            if row['id'] == selected:
                self.sidebar_list.setCurrentItem(item)
        self.sidebar_list.verticalScrollBar().setValue(scroll)

    def open_sidebar_item(self, item):
        if self.busy and not self.tag_drafts.saving:
            return
        vid = item.data(Qt.UserRole)
        def open_video():
            try:
                self.load_folder(str(self.catalog.resolve(vid).parent), vid)
            except OSError as error:
                self.fail(error)
        self.user_actions.request(open_video, self.playback_options.flush_pending)

    def remove_sidebar_favorite(self):
        item = self.sidebar_list.currentItem()
        if item:
            vid = item.data(Qt.UserRole)
            self.catalog.set_favorite(vid, False)
            self.video_details[vid] = self.catalog.video(vid) or {}
            self.refresh_title()

    def toggle_sidebar(self):
        if self.video_fullscreen.active:
            return
        if self.sidebar.isHidden():
            self.sidebar.show()
            self.splitter.setSizes(getattr(self, '_sidebar_sizes', [380, 1020]))
        else:
            self._sidebar_sizes = self.splitter.sizes()
            self.sidebar.hide()

    def tick(self):
        state = self.player.get_state() if self.current else self.vlc.State.NothingSpecial
        self.sync_play_button(state)
        if not self.current or (self.busy and not self.tag_drafts.saving):
            self.seekbar.freeze()
            return
        length, position = self.player.get_length(), self.player.get_time()
        playing = state == self.vlc.State.Playing
        self.media_badge.setText('正在播放' if playing else '已暂停' if state == self.vlc.State.Paused else '播放结束' if state == self.vlc.State.Ended else '正在加载')
        restore = self.playback.restore(playing=playing, paused=state == self.vlc.State.Paused, duration=length)
        if restore is not None:
            self.set_playback_position(restore.position, length)
            if restore.pause:
                self.player.set_pause(1)
        if not self.seekbar.isSliderDown() and self.playback.pending_seek is None:
            self.time_label.setText(f'{format_time(position)} / {format_time(length)}')
        self.playback.acknowledge(position)
        if not self.seekbar.isSliderDown() and self.playback.pending_seek is None:
            self.seekbar.synchronize(position, length, playing, self.playback_options.rate)
        if self.playback.save_due():
            self.save()
            self.playback.saved()
        if self.playback.terminal(ended=state == self.vlc.State.Ended, failed=state == self.vlc.State.Error):
            if state == self.vlc.State.Ended:
                self.catalog.progress(self.current, 0)
                self.advance(1, ended=True)
            else:
                self.fail('无法解码或读取此视频，请检查文件权限、完整性和编码。')

    def advance(self, direction, ended=False):
        if not self.current or (self.busy and not self.tag_drafts.saving):
            return
        self.user_actions.request(lambda: self._advance(direction, ended), self.playback_options.flush_pending)

    def _advance(self, direction, ended=False):  # 按当前播放快照切换。
        if not self.current or self.busy:  # 未播放时快捷键不作用于其他记录。
            return  # 保持状态。
        try:  # 常规目录内切换直接使用已有快照。
            target = self.context.step(self.location, direction)  # 严格执行同目录及同级目录规则。
        except ScanRequired:  # 导入根的下一个同级目录需要延迟扫描。
            context, location, vid = self.context, self.location, self.current  # 固定本次请求的原始播放上下文。
            if getattr(self, 'navigation_pending', False):  # 连续按 X 不重复启动同一目标扫描。
                return  # 等待已有跨目录请求。
            self.navigation_pending = True  # 标记正在补齐播放上下文。
            self.navigation_cancel = threading.Event()  # 为本次延迟扫描创建独立取消标记。
            cancel = self.navigation_cancel  # 捕获标记避免后续导航替换引用。
            self.cancel_button.setEnabled(True)  # 大型同级目录扫描提供可见取消入口。
            self.message('正在扫描下一个同级目录；当前视频保持原状态。')  # 明确后台切换状态。
            def next_ready(next_location, error):  # 在主线程执行已准备的切换。
                self.navigation_pending = False  # 允许后续导航请求。
                self.cancel_button.setEnabled(False)  # 当前导航扫描已经结束。
                if self.busy or cancel.is_set() or self.context is not context or self.location != location or self.current != vid:  # 删除或主动换片后忽略旧请求。
                    return  # 不让晚到结果抢走新播放上下文。
                if error:  # 扫描失败保持当前视频。
                    (self.message if isinstance(error, InterruptedError) else self.fail)(str(error))
                elif next_location:  # 目标目录内存在可播放候选。
                    self.start(context, next_location)  # 仍沿用原上下文而不替换浏览树。
                else:  # 后续同级目录全部为空时停止。
                    self.message('没有后续可播放的同级目录。')  # 不向更高祖先寻找。
            self.work(lambda: context.step_loaded(location, direction, self.store, cancel), next_ready)  # 递归扫描在后台执行且可由取消按钮中断。
            return  # 等待异步目标准备完成。
        if target:  # 存在下一个或上一个逻辑视频。
            self.start(self.context, target)  # 浏览树改变不影响这个上下文。
        else:  # 已到规则边界。
            self.message('没有后续视频，播放已停止。' if direction > 0 and ended else '已到当前切换范围边界。')  # 不回绕播放。

    def toggle(self):  # 空格或按钮切换暂停状态。
        if self.current and not self.busy:  # 不操作空播放器或归档中的句柄。
            if self.player.get_state() == self.vlc.State.Ended:  # 已结束时重新从头播放。
                self.play_path(self.catalog.resolve(self.current), 0, False)  # 重播仍使用当前身份。
            else:  # 正常播放和暂停互相切换。
                self.player.pause()  # 由 VLC 保留当前时间。
                self.sync_play_button()

    def seek(self, offset):
        if self.current and not self.busy and self.player.get_length() > 0:
            total = self.player.get_length()
            before, after = self.playback.relative_seek(self.player.get_time(), offset, total)
            self.set_playback_position(after, total)
            self.seek_notice.show(before, after, total)

    def set_playback_position(self, target, length):
        target = self.playback.seek(target, length)
        self.seekbar.hold(target, length)
        self.player.set_time(target)
        self.preview_seek(self.seekbar.value())

    def preview_seek(self, value):
        length = self.player.get_length()
        self.time_label.setText(f'{format_time(int(value / 10000 * length))} / {format_time(length)}')

    def seek_slider(self):
        if self.current and not self.busy and self.player.get_length() > 0:
            target = int(self.seekbar.value() / 10000 * self.player.get_length())
            self.set_playback_position(target, self.player.get_length())

    def enter_fullscreen(self):  # Enter 和按钮切换仅视频全屏。
        self.video_fullscreen.toggle()  # 目录和导航隐藏，鼠标移动时显示控制栏。

    def exit_fullscreen(self):  # Esc 恢复进入全屏前的窗口与分隔比例。
        self.video_fullscreen.exit()  # 非全屏状态下不改变用户窗口布局。

    def eventFilter(self, obj, event):  # 在应用级统一处理快捷键优先级。
        if self.chrome_event_filter(obj, event):
            return True
        if event.type() != QEvent.KeyPress:
            return False
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return False  # 菜单与模态窗口先处理 Esc 和方向键，不关闭其所属浮层。
        if hasattr(self, 'playback_options'):
            if event.key() == Qt.Key_Escape and self.playback_options.popup_visible():
                self.playback_options.dismiss()
                return True
            if self.playback_options.rating_popup.handle_key(event):
                return True
        # Direct Qt dispatch and IME events can target the edit before an owned
        # tool window has completed activation. Respect that receiver as well.
        focus = obj if isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)) else QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) or isinstance(focus, QComboBox) and focus.isEditable():  # 文本编辑时所有普通键保持输入用途。
            return False  # 不触发播放、分类或跳转。
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:  # 仅将精确的 Ctrl+D 组合用于视频删除。
            if not event.isAutoRepeat():  # 长按不连续删除多个视频。
                self.delete_video()  # 根据显式选择或当前播放身份执行回收。
            return True  # 不让目录控件重复处理组合键。
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):  # 保留其他系统和编辑组合键。
            return False  # 不拦截复制粘贴等操作。
        actions = {Qt.Key_Space: self.toggle, Qt.Key_X: lambda: self.advance(1), Qt.Key_Z: lambda: self.advance(-1), Qt.Key_Left: lambda: self.seek(-5000), Qt.Key_Right: lambda: self.seek(5000), Qt.Key_A: lambda: self.seek(-5000), Qt.Key_D: lambda: self.seek(5000), Qt.Key_Return: self.enter_fullscreen, Qt.Key_Enter: self.enter_fullscreen, Qt.Key_Escape: self.exit_fullscreen, Qt.Key_Q: self.tags_dialog, Qt.Key_R: self.rating_dialog, Qt.Key_W: self.favorite}  # 左/A 后退五秒，右/D 快进五秒，组合键及输入优先。
        if event.key() in actions:  # 仅拦截已定义的按键。
            if not event.isAutoRepeat() or event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_A, Qt.Key_D):  # 四个进度键均允许长按连续跳转，其他字母不重复操作。
                actions[event.key()]()  # 在主线程执行操作。
            return True  # 避免树视图再次消费方向键。
        return False  # 其他按键保持默认行为。

    def refresh_deleted(self, vids):  # 删除后刷新浏览显示而不重排原播放索引。
        self.thumbnail_service.mark_deleted(vids)  # 后台旧请求不再生成已删除视频的缓存。
        for snapshot in (self.browsing, self.context):  # 浏览目录与播放上下文各自维护排除身份。
            if snapshot:  # 启动任务恢复时可能尚无目录。
                snapshot.excluded.update(vids)  # 所有已知硬链接行同时消失。
        for vid in vids:  # 清除同一身份共用的缩略图缓存。
            self.thumbnails.images.pop(vid, None)  # 释放内存图片。
            self.thumbnails.errors.pop(vid, None)  # 不保留失效错误。
            try:  # 派生缓存清理失败不应阻止已成功删除后的连播。
                (self.store.directory / 'thumbnails' / f'{vid}.jpg').unlink(missing_ok=True)  # 仅删除本应用的派生缓存。
            except OSError:  # 病毒扫描等短暂占用可留待后续缓存清理。
                logging.warning('删除后的缩略图缓存暂时无法清理：%s', vid)  # 视频文件操作成功状态仍然准确。
        if self.browsing:  # 保留导入目录和已展开层级。
            model = self.tree.model()  # 获取当前轻量树模型。
            expanded = {node[1] for node in model.nodes if node[0] == 'folder' and self.tree.isExpanded(self.folder_index(node[1]))}  # 保存用户展开的目录。
            model.beginResetModel()  # 告知视图原显示行数已经改变。
            model.endResetModel()  # 原快照视频索引仍保持有效。
            for folder in expanded:  # 恢复可见目录层级。
                self.tree.expand(self.folder_index(folder))  # 不强制重新折叠用户目录。
            self.file_count.setText(f'{sum(len(self.browsing.visible_files(folder)) for folder in self.browsing.folders)} 部')  # 数量不包含已删除视频。

    def folder_index(self, folder):  # 从浏览快照构造一个文件夹索引。
        model = self.tree.model()  # 使用当前模型的稳定节点引用。
        row = 0 if folder == self.browsing.root else self.browsing.folders[str(Path(folder).parent)][0].index(folder)  # 文件夹顺序不会随视频删除变化。
        node = ('folder', folder, -1)  # 与 TreeModel 的目录节点格式一致。
        return model.createIndex(row, 0, model.nodes.setdefault(node, node))  # 支持恢复嵌套展开状态。

    def clear_player(self):
        self.seek_notice.clear()
        self.current = None
        self.playback.clear()
        self.refresh_title()
        self.player.stop()
        self.player.set_media(None)
        self.player_empty.show()
        self.now.setText('播放器')
        self.media_badge.setText('等待播放')
        self.seekbar.hold(0, 0)
        self.time_label.setText('00:00 / 00:00')
        self.sync_play_button()

    def after_deleted_current(self, context, location):  # 使用删除前的播放上下文自动寻找下一条。
        self.clear_player()  # 在异步扫描前清除不存在的当前身份。
        self.busy = True  # 防止等待下一条时收到重复删除或切换请求。
        cancel = threading.Event()  # 允许沿用同一套可取消导航规则。
        self.navigation_cancel = cancel  # 正常退出时可取消后续扫描。
        self.cancel_button.setEnabled(True)  # 删除后的大型同级目录扫描也允许取消。
        def ready(target, error):  # 目标准备完成后回到主线程播放。
            self.busy = False  # 恢复常规操作。
            self.cancel_button.setEnabled(False)  # 目标扫描结束后恢复按钮状态。
            if error:  # 无权限等失败不伪装成正常连播。
                self.fail(f'删除完成，查找下一个视频失败：{error}')
            elif target:  # 与 X 相同的目录边界内存在下一条。
                self.start(context, target)  # 自动播放，仍保留原来的目录顺序。
                self.message('已移入回收站，正在播放下一个视频。')  # 简短反馈成功和切换结果。
            else:  # 没有后续视频时不循环到开头。
                self.message('已移入回收站，没有下一个视频，播放已停止。')  # 明确停止原因。
        self.work(lambda: context.step_loaded(location, 1, self.store, cancel), ready)  # 跨同级目录扫描不阻塞界面。


    def delete_video(self, _target=None, _context=None):
        if self.busy and not self.tag_drafts.saving:
            self.message('文件任务正在处理，请稍候。')
            return
        selected = self.tree.selectionModel().selectedIndexes() if self.tree.selectionModel() and self.sidebar_mode == 'files' and self.sidebar.isVisible() and not self.video_fullscreen.active else []
        item = self.sidebar_list.currentItem() if self.sidebar_mode != 'files' and self.sidebar.isVisible() and not self.video_fullscreen.active else None
        vid = _target or (item.data(Qt.UserRole) if item else None) or next((index.data(Qt.UserRole) for index in selected if index.data(Qt.UserRole)), None) or self.current
        if not vid:
            self.message('请先选中或播放一个视频。')
            return
        context = _context
        if context is None and vid == self.current:
            context = (self.context, self.location)
        elif context is None and item is None:
            index = next(index for index in selected if index.data(Qt.UserRole) == vid)
            _, folder, number = index.internalPointer()
            context = (self.browsing, (folder, number))
        self.user_actions.request(lambda: self._delete_video(vid, context), self.playback_options.flush_pending)

    def _delete_video(self, vid, context):
        playing = vid == self.current
        if context is None:
            try:
                folder = self.catalog.resolve(vid).parent
            except OSError as error:
                self.fail(error)
                return
            self.busy = True
            cancel = threading.Event()
            self.navigation_cancel = cancel
            def ready(result, error):
                self.busy = False
                if error:
                    self.fail(error)
                    return
                snapshot, _ = result
                location = next(((directory, number) for directory, (_, files) in snapshot.folders.items()
                                 for number, (entry_id, _) in enumerate(files) if entry_id == vid), None)
                if location is None:
                    self.fail('所选视频已不可访问。')
                    return
                self._delete_video(vid, (snapshot, location))
            self.work(lambda: scan(folder, self.store, cancel), ready)
            return
        snapshot, location = context
        self.thumbnail_service.mark_deleting({vid}, True)
        self.message('正在移入回收站……')
        operation = self.file_tasks.run(self._file_work(lambda: self.deleter.submit(vid)),
                                        policy=FileTaskPolicy(release_media=playing))
        def completed(outcome):
            self.thumbnail_service.mark_deleting({vid}, False)
            if not outcome.succeeded:
                self._report_file_result(outcome)
                return
            self.refresh_deleted({vid})
            if not playing:
                self.save()
            self.after_deleted_current(snapshot, location)
        operation.on_finished(completed)

    def favorite(self, toggle=False):
        if self.current and not self.busy:
            star = self.catalog.video(self.current)['star']
            value = int(not star) if toggle else 1
            self.catalog.set_favorite(self.current, value)
            self.refresh_title()

    def tags_dialog(self):
        if self.current and not self.busy:
            panel = self.playback_options.tags_popup
            panel.dismiss() if panel.isVisible() else panel.open_above()

    def rating_dialog(self, vid=None):
        vid = vid or self.current
        if not vid or self.busy:
            return
        if vid == self.current:
            panel = self.playback_options.rating_popup
            panel.dismiss() if panel.isVisible() else panel.open_above()
            return
        from score_editor import ScoreEditor
        dialog = ScoreEditor(self.catalog.video(vid), self)
        if dialog.exec() == QDialog.Accepted:
            self.set_rating(vid, dialog.value)

    def set_rating(self, vid, score):
        if self.busy or self.catalog.video(vid) is None:
            return
        video = self.catalog.video(vid)
        if video['score'] == score:
            return
        if video['archived']:
            self.archive(vid, score, json.loads(video['tags']))
        else:
            self.catalog.set_score(vid, score)
            self.video_details[vid] = self.catalog.video(vid) or {}
            self.refresh_title()

    def refresh_names(self, vids):  # 批次完成或部分失败后显示数据库实际提交的名称。
        rows = self.catalog.video_details(vids)
        self.video_details.update(rows)
        names = {vid: row['name'] for vid, row in rows.items()}
        for snapshot in (self.browsing, self.context):  # 两套快照都只更新文字，不重排原序号。
            if snapshot:  # 启动恢复时可能没有目录。
                for children, files in snapshot.folders.values():  # 遍历现有显示与播放条目。
                    for number, (entry_id, entry_name) in enumerate(files):  # 使用视频身份定位全部硬链接入口。
                        if entry_id in names:  # 同一视频的多个行同步显示名称。
                            files[number] = (entry_id, names[entry_id])  # 保持原目录上下文和索引。
                snapshot.visible_cache.clear()  # 不复用旧显示名称缓存。
        self.tree.viewport().update()  # 只刷新可见区域，不折叠目录。

    def _begin_file_task(self, policy):
        self.save()
        video = self.catalog.video(self.current) if self.current else None
        bookmark = (self.current, video['position'] if video else 0,
                    self.playback.paused_intent(self.player.get_state() != self.vlc.State.Playing),
                    policy.release_media)
        self.busy = True
        self.thumbnail_service.pause(True)
        try:
            if policy.cancel_navigation:
                self.scan_cancel.set()
                self.scan_serial += 1
                self.navigation_cancel.set()
                self.cancel_button.setEnabled(False)
            if policy.release_media:
                self.player.stop()
                self.player.set_media(None)
        except Exception:
            self.busy = False
            self.thumbnail_service.pause(False)
            raise
        return bookmark

    def _end_file_task(self, bookmark):
        self.busy = False
        self.thumbnail_service.pause(False)
        vid, position, paused, released = bookmark
        if released and vid:
            if self.catalog.video(vid) is None:
                self.clear_player()
            else:
                try:
                    self.play_path(self.catalog.resolve(vid), position, paused)
                except OSError:
                    self.clear_player()
                    raise

    def _file_work(self, function):
        def run():
            self.thumbnail_service.stop()
            return function()
        return run

    def _report_file_result(self, outcome):
        if outcome.error:
            recovery = '\n可在“更多 → 文件任务”恢复。' if outcome.recoverable else '\n修改未完成，请修正后重试。'
            self.fail(str(outcome.error) + recovery)

    def apply_tags(self, vid, tags, schema, prompt_score=True):
        if self.busy or not self.ensure_storage():
            return Operation.cancelled()
        self.message('正在应用标签并同步相关视频……')
        operation = self.file_tasks.run(self._file_work(
            lambda: self.tag_migration.submit(vid, self.catalog.video(vid)['score'], tags, schema)))
        def completed(outcome):
            updated = outcome.value or [row['id'] for row in self.catalog.videos('archived')]
            self.refresh_names(updated)
            self.refresh_title()
            self._report_file_result(outcome)
            if outcome.succeeded:
                self.message(f'标签已应用，已同步 {len(updated)} 个视频。')
                if prompt_score:
                    QTimer.singleShot(0, lambda: self.rating_dialog(vid))
        operation.on_finished(completed)
        return operation

    def archive(self, vid, score, tags):
        if self.busy or not self.ensure_storage():
            return Operation.cancelled()
        self.message('正在归档，完成后恢复原进度和播放状态。')
        operation = self.file_tasks.run(self._file_work(lambda: self.archiver.submit(vid, score, tags)),
                                        policy=FileTaskPolicy(release_media=vid == self.current))
        def completed(outcome):
            self.refresh_names([vid])
            self.refresh_title()
            self._report_file_result(outcome)
        operation.on_finished(completed)
        return operation

    def library(self, mode):  # 显示互相独立的历史和收藏列表。
        if self.busy:  # 归档过程中不恢复其他视频。
            self.message('请等待归档完成。')  # 明确忙碌状态。
            return  # 不打开可切换视频的列表。
        dialog, layout = QDialog(self), QVBoxLayout()  # 创建列表弹窗。
        dialog.setWindowTitle({'videos': '历史视频 · 双击续播', 'folders': '历史文件夹 · 双击仅加载目录', 'stars': '收藏列表 · 双击续播'}[mode])  # 明确不同打开行为。
        dialog.resize(760, 480)  # 为完整路径和缩略图留出空间。
        dialog.setLayout(layout)  # 安装列表布局。
        listing = QListWidget()  # 创建可双击列表。
        if mode != 'folders':  # 视频历史和收藏直接逐行显示大缩略图。
            listing.setItemDelegate(VideoDelegate(self.thumbnails, listing, current_video=lambda: self.current, details=self.video_details, theme_owner=self))  # 不要求先选中记录才显示画面。
            self.thumbnails.changed.connect(listing.viewport().update)  # 异步完成后刷新当前可见列表。
        layout.addWidget(listing)  # 列表填满弹窗。
        rows = self.catalog.folders() if mode == 'folders' else self.catalog.videos(mode)  # 独立查询三类记录。
        for row in rows:  # 为每条历史或收藏创建一行。
            item = QListWidgetItem(row['path'] if mode == 'folders' else f'{row["name"]}  ·  {format_time(row["position"])}  ·  {"未评分" if row["score"] is None else str(row["score"]) + "分"}', listing)  # 显示身份对应的进度评分。
            item.setData(Qt.UserRole, row['path'] if mode == 'folders' else row['id'])  # 视频列表以 ID 而非路径识别。
        def opened(item):  # 双击列表项执行对应恢复。
            key = item.data(Qt.UserRole)  # 读取视频 ID 或历史目录。
            try:  # 提前处理文件失效问题。
                folder = Path(key) if mode == 'folders' else self.catalog.resolve(key).parent  # 恢复当前有效所在目录。
                if not folder.is_dir():  # 历史目录可能已被删除。
                    raise FileNotFoundError(f'目录不存在：{folder}')  # 明确提示失效位置。
                dialog.accept()  # 关闭列表后开始扫描。
                self.load_folder(str(folder), None if mode == 'folders' else key)  # 历史文件夹绝不自动播放。
            except OSError as error:  # 缺失记录不匹配同名文件。
                QMessageBox.warning(dialog, '无法打开', str(error))  # 保留列表方便选择其他项目。
        listing.itemDoubleClicked.connect(opened)  # 双击才触发恢复。
        if mode == 'stars':  # 收藏列表提供明确取消操作。
            remove = QPushButton('取消选中视频的收藏')  # 不借用 W 作为取消开关。
            def remove_star():  # 仅取消当前列表选中条目。
                item = listing.currentItem()  # 获取选择的视频。
                if item:  # 空选择不修改记录。
                    self.catalog.set_favorite(item.data(Qt.UserRole), False)  # 收藏取消不移动文件。
                    listing.takeItem(listing.row(item))  # 从当前列表移除显示。
                    self.refresh_title()  # 同步当前视频收藏标志。
            remove.clicked.connect(remove_star)  # 绑定取消收藏操作。
            layout.addWidget(remove)  # 放置独立取消入口。
        preview = QLabel('选择视频后异步读取缓存缩略图')  # 缩略图只为实际选中记录生成。
        layout.addWidget(preview)  # 明确软件内部的预览位置。
        if mode != 'folders':  # 文件夹历史不需要视频缩略图。
            def selection():  # 为当前选择请求共享缩略图。
                item = listing.currentItem()  # 获取当前视频项。
                if not item:  # 空列表不执行解码。
                    return  # 保持初始提示。
                vid = item.data(Qt.UserRole)  # 多个硬链接入口共用视频 ID。
                def thumb_ready(path, error):  # 后台完成后只更新仍打开的弹窗。
                    if dialog.isVisible() and listing.currentItem() and listing.currentItem().data(Qt.UserRole) == vid:  # 防止晚到结果覆盖新选择。
                        if error:  # 不支持的编码显示文字而非卡死。
                            preview.setText('缩略图不可用：' + str(error))  # 与播放器兼容性分开报告。
                        else:  # 已生成的图片可安全在主线程显示。
                            from PySide6.QtGui import QPixmap  # 图片对象只在 GUI 线程构造。
                            preview.setPixmap(QPixmap(str(path)))  # 展示共享缓存图片。
                self.work(lambda: self.thumbnail_service.generate(vid), thumb_ready)  # 解码和文件读取均在后台。
            listing.currentItemChanged.connect(selection)  # 选中视频才请求预览。
        dialog.exec()  # 模态窗口优先处理所有按键。


    def task_dialog(self):  # 展示真实归档阶段和失败信息。
        dialog, layout = QDialog(self), QVBoxLayout()  # 创建任务诊断窗口。
        dialog.setWindowTitle('文件任务与恢复')  # 统一展示归档和删除任务。
        dialog.resize(850, 420)  # 容纳任务标识和错误。
        dialog.setLayout(layout)  # 安装任务布局。
        text = QPlainTextEdit()  # 以只读文本展示持久任务。
        text.setReadOnly(True)  # 防止用户直接改写日志。
        kinds = {'hierarchy_jobs': '标签结构', 'jobs': '归档', 'deletion_jobs': '删除'}
        text.setPlainText('\n\n'.join(f'{kinds[row["kind"]]} {row["id"]}  [{row["state"]}]\n{row["error"] or "无错误"}' for row in self.catalog.task_history()) or '暂无文件任务。')
        layout.addWidget(text)  # 放置任务日志。
        retry = QPushButton('重试所有未完成任务')  # 明确执行恢复动作。
        retry.clicked.connect(lambda: (dialog.accept(), self.retry_jobs()))  # 关闭列表后异步恢复。
        layout.addWidget(retry)  # 提供可见恢复入口。
        dialog.exec()  # Esc 优先关闭当前弹窗。

    def retry_jobs(self):
        if self.busy:
            return
        pending = {row['video'] for row in self.catalog.pending_tasks('deletion_jobs')}
        context, location, active = self.context, self.location, self.current
        tag_plans = [json.loads(row['plan']) for row in self.catalog.pending_tasks('hierarchy_jobs')]
        self.thumbnail_service.mark_deleting(pending, True)
        self.message('正在恢复未完成文件任务……')
        def recover():
            errors = self.archiver.recover() + self.tag_migration.recover()
            if not errors:
                errors += self.deleter.recover()
            if errors:
                raise RuntimeError('\n'.join(errors))
        operation = self.file_tasks.run(self._file_work(recover))
        def recovered(outcome):
            if outcome.succeeded:
                self.tag_drafts.reconcile(entry['video'] for plan in tag_plans for entry in plan['videos']
                                          if self.catalog.video(entry['video']) is not None)
            if self.legacy_storage_recovery and not self.has_pending_file_tasks():
                self.archiver.root = self.storage.root
                self.legacy_storage_recovery = False
            self.refresh_names([entry['video'] for plan in tag_plans for entry in plan['videos']])
            self.thumbnail_service.mark_deleting(pending, False)
            deleted = {vid for vid in pending if self.catalog.video(vid) is None}
            self.refresh_deleted(deleted)
            self._report_file_result(outcome)
            if active in deleted:
                self.after_deleted_current(context, location)
            else:
                self.refresh_title()
                if outcome.succeeded:
                    self.message('文件任务恢复完成。')
        operation.on_finished(recovered)

    def help_dialog(self):  # 显示核心交互和部署说明。
        self.message('Ctrl+D：选中视频优先，否则删除当前视频；移入回收站后自动播放下一条，末尾停止。')  # 帮助关闭后仍显示新增快捷键说明。
        QMessageBox.information(self, 'MoPlayer 使用说明', f'拖入一个文件夹，双击视频播放。\n空格：播放/暂停；X/Z：下一个/上一个；左方向键/A：后退5秒；右方向键/D：快进5秒。\nEnter：切换仅视频全屏；鼠标移动显示控制栏；Esc：优先关闭弹窗，其次恢复原布局。\nQ：标签确认后归档；R：整数评分；W：仅添加收藏；Ctrl+D：移入回收站后播放下一条。\n归档根目录：{self.storage.root or "未设置，请在右上角设置中选择"}\n归档期间安全释放并重载视频，保持进度、暂停状态与原播放顺序。\n数据保存在程序旁 data 目录；启动不会恢复目录或自动播放。\n资源管理器缩略图取决于系统缩略图提供程序，详见交付说明。')  # 说明四个进度键并区分 D 与 Ctrl+D。

    def explorer_thumbnail_dialog(self):  # 为资源管理器的视频缩略图提供一次性启用与修复入口。
        if getattr(self, 'thumbnail_setup_pending', False):  # 避免同时运行多个组件配置任务。
            self.message('系统缩略图配置正在处理，请等待完成。')  # 给出真实任务状态。
            return  # 不重复下载或触发 UAC。
        dialog = QMessageBox(self)  # 启用前说明系统关联与便携运行的区别。
        dialog.setWindowTitle('资源管理器 · 视频缩略图支持')  # 明确该设置影响文件夹中的缩略图。
        dialog.setText('启用后，资源管理器会为新旧视频按需生成缩略图，并兼容 MoPlayer 默认打开方式。')  # 说明按文件类型长期生效。
        dialog.setInformativeText('使用 Icaros 3.3.6 官方便携组件，支持常见 H.264、HEVC、VP9、AV1 等编码。\n组件保存在 E:\\tools\\videoplayerenv\\plugins，首次配置可能弹出 Windows UAC。\n此功能需要单独注册系统组件；移动播放器仍可运行，但请保留上述组件目录。损坏、加密或组件不支持的文件仍可能只显示图标。')  # 给出用户需要了解的部署约束。
        enable = dialog.addButton('启用 / 修复', QMessageBox.AcceptRole)  # 用户明确选择才进行注册与下载。
        dialog.addButton('取消', QMessageBox.RejectRole)  # 取消不更改系统配置。
        dialog.exec()  # 保持对话框输入优先规则。
        if dialog.clickedButton() is not enable:  # 关闭或 Esc 均视为放弃本次操作。
            return  # 不自动安装组件。
        self.thumbnail_setup_pending = True  # 将下载与配置状态发布到界面。
        self.message('正在配置全局视频缩略图支持；如出现 Windows UAC，请确认组件注册。')  # 后台处理期间界面仍可响应。
        def completed(result, error):  # 主线程接收实际配置结果。
            self.thumbnail_setup_pending = False  # 无论结果如何都允许后续重试。
            if error:  # 不把下载、权限或注册失败显示为成功。
                self.fail(error)  # 明确显示真实原因。
            else:  # 系统组件及全部视频关联配置完成。
                self.message('全局视频缩略图支持已启用。请重新打开文件夹并使用大图标查看。')  # 不需要逐个视频手动修复。
        from setup_explorer_thumbnails import install  # 按需加载系统集成工具。
        self.work(install, completed)  # 网络、解压和 UAC 等待均不阻塞播放界面。

    def closeEvent(self, event):
        if getattr(self, 'thumbnail_setup_pending', False):
            self.message('系统缩略图正在配置，请等待完成后退出。')
            event.ignore()
            return
        if self.busy and not self.tag_drafts.saving:
            self.message('文件任务正在处理，请等待完成后退出。')
            event.ignore()
            return
        operation = self.playback_options.flush_pending()
        if operation.pending:
            self.user_actions.request(lambda: QTimer.singleShot(0, self.close), self.playback_options.flush_pending, closing=True)
            event.ignore()
            return
        if not operation.outcome.succeeded:
            event.ignore()
            return
        self.scan_cancel.set()
        self.navigation_cancel.set()
        self.thumbnails.closing = True
        self.save()
        self.timer.stop()
        self.seekbar.animation.stop()
        self.playback_options.dismiss()
        self.seek_notice.clear()
        self.video_fullscreen.exit()
        self.player.stop()
        QApplication.instance().removeEventFilter(self)
        event.accept()

def main():  # 程序统一启动入口。
    import ctypes  # 为 Windows 任务栏设置独立的应用身份。
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MoPlayer.Desktop')  # 让任务栏使用云璃应用图标。
    app = QApplication(sys.argv)  # 初始化 Windows GUI 应用。
    app.setWindowIcon(QIcon(str(BUNDLE / 'assets/yunli.ico')))  # 为主窗口与弹窗提供统一图标。
    directory = BASE / 'data'  # 便携数据与程序保持同目录。
    try:  # 数据目录不可写时明确说明原因。
        directory.mkdir(parents=True, exist_ok=True)  # 首次启动创建数据文件夹。
        lock = QLockFile(str(directory / 'application.lock'))  # 同一数据目录仅允许一个实例写入。
        if not lock.tryLock(100):  # 防止两个进程同时归档相同视频。
            from file_open import forward  # 将外部视频请求交给已有主进程。
            if forward(directory, sys.argv[1] if len(sys.argv) > 1 else None):  # 中文和空格路径通过本地管道传输。
                return 0  # 已由现有窗口接收，不重复打开数据库。
            QMessageBox.warning(None, 'MoPlayer', '现有实例暂时无法接收文件，请稍后重试。')  # 不谎报打开成功。
            return 1  # 安全结束重复进程。
        from logging.handlers import RotatingFileHandler  # 限制日志长期占用。
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[RotatingFileHandler(directory / 'moplayer.log', maxBytes=4 * 1024 * 1024, backupCount=3, encoding='utf-8')])  # 日志全部写入便携数据目录。
        window = Window(directory)  # 创建主界面但不导入历史目录。
        window.show()  # 展示可直接操作的播放器。
        QTimer.singleShot(0, window.initialize_storage)  # 首次正常运行选择存储路径，不影响隔离专项构造窗口。
        from file_open import FileOpenServer  # 加载默认应用文件接收服务。
        window.file_server = FileOpenServer(window, directory)  # 在数据库锁保护下创建唯一接收端点。
        if len(sys.argv) > 1:  # 只有用户通过文件关联明确打开时才自动播放。
            window.file_server.pending.append(sys.argv[1])  # 普通无参数启动仍不恢复目录或视频。
        result = app.exec()  # 进入原生事件循环。
        QThreadPool.globalInstance().waitForDone()  # 等待已取消的工作线程安全退出。
        window.thumbnails.pool.waitForDone()  # 等待独立缩略图池安全关闭，避免销毁运行中的 FFmpeg 任务。
        lock.unlock()  # 正常释放单实例锁。
        return result  # 返回 GUI 退出状态。
    except Exception as error:  # 启动失败给出可见提示。
        QMessageBox.critical(None, 'MoPlayer 启动失败', str(error))  # 避免无控制台便携程序静默退出。
        return 1  # 报告失败退出码。

if __name__ == '__main__':  # 仅直接运行时启动应用。
    if len(sys.argv) == 3 and sys.argv[1] == '--ui-refresh-test':
        from verify_ui_refresh import run
        try:
            run(sys.argv[2])
        except Exception:
            import traceback
            traceback.print_exc()
            sys.exit(1)
        else:
            sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == '--seek-notice-test':  # 只验证快进后退的两行进度提示。
        from verify_seek_notice import run  # 生成与用户素材隔离的真实一分钟视频。
        run(sys.argv[2])  # 专项不打开用户数据库。
        sys.exit(0)  # 完成后不进入普通启动流程。
    if len(sys.argv) == 3 and sys.argv[1] == '--storage-test':  # 只验证首次选择与设置中更改存储路径。
        from verify_storage import run  # 使用明确指定的隔离数据库和归档文件夹。
        run(sys.argv[2])  # 不打开真实用户数据库。
        sys.exit(0)  # 专项完成后不进入正常启动流程。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-nesting-test':  # 仅检查互斥展开、父类嵌套和删除标签。
        from verify_tag_nesting import run  # 测试使用指定目录的隔离视频和数据库。
        run(sys.argv[2])  # 不启动正常播放器或读取用户数据。
        sys.exit(0)  # 专项结束立即退出。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-cards-test':  # 仅检查新胶囊标签与半颗心评分，不运行完整回归。
        from verify_tag_cards import run  # 专项直接使用包内正式界面和隔离样例。
        run(sys.argv[2])  # 测试输出必须由调用者明确指定。
        sys.exit(0)  # 专项完成后不打开用户数据库或主窗口。
    if len(sys.argv) == 3 and sys.argv[1] == '--tag-hierarchy-test':  # 验证全局标签层级和完成后的自动按钮评分。
        from verify_tag_hierarchy import run  # 测试只使用明确指定的隔离目录。
        sys.exit(run(sys.argv[2]))  # 生成实际文件、界面截图及检查报告。
    if len(sys.argv) == 3 and sys.argv[1] == '--delete-test':  # 用隔离样例验证真实快捷键回收与自动连播。
        from verify_delete import run  # 按需加载删除验收入口。
        sys.exit(run(sys.argv[2]))  # 不使用用户的视频与元数据。
    if len(sys.argv) == 3 and sys.argv[1] == '--explorer-thumbnail-test':  # 验证系统组件及 MoPlayer 两种默认关联。
        from verify_explorer_thumbnails import run  # 按需加载全局缩略图验收。
        sys.exit(run(sys.argv[2]))  # 样例和报告写入独立目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--ui-test':  # 便携版可检查外观资源与背景设置。
        from verify_ui import run  # 按需加载外观回归检查。
        sys.exit(run(sys.argv[2]))  # 将结果保存到独立测试目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--thumbnail-test':  # 便携版可直接验证缩略图实际显示。
        from verify_thumbnails import run  # 按需加载可见缩略图回归检查。
        sys.exit(run(sys.argv[2]))  # 将截图和报告写入指定隔离目录。
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':  # 提供便携版无开发环境的自检入口。
        from verify import run  # 按需加载验收代码。
        sys.exit(run(sys.argv[2]))  # 将测试数据写入明确指定的目录。
    sys.exit(main())  # 交付操作系统最终退出状态。

