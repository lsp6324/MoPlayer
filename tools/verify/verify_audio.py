import json  # 保存音频实际解码证据。
import sys  # 接收样例目录和输出路径。
import time  # 等待解码器提交 PCM 数据。
from pathlib import Path  # 查找生成的真实编码样例。
from moplayer.runtime import load_vlc
vlc = load_vlc()

def verify(samples):  # 验证音频编码能解码成 PCM，而不依赖人工听音。
    instance = vlc.Instance('--no-video')  # 音频测试不启动视频输出窗口。
    results = {}  # 汇总每个文件的实际采样数量。
    for path in sorted(Path(samples).iterdir()):  # 逐个测试六种容器样例。
        count = [0]  # 使用可变计数器供回调更新。
        @vlc.CallbackDecorators.AudioPlayCb  # 声明符合 libVLC ABI 的 PCM 回调。
        def played(opaque, pcm, samples_count, pts):  # 接收内核已解码音频帧。
            count[0] += samples_count  # 统计实际输出的采样帧数量。
        player = instance.media_player_new()  # 每个样例使用独立播放器。
        player.audio_set_callbacks(played, None, None, None, None, None)  # 将音频送入测试计数器而非声卡。
        player.audio_set_format('S16N', 48000, 2)  # 请求可验证的双声道 PCM 格式。
        media = instance.media_new(str(path))  # 打开实际样例文件。
        player.set_media(media)  # 将媒体绑定到测试播放器。
        media.release()  # 释放调用方引用。
        player.play()  # 启动真实音频解码。
        deadline = time.monotonic() + 10  # 防止坏文件导致无限等待。
        while not count[0] and time.monotonic() < deadline:  # 等待首批 PCM 数据。
            time.sleep(0.02)  # 短间隔检查异步回调结果。
        results[path.name] = {'pcm_frames': count[0], 'decoded': count[0] > 0}  # 记录真实解码输出。
        player.stop()  # 结束当前文件解码。
        player.release()  # 释放播放器及回调关联资源。
    instance.release()  # 关闭本次独立内核实例。
    return results  # 返回可交付的详细音频证据。

if __name__ == '__main__':  # 独立运行音频测试。
    result = verify(sys.argv[1])  # 读取指定测试样例目录。
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding='utf-8')  # 写入机器可读报告。
    sys.exit(0 if all(row['decoded'] for row in result.values()) else 1)  # 任意解码失败都返回失败码。
