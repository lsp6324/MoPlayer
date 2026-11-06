import json  # 保存本次标签改动的独立验收记录。
import sys  # 读取隔离输出路径。
from pathlib import Path  # 不接触用户视频或数据库。
from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QTimer  # 驱动标签点击与内部拖放。
from PySide6.QtGui import QDropEvent  # 使用正式落下处理器。
from PySide6.QtTest import QTest  # 点击真实标签按钮。
from PySide6.QtWidgets import QApplication, QMenu  # 检查右键删除操作。
from moplayer.core import Store, Archiver, identity, validate_layout  # 使用真实数据库与硬链接归档。
from moplayer.gui.tag_editor import TagEditor, MIME  # 验证正式标签界面。
from moplayer.tag_migration import TagMigration  # 验证全局分类同步。

def run(destination):  # 只验证本次标签需求，不运行完整回归。
    output = Path(destination).absolute()  # 显式指定新建的隔离目录。
    output.mkdir(parents=True, exist_ok=True)  # 保存样例与证据。
    app = QApplication.instance() or QApplication([])  # 创建正式 Qt 控件。
    store = Store(output / 'data')  # 与用户数据库隔离。
    archiver = Archiver(store, output / 'archive')  # 与真实归档目录隔离。
    migration = TagMigration(store, archiver)  # 使用生产批次同步机制。
    ids = []  # 保存不同样例的永久身份。
    for number in range(3):  # 覆盖当前、其他已归档和其他未归档视频。
        sample = output / f'{number}.mp4'  # 文件内容不用于解码。
        sample.write_bytes(f'isolated nested tag fixture {number}'.encode())  # 仅生成小型分类样例。
        ids.append(store.register(sample))  # 真实登记独立文件身份。
    archiver.submit(ids[0], 8, ['角色', '待删除'])  # 准备当前视频多标签硬链接。
    archiver.submit(ids[1], 9, ['角色', '待删除'])  # 验证全局改动不改变其他视频评分。
    store.execute('UPDATE videos SET tags=? WHERE id=?', (json.dumps(['待删除']), ids[2]))  # 未归档样例仅含将删除的标签。
    for name in ['游戏', '3D']:  # 创建两个并列父标签候选。
        store.execute('INSERT INTO tags VALUES(?)', (name,))  # 保留实际公共字典行为。
    editor = TagEditor(json.loads(store.video(ids[0])['tags']), store.tag_layout())  # 打开生产标签卡。
    editor.set_parent('游戏', True)  # 对应右键指定父标签。
    editor.set_parent('3D', True)  # 另一个根父标签。
    editor.assign_parent('角色', '3D')  # 为被移动父标签保留原有子标签。
    editor.show()  # 创建真实点击目标。
    app.processEvents()  # 等待布局完成。
    checks = []  # 本轮只记录标签改动。
    def check(name, passed):  # 所有结果必须来自实际状态。
        checks.append({'name': name, 'passed': bool(passed)})  # 保存逐项证据。
        assert passed, name  # 失败时立即停止，不交付假成功。
    QTest.mouseClick(editor.chips['游戏'].arrow, Qt.LeftButton)
    app.processEvents()  # 完成子区重建。
    QTest.mouseClick(editor.chips['3D'].arrow, Qt.LeftButton)
    app.processEvents()  # 完成两组行下展开。
    check('不同父标签可分别在行下展开', editor.expanded == {'游戏', '3D'} and '角色' in editor.chips)
    class InternalDrop(QDropEvent):  # 与正式胶囊拖动保持相同来源校验。
        def source(self):  # 指定同一编辑器来源。
            return editor  # 外部文件仍不能成为标签。
    mime = QMimeData()  # 使用生产内部拖动格式。
    mime.setData(MIME, '3D'.encode('utf-8'))  # 父标签作为拖动源。
    event = InternalDrop(QPointF(10, 10), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)  # 生成真实 Qt 落下事件。
    editor.drop_tag(event, '游戏')  # 父标签归入另一个父标签。
    app.processEvents()  # 保留两组原有展开状态。
    check('父标签拖入父标签保留原有子标签', event.isAccepted() and editor.schema['3D']['parent'] == '游戏' and editor.schema['角色']['parent'] == '3D' and editor.schema['3D']['is_parent'])  # 不丢失后代。
    if '游戏' not in editor.expanded:
        editor.chips['游戏'].arrow.click()
    app.processEvents()  # 显示子父标签胶囊。
    if '3D' not in editor.expanded:
        QTest.mouseClick(editor.chips['3D'].arrow, Qt.LeftButton)
    app.processEvents()  # 等待嵌套子区完成布局。
    check('子父标签在父区内继续行下展开', editor.expanded == {'游戏', '3D'} and '角色' in editor.chips
          and editor.panels['游戏'].isAncestorOf(editor.panels['3D']))
    check('禁止把祖先拖入后代', not editor.assign_parent('游戏', '3D') and editor.schema['游戏']['parent'] is None)  # 防止无限路径。
    validate_layout(editor.schema.values())  # 后端也必须接受合法多层关系。
    editor.grab().save(str(output / 'nested-parent.png'))  # 保存实际子父标签界面。
    migration.submit(ids[0], 8, editor.chosen(), list(editor.schema.values()))  # 真正同步两个已归档视频。
    check('多层目录与嵌套名称同步', (output / 'archive/8分/游戏/3D/角色/0.mp4').exists() and store.resolve(ids[1]).name=='1.mp4')  # 校验真实路径和其他评分。
    paths = store.query('SELECT path FROM paths WHERE id=?', (ids[0],))  # 读取所有真实入口。
    check('嵌套后仍共用硬链接实体', len(paths) == 2 and len({identity(row['path']) for row in paths}) == 1)  # 没有复制视频内容。
    def delete_menu():  # 从用户可见的右键菜单触发删除。
        menu = app.activePopupWidget()  # 获取正式菜单。
        assert isinstance(menu, QMenu)  # 必须已实际创建右键菜单。
        next(action for action in menu.actions() if action.text() == '删除标签').trigger()  # 不直接删除数据库记录。
        menu.close()  # 返回标签草稿界面。
    QTimer.singleShot(0, delete_menu)  # 在菜单事件循环内操作。
    editor.menu('待删除', editor.mapToGlobal(QPoint(20, 20)))  # 普通标签右键必须有删除入口。
    check('右键删除确认前只改草稿', '待删除' not in editor.schema and '待删除' in store.tag_layout())  # 仍可取消修改。
    migration.submit(ids[0], 8, editor.chosen(), list(editor.schema.values()))  # 应用后才全局移除。
    check('删除标签全局移除且不复活', '待删除' not in store.tag_layout() and all('待删除' not in json.loads(store.video(vid)['tags']) for vid in ids))  # 包括未归档视频。
    check('删除标签保留视频及未归档状态', all(store.resolve(vid).exists() for vid in ids) and store.video(ids[2])['archived'] == 0)  # 不借全局删除移动未归档来源。
    editor.delete_tag('3D')  # 删除有子节点的父标签。
    migration.submit(ids[0], 8, editor.chosen(), list(editor.schema.values()))  # 同步子标签提升后的真实目录。
    check('删除父标签提升子节点并同步路径', store.tag_layout()['角色']['parent'] == '游戏' and store.resolve(ids[0]).name == '0.mp4' and store.resolve(ids[1]).name == '1.mp4')  # 不删除角色或其他视频。
    editor.delete_tag('角色')  # 清除最后一个实际选择的标签。
    migration.submit(ids[0], 8, editor.chosen(), list(editor.schema.values()))  # 应用后进入未分类保护目录。
    check('删除最后标签仍保留视频在未分类', store.resolve(ids[0]).parent.name == '未分类' and store.resolve(ids[1]).parent.name == '未分类')  # 不删除最后一个有效入口。
    editor.reject()  # 关闭测试窗口。
    store.db.close()  # 关闭隔离数据库。
    (output / 'results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')  # 写入本次实际测试结果。
    print(f'标签嵌套与删除专项：{len(checks)}/{len(checks)} 通过')  # 不宣称完整测试。

if __name__ == '__main__':  # 只在显式调用时运行。
    run(sys.argv[1])  # 所有输出使用调用者指定目录。
