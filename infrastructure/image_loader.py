"""Decode one still image for presentation.

No widgets, no playback state and no database access: the caller schedules this
on a worker and hands the resulting pixels to the view.
"""
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader


class ImageLoadError(OSError):
    """The file is missing, unreadable or not a decodable still image."""


class ImageLoader:
    """Read still images with EXIF orientation applied and bounded pixel size."""

    def __init__(self, max_side=4096):
        self.max_side = max_side  # 超大照片按长边降采样，避免解码结果占满内存。

    def read(self, path):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)  # 手机竖拍照片按 EXIF 方向摆正。
        size = reader.size()
        longest = max(size.width(), size.height()) if size.isValid() else 0
        if longest > self.max_side:
            factor = self.max_side / longest
            reader.setScaledSize(QSize(max(1, round(size.width() * factor)),
                                       max(1, round(size.height() * factor))))
        image = reader.read()
        if image.isNull():
            raise ImageLoadError(
                f'无法读取图片：{Path(path).name}（{reader.errorString() or "不支持的格式"}）')
        return image
