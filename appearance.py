import json  # 读取便携版外观偏好。
import os  # 原子提交外观配置文件。
import uuid  # 为背景副本生成无冲突文件名。
from pathlib import Path  # 将背景副本保存在便携数据目录。
from PySide6.QtCore import Qt, QRectF, QSize  # 处理背景裁切与图标尺寸。
from PySide6.QtGui import QColor, QPainter, QPixmap, QImageReader  # 绘制渐变背景并安全读取用户图片。
from PySide6.QtWidgets import QWidget
from accent_colors import DEFAULT_ACCENT, normalize_color

class Appearance:  # 独立于视频数据库保存界面偏好。
    def __init__(self, data):  # 初始化当前便携目录的背景设置。
        self.directory = Path(data) / 'appearance'  # 背景副本跟随整个便携目录移动。
        self.directory.mkdir(parents=True, exist_ok=True)  # 建立专用外观数据目录。
        self.file = self.directory / 'settings.json'  # 外观配置不污染视频数据库。
        self.background, self.strength, self.theme = None, 60, 'light'
        self.accent = DEFAULT_ACCENT
        try:  # 配置损坏或不存在时安全使用默认主题。
            settings = json.loads(self.file.read_text(encoding='utf-8'))  # 读取上次确认的外观偏好。
            if not isinstance(settings,dict):
                raise ValueError('外观配置格式无效')
            try:
                self.accent = normalize_color(settings.get('accent',DEFAULT_ACCENT))
            except ValueError:
                self.accent = DEFAULT_ACCENT
            self.theme = 'dark' if settings.get('theme') == 'dark' else 'light'
            self.strength = max(10, min(100, int(settings.get('strength', 60))))  # 限制背景显示强度范围。
            name = settings.get('background')  # 只允许相对于专用目录的文件名。
            if name and Path(name).name == name and (self.directory / name).is_file():  # 拒绝配置中的路径穿越或失效文件。
                self.background = self.directory / name  # 使用便携目录中的有效背景副本。
        except (OSError, ValueError, TypeError, AttributeError):  # 无效配置不应阻止应用启动。
            pass  # 保留默认蓝白主题。

    def image(self, path):  # 统一读取用户选择的背景并限制解码规模。
        reader = QImageReader(str(path))  # 使用 Qt 支持的图片格式读取。
        reader.setAutoTransform(True)  # 正确处理照片 EXIF 方向。
        size = reader.size()  # 在解码前检查图像尺寸。
        if not size.isValid() or size.width() * size.height() > 100_000_000:  # 拒绝无效或异常巨大的图像。
            raise ValueError('图片无效或超过一亿像素，请选择较小的 PNG、JPG、WebP 或 BMP。')  # 给出明确反馈。
        if max(size.width(), size.height()) > 3840:  # 背景副本无需超过常用 4K 屏幕尺寸。
            reader.setScaledSize(size.scaled(QSize(3840, 3840), Qt.KeepAspectRatio))  # 限制内存占用且保持比例。
        image = reader.read()  # 读取图片实际像素。
        if image.isNull():  # 不能解码的图片不会覆盖已有设置。
            raise ValueError('无法读取背景图片：' + reader.errorString())  # 说明格式或文件问题。
        return image  # 原始用户图片从不修改。

    def save(self, path, strength, theme=None, accent=None):
        accent = normalize_color(self.accent if accent is None else accent)
        target = self.background if path and self.background and Path(path) == self.background else None  # 已有副本无需重复写入。
        created = False  # 记录本次是否创建了新文件。
        if path and target is None:  # 将新背景转存为可迁移的独立图片。
            image = self.image(path)  # 先确认实际可解码。
            target = self.directory / f'background-{uuid.uuid4().hex}.png'  # 不覆盖原背景或任何用户文件。
            if not image.save(str(target), 'PNG'):  # 检查磁盘空间和写入权限。
                raise OSError('背景副本写入失败，请检查磁盘空间和权限。')  # 不显示保存成功。
            created = True  # 后续配置失败时只清理本次副本。
        settings = {'background': target.name if target else None, 'strength': max(10, min(100, int(strength)))}  # 只保存相对文件名，支持迁移便携目录。
        settings['theme'] = theme if theme in ('dark', 'light') else self.theme
        settings['accent'] = accent
        temporary = self.directory / f'settings-{uuid.uuid4().hex}.tmp'  # 用独立临时文件保护旧配置。
        try:  # 配置提交失败仍保持原设置有效。
            with temporary.open('w', encoding='utf-8') as stream:  # 将新配置写入临时文件。
                json.dump(settings, stream, ensure_ascii=False, indent=2)  # 保存可读的外观设置。
                stream.flush()  # 刷新文本缓冲区。
                os.fsync(stream.fileno())  # 在原子替换前刷新磁盘内容。
            os.replace(temporary, self.file)  # 一次替换完整配置，不留下半个 JSON。
        except Exception:  # 不丢弃原来已确认的背景配置。
            temporary.unlink(missing_ok=True)  # 只删除本次临时配置。
            if created:  # 新背景没有被任何成功配置引用。
                target.unlink(missing_ok=True)  # 清理本次未提交的副本。
            raise  # 把真实失败原因交给设置弹窗。
        self.background, self.strength = target, settings['strength']  # 提交成功后更新内存偏好。
        self.theme = settings['theme']
        self.accent = settings['accent']

class BackgroundCanvas(QWidget):  # 用独立底层绘制实现网页般的柔和背景。
    def __init__(self, appearance):  # 读取当前已保存的背景偏好。
        super().__init__()  # 初始化主窗口中央容器。
        self.appearance, self.image, self.strength = appearance, QPixmap(), appearance.strength  # 保存绘制所需状态。
        self.theme = appearance.theme
        self.setObjectName('appCanvas')  # 为主题样式提供明确选择器。
        try:  # 已保存图片被外部损坏时仍允许启动播放器。
            self.set_background(appearance.background, appearance.strength)  # 启动只恢复外观，不恢复视频或目录。
        except (OSError, ValueError):  # 损坏的背景不会阻断视频管理功能。
            appearance.background = None  # 回退到可用的默认渐变主题。

    def set_background(self, path, strength):  # 设置实时预览，不自动写入配置。
        self.image = QPixmap.fromImage(self.appearance.image(path)) if path else QPixmap()  # 用户背景使用安全读取后的图片。
        self.strength = strength  # 调节背景与浅色遮罩的混合比例。
        self.update()  # 更新主窗口背景。

    def paintEvent(self, event):  # 以实际窗口尺寸绘制渐变或自定义图像。
        painter = QPainter(self)  # 在当前窗口背景上绘制。
        painter.setRenderHint(QPainter.SmoothPixmapTransform)  # 平滑缩放背景照片。
        base = QColor('#f7f8fa' if self.theme == 'light' else '#1a1d23')
        painter.fillRect(self.rect(), base)
        if not self.image.isNull():  # 自定义图片按覆盖模式居中显示。
            ratio = max(self.width() / self.image.width(), self.height() / self.image.height())  # 等比放大直到覆盖窗口。
            width, height = self.width() / ratio, self.height() / ratio  # 计算不拉伸的源图裁切尺寸。
            source = QRectF((self.image.width() - width) / 2, (self.image.height() - height) / 2, width, height)  # 居中裁切多余边缘。
            painter.drawPixmap(QRectF(self.rect()), self.image, source)  # 背景随窗口缩放且不变形。
            base.setAlpha(round(255 * (1 - self.strength / 100)))
            painter.fillRect(self.rect(), base)
