from PySide6.QtCore import QObject, QTimer  # 用墙钟计时控制提示，即使暂停也会自动隐藏。

def short_time(milliseconds):  # 短视频使用分秒，长视频保留小时。
    seconds = max(0, int(milliseconds)) // 1000  # 按播放时间向下取整，不显示负值。
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}' if seconds >= 3600 else f'{seconds // 60:02}:{seconds % 60:02}'  # 一分钟显示 01:00。

def notice_text(before, after, total):  # 两行只展示跳转时间与跳转后的占比。
    return f'{short_time(before)}→{short_time(after)}({short_time(total)})\n{after / total * 100:.1f}%'  # 百分比按照实际有效总时长计算。

class SeekNotice(QObject):  # 使用内核文字层，避免被原生视频窗口覆盖。
    def __init__(self, window, vlc):  # 复用应用已配置好的便携 VLC 内核。
        super().__init__(window)  # 生命周期与播放器窗口一致。
        self.window, self.option = window, vlc.VideoMarqueeOption  # 不创建独立窗口或抢占输入焦点。
        self.timer = QTimer(self)  # 暂停时也按真实时间隐藏提示。
        self.timer.setSingleShot(True)  # 每次按键重新开始一次短暂显示。
        self.timer.timeout.connect(self.clear)  # 到期关闭内核文字层。

    def show(self, before, after, total):  # 只在有效跳转后显示提示。
        player, option = self.window.player, self.option  # 使用当前视频对应的同一播放器。
        width, height = player.video_get_size(0)  # 将字号换算到视频源坐标。
        scale = min(self.window.surface.width() / max(1, width), self.window.surface.height() / max(1, height))  # 等比缩放后的实际画面比例。
        size = max(4, min(1024, round(22 / max(0.02, scale))))  # 目标显示约 22 像素，低分辨率视频放大后也不出现巨型文字。
        margin = max(4, round(16 / max(0.1, scale)))  # 左上角留约 16 像素间距。
        for setting, value in ((option.Position, 5), (option.X, margin), (option.Y, margin), (option.Size, size), (option.Color, 0xffffff), (option.Opacity, 255), (option.Timeout, 1600), (option.Refresh, 50)):  # VLC marquee 使用左与上位标记 1|4=5，白字沿用内核描边。
            player.video_set_marquee_int(setting, value)  # 文字直接叠入普通和全屏视频画面。
        player.video_set_marquee_string(option.Text, notice_text(before, after, total).replace('%', '%%'))  # 内核会解析时间格式，转义百分号才能正常显示百分比。
        player.video_set_marquee_int(option.Enable, 1)  # 不改变播放或暂停状态。
        self.timer.start(1600)  # 长按时刷新倒计时，不堆叠多个提示。

    def clear(self):  # 换片或到期后不保留上一条视频的提示。
        self.timer.stop()  # 丢弃上一轮隐藏回调。
        self.window.player.video_set_marquee_int(self.option.Enable, 0)  # 停止显示文字层。
        self.window.player.video_set_marquee_string(self.option.Text, '')  # 新媒体不继承旧进度文案。
