import json  # 保存可见缩略图的实际验收证据。
import os  # 建立同一个视频的多个硬链接入口。
import subprocess  # 生成本次回归专用的真实视频样例。
import sys  # 读取自检输出目录。
import time  # 等待异步图片显示。
from pathlib import Path  # 管理独立验证数据。
from PySide6.QtCore import Qt, QRect, QThreadPool  # 驱动真实 Qt 列表与事件循环。
from PySide6.QtGui import QImage, QImageReader  # 验证实际图像文件与可见像素。
from PySide6.QtWidgets import QApplication  # 验证目录树和侧栏视频列表。
from moplayer.gui.library_views import THUMB_VIEW, THUMB_ROW

def run(destination):  # 源码和打包后的 EXE 使用同一可见性检查。
    from moplayer.app import Window, BUNDLE  # 使用生产窗口及随包资源路径。
    output = Path(destination).absolute()  # 使用明确隔离的测试输出路径。
    output.mkdir(parents=True, exist_ok=True)  # 创建测试目录。
    samples = output / 'videos'  # 与用户视频完全分开的测试目录。
    samples.mkdir(exist_ok=True)  # 保存两个共用内容的样例入口。
    ffmpeg = BUNDLE / 'ffmpeg.exe'  # 优先使用实际便携包中的工具。
    if not ffmpeg.exists():  # 源码运行使用隔离开发环境中的二进制。
        import imageio_ffmpeg  # 不使用系统全局 FFmpeg。
        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())  # 定位包内工具。
    first = samples / '第2集.mp4'  # 自然排序下应当先显示的样例。
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25', '-t', '2', '-c:v', 'libx264', '-threads', '2', '-y', str(first)], check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)  # 生成有明显色彩的真实视频帧。
    os.link(first, samples / '第10集.mp4')  # 验证多个入口共用缩略图缓存。
    application = QApplication.instance() or QApplication([])  # 创建真实 GUI 应用。
    window = Window(output / 'data')  # 使用隔离数据库运行完整界面。
    report = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}  # 保存实际测试条件。
    def check(name, passed):  # 在报告中记录每项检查。
        report['checks'].append({'name': name, 'ok': bool(passed)})  # 不隐藏任何失败条件。
        if not passed:  # 条件不满足时立刻停止验收。
            raise AssertionError(name)  # 由外层保存失败报告。
    def wait_until(predicate):  # 有限等待后台解码和视口重绘。
        deadline = time.monotonic() + 25  # 为慢速机器提供明确超时。
        while time.monotonic() < deadline:  # 在规定时间内持续处理界面事件。
            application.processEvents()  # 让工作结果回到 GUI 线程。
            window.grab()  # 隐藏方式启动 EXE 自检时也触发真实控件绘制，避免把未发生绘制误判为缩略图加载失败。
            if predicate():  # 检查真实图片发布状态。
                return True  # 图片就绪后立即继续。
            time.sleep(0.02)  # 避免忙等占用 CPU。
        return False  # 超时返回失败而不伪报成功。
    def colored_pixels(view, index):  # 直接检查可见缩略图区域的像素而非只看缓存文件。
        row = view.visualRect(index)  # 取得视图实际布局中的视频行区域。
        region = QRect(row.left() + 10, row.top() + 8, *THUMB_VIEW)
        frame = view.viewport().grab(region).toImage()  # 抓取实际视口中已绘制的缩略图。
        ratio = frame.devicePixelRatio()
        colors = [frame.pixelColor(round(x * ratio), round(y * ratio))
                  for x in range(5, THUMB_VIEW[0] - 5, 5) for y in range(5, THUMB_VIEW[1] - 5, 5)]
        colorful = sum(color.saturation() > 170 for color in colors)
        return row.height() >= THUMB_ROW and len({color.rgb() for color in colors}) > 30 and colorful > 100
    try:  # 无论成功或失败都保存截图证据。
        vid = window.store.register(first)  # 为旧缓存迁移测试提前登记身份。
        cache = output / 'data/thumbnails'  # 使用生产缓存位置。
        cache.mkdir(exist_ok=True)  # 创建缓存目录。
        old = QImage(32, 32, QImage.Format_RGB32)  # 模拟旧版本不足 120×120 的缓存。
        old.fill(Qt.black)  # 用明显不可通过画面检查的纯黑缓存。
        old.save(str(cache / f'{vid}.jpg'))  # 保存需要自动重建的旧图片。
        window.show()  # 必须展示真实列表，不只测试后台函数。
        window.load_folder(str(samples))  # 通过正式异步导入流程加载目录。
        check('无需选择视频自动显示缩略图', wait_until(lambda: window.library_controller.browsing is not None and vid in window.thumbnails.images))  # 导入展开后无需点击视频。
        first_index = window.library_view.files.model().index(0, 0)
        second_index = window.library_view.files.model().index(1, 0)
        check('目录树实际绘制140×79视频画面', colored_pixels(window.library_view.files, first_index))
        check('两个硬链接入口均显示且共用缓存', colored_pixels(window.library_view.files, second_index) and len(window.thumbnails.images) == 1)  # 不重复解码同一个视频。
        check('旧32×32缓存重建为240×160', QImageReader(str(cache / f'{vid}.jpg')).size().width() == 240 and QImageReader(str(cache / f'{vid}.jpg')).size().height() == 160)  # 检查实际缓存迁移。
        check('生成缩略图不自动播放', window.current is None)  # 保持启动和导入时不自动播放规则。
        window.grab().save(str(output / 'directory-thumbnails.png'))  # 保存可供人工查看的目录缩略图截图。
        window.store.execute('UPDATE videos SET played=1,star=1 WHERE id=?', (vid,))  # 将测试视频加入历史和收藏。
        for mode in ['videos', 'stars']:  # 验证两个常用列表也无需选中才显示。
            window.library_view.show_mode(mode)
            listing = window.library_view.lists[mode]
            check(f'{mode}列表直接显示缩略图', wait_until(lambda: colored_pixels(listing, listing.model().index(0, 0))))
            window.grab().save(str(output / f'{mode}-thumbnails.png'))
        check('解码线程与排队数受限', window.thumbnails.pool.maxThreadCount() == 2 and len(window.thumbnails.pending) <= 24)  # 保证批量目录不无限启动解码器。
        report['success'] = True  # 本次所有可见性检查已通过。
    except Exception as error:  # 记录实际界面或解码失败。
        report['success'], report['error'] = False, repr(error)  # 明确标记未通过条件。
        window.grab().save(str(output / 'failure.png'))  # 保留失败现场截图。
    finally:  # 安全退出本次隔离验收。
        window.close()  # 保存测试状态并停止新请求。
        QThreadPool.globalInstance().waitForDone()  # 等待目录和预览工作线程。
        window.thumbnails.pool.waitForDone()  # 等待独立缩略图生成线程结束。
        (output / 'thumbnail-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 写出机器可读证据。
    return 0 if report.get('success') else 1  # 用退出码表示是否真正通过。

if __name__ == '__main__':  # 支持源码环境独立运行验证。
    sys.exit(run(sys.argv[1]))  # 输出路径由调用方明确指定。
