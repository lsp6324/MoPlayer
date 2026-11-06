import json  # 读取归档后标签状态。
import os  # 检查硬链接实体身份。
import threading  # 构造扫描取消信号。
from pathlib import Path  # 创建隔离测试目录。
import pytest  # 提供参数化测试和异常断言。
from moplayer.core import Store, Archiver, scan, identity, validate_tag, natural  # 测试实际生产核心代码。

@pytest.fixture  # 每个测试拥有独立数据库与归档目录。
def library(tmp_path):  # 不接触用户真实视频。
    store = Store(tmp_path / 'data')  # 创建临时数据库。
    archive = Archiver(store, tmp_path / 'archive')  # 使用隔离归档根目录。
    return store, archive  # 向测试提供实际对象。

def video(path):  # 创建用于文件规则测试的小型二进制文件。
    path.parent.mkdir(parents=True, exist_ok=True)  # 建立测试目录层级。
    path.write_bytes(b'video-test-content' * 1000)  # 这些测试只验证文件系统，不声称解码兼容。
    return path  # 返回创建的路径。

def test_natural_sort():  # 验证中文剧集编号自然顺序。
    assert sorted(['第10集', '第2集', '第1集'], key=natural) == ['第1集', '第2集', '第10集']  # 数字按数值排列。

def test_navigation_and_replaced_browse(tmp_path, library):  # 验证目录边界与浏览替换隔离。
    store, archive = library  # 使用独立测试库。
    root = tmp_path / 'source'  # 创建逻辑播放根目录。
    for name in ['第1组/第10集.mp4', '第1组/第2集.mp4', '第3组/深层/a.mkv', '第4组/direct.mp4', '第4组/deep/b.mp4']:  # 覆盖同目录自然顺序和递归目标。
        video(root / name)  # 创建候选视频。
    (root / '第2组').mkdir()  # 加入需要跳过的空目录。
    context, errors = scan(root, store, threading.Event())  # 使用正式扫描函数。
    folder = str(root / '第1组')  # 第一组所在逻辑目录。
    assert [x[1] for x in context.folders[folder][1]] == ['第2集.mp4', '第10集.mp4']  # 文件自然排序正确。
    assert context.step((folder, 0), -1) is None  # Z 在首个视频不跨目录。
    assert context.step((folder, 0), 1) == (folder, 1)  # X 优先同目录下一个。
    assert context.step((folder, 1), 1) == (str(root / '第3组/深层'), 0)  # 跳过空同级目录并递归。
    assert context.step((str(root / '第3组/深层'), 0), 1) is None  # 不向更高祖先扩展。
    assert context.first(str(root / '第4组')) == (str(root / '第4组'), 0)  # 目标直接视频优先于子目录。
    second = video(tmp_path / 'replacement' / 'new.mp4')  # 准备新的浏览目录。
    browsing, errors = scan(second.parent, store, threading.Event())  # 替换浏览快照。
    assert context.step((folder, 0), 1) == (folder, 1) and browsing.root != context.root  # 原播放顺序不变。

def test_hardlink_identity_and_archive(tmp_path, library):  # 验证多标签共享内容和稳定元数据。
    store, archive = library  # 获取生产对象。
    source = video(tmp_path / 'source' / 'movie.mp4')  # 创建来源文件。
    vid = store.register(source)  # 建立稳定身份。
    store.progress(vid, 12345)  # 保存可验证播放进度。
    store.execute('UPDATE videos SET star=1 WHERE id=?', (vid,))  # 添加收藏。
    archive.submit(vid, 0, ['标签甲', '标签乙'])  # 零分与多标签首次归档。
    a, b = archive.root / '0分/标签甲/movie.mp4', archive.root / '0分/标签乙/movie.mp4'  # 两个入口都包含自然排序后的全部标签。
    assert not source.exists() and a.exists() and b.exists()  # 成功后来源移出。
    assert identity(a) == identity(b) and a.stat().st_nlink == 2  # 内容只有一个实体并且没有遗留锚点。
    assert store.register(b) == vid and len(store.query('SELECT * FROM videos')) == 1  # 扫描第二硬链接不产生重复身份。
    assert store.video(vid)['position'] == 12345 and store.video(vid)['star'] == 1  # 进度收藏随视频身份保留。
    archive.submit(vid, 8, ['标签乙', '标签丙'])  # 同时改变评分和标签。
    assert not a.exists() and not b.exists()  # 旧评分入口被移除。
    assert (archive.root / '8分/标签丙/movie.mp4').exists()  # 新评分与全部标签替换原前缀。
    archive.submit(vid, None, [])  # 清除评分并取消全部标签。
    assert store.resolve(vid) == archive.root / '未评分/未分类/movie.mp4'  # 清空标签和评分后替换命名前缀。
    assert store.video(vid)['score'] is None and json.loads(store.video(vid)['tags']) == []  # 数据库与目录一致。

@pytest.mark.parametrize('stage', ['planned', 'prepared', 'linked', 'committed', 'done'])  # 覆盖关键事务边界中断。
def test_recovery_after_failure(tmp_path, library, stage):  # 验证失败后数据仍可恢复。
    store, archive = library  # 使用隔离库。
    source = video(tmp_path / 'source' / 'movie.mp4')  # 创建来源。
    vid = store.register(source)  # 登记身份。
    def fault(current):  # 模拟任务阶段中进程中断。
        if current == stage:  # 只在指定边界触发。
            raise RuntimeError('simulated crash')  # 让持久任务保持未完成状态。
    archive.fault = fault  # 安装故障注入器。
    if stage == 'planned':  # 计划保存后尚未执行任何文件操作。
        original = archive.run  # 保存正式执行入口。
        archive.run = lambda job: (_ for _ in ()).throw(RuntimeError('simulated crash'))  # 直接中断执行。
    with pytest.raises(RuntimeError):  # 首次调用必须报告失败。
        archive.submit(vid, 8, ['测试'])  # 运行真正的归档逻辑。
    assert source.exists() or (archive.root / '8分/测试/movie.mp4').exists()  # 任何边界至少保留一份原始数据。
    recovering = Archiver(store, archive.root)  # 模拟重新启动后的新对象。
    assert recovering.recover() == []  # 持久计划自动恢复成功。
    assert not source.exists() and store.resolve(vid).exists()  # 最终完成移出且身份仍可定位。
    assert all(row['state'] == 'done' for row in store.query('SELECT state FROM jobs'))  # 任务状态正确完成。

def test_collision_never_overwrites(tmp_path, library):  # 验证同名不同视频绝不覆盖。
    store, archive = library  # 使用隔离归档器。
    old = video(archive.root / '8分/测试/movie.mp4')  # 与新规则生成的完整文件名发生实际冲突。
    old.write_bytes(b'unrelated')  # 使用不同内容以便检查。
    source = video(tmp_path / 'source/movie.mp4')  # 创建同名来源。
    vid = store.register(source)  # 登记新视频身份。
    archive.submit(vid, 8, ['测试'])  # 归档时自动产生不冲突名称。
    assert old.read_bytes() == b'unrelated' and store.resolve(vid) != old  # 原有文件内容完全保留。

@pytest.mark.parametrize('name', ['', '..', '../x', 'a/b', 'a\\b', 'CON', 'NUL.txt', 'COM1', 'LPT9.mp4', 'abc.', '尾空格 ', '未分类', 'a:b', 'a\x00b'])  # 覆盖设备名、穿越和非法字符。
def test_bad_tags(name):  # 非法标签不能进入归档计划。
    with pytest.raises(ValueError):  # 必须明确拒绝。
        validate_tag(name)  # 测试生产校验器。

def test_cancel_and_missing_identity(tmp_path, library):  # 验证扫描取消和同名替换保护。
    store, archive = library  # 使用独立库。
    source = video(tmp_path / 'source/movie.mp4')  # 创建待扫描视频。
    vid = store.register(source)  # 保存原始身份。
    cancelled = threading.Event()  # 创建取消标记。
    cancelled.set()  # 在扫描前取消。
    with pytest.raises(InterruptedError):  # 扫描应及时结束。
        scan(source.parent, store, cancelled)  # 不发布部分结果。
    source.rename(source.with_suffix('.old'))  # 保留原实体但移出已知路径。
    video(source)  # 在相同名字创建另一个文件。
    with pytest.raises(FileNotFoundError):  # 不把新同名文件当作原视频。
        store.resolve(vid)  # 严格检查文件身份。

def test_link_failure_retains_source(tmp_path, library, monkeypatch):  # 验证硬链接失败不会删除来源。
    store, archive = library  # 创建隔离归档器。
    source = video(tmp_path / 'source/movie.mp4')  # 准备来源数据。
    vid = store.register(source)  # 登记视频。
    def denied(*args):  # 模拟无权限或不支持硬链接。
        raise PermissionError('hardlink denied')  # 产生实际文件操作异常类型。
    monkeypatch.setattr(os, 'link', denied)  # 注入硬链接失败。
    with pytest.raises(PermissionError):  # 不得静默降级复制。
        archive.submit(vid, 8, ['测试'])  # 尝试归档。
    assert source.exists() and not store.video(vid)['archived']  # 源文件和未归档元数据保持一致。

@pytest.mark.parametrize('stage', ['copy_verified', 'prepared', 'linked', 'committed'])  # 覆盖跨卷复制分支的关键中断阶段。
def test_cross_volume_branch_recovery(tmp_path, library, monkeypatch, stage):  # 注入卷判断，使用真实复制和 SHA256 校验。
    from moplayer import core  # 替换卷判断而不替换复制实现。
    store, archive = library  # 使用隔离测试数据。
    source = video(tmp_path / 'source/movie.mp4')  # 创建完整来源内容。
    original_hash = core.digest(source)  # 保存用于恢复后比较的内容摘要。
    vid = store.register(source)  # 登记原视频身份。
    monkeypatch.setattr(core, 'same_volume', lambda a, b: False)  # 强制走跨卷分支，报告中明确这是模拟卷边界。
    def fault(state):  # 在持久阶段后模拟异常退出。
        if state == stage:  # 仅触发指定故障点。
            raise RuntimeError('cross-volume crash')  # 保留真实任务日志。
    archive.fault = fault  # 安装故障注入器。
    with pytest.raises(RuntimeError):  # 首次操作应报告中断。
        archive.submit(vid, None, ['测试'])  # 执行复制和校验流程。
    assert source.exists()  # 清理前中断时原视频仍存在。
    assert Archiver(store, archive.root).recover() == []  # 新归档器可从持久记录恢复。
    assert not source.exists() and core.digest(store.resolve(vid)) == original_hash  # 只有完整复制成功后才清理来源。

def test_database_commit_failure_keeps_data(tmp_path, library, monkeypatch):  # 模拟新入口建立后数据库提交失败。
    store, archive = library  # 使用实际数据库和文件系统。
    source = video(tmp_path / 'source/movie.mp4')  # 创建来源视频。
    vid = store.register(source)  # 保存稳定身份。
    original = archive.checkpoint  # 保留正式阶段提交方法。
    def failing(job, plan, state):  # 在文件已建立但分类事务尚未开始时失败。
        original(job, plan, state)  # 持久记录已经建立新入口。
        if state == 'linked':  # 该阶段对应文件成功、数据库未提交。
            raise OSError('simulated database unavailable')  # 保持旧元数据与来源可恢复。
    monkeypatch.setattr(archive, 'checkpoint', failing)  # 注入故障边界。
    with pytest.raises(OSError):  # 界面必须得到失败结果。
        archive.submit(vid, 10, ['测试'])  # 执行真实文件建立流程。
    assert source.exists() and not store.video(vid)['archived']  # 数据库不提前显示归档成功。
    assert Archiver(store, archive.root).recover() == []  # 数据库恢复后可安全重试。

def test_space_failure(tmp_path, library, monkeypatch):  # 验证空间不足不会删除源视频。
    from moplayer import core  # 注入剩余空间与卷分支。
    store, archive = library  # 获取归档器。
    source = video(tmp_path / 'source/movie.mp4')  # 准备源文件。
    vid = store.register(source)  # 登记身份。
    monkeypatch.setattr(core, 'same_volume', lambda a, b: False)  # 触发需要复制的分支。
    monkeypatch.setattr(core.shutil, 'disk_usage', lambda p: type('Space', (), {'free': 0})())  # 模拟归档卷没有可用空间。
    with pytest.raises(OSError, match='空间不足'):  # 明确报告磁盘空间问题。
        archive.submit(vid, 8, ['测试'])  # 尝试复制归档。
    assert source.exists() and store.resolve(vid) == source  # 保留来源与原身份映射。

def test_import_root_can_advance_to_next_sibling(tmp_path, library):  # 导入根中的视频也必须遵守一层同级切换规则。
    store, archive = library  # 使用独立数据库。
    first = video(tmp_path / 'collection/第1组/a.mp4')  # 直接导入第一组目录。
    (tmp_path / 'collection/第2组').mkdir()  # 中间同级目录完全没有视频。
    target = video(tmp_path / 'collection/第3组/deep/b.mp4')  # 下一个有视频的同级子树。
    context, errors = scan(first.parent, store, threading.Event())  # 初始仅递归导入目录。
    assert str(target.parent) not in context.folders  # 不提前扫描其他同级子树。
    result = context.step_loaded((str(first.parent), 0), 1, store, threading.Event())  # 后台按需扩展下一同级目录。
    assert result == (str(target.parent), 0)  # 跳过空目录并递归找到目标。
    assert context.step(result, 1) is None  # 深层目录结束仍不向更高祖先扩展。

def test_large_scan_cancels_midway(tmp_path, library, monkeypatch):  # 验证大型目录已开始扫描后仍能取消。
    store, archive = library  # 使用实际独立数据库。
    root = tmp_path / 'large'  # 创建批量文件测试目录。
    root.mkdir()  # 建立候选文件父目录。
    for number in range(2000):  # 提供足够多的真实目录项。
        (root / f'第{number}集.mp4').write_bytes(b'test')  # 仅测试扫描无需实际视频解码。
    cancel, count = threading.Event(), []  # 跟踪取消触发点和处理数量。
    original = store.register  # 保留生产身份登记方法。
    def register(path):  # 在扫描确实进行后触发取消。
        result = original(path)  # 执行真实数据库登记。
        count.append(path)  # 记录处理过的条目。
        if len(count) == 30:  # 在扫描途中而非开始之前取消。
            cancel.set()  # 模拟用户点击取消按钮。
        return result  # 返回正常视频身份。
    monkeypatch.setattr(store, 'register', register)  # 注入确定性取消时机。
    with pytest.raises(InterruptedError):  # 扫描不应继续遍历整个大目录。
        scan(root, store, cancel)  # 运行正式递归扫描。
    assert len(count) == 30  # 下一次循环即响应取消。

@pytest.mark.skipif(os.name != 'nt', reason='Windows junction test')  # 仅在 Windows 验证实际目录联接。
def test_junction_loop_is_skipped(tmp_path, library):  # 验证真实自引用 junction 不造成无限递归。
    import subprocess  # 使用系统自带命令建立测试联接。
    store, archive = library  # 使用隔离元数据。
    root = tmp_path / 'linked'  # 联接只能位于本测试临时目录。
    video(root / 'sample.mp4')  # 提供普通可扫描文件。
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(root / 'loop'), str(root)], check=True, capture_output=True)  # 建立指向自身的真实 NTFS 目录联接。
    context, errors = scan(root, store, threading.Event())  # 使用重解析点过滤规则扫描。
    assert len(context.folders) == 1 and len(context.folders[str(root)][1]) == 1  # 只扫描原目录且跳过联接。
