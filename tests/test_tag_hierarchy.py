import json  # 检查全局批次和标签元数据。
import threading  # 验证扫描登记不能穿插文件迁移提交。
from pathlib import Path  # 检查被迁移的旧入口是否已清理。
import pytest  # 参数化校验危险结构与中断恢复。
from moplayer.core import Store, Archiver, identity, validate_layout, archive_name  # 使用真实路径、硬链接和永久身份实现。
from moplayer.tag_migration import TagMigration  # 验证跨多个视频的全局迁移。
from moplayer.video_delete import DeletionManager  # 检查全局迁移与删除互斥保护。

def schema(parent='绝区零'):  # 创建两个独立标签和一个父子分类。
    return [{'name': parent, 'kind': 'major', 'parent': None}, {'name': '爱丽丝', 'kind': 'minor', 'parent': parent}, {'name': '黑丝', 'kind': 'major', 'parent': None}]  # 使用用户示例中的名称。

def library(tmp_path):  # 创建两个包含相同角色标签的视频。
    store = Store(tmp_path / 'data')  # 与真实视频库完全隔离。
    archive = Archiver(store, tmp_path / 'archive')  # 不使用用户归档根目录。
    vids = []  # 保留检查用的稳定身份。
    for name, score in [('abc-123.mp4', 8), ('second.mp4', 9)]:  # 覆盖不同评分下的全局迁移。
        path = tmp_path / name  # 样例独立于用户数据。
        path.write_bytes(name.encode())  # 内容不同可证明没有同名身份混淆。
        vid = store.register(path)  # 分配永久 UUID。
        archive.submit(vid, score, ['绝区零', '爱丽丝', '黑丝'])  # 模拟旧版本三个平级入口。
        store.execute('UPDATE videos SET star=1,position=1234,played=1 WHERE id=?', (vid,))  # 加入需保持的收藏历史进度。
        vids.append(vid)  # 两个视频都应受角色结构变更影响。
    return store, archive, vids  # 提供正式生产组件。

def test_global_hierarchy_and_rating(tmp_path):  # 全部相关视频同步路径、名称且仍共用各自内容。
    store, archive, vids = library(tmp_path)  # 初始化旧版平级库。
    entities = {vid: identity(store.resolve(vid)) for vid in vids}  # 记录两个独立内容实体。
    old_paths = [row['path'] for row in store.query('SELECT path FROM paths')]  # 保存清理前的全部入口。
    affected = TagMigration(store, archive).submit(vids[0], 8, ['绝区零', '爱丽丝', '黑丝'], schema())  # 一次确认修改全局角色归属。
    assert set(affected) == set(vids)  # 不只更新当前视频。
    for vid, score, original in zip(vids, [8, 9], ['abc-123.mp4', 'second.mp4']):  # 两条视频保持自己的评分和原名。
        name = original  # 文件名独立于父子分类。
        paths = [archive.root / f'{score}分' / '绝区零' / '爱丽丝' / name, archive.root / f'{score}分' / '黑丝' / name]  # 小类嵌套，独立标签保持原层级。
        assert all(path.exists() and identity(path) == entities[vid] for path in paths)  # 同卷迁移没有复制或换实体。
        assert paths[0].stat().st_nlink == 2  # 同时勾选父子不多创建父级根入口。
        assert store.video(vid)['star'] == 1 and store.video(vid)['position'] == 1234  # 历史收藏和进度不变。
        assert json.loads(store.video(vid)['tags']) == ['爱丽丝', '黑丝']  # 父级由全局关系隐含保存。
    assert all(not Path(path).exists() for path in old_paths if '爱丽丝' in Path(path).parts and '绝区零' not in Path(path).parts)  # 原平级入口已在新入口安全后清理。
    archive.submit(vids[0], 10, ['爱丽丝', '黑丝'])  # 后续 R 评分沿用全局层级。
    assert store.resolve(vids[0]).name == 'abc-123.mp4' and store.resolve(vids[0]).parent.parent.name == '绝区零'  # 评分不能把小类恢复为平级。

def test_reparent_and_independent(tmp_path):  # 小类换父级和恢复独立大类均同步所有视频。
    store, archive, vids = library(tmp_path)  # 创建两条相关记录。
    manager = TagMigration(store, archive)  # 共用全局批次管理器。
    manager.submit(vids[0], 8, ['爱丽丝', '黑丝'], schema())  # 首次建立角色归属。
    new_schema = schema('新大类') + [{'name': '绝区零', 'kind': 'major', 'parent': None}]  # 移动角色到另一个大类。
    manager.submit(vids[0], 8, ['爱丽丝', '黑丝'], new_schema)  # 再次确认全局变更。
    assert all((archive.root/f"{store.video(vid)['score']}分"/'新大类'/'爱丽丝'/store.video(vid)['original_name']).exists() for vid in vids)  # 所有包含该小类的视频同步目录。
    new_schema[1] = {'name': '爱丽丝', 'kind': 'major', 'parent': None}  # 明确恢复为独立大类。
    manager.submit(vids[0], 8, ['爱丽丝', '黑丝'], new_schema)  # 迁移回单层入口。
    assert all('（' not in store.resolve(vid).name for vid in vids)  # 不残留旧父级文件名前缀。

def test_batch_interruption_recovery(tmp_path):  # 第一条完成后中断仍能恢复剩余视频及公共结构。
    store, archive, vids = library(tmp_path)  # 使用真实硬链接和数据库。
    def fault(stage):  # 模拟批次检查点后异常退出。
        raise RuntimeError('批次中断')  # 已完成视频仍保持有效入口。
    with pytest.raises(RuntimeError, match='批次中断'):  # 不应报告全部应用成功。
        TagMigration(store, archive, fault).submit(vids[0], 8, ['爱丽丝'], schema())  # 批次在第一条后暂停。
    assert store.tag_layout()['爱丽丝']['kind'] == 'major'  # 全局结构在全部完成前不伪报成功。
    assert all(store.resolve(vid).exists() for vid in vids)  # 两个视频始终可定位。
    assert TagMigration(store, archive).recover() == []  # 新进程从持久计划继续。
    assert store.tag_layout()['爱丽丝']['parent'] == '绝区零'  # 所有文件成功后才提交公共关系。
    assert all((archive.root/f"{store.video(vid)['score']}分"/'绝区零'/'爱丽丝'/store.video(vid)['original_name']).exists() for vid in vids)  # 剩余视频也完成。

def test_child_archive_failure_recovery(tmp_path):  # 单视频建立新入口后失败仍能恢复整个批次。
    store, archive, vids = library(tmp_path)  # 创建两个既有归档视频。
    def fault(stage):  # 在归档子任务的 linked 阶段模拟退出。
        if stage == 'linked':  # 旧入口尚未清理。
            raise RuntimeError('子任务中断')  # 新旧入口都保留供恢复。
    archive.fault = fault  # 使用真实归档日志而非模拟结果。
    with pytest.raises(RuntimeError, match='子任务中断'):  # 不弹出成功后的评分。
        TagMigration(store, archive).submit(vids[0], 8, ['爱丽丝'], schema())  # 批次保持未完成状态。
    archive.fault = None  # 模拟下次启动故障已消失。
    assert TagMigration(store, archive).recover() == []  # 先恢复子任务，再继续批次。
    assert all(row['state'] == 'done' for row in store.query('SELECT state FROM jobs'))  # 不遗留进行中的归档。
    assert all(store.resolve(vid).exists() for vid in vids)  # 所有视频可播放入口始终保留。

def test_global_database_failure(tmp_path):  # 文件已迁移但全局关系提交失败时保留可恢复记录。
    store, archive, vids = library(tmp_path)  # 创建独立数据库。
    store.execute('CREATE TRIGGER fail_layout BEFORE INSERT ON tag_layout BEGIN SELECT RAISE(ABORT,"结构提交失败"); END')  # 注入真实 SQLite 写入失败。
    with pytest.raises(Exception, match='结构提交失败'):  # 批次必须显示失败。
        TagMigration(store, archive).submit(vids[0], 8, ['爱丽丝'], schema())  # 磁盘操作已安全完成。
    assert all(store.resolve(vid).exists() for vid in vids) and not store.query('SELECT * FROM tag_layout')  # 全局事务回滚且文件不丢失。
    store.execute('DROP TRIGGER fail_layout')  # 恢复数据库可写状态。
    assert TagMigration(store, archive).recover() == []  # 不需重新移动文件即可提交结构。
    assert store.tag_layout()['爱丽丝']['kind'] == 'minor'  # 最终数据库与目录语义一致。

@pytest.mark.parametrize('rows', [[{'name': 'a', 'kind': 'minor', 'parent': None}], [{'name': 'a', 'kind': 'major', 'parent': 'a'}], [{'name': 'a', 'kind': 'minor', 'parent': 'b'}, {'name': 'b', 'kind': 'minor', 'parent': 'a'}], [{'name': '../bad', 'kind': 'major'}], [{'name': 'A', 'kind': 'major'}, {'name': 'a', 'kind': 'major'}]])  # 覆盖未归属、循环、穿越与大小写重复。
def test_invalid_layout(rows):  # 错误结构必须在文件操作前被拒绝。
    with pytest.raises(ValueError):  # 不悄悄改写不合法分类。
        validate_layout(rows)  # 使用正式全局校验函数。

def test_multiple_children_name():  # 多个子类合并在同一大类括号内。
    rows = schema() + [{'name': '角色2', 'kind': 'minor', 'parent': '绝区零'}]  # 添加第二个角色。
    layout = validate_layout(rows)  # 固定有效的两级结构。
    assert archive_name('xxx.mp4') == 'xxx.mp4'  # 分类不再写入文件名。

def test_pending_batch_protects_file_operations(tmp_path):  # 部分迁移时禁止其他归档或删除覆盖恢复意图。
    store, archive, vids = library(tmp_path)  # 创建真实旧版平级入口。
    def fault(stage):  # 第一个视频完成后保留未完成批次。
        raise RuntimeError('中断')  # 模拟用户稍后恢复。
    with pytest.raises(RuntimeError):  # 首次提交保持失败状态。
        TagMigration(store, archive, fault).submit(vids[0], 8, ['爱丽丝'], schema())  # 结构尚未全局提交。
    with pytest.raises(RuntimeError, match='标签结构迁移'):  # 删除不能移走批次还需要的入口。
        DeletionManager(store).submit(vids[1])  # 校验阶段拒绝，不调用系统回收站。
    with pytest.raises(RuntimeError, match='标签结构迁移'):  # 独立评分归档也不能覆盖冻结目标。
        archive.submit(vids[1], 0, [])  # 原批次保持可恢复。
    assert all(store.resolve(vid).exists() for vid in vids)  # 两条视频数据均受保护。

def test_invalid_selection_rejected_before_batch(tmp_path):  # 非法路径标签不得成为无法恢复的持久意图。
    store, archive, vids = library(tmp_path)  # 初始化隔离样例。
    before = [row['path'] for row in store.query('SELECT path FROM paths')]  # 保存原入口集合。
    with pytest.raises(ValueError):  # 非法名称在日志与文件变动前拒绝。
        TagMigration(store, archive).submit(vids[0], 8, ['../bad'], schema())  # 不容许路径穿越。
    assert not store.query('SELECT * FROM hierarchy_jobs') and all(Path(path).exists() for path in before)  # 原结构、文件和任务状态保持原样。

def test_scan_registration_waits_for_file_commit(tmp_path):  # 大目录扫描与归档并发时不重新创建已移走的旧入口。
    store = Store(tmp_path / 'data')  # 创建线程共享但受锁保护的实际数据库。
    source = tmp_path / 'source.mp4'  # 仅测试生成的来源文件。
    source.write_bytes(b'concurrent-scan')  # 内容用于稳定身份检查。
    vid = store.register(source)  # 原视频只有一个永久身份。
    linked, proceed, registered = threading.Event(), threading.Event(), threading.Event()  # 精确控制归档与扫描的交叉时刻。
    errors = []  # 保存后台线程真实异常。
    def checkpoint(stage):  # 暂停在新入口创建完成但旧入口尚未清理的阶段。
        if stage == 'linked':  # 此时目录扫描最容易重新登记旧路径。
            linked.set()  # 通知测试可以启动并发扫描。
            assert proceed.wait(5)  # 有限等待，不让失败测试挂起。
    archive = Archiver(store, tmp_path / 'archive', fault=checkpoint)  # 使用正式文件操作和检查点。
    def migrate():  # 在真实后台线程执行归档。
        try:  # 线程异常必须交给主测试断言。
            archive.submit(vid, 8, ['测试'])  # 来源最终从原位置移出。
        except Exception as error:  # 不丢失工作线程失败。
            errors.append(error)  # 供最终验证。
    def discover():  # 模拟已取消扫描中最后一个尚在执行的登记。
        try:  # 迁移结束后旧路径应已不存在。
            store.register(source)  # 必须先等待文件操作共享锁。
        except FileNotFoundError:  # 不能为失效旧路径创建新视频。
            pass  # 正确地丢弃已移动的来源项。
        finally:  # 无论成功或失败都通知线程结束。
            registered.set()  # 可断言扫描确实等到提交后才完成。
    migration = threading.Thread(target=migrate)  # 启动归档线程。
    migration.start()  # 进入受共享锁保护的文件事务。
    assert linked.wait(5)  # 新入口真实建立后再模拟扫描。
    scanner = threading.Thread(target=discover)  # 扫描登记使用同一个 Store。
    scanner.start()  # 尝试登记仍处于迁移中的来源路径。
    try:  # 失败也必须放行后台事务。
        assert not registered.wait(0.1)  # 扫描不能在事务中间完成登记。
    finally:  # 防止断言失败遗留阻塞线程。
        proceed.set()  # 允许归档完成数据库提交和旧入口清理。
        migration.join(5)  # 有限等待归档结束。
        scanner.join(5)  # 扫描随后观察到旧路径已经消失。
    assert not errors and not migration.is_alive() and not scanner.is_alive()  # 所有线程正常结束。
    assert len(store.query('SELECT * FROM videos')) == 1 and not store.query('SELECT * FROM paths WHERE path=?', (str(source),))  # 不产生重复身份或失效旧路径映射。
