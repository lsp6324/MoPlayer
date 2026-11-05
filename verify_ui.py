import json  # 保存外观回归证据。
import shutil  # 验证便携目录迁移。
import sys  # 接收独立测试目录。
from pathlib import Path  # 管理测试资源。
from unittest.mock import patch  # 模拟文件选择而不触碰用户图片。
from PySide6.QtCore import Qt, QTimer, QThreadPool  # 驱动模态窗口与异步任务。
from PySide6.QtGui import QImage, QColor  # 创建可辨识的背景测试图。
from PySide6.QtWidgets import QApplication, QPushButton, QDialogButtonBox, QSlider  # 操作实际设置控件。
from appearance import Appearance, BackgroundCanvas
from appearance_dialog import AppearanceDialog
from theme import apply_theme

def run(destination):  # 源码与打包 EXE 共用真实界面验收。
    from app import Window, BUNDLE  # 延迟加载正式播放器。
    output = Path(destination).absolute()  # 使用明确的隔离测试目录。
    output.mkdir(parents=True, exist_ok=True)  # 创建报告目录。
    application = QApplication.instance() or QApplication([])  # 初始化真实 Qt 控件。
    window = Window(output / 'data')  # 不修改用户数据库。
    def appearance_dialog(window):
        return AppearanceDialog(window,window.appearance,
            preview_theme=lambda theme,accent:apply_theme(window,theme,accent),
            preview_background=window.canvas.set_background).exec()
    report = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}  # 记录执行环境与结果。
    def check(name, result):  # 每个断言同时记录到报告。
        report['checks'].append({'name': name, 'ok': bool(result)})  # 保存实际判断值。
        if not result:  # 任何失败均终止验收。
            raise AssertionError(name)  # 不隐藏错误。
    try:  # 失败时也保留诊断证据。
        window.show()  # 显示完整界面用于渲染验证。
        application.processEvents()  # 完成初始布局。
        window.grab().save(str(output / 'blue-layout.png'))  # 保存蓝色默认布局截图。
        check('云璃窗口图标和原始素材已加载', not window.windowIcon().isNull() and (BUNDLE / 'assets/yunli-chibi.png').is_file())  # 检查实际包内资源。
        picture = QImage(800, 600, QImage.Format_RGB32)  # 生成不含用户内容的背景夹具。
        for y in range(600):  # 构造可明显观察的蓝紫渐变。
            for x in range(800):  # 对每个测试像素赋值。
                picture.setPixelColor(x, y, QColor(60 + x // 5, 95 + y // 5, 220))  # 使用合法 RGB 范围。
        original = output / 'original.png'  # 模拟用户选择的本地原图。
        picture.save(str(original))  # 将夹具写到测试目录。
        original_bytes = original.read_bytes()  # 保存原图基线用于比较。
        def interact(save):  # 通过真实弹窗按钮修改背景。
            dialog = QApplication.activeModalWidget()  # 获取生产外观弹窗。
            dialog.findChild(QPushButton, 'chooseBackground').click()  # 打开被模拟的文件选择器。
            dialog.findChild(QSlider, 'backgroundStrength').setValue(80)  # 验证强度调节。
            dialog.grab().save(str(output / 'appearance-dialog.png'))  # 保存设置界面实际画面。
            controls = dialog.findChild(QDialogButtonBox)  # 定位明确提交按钮。
            controls.button(QDialogButtonBox.Ok if save else QDialogButtonBox.Cancel).click()  # 分别验证提交和撤销。
        with patch('appearance_dialog.QFileDialog.getOpenFileName', return_value=(str(original), 'PNG')):
            QTimer.singleShot(150, lambda: interact(False))  # 先验证用户取消预览。
            appearance_dialog(window)  # 执行实际模态设置流程。
            check('取消预览恢复默认且不写配置', window.canvas.image.isNull() and not window.appearance.file.exists())  # 不把临时预览误当成功提交。
            QTimer.singleShot(150, lambda: interact(True))  # 再验证明确确认。
            appearance_dialog(window)  # 保存生产配置与背景副本。
        saved = window.appearance.background  # 获取实际便携副本路径。
        check('保存副本且原图内容不变', saved.is_file() and saved != original and original.read_bytes() == original_bytes)  # 保护用户原始图片。
        restored = Appearance(output / 'data')  # 模拟重新启动读取配置。
        check('重启恢复背景与强度', restored.background == saved and restored.strength == 80)  # 验证持久化。
        shutil.copytree(output / 'data/appearance', output / 'moved/appearance')  # 模拟整个便携数据移动。
        moved = Appearance(output / 'moved')  # 从新位置读取相对路径。
        check('移动目录后背景仍有效', moved.background.is_file() and moved.background.parent == output / 'moved/appearance')  # 配置不依赖开发机路径。
        window.grab().save(str(output / 'custom-background.png'))  # 记录自定义背景效果。
        check('外观调整不导入或播放视频', window.current is None and window.library_controller.browsing is None)  # 保持启动交互约束。
        broken = output / 'broken.png'  # 构造损坏图像。
        broken.write_bytes(b'not an image')  # 写入不能解码的数据。
        rejected = False  # 记录是否正确拒绝坏图。
        try:  # 无效背景不能覆盖成功保存的配置。
            window.appearance.save(broken, 60)  # 尝试导入损坏图片。
        except ValueError:  # 预期给出图像错误。
            rejected = True  # 标记拒绝成功。
        check('损坏图片不覆盖原配置', rejected and window.appearance.background == saved)  # 保护已保存设置。
        moved.background.write_bytes(b'broken')  # 模拟已存背景被外部破坏。
        fallback = BackgroundCanvas(moved)  # 实际构造启动背景。
        check('背景损坏时安全回退默认', fallback.image.isNull())  # 不因背景导致应用无法打开。
        window.appearance.save(None, 60)  # 验证清除自定义背景。
        check('可恢复默认渐变', Appearance(output / 'data').background is None)  # 确认持久化清除成功。
        report['success'] = True  # 所有检查通过后才能标记成功。
    except Exception as error:  # 记录真实失败原因。
        report['success'], report['error'] = False, repr(error)  # 不掩盖异常。
    finally:  # 保证测试任务安全退出。
        window.close()  # 停止播放与定时器。
        QThreadPool.globalInstance().waitForDone()  # 等待后台任务。
        window.thumbnails.pool.waitForDone()  # 等待缩略图工作池。
        (output / 'ui-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')  # 保存机器可读验收结果。
    return 0 if report.get('success') else 1  # 向调用者返回真实结果。

if __name__ == '__main__':  # 支持直接运行源码测试。
    sys.exit(run(sys.argv[1]))  # 输出到调用者指定的隔离目录。
