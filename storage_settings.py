import json  # 独立保存每位用户的归档位置。
import os  # 原子替换配置并刷新磁盘。
import uuid  # 并发写入时使用独立临时文件。
from pathlib import Path  # 不依赖开发机器的固定盘符。
from application.archive_folders import ArchiveFolders
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
        self.file = Path(directory).absolute() / 'storage.json'  # 不更改历史视频数据库位置。
        self.folders = ArchiveFolders()
        self.root, self.error = None, ''
        try:  # 不把损坏配置当作可用路径。
            settings = json.loads(self.file.read_text(encoding='utf-8'))  # 读取上次明确保存的位置。
            value = settings['archive_root']  # 保持配置格式简单明确。
            if not isinstance(value, str) or (value != 'video' and not Path(value).is_absolute()):
                raise ValueError('保存的存储路径无效，请重新选择。')  # 启动时提示重新配置。
            folders = ArchiveFolders.from_dict(settings['archive_folders']) if 'archive_folders' in settings else ArchiveFolders()
            self.folders = folders
            self.root = self.default_root if value == 'video' else Path(value)
        except FileNotFoundError:  # 首次启动不存在配置是正常情况。
            self.root = self.default_root  # 新安装直接使用程序旁 video；首次归档再验证并创建。
        except (OSError, ValueError, KeyError, TypeError):  # 损坏或无法读取时保留旧文件供诊断。
            self.error = '存储设置无法读取，请重新选择存储路径。'  # 首次设置窗口中显示原因。

    @property
    def default_root(self):
        return self.file.parent.parent / 'video'

    def save(self, root, folders=None):  # 只在后台能力检查成功后保存。
        root = Path(root)  # 统一调用方传入的路径对象。
        folders = self.folders if folders is None else folders
        if not root.is_absolute():  # API 同样禁止相对路径。
            raise ValueError('存储路径必须是完整的绝对路径。')  # 不修改已有设置。
        self.file.parent.mkdir(parents=True, exist_ok=True)  # 数据目录可正常保存配置。
        temporary = self.file.with_name(f'.storage-{uuid.uuid4().hex}.tmp')  # 不覆盖半成品配置。
        try:  # 写入失败保留上次设置和内存状态。
            with temporary.open('x', encoding='utf-8') as stream:  # 独占创建本次配置草稿。
                value = 'video' if root == self.default_root else str(root)
                json.dump({'archive_root': value, 'archive_folders': folders.to_dict()}, stream, ensure_ascii=False, indent=2)
                stream.flush()  # 刷新 Python 缓冲。
                os.fsync(stream.fileno())  # 在原子提交前确保内容落盘。
            os.replace(temporary, self.file)  # 完整替换，不留下半个 JSON。
        finally:  # 只清理本次临时文件。
            temporary.unlink(missing_ok=True)  # 不删除原配置。
        self.folders = folders
        self.root, self.error = root, ''  # 保存成功后才切换有效设置。
