"""Qt worker-to-application-thread result delivery."""
import logging
from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):  # 在线程间传递任务结果。
    finished = Signal(object, object)

class Work(QRunnable):  # 在线程池中执行阻塞操作。
    def __init__(self, function):  # 接收无参数任务函数。
        super().__init__()  # 初始化 Qt 任务对象。
        self.function, self.signals = function, Signals()  # 信号对象由界面保持引用。

    def run(self):  # 工作线程不得直接操作控件。
        try:  # 将异常转换成主线程反馈。
            result = self.function()  # 执行扫描、归档或缩略图生成。
            self.signals.finished.emit(result, None)  # 通知任务成功。
        except InterruptedError as error:  # 正常取消扫描或缩略图不当成程序故障记录。
            logging.info('后台任务已取消：%s', error)  # 保留可追踪取消状态而不刷错误堆栈。
            self.signals.finished.emit(None, error)  # 界面仍按原取消约定处理结果。
        except Exception as error:  # 保留异常到日志与界面。
            logging.exception('后台任务失败')  # 记录完整堆栈。
            self.signals.finished.emit(None, error)
