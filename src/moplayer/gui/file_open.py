import hashlib  # 根据数据目录隔离不同便携副本的通信端点。
import json  # 编码带有中文和空格的本地文件路径。
from pathlib import Path  # 校验 Windows 传入的真实文件。
from PySide6.QtCore import QTimer  # 将打开操作安排到主界面事件循环。
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # 把第二次双击转发给已有进程。
from PySide6.QtWidgets import QApplication  # 避免外部打开打断正在编辑的模态窗口。

def endpoint(directory):  # 同一便携数据目录使用唯一命名管道。
    return 'MoPlayer-' + hashlib.sha256(str(Path(directory).resolve()).casefold().encode()).hexdigest()[:24]  # 不同副本不会互相串台。

def forward(directory, path):  # 第二个进程向持有数据库锁的主进程发送请求。
    socket = QLocalSocket()  # 创建本地管道客户端。
    socket.connectToServer(endpoint(directory))  # 仅连接本应用对应的数据目录。
    if not socket.waitForConnected(3000):  # 首个进程可能仍在初始化播放器。
        return False  # 连接失败时不谎报已打开。
    socket.write((json.dumps({'path': path}, ensure_ascii=False) + '\n').encode('utf-8'))  # 用换行作为完整消息边界。
    socket.flush()  # 立即提交请求字节。
    if not socket.waitForReadyRead(3000):  # 等待主进程明确确认接收。
        return False  # 超时提示用户重试。
    return bytes(socket.readAll()).strip() == b'OK'  # 只有真实回执才认为转发成功。

class FileOpenServer(QLocalServer):  # 接收双击并在安全时机打开视频。
    def __init__(self, window, directory):  # 跟随主窗口生命周期保存服务。
        super().__init__(window)  # 由 Qt 主窗口负责释放。
        self.window, self.pending = window, []  # 使用队列避免打断归档或弹窗。
        name = endpoint(directory)  # 得到当前便携副本唯一端点。
        QLocalServer.removeServer(name)  # 已持有数据库锁，因此只清理崩溃遗留端点。
        if not self.listen(name):  # 不允许静默失去默认播放器接收能力。
            raise OSError(self.errorString())  # 把失败交给启动错误处理。
        self.newConnection.connect(self.accept_request)  # 每个连接拥有独立消息缓冲。
        self.timer = QTimer(self)  # 定期处理等待中的明确打开请求。
        self.timer.timeout.connect(self.dispatch)  # 仅在主线程操作播放器。
        self.timer.start(250)  # 保持打开响应及时。

    def accept_request(self):  # 读取来自资源管理器启动的新进程。
        while self.hasPendingConnections():  # 接收当前所有等待连接。
            socket = self.nextPendingConnection()  # 每个请求独立传输。
            buffer = bytearray()  # 处理消息拆分而不是假设一次读完。
            def receive(socket=socket, buffer=buffer):  # 固定当前连接与对应缓冲。
                buffer.extend(bytes(socket.readAll()))  # 收集已经到达的字节。
                if len(buffer) > 65536:  # 限制本地输入规模。
                    socket.disconnectFromServer()  # 拒绝异常大的消息。
                    return  # 不继续解析。
                if b'\n' in buffer:  # 只有消息完整后才解析。
                    try:  # 错误请求不能让主进程退出。
                        payload = json.loads(buffer.split(b'\n', 1)[0])  # 解码完整 JSON 请求。
                        self.pending.append(payload['path'])  # 记录用户明确要求打开的路径。
                        socket.write(b'OK\n')  # 确认已排队而非声称解码成功。
                        socket.flush()  # 立即返回回执。
                    except (ValueError, KeyError, TypeError):  # 不接收不完整结构。
                        pass  # 忽略无效消息。
                    socket.disconnectFromServer()  # 一次连接只处理一个请求。
            socket.readyRead.connect(receive)  # 后续到达的数据继续读取。
            socket.disconnected.connect(socket.deleteLater)  # 及时释放已断开的连接。
            receive()  # 处理建立连接时已到达的请求。

    def dispatch(self):  # 在不干扰归档和模态编辑时打开请求。
        if not self.pending or self.window.busy or QApplication.activeModalWidget():  # 不改变正在提交的标签目标。
            return  # 保留队列等待安全时机。
        path = self.pending.pop(0)  # 按用户请求顺序处理。
        self.window.showNormal() if self.window.isMinimized() else self.window.show()  # 从最小化恢复但保持已有全屏。
        self.window.raise_()  # 将接收请求的播放器显示到前方。
        self.window.activateWindow()  # 尝试激活当前播放器。
        if path:  # 无参数二次启动只显示已有窗口。
            try:  # 失效路径给出明确提示。
                target = Path(path).resolve(strict=True)  # 不按文件名猜测其他视频。
                if not target.is_file():  # 默认应用只接收文件。
                    raise ValueError('请选择一个有效视频文件。')  # 不将目录当成视频。
                vid = self.window.catalog.register(target)  # 使用同一套稳定身份和硬链接识别。
                self.window.load_folder(str(target.parent), vid)  # 建立所在目录上下文并恢复播放进度。
            except (OSError, ValueError) as error:  # 文件被删除或无权限时不崩溃。
                self.window.fail(error)  # 显示实际打开失败原因。
