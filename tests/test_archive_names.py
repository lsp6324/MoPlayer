import json  # 检查恢复日志中的原名与新名称。
import pytest  # 验证超长名称拒绝与异常恢复。
from core import Store, Archiver, archive_name, identity  # 使用真实数据库、硬链接和归档实现。

def sample(tmp_path):  # 为每个测试创建独立视频及库。
    source = tmp_path / 'source' / 'abc-123.mp4'  # 保留可直接核对的原始名称。
    source.parent.mkdir()  # 不访问用户真实归档目录。
    source.write_bytes(b'archive-name-test')  # 文件操作测试不声称真实解码。
    store = Store(tmp_path / 'data')  # 建立独立 SQLite 数据库。
    vid = store.register(source)  # 获得持久视频身份。
    return store, Archiver(store, tmp_path / 'archive'), source, vid  # 返回正式生产对象。

def test_rename_rating_tags_and_original(tmp_path):  # 修改分类只替换前缀而不层层叠加。
    store, archive, source, vid = sample(tmp_path)  # 初始化隔离来源。
    before = identity(source)  # 保存文件实体身份。
    store.execute('UPDATE videos SET star=1,position=12345,played=1 WHERE id=?', (vid,))  # 加入历史进度与收藏。
    archive.submit(vid, 8, ['白丝', '标签2'])  # 首次使用两个标签归档。
    expected = '8分 标签2 白丝 abc-123.mp4'  # 标签沿用自然排序规则。
    paths = [archive.root / '8分' / tag / expected for tag in ['白丝', '标签2']]  # 两个文件夹使用同一名称。
    assert all(path.exists() and identity(path) == before for path in paths)  # 改名不复制内容或更换视频实体。
    assert store.video(vid)['name'] == expected and store.video(vid)['original_name'] == 'abc-123.mp4'  # 当前名和永久原名分离。
    archive.submit(vid, 9, ['白丝'])  # 删除标签并改变评分。
    assert store.resolve(vid).name == '9分 白丝 abc-123.mp4' and all(not path.exists() for path in paths)  # 旧前缀和所有旧入口都已清理。
    assert store.video(vid)['star'] == 1 and store.video(vid)['position'] == 12345  # 历史收藏继续关联同一身份。
    archive.submit(vid, 0, [])  # 零分和取消全部标签均有独立命名。
    assert store.resolve(vid).name == '0分 未分类 abc-123.mp4'  # 不误写成未评分。
    archive.submit(vid, None, ['白丝'])  # 清除评分后再次添加标签。
    assert store.resolve(vid).name == '未评分 白丝 abc-123.mp4'  # 未评分明确显示且原名不重复。

def test_old_record_and_recovery(tmp_path):  # 老版本记录首次改名以及中断恢复均保留正确原名。
    store, archive, source, vid = sample(tmp_path)  # 创建实际样例。
    store.execute('UPDATE videos SET original_name=NULL WHERE id=?', (vid,))  # 模拟旧版本尚无原名的记录。
    def fault(stage):  # 在新入口全部建立后模拟退出。
        if stage == 'linked':  # 数据库尚未提交新显示名。
            raise RuntimeError('中断')  # 日志保留固化的新命名计划。
    archive.fault = fault  # 使用真实检查点故障注入。
    with pytest.raises(RuntimeError):  # 不能把中断当作改名成功。
        archive.submit(vid, 8, ['白丝'])  # 新名字入口已建立但旧来源仍保留。
    plan = json.loads(store.query('SELECT plan FROM jobs')[0]['plan'])  # 检查持久恢复计划。
    assert plan['original_name'] == 'abc-123.mp4' and plan['name'] == '8分 白丝 abc-123.mp4'  # 重启不需要猜测原名。
    assert Archiver(store, archive.root).recover() == []  # 新管理器完成文件与数据库提交。
    assert store.resolve(vid).name == '8分 白丝 abc-123.mp4' and not source.exists()  # 来源只在新入口安全后移除。
    archive.fault = None  # 后续修改不再注入中断。
    archive.submit(vid, 10, ['白丝'])  # 第二次评分仍以原名构造。
    assert store.resolve(vid).name == '10分 白丝 abc-123.mp4'  # 不出现嵌套的旧评分前缀。

def test_length_and_literal_original(tmp_path):  # 超长标签组合不得破坏来源，也不猜测原名中的前缀。
    store, archive, source, vid = sample(tmp_path)  # 创建独立来源。
    with pytest.raises(ValueError, match='长度'):  # 所有标签无法完整放入文件名时明确拒绝。
        archive.submit(vid, 8, [character * 80 for character in ['甲', '乙', '丙', '丁']])  # 不截短用户原名和标签。
    assert source.exists() and not store.query('SELECT * FROM jobs')  # 校验发生在文件任务创建之前。
    assert archive_name('9分 白丝 original.MKV', 8, ['标签']) == '8分 标签 9分 白丝 original.MKV'  # 原名中本来已有的字样作为原文保留。

def test_database_schema_migration(tmp_path):  # 旧数据库自动增加原名列且不覆盖视频元数据。
    store, archive, source, vid = sample(tmp_path)  # 创建接近旧版本的数据结构。
    store.execute('UPDATE videos SET star=1,position=4567 WHERE id=?', (vid,))  # 记录需要完整保留的用户状态。
    store.execute('ALTER TABLE videos DROP COLUMN original_name')  # 模拟旧版本尚无永久原名列。
    store.db.close()  # 模拟正常退出再升级启动。
    reopened = Store(tmp_path / 'data')  # 新版本创建缺失的列。
    assert reopened.video(vid)['star'] == 1 and reopened.video(vid)['position'] == 4567  # 升级不重置原记录。
    Archiver(reopened, tmp_path / 'archive').submit(vid, 8, ['白丝'])  # 老记录首次新规则归档。
    assert reopened.video(vid)['original_name'] == 'abc-123.mp4' and reopened.resolve(vid).name == '8分 白丝 abc-123.mp4'  # 原名从旧记录安全初始化。
