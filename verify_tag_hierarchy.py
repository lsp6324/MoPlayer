import json  # 保存实际层级标签和评分验收结果。
import shutil  # 生成不同身份的隔离视频样例。
import subprocess  # 使用实际随包 FFmpeg 创建可播放视频。
import time  # 等待真实异步归档与播放状态。
from pathlib import Path  # 限定测试文件输出边界。
from PySide6.QtCore import Qt, QTimer, QPointF, QPoint, QMimeData, QThreadPool  # 驱动真实 Qt 弹窗与拖放处理。
from PySide6.QtGui import QDropEvent  # 经过生产标签树的拖放处理校验层级。
from PySide6.QtTest import QTest  # 使用真实鼠标按钮与键盘事件。
from PySide6.QtWidgets import QApplication, QPushButton, QComboBox, QDialog, QDialogButtonBox, QMessageBox  # 检查评分按钮、类型控件和真实失败反馈。
from core import Archiver, identity  # 使用真实 NTFS 硬链接归档。
from tag_migration import TagMigration  # 全局批次必须使用隔离归档根目录。
from tag_editor import TagEditor, MIME  # 验证胶囊界面与内部拖动格式。
from score_editor import ScoreEditor  # 验证自动出现的评分界面。

def run(destination):  # 源码和便携 EXE 使用相同验收入口。
    from app import Window, BUNDLE  # 加载真实播放内核和窗口。
    from runtime import load_vlc
    vlc = load_vlc()
    output = Path(destination).absolute()  # 每次测试指定独立目录。
    output.mkdir(parents=True, exist_ok=True)  # 不接触用户视频与数据库。
    samples = output / 'samples'  # 用于原播放上下文的来源目录。
    samples.mkdir()  # 避免复用旧验收视频。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 验证便携版随包工具。
    if not ffmpeg.exists():  # 源码模式使用隔离环境工具。
        import imageio_ffmpeg  # 不依赖系统全局安装。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 定位已有开发依赖。
    first = samples / '1.mp4'  # 创建足够长的真实播放视频。
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=20', '-t', '30', '-c:v', 'libx264', '-threads', '2', '-y', str(first)], check=True, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)  # 隔离生成有真实画面的视频。
    shutil.copyfile(first, samples / '2.mp4')  # 第二条拥有独立文件身份，用于验证全局迁移。
    application = QApplication.instance() or QApplication([])  # 运行真实 Qt 事件循环。
    window = Window(output / 'data')  # 全部用户状态与真实库隔离。
    window.archiver = Archiver(window.store, output / 'archive')  # 绝不写入用户归档根目录。
    window.tag_migration = TagMigration(window.store, window.archiver)  # 批次和评分子任务共用同一个隔离归档器。
    window.show()  # VLC 使用实际原生窗口播放。
    checks = []  # 汇总可核对的验收项目。
    def wait(predicate, seconds=30):  # 等待真正的异步任务完成条件。
        deadline = time.monotonic() + seconds  # 所有等待均有明确上限。
        while time.monotonic() < deadline:  # 不使用固定延时假装归档完成。
            application.processEvents()  # 执行工作线程回调和模态弹窗事件。
            if predicate():  # 检查实际数据库和播放器状态。
                return True  # 完成后立即继续。
            QTest.qWait(30)  # 给后台文件操作和解码器运行时间。
        return False  # 超时必须报告失败。
    def check(name, result):  # 不将失败项目包装成通过。
        checks.append({'name': name, 'passed': bool(result)})  # 保存逐项结果。
        if not result:  # 失败时停止后续测试文件操作。
            raise AssertionError(name)  # 最终进程退出码体现失败。
    def drag_child(editor):  # 使用生产胶囊拖放入口建立角色归属。
        editor.set_parent('绝区零', True)  # 对应右键指定父标签。
        editor.search.clear()  # 显示全部根标签。
        class InternalDrop(QDropEvent):  # 注入同窗口内部拖动来源。
            def source(self):  # 正式处理器仍然校验来源。
                return editor  # 拖动对象由标签编辑器持有。
        mime = QMimeData()  # 与实际胶囊拖动使用相同格式。
        mime.setData(MIME, '爱丽丝'.encode('utf-8'))  # 指定角色标签。
        event = InternalDrop(QPointF(10, 10), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)  # 使用真实 Qt 拖放事件。
        editor.drop_tag(event, '绝区零')  # 调用生产落下校验与草稿更新。
        return event.isAccepted() and editor.schema['爱丽丝']['parent'] == '绝区零' and not editor.expanded  # 拖入不自动展开。
    try:  # 任意失败仍保留报告和界面证据。
        window.thumbnail_service.pause(True)  # 构造旧版样例期间不让缩略图读取马上要移动的来源路径。
        window.load_folder(str(samples))  # 使用正式异步扫描建立原播放上下文。
        check('来源异步扫描完成', wait(lambda: window.library_controller.browsing is not None))  # 等待完整快照。
        context = window.library_controller.browsing  # 归档后仍需保持原播放顺序。
        vids = [entry[0] for entry in context.folders[str(samples)][1]]  # 保存两个稳定身份。
        tags = ['绝区零', '爱丽丝', '黑丝', '足交', 'ASMR', 'cosplay']  # 使用用户给出的六标签场景。
        window.archiver.submit(vids[0], 8, tags)  # 创建旧版平级六入口样例。
        window.archiver.submit(vids[1], 9, ['爱丽丝', 'cosplay'])  # 第二条共享角色标签，评分保持独立。
        window.thumbnail_service.pause(False)  # 样例建立完成后恢复正式缩略图行为。
        for vid in vids:  # 全局迁移应保留这些元数据。
            window.store.execute('UPDATE videos SET star=1,position=1000,played=1 WHERE id=?', (vid,))  # 加入历史、收藏与续播进度。
        old = [Path(row['path']) for row in window.store.query('SELECT path FROM paths')]  # 保存旧平级入口用于检查清理。
        entities = {vid: identity(window.store.resolve(vid)) for vid in vids}  # 保留实际文件实体身份。
        window.start(context, (str(samples), 0))  # 从原播放上下文打开已归档视频。
        check('视频真实解码播放', wait(lambda: window.playback.resume is None and window.player.get_time() > 1100))  # 不仅检查当前 ID。
        window.player.set_pause(1)  # 固定场景以验证弹窗与归档保留暂停。
        check('播放暂停准备完成', wait(lambda: window.player.get_state() == vlc.State.Paused))  # 排除异步暂停未完成的假象。
        draft = TagEditor(json.loads(window.store.video(vids[0])['tags']), window.store.tag_layout(), window)  # 先验证取消不会移动任何文件。
        draft.setModal(True)  # 复用正式弹窗输入优先规则。
        draft.show()  # 实际渲染类型控件与标签树。
        application.processEvents()  # 让模型行具备真实几何。
        check('标签使用胶囊且无类型下拉框', bool(draft.chips) and not draft.findChildren(QComboBox))  # 检查正式界面。
        check('小类类型与拖放建立层级', drag_child(draft))  # 检查生产拖放处理器。
        draft.search.setText('爱丽丝')  # 搜索子类需要保留父级上下文。
        check('搜索小类保留父胶囊但不自动展开', set(draft.chips) == {'绝区零'} and not draft.expanded)  # 搜索不改变展开状态。
        check('确认前全局结构和文件不变', window.store.tag_layout()['爱丽丝']['kind'] == 'major' and all(path.exists() for path in old))  # 拖动草稿不即时移动文件。
        QTest.keyClick(draft, Qt.Key_Escape)  # 用户取消全部草稿。
        check('Esc 取消不应用层级', not draft.isVisible() and window.store.tag_layout()['爱丽丝']['kind'] == 'major')  # 不留下半套全局关系。
        automatic, errors = [], []  # 保存模态回调结果以免异常丢在 Qt 事件中。
        def edit_tags():  # 在正式 Q 弹窗中操作层级。
            try:  # 回调失败时关闭弹窗，交给主流程报告。
                editor = QApplication.activeModalWidget()  # 获取实际生产弹窗。
                if not drag_child(editor):  # 必须由类型选择和拖放路径完成。
                    raise AssertionError('正式标签拖放失败')  # 不直接伪造正确结构。
                editor.search.clear()  # 截图展示完整六标签分组。
                editor.grab().save(str(output / 'tag-editor.png'))  # 保存实际 UI 渲染结果。
                editor.buttons.button(QDialogButtonBox.Ok).click()  # 明确应用全部标签及全局层级。
            except Exception as error:  # 不让异常留在模态循环中。
                errors.append(str(error))  # 最后由主线程断言。
                QApplication.activeModalWidget().reject()  # 安全结束本次测试弹窗。
        deadline = time.monotonic() + 30  # 自动评分必须在整个批次成功后出现。
        def rate_after_apply():  # 观察真实自动弹窗，而不是手动调用评分方法。
            dialog = QApplication.activeModalWidget()  # 检查当前活动弹窗。
            if isinstance(dialog, ScoreEditor):  # 正式代码在标签全部完成后自动创建。
                automatic.append(all('绝区零（爱丽丝）' in window.store.resolve(vid).name for vid in vids) and all(row['state'] == 'done' for row in window.store.query('SELECT state FROM hierarchy_jobs')))  # 评分出现时所有相关视频必须已经迁移。
                automatic.append(len(dialog.hearts) == 5 and not dialog.findChildren(QComboBox))  # 五颗心且没有评分下拉框。
                dialog.grab().save(str(output / 'score-editor.png'))  # 保存真实评分界面。
                QTest.mouseClick(dialog.hearts[3], Qt.LeftButton, pos=QPoint(36, 24))  # 第四颗右半一次提交八分。
            elif time.monotonic() < deadline:  # 等待标签批次完成。
                QTimer.singleShot(30, rate_after_apply)  # 嵌套模态事件循环中也可以继续观察。
        QTimer.singleShot(100, edit_tags)  # 标签界面完成渲染后开始操作。
        QTimer.singleShot(30, rate_after_apply)  # 同时观察自动评分，不抢先创建它。
        window.player_view.toggle_tags()  # 运行用户通过 Q 调用的完整正式流程。
        check('标签全部应用后自动评分', wait(lambda: bool(automatic) and not window.busy) and all(automatic) and not errors)  # 不接受部分迁移就弹窗。
        check('主评分区五颗心且无下拉框', len(automatic) == 2 and automatic[1])  # 与用户明确交互一致。
        name = '1.mp4'  # 父子分组优先，其他标签沿用自然排序。
        primary = output / 'archive' / '8分' / '绝区零' / '爱丽丝' / name  # 小类归档使用实际两层路径。
        check('小类路径与大类括号文件名正确', primary.exists() and window.store.video(vids[0])['name'] == name)  # 验证真实文件系统及数据库。
        first_paths = [Path(row['path']) for row in window.store.query('SELECT path FROM paths WHERE id=?', (vids[0],))]  # 第一条六标签合并父子后有五入口。
        check('父子不重复入口且所有入口硬链接同一实体', len(first_paths) == 5 and all(path.name == name and identity(path) == entities[vids[0]] for path in first_paths) and primary.stat().st_nlink == 5)  # 不增加重复视频内容。
        check('另一评分的视频同步全局角色归属', window.store.video(vids[1])['score'] == 9 and window.store.resolve(vids[1]).name == '2.mp4')  # 迁移全局关系但不改其他视频评分。
        check('原平级入口全部清理', all(not path.exists() for path in old))  # 新入口安全后移除旧路径。
        check('历史收藏进度保持原身份', all(window.store.video(vid)['star'] == 1 and window.store.video(vid)['position'] >= 1000 for vid in vids))  # 两个 UUID 不发生替换。
        check('归档和评分保持原播放顺序及暂停', wait(lambda: window.player.get_state() == vlc.State.Paused) and window.context is context and window.location == (str(samples), 0))  # 层级修改不改连播上下文。
        failures, premature = [], []  # 记录失败时是否错误进入评分。
        def fail_batch(stage):  # 模拟一个视频完成后批次异常中断。
            raise RuntimeError('验收注入的标签迁移中断')  # 仅影响本测试生成的文件和数据库。
        window.tag_migration.fault = fail_batch  # 使用正式批次检查点注入故障。
        failure_deadline = time.monotonic() + 30  # 错误弹窗必须可见且不会无限等待。
        def close_failure():  # 观察正式代码的失败反馈并关闭测试弹窗。
            modal = QApplication.activeModalWidget()  # 读取当前真实弹窗类型。
            if isinstance(modal, QMessageBox):  # 文件任务失败应显示明确错误。
                failures.append(True)  # 记录实际发生了失败反馈。
                modal.accept()  # 不阻塞自动化验收。
            elif isinstance(modal, ScoreEditor):  # 标签部分完成时不应要求评分。
                premature.append(True)  # 记录错误的提前评分行为。
                modal.reject()  # 避免测试挂起。
            elif time.monotonic() < failure_deadline:  # 等待后台注入的异常返回。
                QTimer.singleShot(30, close_failure)  # 持续处理 Qt 主线程事件。
        QTimer.singleShot(30, close_failure)  # 在提交异步任务前开始观察。
        window.classification.apply_tags(vids[0], json.loads(window.store.video(vids[0])['tags']), list(window.store.tag_layout().values()))  # 即使结构不变，也通过正式应用路径验证失败保护。
        check('标签部分失败不提前弹出评分', wait(lambda: bool(failures) and not window.busy) and not premature)  # 不把局部完成显示成整个操作成功。
        check('失败批次保留恢复日志及有效文件', bool(window.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"')) and all(window.store.resolve(vid).exists() for vid in vids))  # 所有视频仍可恢复和播放。
        window.tag_migration.fault = None  # 模拟用户重试时故障消失。
        automatic.clear()  # 重新观察恢复完成后的评分弹窗。
        deadline = time.monotonic() + 30  # 恢复使用同样的有限等待。
        QTimer.singleShot(30, rate_after_apply)  # 只在恢复确实完成后点击评分。
        window.recovery.retry()  # 使用更多 → 文件任务中的正式恢复入口。
        check('恢复全部标签后再自动评分', wait(lambda: bool(automatic) and not window.busy) and all(automatic) and not window.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"'))  # 全局结构、文件和评分状态最终一致。
        for chosen, object_name in [(0, 'score_0'), (None, 'score_unrated')]:  # 明确测试兼容原有的两个特殊状态。
            score = ScoreEditor(window.store.video(vids[0]), window)  # 与自动弹窗使用同一真实组件。
            score.show()  # 创建实际可点击按钮。
            QTest.mouseClick(score.findChild(QPushButton, object_name), Qt.LeftButton)  # 不用下拉框或额外确认。
            check('独立评分状态 ' + object_name, score.result() == QDialog.Accepted and score.value == chosen)  # 零分和未评分严格区分。
    finally:  # 释放测试中的真实播放器与工作线程。
        for widget in application.topLevelWidgets():  # 防止失败时遗留模态测试弹窗。
            if isinstance(widget, QDialog):  # 只处理本进程测试创建的对话框。
                widget.reject()  # 不阻塞退出和报告保存。
        wait(lambda: not window.busy)  # 文件任务达到安全状态后关闭。
        window.close()  # 只更新隔离数据库。
        QThreadPool.globalInstance().waitForDone()  # 等待文件操作线程结束。
        window.thumbnails.pool.waitForDone()  # 取消的 FFmpeg 任务也要释放完毕。
        (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 保存可核对的真实结果。
    return 0  # 所有断言通过后才成功退出。
