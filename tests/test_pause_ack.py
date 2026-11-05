import time  # 避免周期进度保存干扰暂停确认场景。
from PySide6.QtWidgets import QApplication  # 运行真实窗口控件与播放状态显示。
from app import Window  # 调用生产定时器和 VLC 状态定义。
from runtime import load_vlc
vlc = load_vlc()

def test_reload_waits_for_pause_acknowledgement(tmp_path):  # 暂停命令发出后，内核尚在播放时不能结束恢复状态。
    application = QApplication.instance() or QApplication([])  # 控件图标需要实际 GUI 应用对象。
    window = Window(tmp_path / 'data')  # 所有元数据与用户库隔离。
    window.timer.stop()  # 由测试明确推动每次状态刷新。
    source = tmp_path / 'sample.mp4'  # 文件只用于创建稳定身份，不启动解码。
    source.write_bytes(b'pause-ack-test')  # 不读取用户视频。
    window.current = window.store.register(source)  # 为实际界面提供有效视频记录。
    original = window.player  # 清理时恢复真正的 VLC 对象。
    class DelayedPlayer:  # 模拟 VLC 接收暂停但延后报告 Paused 的真实异步行为。
        state, requests = vlc.State.Playing, []  # 初始仍报告正在播放。
        def get_state(self):  # 每次刷新取得当前内核确认状态。
            return self.state  # 状态不会被 set_pause 立即改变。
        def get_length(self):  # 提供有效恢复范围。
            return 10000  # 使用十秒样例时长。
        def get_time(self):  # 恢复前仍可报告旧位置。
            return 1200  # 测试只关心暂停确认，不伪造媒体帧。
        def set_time(self, position):  # 记录恢复位置请求。
            self.position = position  # 不把请求当作状态确认。
        def set_pause(self, paused):  # 模拟异步命令送达。
            self.requests.append(paused)  # 内核状态保持 Playing 直到下一轮显式确认。
    delayed = DelayedPlayer()  # 替身只控制内核状态，不替换生产 tick 逻辑。
    window.player = delayed
    window.playback.begin(500, True)  # 模拟分类重载需要恢复到暂停状态。
    window.playback.last_save = time.monotonic()  # 当前轮无需周期保存。
    try:  # 失败也恢复并释放实际窗口。
        window.tick()  # 正式代码发出 seek 与 pause 请求。
        assert delayed.requests == [1] and window.playback.resume.position == 500  # 请求未确认前，连续操作仍能读取正确暂停意图。
        window.tick()  # 再一轮内核仍报告 Playing。
        assert window.playback.resume.position == 500 and window.playback.resume.paused is True  # 不因为短暂播放状态丢失目标。
        delayed.state = vlc.State.Paused  # 模拟异步暂停真正完成。
        window.tick()  # 正式代码收到实际状态确认。
        assert window.playback.resume is None  # 只有确认后才允许普通进度保存和后续状态判断。
    finally:  # 不让测试替身影响窗口关闭。
        window.player, window.current = original, None  # 真实 VLC 对象负责最终释放。
        window.close()  # 清理事件过滤器和播放器定时器。
        application.processEvents()  # 交付 Qt 的关闭事件。
