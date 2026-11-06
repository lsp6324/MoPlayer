import os  # 创建测试视频的硬链接入口。
import threading  # 驱动正式目录扫描。
import pytest  # 验证故障及恢复结果。
from moplayer.core import Store, Archiver, scan  # 使用实际数据库和播放顺序实现。
from moplayer.video_delete import DeletionManager  # 测试生产删除事务。

def setup(tmp_path):  # 构造完全隔离的文件与回收替身。
    store = Store(tmp_path / 'data')  # 每项测试使用独立数据库。
    source = tmp_path / 'source'  # 不访问用户视频目录。
    source.mkdir()  # 建立样例文件夹。
    path = source / '1.mp4'  # 文件内容仅用于身份与事务验证。
    path.write_bytes(b'original-video')  # 创建独立文件实体。
    vid = store.register(path)  # 分配真实稳定身份。
    recycled = tmp_path / 'bin'  # 替身保留内容便于验证不丢数据。
    recycled.mkdir()  # 仅在测试中模拟回收站。
    def recycle(item):  # 移动入口而不永久删除内容。
        item.rename(recycled / (str(len(list(recycled.iterdir()))) + item.name))  # 保留所有回收结果避免同名覆盖。
    return store, source, path, vid, recycled, recycle  # 提供检查所需对象。

def test_all_links_and_metadata(tmp_path):  # 同身份所有入口完成后才清理历史收藏。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化隔离样例。
    linked = source / 'link.mp4'  # 模拟另一个标签入口。
    os.link(path, linked)  # 两条路径共用一个视频实体。
    assert store.register(linked) == vid  # 真实身份去重。
    store.execute('UPDATE videos SET star=1,played=1,position=5000 WHERE id=?', (vid,))  # 为删除加入元数据。
    DeletionManager(store, recycle).submit(vid)  # 执行正式删除流程。
    assert not path.exists() and not linked.exists()  # 全部入口都已移走。
    assert not store.query('SELECT * FROM videos') and not store.query('SELECT * FROM paths')  # 无残留历史或收藏。
    assert len(list(recycled.iterdir())) == 2  # 回收内容仍然存在。
    assert store.query('SELECT state FROM deletion_jobs')[0]['state'] == 'done'  # 真实完成才提交状态。

@pytest.mark.parametrize('stage', ['planned', 'recycling', 'files_recycled'])  # 覆盖文件与数据库提交边界。
def test_interruption_recovery(tmp_path, stage):  # 任意阶段中断后可幂等恢复。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 使用独立数据库。
    def fault(current):  # 模拟进程在持久检查点后退出。
        if current == stage:  # 仅在指定阶段注入一次失败。
            raise RuntimeError('模拟中断')  # 保留已落盘任务。
    with pytest.raises(RuntimeError):  # 不应把中断显示成成功。
        DeletionManager(store, recycle, fault).submit(vid)  # 文件操作可能已发生但身份尚保留。
    assert store.video(vid)  # 元数据在最终提交之前仍然有效。
    assert DeletionManager(store, recycle).recover() == []  # 新管理器只从数据库重建计划。
    assert not store.query('SELECT * FROM videos') and len(list(recycled.iterdir())) == 1  # 不重复回收且数据仍可恢复。

def test_occupied_retry(tmp_path):  # 外部占用失败时不删除元数据且允许重试。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化隔离样例。
    def occupied(item):  # 模拟 Windows 拒绝文件操作。
        raise PermissionError('文件被占用')  # 文件保留在原位置。
    with pytest.raises(PermissionError):  # 必须报告真实失败。
        DeletionManager(store, occupied).submit(vid)  # 第一次操作失败。
    assert path.exists() and store.video(vid)  # 失败不能清空视频元数据。
    DeletionManager(store, recycle).submit(vid)  # 使用相同持久任务恢复。
    assert len(store.query('SELECT * FROM deletion_jobs')) == 1 and not path.exists()  # 重试不产生重复任务。

def test_replaced_identity_protected(tmp_path):  # 同名替换不能被误删。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 保存原身份。
    path.rename(source / 'original.mp4')  # 保留旧文件防止系统复用文件索引。
    path.write_bytes(b'different-video')  # 原路径放入另一视频。
    with pytest.raises(OSError):  # 文件名相同不足以通过删除预检。
        DeletionManager(store, recycle).submit(vid)  # 不触碰替换后的内容。
    assert path.read_bytes() == b'different-video' and not list(recycled.iterdir())  # 无任何误删。

def test_partial_links_retry(tmp_path):  # 第二入口失败时第一个仍在回收站且剩余可恢复。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化隔离样例。
    linked = source / '2.mp4'  # 增加第二入口。
    os.link(path, linked)  # 保留同一个实体。
    store.register(linked)  # 登记全部入口。
    def partial(item):  # 仅第二入口模拟占用。
        if item == linked:  # 第一入口已完成回收。
            raise PermissionError('第二入口占用')  # 保留其余有效入口。
        recycle(item)  # 正常移动第一个入口。
    with pytest.raises(PermissionError):  # 部分完成仍然属于失败。
        DeletionManager(store, partial).submit(vid)  # 不提前删除元数据。
    assert linked.exists() and store.resolve(vid) == linked  # 尚存入口可以继续播放。
    assert DeletionManager(store, recycle).recover() == []  # 只处理剩下的入口。
    assert len(list(recycled.iterdir())) == 2  # 不会丢失最后入口。

def test_archive_conflict_and_navigation(tmp_path):  # 删除不破坏原索引及归档互斥。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化隔离样例。
    for name in ['2.mp4', '10.mp4']:  # 建立自然顺序可验证样例。
        (source / name).write_bytes(name.encode())  # 独立文件身份。
    context, errors = scan(source, store, threading.Event())  # 使用正式扫描。
    second = context.folders[str(source)][1][1][0]  # 记录中间视频身份。
    context.excluded.add(second)  # 模拟删除后保留快照索引。
    assert context.step((str(source), 0), 1) == (str(source), 2)  # 下一个跳过已删除视频。
    assert context.step((str(source), 2), -1) == (str(source), 0)  # 上一个仍在当前文件夹。
    assert context.step((str(source), 2), 1) is None  # 不回绕播放。
    def occupied(item):  # 创建可恢复的未完成删除任务。
        raise PermissionError('占用')  # 文件仍在来源目录。
    with pytest.raises(PermissionError):  # 持久记录删除请求。
        DeletionManager(store, occupied).submit(vid)  # 创建未完成状态。
    with pytest.raises(RuntimeError, match='删除任务'):  # 同一视频不得交叉归档。
        Archiver(store, tmp_path / 'archive').submit(vid, 8, ['测试'])  # 不与删除争夺最后入口。

def test_database_commit_failure(tmp_path):  # 文件已回收但数据库提交失败时可以继续恢复。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化独立数据库。
    store.execute('CREATE TRIGGER fail_delete BEFORE DELETE ON videos BEGIN SELECT RAISE(ABORT,"数据库故障"); END')  # 注入真实 SQLite 写入失败。
    with pytest.raises(Exception, match='数据库故障'):  # 数据库失败必须向上层报告。
        DeletionManager(store, recycle).submit(vid)  # 文件阶段完成，事务删除阶段回滚。
    assert not path.exists() and store.video(vid) and store.query('SELECT * FROM paths WHERE id=?', (vid,))  # 回收数据安全且元数据原子保留。
    store.execute('DROP TRIGGER fail_delete')  # 模拟数据库恢复可写。
    assert DeletionManager(store, recycle).recover() == []  # 无需原始文件重建也可提交剩余阶段。
    assert len(list(recycled.iterdir())) == 1 and not store.query('SELECT * FROM videos')  # 不重复回收且最终一致。

def test_pending_archive_blocks_delete(tmp_path):  # 未完成归档不能被删除破坏安全入口。
    store, source, path, vid, recycled, recycle = setup(tmp_path)  # 初始化隔离样例。
    def fault(stage):  # 模拟归档刚完成持久计划后退出。
        raise RuntimeError('归档中断')  # 保留归档恢复任务。
    with pytest.raises(RuntimeError):  # 首次归档不应完成。
        Archiver(store, tmp_path / 'archive', fault=fault).submit(vid, 8, ['测试'])  # 使用实际归档任务日志。
    with pytest.raises(RuntimeError, match='未完成归档'):  # 删除必须等待归档先恢复。
        DeletionManager(store, recycle).submit(vid)  # 不触碰尚被归档保护的文件。
    assert path.exists() and not list(recycled.iterdir())  # 所有来源数据都保留。


def test_forget_keeps_all_hard_links_and_removes_only_this_record(tmp_path):
    store, source, path, vid, recycled, recycle = setup(tmp_path)
    linked = source / 'linked.mp4'
    os.link(path, linked)
    store.register(linked)
    other = source / 'other.mp4'
    other.write_bytes(b'other')
    other_id = store.register(other)
    store.execute('UPDATE videos SET score=7,star=1,tags=?,played=9,position=12000 WHERE id=?', ('["test"]', vid))
    DeletionManager(store, lambda path: pytest.fail('Metadata removal must not recycle')).forget(vid)
    assert path.read_bytes() == linked.read_bytes() == b'original-video'
    assert not store.query('SELECT * FROM videos WHERE id=?', (vid,))
    assert not store.query('SELECT * FROM paths WHERE id=?', (vid,))
    assert store.video(other_id) and other.exists() and not list(recycled.iterdir())


def test_forget_recovery_retains_mode_and_rolls_back_metadata_on_failure(tmp_path):
    store, source, path, vid, recycled, recycle = setup(tmp_path)
    store.execute('CREATE TRIGGER fail_forget BEFORE DELETE ON videos BEGIN SELECT RAISE(ABORT,"forget failed"); END')
    with pytest.raises(Exception, match='forget failed'):
        DeletionManager(store, recycle).forget(vid)
    assert store.video(vid) and store.query('SELECT * FROM paths WHERE id=?', (vid,))
    assert path.exists() and not list(recycled.iterdir())
    store.execute('DROP TRIGGER fail_forget')
    manager = DeletionManager(store, lambda path: pytest.fail('Recovery must retain metadata-only mode'))
    assert manager.recover() == []
    assert path.exists() and not store.query('SELECT * FROM videos WHERE id=?', (vid,))


def test_forget_missing_or_replaced_file_never_touches_replacement(tmp_path):
    store, source, path, vid, recycled, recycle = setup(tmp_path)
    path.rename(source / 'original.mp4')
    path.write_bytes(b'replacement')
    DeletionManager(store, recycle).forget(vid)
    assert path.read_bytes() == b'replacement' and not list(recycled.iterdir())


def test_pending_deletion_cannot_be_reinterpreted_as_another_mode(tmp_path):
    store, source, path, vid, recycled, recycle = setup(tmp_path)
    def fail(stage):
        raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError):
        DeletionManager(store, recycle, fault=fail).forget(vid)
    with pytest.raises(RuntimeError, match='仅删除记录'):
        DeletionManager(store, recycle).submit(vid)
    assert DeletionManager(store, recycle).recover() == [] and path.exists()
    vid = store.register(path)
    with pytest.raises(RuntimeError):
        DeletionManager(store, recycle, fault=fail).submit(vid)
    with pytest.raises(RuntimeError, match='本地文件删除'):
        DeletionManager(store, recycle).forget(vid)
    assert path.exists()



def test_forget_cancels_retired_entry_cleanup_without_deleting_it(tmp_path):
    from moplayer.core import identity
    from moplayer.infrastructure.archive_cleanup import ArchiveCleanup
    store, source, path, vid, recycled, recycle = setup(tmp_path)
    retired = source / 'retired.mp4'
    os.link(path, retired)
    info = retired.stat()
    store.execute('INSERT INTO cleanup_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                  ('retired', vid, str(retired), identity(retired), info.st_size, info.st_mtime_ns, 'pending', None, 0))
    DeletionManager(store, recycle).forget(vid)
    assert ArchiveCleanup(store).drain() == 0
    assert retired.exists() and path.exists()
    assert store.query('SELECT state FROM cleanup_jobs')[0]['state'] == 'done'
