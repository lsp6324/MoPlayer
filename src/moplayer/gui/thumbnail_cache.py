"""Bounded Qt image cache and delivery; decoding belongs to the adapter."""
from collections import OrderedDict
from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from moplayer.gui.background_work import Work


class ThumbnailCache(QObject):  # 为目录、历史和收藏共用有界异步缩略图队列。
    changed = Signal()  # 缩略图完成后通知所有可见列表重绘。

    def __init__(self, service, is_busy, parent):  # 使用窗口已有的视频身份和磁盘缓存逻辑。
        super().__init__(parent)  # 随主窗口管理信号生命周期。
        self.service, self.is_busy = service, is_busy
        self.images, self.errors, self.pending = OrderedDict(), OrderedDict(), {}  # 共用视频 ID 并限制缓存资源。
        self.pool = QThreadPool(self)  # 与目录扫描、归档使用不同工作队列。
        self.pool.setMaxThreadCount(2)  # 最多同时启动两个 FFmpeg，避免批量解码耗尽资源。
        self.closing = False  # 退出时停止接受新缩略图请求。

    def request(self, vid):  # 绘制可见视频行时按需请求缩略图。
        if vid in self.images:  # 热缓存无需磁盘读取。
            self.images.move_to_end(vid)  # 保留最近显示的视频图片。
            return self.images[vid]  # 在 GUI 线程返回已加载的 QPixmap。
        if self.closing or self.is_busy() or self.service.blocked(vid) or vid in self.pending or vid in self.errors or len(self.pending) >= 24:  # 文件批次和快速滚动均限制新解码请求。
            return None  # 加载期间由列表绘制明确占位提示。
        job = Work(lambda: self.service.generate(vid))  # 在工作线程读取缓存或生成 240×160 JPEG。
        self.pending[vid] = job  # 按稳定身份去重后台解码。
        def finished(path, error):  # 在主线程将已生成图片发布给视图。
            self.pending.pop(vid, None)  # 释放已完成任务引用和队列容量。
            if isinstance(error, InterruptedError):  # 文件任务取消的解码不能被当成视频损坏。
                if not self.closing:  # 窗口仍在使用时允许后续重试。
                    self.changed.emit()  # 忙碌状态结束后重新按需生成图片。
                return  # 不写入持久错误缓存。
            if self.closing or self.service.blocked(vid):  # 文件任务期间取消的旧解码结果不发布为错误缓存。
                return  # 只等待任务安全结束。
            image = QPixmap(str(path)) if not error else QPixmap()  # 仅在主线程读取完成的缓存图片。
            if image.isNull():  # 解码失败不无限重试同一坏文件。
                self.errors[vid] = str(error or '缩略图图像无效')  # 保存可显示的失败原因。
                while len(self.errors) > 256:  # 限制错误缓存长期占用。
                    self.errors.popitem(last=False)  # 释放最早的失败记录。
            else:  # 发布实际视频画面。
                self.images[vid] = image  # 同一个视频的多个入口引用同一张图片。
                while len(self.images) > 256:  # 只保留最近使用的 256 张内存图片。
                    self.images.popitem(last=False)  # 淘汰后仍可复用磁盘缓存。
            self.changed.emit()  # 重绘当前视口并继续请求尚未排队的可见视频。
        job.signals.finished.connect(finished)  # 通过 Qt 排队信号安全回到主线程。
        self.pool.start(job)  # 不在绘制过程中执行解码或大文件读取。
        return None
