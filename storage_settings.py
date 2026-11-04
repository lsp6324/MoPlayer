import json  # 独立保存每位用户的归档位置。
import os  # 原子替换配置并刷新磁盘。
import uuid  # 并发写入时使用独立临时文件。
from pathlib import Path  # 不依赖开发机器的固定盘符。
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QDialogButtonBox  # 构建首次设置和后续修改共用的窗口。
from core import require_ntfs  # 实际验证硬链接能力与写入权限。

def validate_storage_path(value):  # 只接受用户明确选择的本地绝对路径。
    if not value or not str(value).strip():  # 空值不能退回开发机器目录。
        raise ValueError('请选择视频存储文件夹。')  # 提示用户完成必填项。
    root = Path(str(value).strip())  # 保留中文和空格路径。
    if not root.is_absolute():  # 相对路径可能随工作目录变化。
        raise ValueError('存储路径必须是完整的绝对路径。')  # 不擅自补到程序目录。
    for component in (root, *root.parents):  # 归档位置不能经目录链接重定向。
        if component.exists() and (component.is_symlink() or getattr(component.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):  # 与归档安全规则一致地拒绝重解析点。
            raise ValueError('存储路径不能包含目录链接或挂载重解析点。')  # 不保存以后无法安全归档的位置。
    require_ntfs(root)  # 在后台创建小探针，验证 NTFS、权限和实际硬链接。
    return root.absolute()  # 返回通过实际检查的归档根目录。

class StorageSettings:  # 本地偏好不写入源码或公共仓库。
    def __init__(self, directory):  # 配置与便携数据放在一起。
        self.file = Path(directory) / 'storage.json'  # 不更改历史视频数据库位置。
        self.root, self.error = None, ''  # 未配置时没有默认归档盘符。
        try:  # 不把损坏配置当作可用路径。
            settings = json.loads(self.file.read_text(encoding='utf-8'))  # 读取上次明确保存的位置。
            value = settings['archive_root']  # 保持配置格式简单明确。
            if not isinstance(value, str) or not Path(value).is_absolute():  # 拒绝错误类型或相对位置。
                raise ValueError('保存的存储路径无效，请重新选择。')  # 启动时提示重新配置。
            self.root = Path(value)  # 启动不扫描、移动或创建视频文件夹。
        except FileNotFoundError:  # 首次启动不存在配置是正常情况。
            pass  # 等用户选择，不自动使用旧固定路径。
        except (OSError, ValueError, KeyError, TypeError):  # 损坏或无法读取时保留旧文件供诊断。
            self.error = '存储设置无法读取，请重新选择存储路径。'  # 首次设置窗口中显示原因。

    def save(self, root):  # 只在后台能力检查成功后保存。
        root = Path(root)  # 统一调用方传入的路径对象。
        if not root.is_absolute():  # API 同样禁止相对路径。
            raise ValueError('存储路径必须是完整的绝对路径。')  # 不修改已有设置。
        self.file.parent.mkdir(parents=True, exist_ok=True)  # 数据目录可正常保存配置。
        temporary = self.file.with_name(f'.storage-{uuid.uuid4().hex}.tmp')  # 不覆盖半成品配置。
        try:  # 写入失败保留上次设置和内存状态。
            with temporary.open('x', encoding='utf-8') as stream:  # 独占创建本次配置草稿。
                json.dump({'archive_root': str(root)}, stream, ensure_ascii=False, indent=2)  # 中文路径按原文保存。
                stream.flush()  # 刷新 Python 缓冲。
                os.fsync(stream.fileno())  # 在原子提交前确保内容落盘。
            os.replace(temporary, self.file)  # 完整替换，不留下半个 JSON。
        finally:  # 只清理本次临时文件。
            temporary.unlink(missing_ok=True)  # 不删除原配置。
        self.root, self.error = root, ''  # 保存成功后才切换有效设置。

class StorageDialog(QDialog):  # 首次运行与设置菜单使用同一表单。
    def __init__(self, window, first_run=False):  # 外层窗口负责后台线程和归档器。
        super().__init__(window)  # 弹窗期间保留视频播放状态。
        self.window, self.pending = window, False  # 防止检查中重复保存或关闭。
        self.setWindowTitle('首次设置 · 视频存储路径' if first_run else '视频存储路径')  # 明确本次配置用途。
        self.setMinimumWidth(580)  # 中文路径和说明保留足够空间。
        layout = QVBoxLayout(self)  # 路径、选择器、说明和提交操作单列排列。
        layout.setContentsMargins(24, 22, 24, 20)  # 与现有设置窗口保持一致留白。
        layout.setSpacing(14)  # 不把路径输入和提示挤在一起。
        layout.addWidget(QLabel('请选择视频分类后的存储文件夹' if first_run else '视频分类存储路径'))  # 首次运行不预设用户的盘符。
        row = QHBoxLayout()  # 输入框和浏览按钮并排。
        self.path = QLineEdit(str(window.storage.root or ''))  # 修改时显示实际当前位置。
        self.path.setObjectName('archiveRootInput')  # 为专项检查提供稳定入口。
        self.path.setPlaceholderText('选择或输入完整文件夹路径')  # 用户可以输入待创建的新子目录。
        row.addWidget(self.path, 1)  # 长路径占据主要宽度。
        self.browse = QPushButton('选择文件夹')  # 使用系统文件夹选择器。
        self.browse.clicked.connect(self.choose)  # 选择不立即修改存储设置。
        row.addWidget(self.browse)  # 浏览按钮保持可见。
        layout.addLayout(row)  # 路径操作集中在同一行。
        note = QLabel('需要可写的 NTFS 磁盘，以便多标签共用一份视频内容。\n更改后，新归档及以后修改标签、评分的视频使用新路径；不会立即迁移整库，历史和收藏仍可找到原视频。\n取消可先浏览和播放，归档前需要完成设置。')  # 说明修改范围及取消行为。
        note.setWordWrap(True)  # 不让长说明撑宽窗口。
        layout.addWidget(note)  # 不显示不相关技术参数。
        self.status = QLabel(window.storage.error)  # 错误就地显示，不叠加弹窗。
        self.status.setWordWrap(True)  # 长错误原因自动换行。
        layout.addWidget(self.status)  # 检查进度也使用同一位置。
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)  # 用户明确保存才切换。
        self.buttons.button(QDialogButtonBox.Save).setText('保存路径')  # 动作直接对应用户目标。
        self.buttons.button(QDialogButtonBox.Cancel).setText('稍后设置' if first_run else '取消')  # 首次取消不会误用固定目录。
        self.buttons.accepted.connect(self.commit)  # NTFS 和写入检查异步执行。
        self.buttons.rejected.connect(self.reject)  # 取消保留旧路径。
        layout.addWidget(self.buttons)  # 保存入口固定在底部。

    def choose(self):  # 浏览只修改表单草稿。
        selected = QFileDialog.getExistingDirectory(self, '选择视频存储文件夹', self.path.text())  # 起始位置沿用当前设置。
        if selected:  # 取消文件选择不改变原路径。
            self.path.setText(selected)  # 等待用户点击保存。

    def commit(self):  # 不在主线程检测磁盘和硬链接。
        if self.pending:  # 阻止重复点击产生多个后台请求。
            return  # 当前请求完成后才可再次操作。
        if self.window.busy or self.window.has_pending_file_tasks():  # 任务目标冻结期间不改变根目录。
            self.status.setText('请先等待文件任务完成，或通过“更多 → 文件任务”恢复，再更改路径。')  # 不把恢复剩余视频分散到新位置。
            return  # 保留原配置与草稿。
        value = self.path.text()  # 冻结本次用户提交值。
        self.pending = True  # 检查期间不能关闭或重复提交。
        self.path.setEnabled(False)  # 不让文本与实际检查位置不一致。
        self.browse.setEnabled(False)  # 检查中禁用其他文件夹选择。
        self.buttons.setEnabled(False)  # 保存和取消等待本次小探针结束。
        self.status.setText('正在检查文件夹权限和硬链接支持……')  # 显示实际状态。
        def checked(root, error):  # 工作结果在主线程提交。
            self.pending = False  # 允许用户修正失败的路径。
            self.path.setEnabled(True)  # 恢复表单输入。
            self.browse.setEnabled(True)  # 恢复浏览操作。
            self.buttons.setEnabled(True)  # 检查失败后可以取消或重试。
            if not error:  # 磁盘验证成功才保存本地偏好。
                try:  # 配置文件写入失败不切换归档器。
                    self.window.storage.save(root)  # 原子保存到当前用户的便携数据目录。
                    self.window.archiver.root = root  # 全局分类与评分共用这个归档器。
                    self.window.legacy_storage_recovery = False  # 用户已明确完成首次设置。
                except (OSError, ValueError) as failure:  # 保留实际保存失败原因。
                    error = failure  # 统一在表单显示错误。
            if error:  # 不把能力检查或保存失败显示为成功。
                self.status.setText(str(error))  # 保留用户输入以便直接修正。
                return  # 当前有效设置保持原值。
            self.window.message(f'视频存储路径已设置：{root}')  # 反馈实际保存的位置。
            self.accept()  # 成功后回到播放器。
        self.window.work(lambda: validate_storage_path(value), checked)  # 磁盘创建和硬链接验证均在后台运行。

    def reject(self):  # 检查结束前避免后台回调指向已关闭窗口。
        if not self.pending:  # 未开始或已结束检查才能取消。
            super().reject()  # 不写配置也不创建归档任务。

    def closeEvent(self, event):  # 关闭按钮遵守相同的检查中保护。
        if self.pending:  # 后台仍在验证用户选择的文件夹。
            event.ignore()  # 完成后即可正常关闭。
        else:  # 没有未完成验证时正常取消。
            super().closeEvent(event)  # 不强制完成首次设置。
