import json  # 读取便携版外观偏好。
import os  # 原子提交外观配置文件。
import uuid  # 为背景副本生成无冲突文件名。
from pathlib import Path  # 将背景副本保存在便携数据目录。
from PySide6.QtCore import Qt, QRectF, QSize  # 处理背景裁切与图标尺寸。
from PySide6.QtGui import QColor, QPainter, QPixmap, QLinearGradient, QRadialGradient, QImageReader  # 绘制渐变背景并安全读取用户图片。
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QDialogButtonBox, QFileDialog, QMessageBox  # 构建背景图设置与实时预览。

class Appearance:  # 独立于视频数据库保存界面偏好。
    def __init__(self, data):  # 初始化当前便携目录的背景设置。
        self.directory = Path(data) / 'appearance'  # 背景副本跟随整个便携目录移动。
        self.directory.mkdir(parents=True, exist_ok=True)  # 建立专用外观数据目录。
        self.file = self.directory / 'settings.json'  # 外观配置不污染视频数据库。
        self.background, self.strength = None, 60  # 默认使用蓝白渐变及适中背景显示强度。
        try:  # 配置损坏或不存在时安全使用默认主题。
            settings = json.loads(self.file.read_text(encoding='utf-8'))  # 读取上次确认的外观偏好。
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

    def save(self, path, strength):  # 明确确认后才保存背景和显示强度。
        target = self.background if path and self.background and Path(path) == self.background else None  # 已有副本无需重复写入。
        created = False  # 记录本次是否创建了新文件。
        if path and target is None:  # 将新背景转存为可迁移的独立图片。
            image = self.image(path)  # 先确认实际可解码。
            target = self.directory / f'background-{uuid.uuid4().hex}.png'  # 不覆盖原背景或任何用户文件。
            if not image.save(str(target), 'PNG'):  # 检查磁盘空间和写入权限。
                raise OSError('背景副本写入失败，请检查磁盘空间和权限。')  # 不显示保存成功。
            created = True  # 后续配置失败时只清理本次副本。
        settings = {'background': target.name if target else None, 'strength': max(10, min(100, int(strength)))}  # 只保存相对文件名，支持迁移便携目录。
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

class BackgroundCanvas(QWidget):  # 用独立底层绘制实现网页般的柔和背景。
    def __init__(self, appearance):  # 读取当前已保存的背景偏好。
        super().__init__()  # 初始化主窗口中央容器。
        self.appearance, self.image, self.strength = appearance, QPixmap(), appearance.strength  # 保存绘制所需状态。
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
        gradient = QLinearGradient(0, 0, self.width(), self.height())  # 默认使用左上到右下的蓝白渐变。
        gradient.setColorAt(0, QColor('#eef0f3'))  # 默认使用低饱和度的中性背景。
        gradient.setColorAt(0.52, QColor('#eef0f3'))  # 不添加装饰性渐变或高光。
        gradient.setColorAt(1, QColor('#eef0f3'))  # 整个工作区保持一致底色。
        painter.fillRect(self.rect(), gradient)  # 整个应用始终有完整背景。
        if not self.image.isNull():  # 自定义图片按覆盖模式居中显示。
            ratio = max(self.width() / self.image.width(), self.height() / self.image.height())  # 等比放大直到覆盖窗口。
            width, height = self.width() / ratio, self.height() / ratio  # 计算不拉伸的源图裁切尺寸。
            source = QRectF((self.image.width() - width) / 2, (self.image.height() - height) / 2, width, height)  # 居中裁切多余边缘。
            painter.drawPixmap(QRectF(self.rect()), self.image, source)  # 背景随窗口缩放且不变形。
            painter.fillRect(self.rect(), QColor(239, 245, 255, round(255 * (1 - self.strength / 100))))  # 用显示强度控制图片可见程度。

def appearance_dialog(window):  # 提供可预览、可撤销的自定义背景设置。
    appearance = window.appearance  # 使用本便携数据目录的外观偏好。
    selected = [appearance.background]  # 暂存本次选择，确认前不覆盖原配置。
    dialog = QDialog(window)  # 外观弹窗优先接收键盘操作。
    dialog.setWindowTitle('外观 · 自定义背景')  # 明确设置范围。
    dialog.setObjectName('appearanceDialog')  # 允许主题统一设置背景色。
    dialog.setMinimumWidth(520)  # 给背景预览和设置说明足够空间。
    layout = QVBoxLayout(dialog)  # 按预览、选择、强度、提交组织内容。
    layout.setContentsMargins(28, 24, 28, 24)  # 使用与主界面一致的留白。
    layout.setSpacing(16)  # 拉开控件间距避免拥挤。
    title = QLabel('背景设置')  # 设置标题只表达功能。
    title.setProperty('role', 'sectionTitle')  # 应用标题字体样式。
    layout.addWidget(title)  # 标题位于预览之上。
    preview = QLabel()  # 展示当前选中的背景图片。
    preview.setObjectName('backgroundPreview')  # 设置蓝白预览卡片样式。
    preview.setFixedSize(464, 190)  # 保持固定宽屏预览比例。
    preview.setAlignment(Qt.AlignCenter)  # 默认说明居中显示。
    layout.addWidget(preview)  # 提供立即可见的预览。
    buttons = QHBoxLayout()  # 并排放置选择和恢复按钮。
    choose = QPushButton('选择背景图')  # 允许用户选择本地图片。
    choose.setObjectName('chooseBackground')  # 自动化验收可定位此入口。
    choose.setProperty('role', 'primary')  # 突出主要操作。
    reset = QPushButton('恢复默认背景')  # 提供一键清除自定义背景的入口。
    reset.setObjectName('resetBackground')  # 自动化验收可定位恢复操作。
    buttons.addWidget(choose)  # 放置选择按钮。
    buttons.addWidget(reset)  # 放置恢复按钮。
    layout.addLayout(buttons)  # 控制按钮位于预览下方。
    strength_text = QLabel()  # 显示当前背景强度数值。
    layout.addWidget(strength_text)  # 数值与滑块同组。
    strength = QSlider(Qt.Horizontal)  # 允许拖动调整背景清晰程度。
    strength.setObjectName('backgroundStrength')  # 为自动化测试提供稳定对象名。
    strength.setRange(10, 100)  # 避免意外选择完全不可见的自定义背景。
    strength.setValue(appearance.strength)  # 默认沿用用户已经保存的强度。
    layout.addWidget(strength)  # 添加滑块。
    note = QLabel('支持 PNG、JPG、WebP、BMP。图片将保存到便携数据目录，原图不会被修改。')  # 说明迁移和原文件保护行为。
    note.setWordWrap(True)  # 长说明自然换行。
    note.setProperty('role', 'muted')  # 次要说明使用低强调文字。
    layout.addWidget(note)  # 放置简短说明。
    def refresh():  # 同时刷新弹窗和主界面预览。
        strength_text.setText(f'背景显示强度  {strength.value()}%')  # 显示精确调节比例。
        window.canvas.set_background(selected[0], strength.value())  # 仅修改临时可见效果。
        if selected[0]:  # 选择图片时展示等比预览。
            pixmap = QPixmap.fromImage(appearance.image(selected[0]))  # 使用同一安全图片加载逻辑。
            preview.setPixmap(pixmap.scaled(preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))  # 不拉伸用户原图。
        else:  # 无自定义图片时说明恢复后的外观。
            preview.setPixmap(QPixmap())  # 清除旧预览图片。
            preview.setText('默认背景')  # 使用直接的设置状态文字。
    def select():  # 通过系统文件选择器导入背景。
        path, chosen_filter = QFileDialog.getOpenFileName(dialog, '选择背景图片', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')  # 仅筛选常见图片格式。
        if path:  # 取消文件选择器不改变当前预览。
            try:  # 图片损坏时继续保留原选择。
                appearance.image(path)  # 先校验实际像素可读取。
                selected[0] = Path(path)  # 只暂存新的本地路径。
                refresh()  # 立即预览选择效果。
            except (OSError, ValueError) as error:  # 图片失败不提交外观配置。
                QMessageBox.warning(dialog, '背景图片无法使用', str(error))  # 给出明确错误说明。
    choose.clicked.connect(select)  # 绑定文件选择按钮。
    reset.clicked.connect(lambda: (selected.__setitem__(0, None), refresh()))  # 恢复默认也允许取消撤销。
    strength.valueChanged.connect(refresh)  # 拖动强度滑块立即更新预览。
    confirm = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)  # 用户明确保存或放弃修改。
    confirm.button(QDialogButtonBox.Ok).setText('保存外观')  # 提示确认才持久化。
    confirm.button(QDialogButtonBox.Cancel).setText('取消')  # 使用中文取消文案。
    def commit():  # 提交成功后才关闭弹窗。
        try:  # 处理磁盘满和无权限错误。
            appearance.save(selected[0], strength.value())  # 原子保存背景副本与相对路径配置。
            window.canvas.set_background(appearance.background, appearance.strength)  # 切换到已保存的便携副本。
            dialog.accept()  # 表示外观保存完成。
        except (OSError, ValueError) as error:  # 失败时保留弹窗方便调整。
            QMessageBox.warning(dialog, '外观未保存', str(error))  # 不谎报成功。
    confirm.accepted.connect(commit)  # 确认按钮执行事务式保存。
    confirm.rejected.connect(dialog.reject)  # 取消和 Esc 不保存预览。
    layout.addWidget(confirm)  # 提交按钮位于设置底部。
    refresh()  # 首次展示读取已保存偏好。
    if dialog.exec() != QDialog.Accepted:  # 用户关闭或取消设置时撤销临时预览。
        window.canvas.set_background(appearance.background, appearance.strength)  # 恢复打开弹窗之前的已保存背景。
