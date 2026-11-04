import json  # 记录本次标签与评分的专项结果。
import sys  # 读取隔离证据目录。
from pathlib import Path  # 限定所有测试文件的位置。
from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QTimer, QEvent  # 驱动真实点击与内部拖放事件。
from PySide6.QtGui import QDropEvent, QMouseEvent  # 经过正式拖放和悬停处理器。
from PySide6.QtTest import QTest  # 只测试标签与评分控件。
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QMenu  # 检查右键菜单与评分提交。
from core import Store, Archiver, identity  # 验证隔离标签目录的真实硬链接。
from tag_editor import TagEditor, MIME  # 使用正式胶囊界面。
from score_editor import ScoreEditor  # 使用正式五颗心界面。
from tag_migration import TagMigration  # 验证父标签的持久保存。

def run(destination):  # 不运行播放、删除或完整回归。
    output = Path(destination).absolute()  # 所有样例由调用方指定独立位置。
    output.mkdir(parents=True, exist_ok=True)  # 创建证据目录。
    application = QApplication.instance() or QApplication([])  # 初始化真实 Qt 控件。
    store = Store(output / 'data')  # 不打开用户数据库。
    sample = output / 'sample.mp4'  # 只验证分类文件操作，无需视频解码。
    sample.write_bytes(b'isolated tag and score fixture')  # 不读取或改动用户的视频。
    vid = store.register(sample)  # 用真实文件身份登记测试视频。
    names = ['绝区零', '爱丽丝', '黑丝', '空父类']  # 同时覆盖普通标签、子类与空父类。
    for name in names:  # 初始化四个旧版平级标签。
        store.execute('INSERT INTO tags VALUES(?)', (name,))  # 新界面应兼容已有标签。
    editor = TagEditor(store, vid)  # 打开真实标签卡。
    editor.show()  # 允许控件计算几何与点击区域。
    application.processEvents()  # 完成首次布局。
    checks = []  # 只记录本次实际执行的专项。
    def check(name, passed):  # 遇到失败立即停止，避免误报通过。
        checks.append({'name': name, 'passed': bool(passed)})  # 保存可核对结果。
        assert passed, name  # 不把失败包装成成功。
    def choose_parent_menu():  # 通过真实右键菜单操作指定父标签。
        menu = application.activePopupWidget()  # 获取正式菜单。
        assert isinstance(menu, QMenu)  # 菜单必须已实际打开。
        next(action for action in menu.actions() if action.text() == '设为父标签').trigger()  # 触发用户可见的父标签操作。
        menu.close()  # 结束菜单事件循环。
    QTimer.singleShot(0, choose_parent_menu)  # 在菜单显示后执行操作。
    editor.menu('绝区零', editor.mapToGlobal(QPoint(30, 30)))  # 经过正式菜单入口。
    editor.set_parent('空父类', True)  # 另一个父类必须保持折叠。
    application.processEvents()  # 完成胶囊重建。
    check('右键设为父标签且默认折叠', editor.schema['绝区零']['is_parent'] and not editor.expanded)  # 设置身份不展开子区。
    class InternalDrop(QDropEvent):  # 模拟同窗口原生拖动数据来源。
        def source(self):  # 正式处理器只接受当前标签编辑器。
            return editor  # 不绕过来源校验。
    mime = QMimeData()  # 与胶囊拖动使用同一 MIME 格式。
    mime.setData(MIME, '爱丽丝'.encode('utf-8'))  # 使用完整中文标签名。
    drop = InternalDrop(QPointF(10, 10), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)  # 构造真实 Qt 拖放事件。
    editor.drop_tag(drop, '绝区零')  # 调用正式落下处理器。
    application.processEvents()  # 完成归类后的布局。
    check('拖入父类后保持全部折叠', drop.isAccepted() and not editor.expanded and '爱丽丝' not in editor.chips)  # 不隐式展开。
    editor.grab().save(str(output / 'tags-collapsed.png'))  # 保存折叠界面证据。
    QTest.mouseClick(editor.chips['绝区零'], Qt.LeftButton)  # 点击父胶囊才显示子类。
    application.processEvents()  # 等待子类区布局。
    check('只展开主动点击的父标签', editor.expanded == {'绝区零'} and '爱丽丝' in editor.chips)  # 另一父标签仍折叠。
    QTest.mouseClick(editor.chips['爱丽丝'], Qt.LeftButton)  # 实际点击选中子标签。
    QTest.mouseClick(editor.chips['黑丝'], Qt.LeftButton)  # 普通标签仍能多选。
    editor.entry.setText('新增')  # 验证底部加号操作。
    QTest.mouseClick(editor.add_button, Qt.LeftButton)  # 新增不会自动提交。
    application.processEvents()  # 刷新胶囊。
    check('新增和多选保留已有展开集合', editor.expanded == {'绝区零'} and set(editor.chosen()) == {'爱丽丝', '黑丝', '新增'})  # 不展开其他父类。
    editor.grab().save(str(output / 'tags-expanded.png'))  # 保存主动展开的真实画面。
    check('确认前数据库未归类', store.tag_layout()['爱丽丝']['parent'] is None)  # 草稿不移动文件。
    editor.accept()  # 只有确认才向主流程提交草稿。
    archiver = Archiver(store, output / 'archive')  # 固定隔离归档根目录。
    migration = TagMigration(store, archiver)  # 使用正式持久化逻辑。
    migration.submit(vid, 9, editor.chosen(), list(editor.schema.values()))  # 应用标签及九分样例。
    layout = store.tag_layout()  # 重新读取数据库而非草稿。
    check('父子与空父标签持久保存', layout['爱丽丝']['parent'] == '绝区零' and layout['空父类']['is_parent'])  # 空父标签重开仍可接收拖动。
    paths = [Path(row['path']) for row in store.query('SELECT path FROM paths WHERE id=?', (vid,))]  # 获取真实归档入口。
    check('标签目录和九分文件名同步且共用实体', len(paths) == 3 and all(path.exists() and path.name.startswith('9分 绝区零（爱丽丝）') and identity(path) == identity(paths[0]) for path in paths))  # 不按标签复制内容。
    score = ScoreEditor(store.video(vid))  # 从真实九分记录绘制。
    score.show()  # 显示真实评分卡。
    application.processEvents()  # 绘制四颗半心形。
    score.grab().save(str(output / 'score-9.png'))  # 保存九分的半颗红心证据。
    check('评分只有五颗心且九分读数正确', len(score.hearts) == 5 and score.readout.text() == '9 / 10')  # 不保留十按钮界面。
    QTest.mouseClick(score.hearts[4], Qt.LeftButton, pos=QPoint(12, 24))  # 点击第五颗左半。
    check('第五颗左半提交九分', score.value == 9 and score.result() == QDialog.Accepted)  # 九分保持整数。
    for number in range(1, 11):  # 只检查十个半颗点击区域。
        card = ScoreEditor({'name': 'sample.mp4', 'score': None})  # 每次从未评分状态开始。
        card.show()  # 保证按钮可接收真实点击。
        QTest.mouseClick(card.hearts[(number - 1) // 2], Qt.LeftButton, pos=QPoint(12 if number % 2 else 36, 24))  # 左奇右偶。
        assert card.value == number and card.result() == QDialog.Accepted  # 所有分值都准确提交。
    check('十个半颗点击覆盖一至十分', True)  # 全部真实按钮点击通过才记录。
    for value, target in [(0, 'score_0'), (None, 'score_unrated')]:  # 零分与未评分分别测试。
        card = ScoreEditor({'name': 'sample.mp4', 'score': 9})  # 从已有评分修改。
        card.show()  # 创建真实操作目标。
        QTest.mouseClick(card.findChild(QPushButton, target), Qt.LeftButton)  # 点击零分或清除。
        check('独立状态 ' + target, card.value == value and card.result() == QDialog.Accepted)  # 未评分不能等于零。
    archiver.submit(vid, 8, editor.chosen())  # 真实评分变化同步全部标签入口。
    check('评分变化同步标签路径和原视频身份', store.video(vid)['score'] == 8 and store.resolve(vid).name.startswith('8分 绝区零（爱丽丝）') and all(not path.exists() for path in paths))  # 新评分生效且旧入口清理。
    preview = ScoreEditor(store.video(vid))  # 单独检查预览和取消不会保存。
    preview.show()  # 保证鼠标能够进入心形。
    hover = QMouseEvent(QEvent.MouseMove, QPointF(12, 24), QPointF(preview.hearts[4].mapToGlobal(QPoint(12, 24))), Qt.NoButton, Qt.NoButton, Qt.NoModifier)  # 固定悬停事件避免原生鼠标恰好位于同一点不发移动。
    application.sendEvent(preview.hearts[4], hover)  # 经过正式悬停处理器预览九分。
    application.processEvents()  # 分发真实鼠标移动事件。
    check('悬停预览不修改实际评分', preview.value == 8 and preview.preview == 9)  # 只有点击才提交。
    QTest.keyClick(preview, Qt.Key_Escape)  # 评分卡仍可取消。
    check('Esc 取消评分', preview.result() == QDialog.Rejected and store.video(vid)['score'] == 8)  # 不改变数据库。
    scrolling = TagEditor(store, vid)  # 构造仅含草稿的大标签列表。
    for index in range(100):  # 足够多的胶囊形成真实滚动区。
        name = f'滚动标签{index}'  # 与用户标签无关的隔离名称。
        scrolling.schema[name] = {'name': name, 'kind': 'major', 'parent': None, 'is_parent': False}  # 不写数据库。
    scrolling.rebuild()  # 按生产换行布局创建胶囊。
    scrolling.show()  # 让滚动条产生实际范围。
    application.processEvents()  # 完成控件布局。
    bar = scrolling.scroll.verticalScrollBar()  # 读取实际滚动条。
    bar.setValue(bar.maximum() // 2)  # 模拟用户停在列表中间。
    before = bar.value()  # 记录归类前的位置。
    scrolling.assign_parent('滚动标签0', '空父类')  # 将普通标签移入折叠父类。
    application.processEvents()  # 完成重建和延迟视口恢复。
    check('归类不跳顶部且不展开父类', before > 0 and bar.value() == before and not scrolling.expanded)  # 同时确认关键交互约束。
    scrolling.reject()  # 丢弃大列表样例草稿。
    (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 保存本次有限范围的测试结果。
    store.db.close()  # 关闭隔离数据库。
    print(f'标签与评分专项：{len(checks)}/{len(checks)} 通过')  # 不宣称完整回归。

if __name__ == '__main__':  # 仅显式调用时运行专项。
    run(sys.argv[1])  # 证据输出路径必须由调用者提供。
