import json  # 记录本次存储路径专项结果。
import sys  # 接收明确的隔离测试目录。
import time  # 为后台验证设置有限等待。
from pathlib import Path  # 所有样例都位于隔离目录。
from unittest.mock import patch  # 仅注入配置提交失败，不修改用户文件。
from PySide6.QtCore import QTimer, QThreadPool  # 等待真实后台验证回调。
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # 检查首次弹窗与右上角菜单。
from archive_settings_dialog import ArchiveSettingsDialog as StorageDialog
from storage_settings import StorageSettings, validate_storage_path  # 使用正式设置实现。
from core import identity  # 确认移动后保留正确的文件实体。

def run(destination):  # 不运行播放或完整回归测试。
    from app import Window  # 在正式运行库环境中构建真实窗口。
    output = Path(destination).absolute()  # 不使用真实用户数据或归档目录。
    output.mkdir(parents=True, exist_ok=True)  # 保存样例和证据。
    app = QApplication.instance() or QApplication([])  # 初始化真实 Qt 对话框。
    window = Window(output / 'data')  # 不触发正常启动的全局路径选择。
    window.show()  # 允许设置窗口实际渲染。
    checks, failures = [], []  # 异步回调错误由主测试线程统一处理。
    def check(name, passed):  # 只记录实际完成的相关验证。
        checks.append({'name': name, 'passed': bool(passed)})  # 逐项保存结果。
        assert passed, name  # 失败必须停止而非误报通过。
    check('首次默认使用程序旁video', window.storage.root == output/'video' and window.archiver.root == output/'video')
    window.initialize_storage()  # 使用正常启动调用的同一入口。
    check('首次无强制弹窗不自动播放', app.activeModalWidget() is None and not window.storage.file.exists() and window.current is None and window.library_controller.browsing is None)
    sample = output / 'sample.mp4'  # 创建无需解码的归档样例。
    sample.write_bytes(b'isolated storage settings fixture')  # 不读取真实视频。
    vid = window.store.register(sample)  # 记录稳定身份。
    window.archiver.submit(vid, 8, ['样例'])
    check('默认归档创建video并保留原名', window.store.resolve(vid) == output/'video'/'8分'/'样例'/'sample.mp4')
    root_a, root_b = output / '存储A', output / '存储B'  # 模拟用户自定义的两个目录。
    def submit(root, screenshot=None):  # 操作真实模态表单并等待后台检查。
        def fill():  # 窗口显示后输入新路径。
            try:  # 回调错误不能遗失在 Qt 信号中。
                dialog = app.activeModalWidget()  # 必须是真正的存储设置弹窗。
                assert isinstance(dialog, StorageDialog)  # 保证菜单连接正确。
                dialog.path.setText(str(root))  # 输入中文目录。
                if screenshot:  # 保存实际设置窗口外观。
                    dialog.grab().save(str(output / screenshot))  # 不使用原型截图。
                dialog.buttons.button(dialog.buttons.StandardButton.Save).click()  # 经过用户可见的保存按钮。
                deadline = time.monotonic() + 8  # NTFS 小探针不应长时间等待。
                def watch():  # 遇到验证失败时退出而不是卡住测试。
                    if dialog.isVisible() and (not dialog.pending or time.monotonic() > deadline):  # 保存失败或超时均保留真实错误。
                        failures.append(dialog.status.text())  # 保存错误原因供主线程断言。
                        if not dialog.pending:  # 不打断仍在执行的文件验证。
                            dialog.reject()  # 安全退出失败的表单。
                    elif dialog.isVisible():  # 后台仍在工作。
                        QTimer.singleShot(20, watch)  # 继续处理正常事件循环。
                QTimer.singleShot(20, watch)  # 等待能力验证和配置提交。
            except Exception as error:  # 回调失败交给同步断言处理。
                failures.append(str(error))  # 不隐藏界面错误。
                app.activeModalWidget().reject()  # 避免模态循环挂起。
        QTimer.singleShot(0, fill)  # 调用方随后打开正式设置窗口。
    submit(root_a, 'first-storage.png')  # 首次设置新路径。
    window.storage_dialog()  # 默认可用后，通过设置修改。
    check('首次保存通过NTFS硬链接检查并持久化', not failures and window.archiver.root == root_a and StorageSettings(window.store.directory).root == root_a)  # 不只检查输入框。
    window.archiver.submit(vid, 8, ['样例'])  # 后续归档写入已选择目录。
    archived = window.store.resolve(vid)  # 保存原归档有效路径。
    entity = identity(archived)  # 同卷更换目录应保留文件身份。
    window.store.progress(vid, 12345)  # 更换设置不能丢失历史进度。
    check('归档实际使用自定义目录', root_a in archived.parents and archived.exists() and not sample.exists())  # 首次来源按原安全逻辑移出。
    submit(root_b, 'change-storage.png')  # 准备通过右上角菜单修改。
    settings = window.findChild(QPushButton, 'settingsButton')  # 定位真实设置入口。
    next(action for action in settings.menu().actions() if action.text() == '归档设置').trigger()  # 菜单必须能打开修改窗口。
    check('右上角设置可修改并保存路径', not failures and window.archiver.root == root_b and StorageSettings(window.store.directory).root == root_b)  # 配置和归档器一致。
    check('保存路径立即整理全部已归档视频且历史有效', not archived.exists() and root_b in window.store.resolve(vid).parents and window.store.video(vid)['position'] == 12345)  # 保存设置会立即整理已归档视频。
    window.archiver.submit(vid, 9, ['样例'])  # 后续修改继续沿用已保存的新路径。
    current = window.store.resolve(vid)  # 使用同一视频 UUID 找到新入口。
    check('后续归档使用新路径并保留身份进度', root_b in current.parents and identity(current) == entity and not archived.exists() and window.store.video(vid)['position'] == 12345)  # 同卷不复制内容。
    before = window.storage.file.read_bytes()  # 保存原子写入失败前配置。
    try:  # 只模拟设置文件最终提交失败。
        with patch('storage_settings.os.replace', side_effect=OSError('隔离验收：写入失败')):  # 不影响任何用户目录。
            window.storage.save(root_a)  # 失败不能切换有效路径。
    except OSError:  # 预期失败保留旧设置。
        pass  # 随后检查磁盘和内存。
    check('配置提交失败保留原路径', window.storage.root == root_b and window.storage.file.read_bytes() == before)  # 不出现界面成功而配置失败。
    window.store.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', ('pending-settings-check', vid, 'planned', '{}', None, time.time()))  # 仅在隔离库检查路径修改保护。
    check('未完成文件任务阻止修改路径', window.storage_dialog() is False and window.archiver.root == root_b)  # 不把同一批次分散到多个根目录。
    window.store.execute('DELETE FROM jobs WHERE id=?', ('pending-settings-check',))  # 移除本次隔离的保护探针记录。
    try:  # 相对路径不能受当前工作目录影响。
        validate_storage_path('relative-folder')  # 不实际创建目录。
        raise AssertionError('相对路径未被拒绝')  # 必须触发校验错误。
    except ValueError:  # 预期拒绝无效路径。
        check('拒绝相对路径', True)  # 保持旧配置。
    called = []  # 检查已配置启动不重复显示首次设置。
    with patch.object(window, 'storage_dialog', side_effect=lambda **kwargs: called.append(True)):  # 只观察是否触发设置入口。
        window.initialize_storage()  # 与正常启动使用同一入口。
    check('已配置启动不重复弹窗', not called)  # 用户无需每次重新选择。
    other = output / 'other.mp4'  # 为批次恢复创建第二个隔离视频。
    other.write_bytes(b'isolated root recovery fixture')  # 不读取用户素材。
    other_id = window.store.register(other)  # 同一批次包含两个不同身份。
    window.archiver.submit(other_id, 6, ['样例'])  # 让公共标签关系变化影响另一已归档视频。
    rows = [{'name': '父类', 'kind': 'major', 'parent': None, 'is_parent': True}, {'name': '样例', 'kind': 'minor', 'parent': '父类'}]  # 新结构需要两个视频同步。
    def stop_batch(stage):  # 模拟首个视频完成后异常退出。
        raise OSError('隔离验收：批次中断')  # 只影响当前验证目录。
    window.tag_migration.fault = stop_batch  # 使用正式持久批次检查点。
    try:  # 确认未完成视频仍等待恢复。
        window.tag_migration.submit(vid, 9, ['样例'], rows)  # 计划冻结当前存储B。
    except OSError:  # 预期中断不代表数据丢失。
        pass  # 随后从持久日志重放。
    window.tag_migration.fault = None  # 恢复时不再注入故障。
    window.archiver.root = root_a  # 模拟重启后外部配置已变，恢复仍应遵守原计划。
    errors = window.tag_migration.recover()  # 读取冻结根目录继续剩余视频。
    check('中断批次恢复沿用原根目录', not errors and all(root_b in window.store.resolve(item).parents and window.store.resolve(item).parent.parent.name == '父类' for item in (vid, other_id)))  # 不把同一任务写入后来修改的位置。
    window.archiver.root = root_b  # 恢复隔离窗口的已保存设置。
    window.close()  # 只关闭本次隔离播放器。
    QThreadPool.globalInstance().waitForDone()  # 不遗留路径验证任务。
    window.thumbnails.pool.waitForDone()  # 等待窗口附属线程安全结束。
    window.store.db.close()  # 释放隔离数据库。
    (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 保存实际专项结果。
    print(f'存储路径专项：{len(checks)}/{len(checks)} 通过')  # 不宣称运行完整回归。

if __name__ == '__main__':  # 只显式调用时运行该专项。
    run(sys.argv[1])  # 所有测试输出由调用者指定。
