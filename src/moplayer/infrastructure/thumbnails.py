"""Thumbnail files and owned FFmpeg processes; never accesses widgets."""
import os
from pathlib import Path
import subprocess
import threading


class ThumbnailService:
    def __init__(self, directory, resolve, bundle):
        self.directory, self.resolve, self.bundle = Path(directory), resolve, Path(bundle)
        self.guard = threading.RLock()
        self.processes = {}
        self.paused = False
        self._deleting, self._deleted = set(), set()

    def pause(self, paused):
        with self.guard:
            self.paused = paused

    def mark_deleting(self, vids, active):
        with self.guard:
            (self._deleting.update if active else self._deleting.difference_update)(vids)

    def mark_deleted(self, vids):
        with self.guard:
            self._deleted.update(vids)

    def is_deleting(self, vid):
        with self.guard:
            return vid in self._deleting

    def blocked(self, vid):
        with self.guard:
            return self.paused or vid in self._deleting or vid in self._deleted

    def stop(self, vids=None):  # 在后台释放目标文件的全部 FFmpeg 占用。
        with self.guard:
            vids = set(self.processes) if vids is None else vids  # 与解码进程创建使用同一个锁。
            processes = [process for vid in vids for process in self.processes.get(vid, set())]  # 只处理本应用启动的目标视频解码器。
            for process in processes:  # 禁止新目标进程的标志已由主线程设置。
                if process.poll() is None:  # 已结束的进程无需终止。
                    process.kill()  # 取消派生缩略图不影响用户视频数据。
        for process in processes:  # 等待操作系统关闭进程文件句柄。
            process.wait(timeout=5)

    def generate(self, vid):  # 生成以稳定 ID 命名的共享缓存。
        cache = self.directory / 'thumbnails'  # 缓存随便携数据保存。
        cache.mkdir(exist_ok=True)  # 确保缓存目录存在。
        target = cache / f'{vid}.jpg'  # 多标签入口使用同一个缓存文件。
        if target.exists():  # 验证已有缓存满足最新尺寸要求。
            from PySide6.QtGui import QImageReader  # 仅读取图像头即可检查尺寸。
            size = QImageReader(str(target)).size()  # 不在界面线程完整解码缓存。
            if size.width() == 240 and size.height() == 160:  # 宽高均超过用户要求的 120 像素。
                return target  # 合格缓存跨多个标签入口共用。
        source = self.resolve(vid)  # 找到当前有效视频路径。
        ffmpeg = self.bundle / 'ffmpeg.exe'  # 便携版内置缩略图工具。
        if not ffmpeg.exists():  # 源码运行使用隔离环境已安装的工具。
            import imageio_ffmpeg  # 仅开发环境需要该 Python 包。
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 使用包内现成二进制不在线下载。
        temporary = cache / f'{vid}-{threading.get_ident()}.jpg'  # 并发请求不共享半成品。
        command = [str(ffmpeg), '-v', 'error', '-i', str(source), '-frames:v', '1', '-vf', 'scale=240:160:force_original_aspect_ratio=decrease,pad=240:160:(ow-iw)/2:(oh-ih)/2:color=0x151b25,setsar=1', '-y', str(temporary)]  # 按原比例缩放并补边到 240×160，保证两边至少 120 像素。
        with self.guard:  # 进程创建与删除标志同步，避免漏掉文件占用。
            if self.paused or vid in self._deleting or vid in self._deleted:  # 文件任务已开始时不重新打开旧路径。
                raise InterruptedError('视频正在删除。')  # 由异步缓存丢弃旧请求。
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)  # 记录可取消的隐藏解码进程。
            self.processes.setdefault(vid, set()).add(process)  # 同一身份的并发请求全部纳入管理。
        try:  # 无论成功、超时还是删除取消都清理临时文件。
            output, errors = process.communicate(timeout=40)  # 限制坏文件的解码等待时间。
            if process.returncode:  # 被取消或解码失败时不发布半成品。
                if self.paused or vid in self._deleting:  # 区分主动释放占用与真正的解码失败。
                    raise InterruptedError('文件任务已取消缩略图解码。')  # 允许任务结束后自动重试。
                raise OSError('缩略图解码失败或已取消。')  # 保持后台错误可见。
            with self.guard:  # 删除标志和缓存发布使用同一把锁。
                if self.paused or vid in self._deleting or vid in self._deleted:  # 文件任务取消的迟到结果不可重新发布。
                    raise InterruptedError('视频正在删除。')  # 不替换正式缓存。
                os.replace(temporary, target)  # 完成后原子发布缓存。
        finally:  # 释放进程、文件句柄和缓存临时文件。
            if process.poll() is None:  # 超时异常可能仍有解码进程存活。
                process.kill()  # 只结束当前缩略图子进程。
                process.communicate()  # 等待关闭原视频句柄。
            with self.guard:  # 与删除任务读取进程表互斥。
                self.processes.get(vid, set()).discard(process)
                if not self.processes.get(vid):
                    self.processes.pop(vid, None)  # 不保留已退出的解码器。
            temporary.unlink(missing_ok=True)  # 不积累失败产生的半成品。
        return target
