import struct  # 写入标准 Windows ICO 多尺寸容器。
from pathlib import Path  # 定位项目内的正式角色图标资源。
from PySide6.QtCore import Qt, QBuffer, QIODevice  # 在内存中编码图标 PNG 帧。
from PySide6.QtGui import QImage, QPainter  # 保留透明度并导出各 Windows 图标尺寸。

directory = Path(__file__).resolve().parents[1] / 'assets'  # 图标资源随源码交付。
source = QImage(str(directory / 'yunli-chibi.png'))  # 读取内置图像工具生成的云璃 Q 版素材。
if source.isNull():  # 缺失素材时拒绝构建错误图标。
    raise RuntimeError('云璃图标 PNG 缺失或无法读取')  # 明确指出需要恢复的资源。
frames = []  # 收集每种 Windows 图标尺寸的透明 PNG。
for size in [16, 24, 32, 48, 64, 128, 256]:  # 同时覆盖资源管理器、任务栏和高 DPI 图标。
    frame = QImage(size, size, QImage.Format_ARGB32)  # 创建透明正方形图标画布。
    frame.fill(Qt.transparent)  # 保持原始贴纸透明背景。
    resized = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # 仅为图标格式转换等比缩放，不改动原始插画。
    painter = QPainter(frame)  # 将完整贴纸居中放入画布。
    painter.drawImage((size - resized.width()) // 2, (size - resized.height()) // 2, resized)  # 不裁切角色发饰或面部。
    painter.end()  # 结束本尺寸画布绘制。
    buffer = QBuffer()  # 使用内存编码避免产生临时文件。
    buffer.open(QIODevice.WriteOnly)  # 开启 PNG 写入通道。
    if not frame.save(buffer, 'PNG'):  # 确保各尺寸图像有效编码。
        raise RuntimeError('图标 PNG 帧编码失败')  # 不输出损坏 ICO。
    frames.append((size, bytes(buffer.data())))  # 保存帧尺寸与编码内容。
offset = 6 + 16 * len(frames)  # ICO 文件头之后紧跟固定大小目录项。
entries = []  # 为各 PNG 帧建立 Windows 图标索引。
for size, data in frames:  # 按从小到大的标准尺寸顺序写入。
    entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))  # 256 像素按 ICO 规范用零表示。
    offset += len(data)  # 下一个 PNG 紧跟当前帧。
(directory / 'yunli.ico').write_bytes(struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries) + b''.join(data for size, data in frames))  # 输出可直接嵌入 EXE 的多尺寸 ICO。
print(directory / 'yunli.ico')  # 打印最终图标资源路径。
