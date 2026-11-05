import ctypes  # 调用 Windows 卷信息接口。
import hashlib  # 校验跨卷复制内容。
import json  # 保存可恢复的归档计划。
import os  # 读取文件身份并建立硬链接。
import re  # 自然排序和标签校验。
import shutil  # 检查磁盘空间。
import sqlite3  # 持久保存视频元数据与任务。
import threading  # 串行化数据库写入。
import time  # 记录历史时间。
import uuid  # 生成不依赖路径的视频标识。
from application.archive_folders import ArchiveFolders
from infrastructure.schema import migrate
from pathlib import Path  # 统一处理 Windows 路径。

ARCHIVE_ROOT = Path('E:/我觉得是学习资料')  # 固定用户指定的归档根目录。
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.m4v', '.mpeg', '.mpg', '.ts'}  # 交给播放内核的视频容器。
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tif', '.tiff'}  # 播放区按静态图片展示的格式。
EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS  # 仅用于候选文件筛选。

def media_kind(name):  # 只决定播放区如何展示，不参与文件身份、归档或命名规则。
    return 'image' if Path(name).suffix.lower() in IMAGE_EXTENSIONS else 'video'  # 视频与未知后缀继续走播放内核。

def natural(value):  # 将数字片段按数值比较。
    return [(1, int(x)) if x.isdigit() else (0, x.casefold()) for x in re.split(r'(\d+)', str(value))]  # 保持中文名称和数字自然顺序。

def identity(path):  # 返回同卷硬链接共享的文件身份。
    stat = os.stat(path)  # 跟踪实际文件并取得 Windows 文件索引。
    return f'{stat.st_dev}:{stat.st_ino}:{getattr(stat, "st_birthtime_ns", 0)}'  # 加入创建时间降低文件索引复用风险。

def digest(path):  # 流式计算校验值，避免整段视频进入内存。
    h = hashlib.sha256()  # 使用 SHA256 校验复制完整性。
    with open(path, 'rb') as stream:  # 只读打开源文件。
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):  # 分块处理大型视频。
            h.update(chunk)  # 累积内容摘要。
    return h.hexdigest()  # 返回可记录的完整摘要。

def same_volume(source, destination):  # 独立判断实际文件系统卷，方便故障测试覆盖跨卷分支。
    return source.stat().st_dev == destination.stat().st_dev  # 不仅比较可能映射到挂载点的盘符。

def validate_tag(value):  # 严格检查 Windows 文件夹名称。
    if not value or value != value.strip() or len(value) > 80 or value[-1:] in {'.', ' '}:  # 拒绝空名称和不稳定尾字符。
        raise ValueError('标签需为 1～80 个字符，不能有首尾空格或以点结尾。')  # 给出明确输入反馈。
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value in {'.', '..', '未分类'}:  # 阻止路径穿越和保留业务目录。
        raise ValueError('标签含非法字符或保留名称。')  # 不自动改写用户标签。
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', value, re.I):  # 拒绝 Windows 设备名称。
        raise ValueError('标签不能使用 Windows 设备保留名称。')  # 避免创建异常设备路径。
    return value  # 返回已通过校验的名称。

def validate_layout(rows):  # 校验全局标签树，禁止路径穿越与循环。
    result, keys = {}, set()  # 同一标签名称在整个库中保持唯一身份。
    for row in rows:  # 校验完整草稿后才允许操作磁盘。
        name = validate_tag(row['name'])  # 标签名称沿用 Windows 安全规则。
        if name.casefold() in keys or row['kind'] not in ('major', 'minor'):  # 不允许重名或未知类型。
            raise ValueError('标签重复或类型无效：' + name)  # 保留原分类不提交。
        keys.add(name.casefold())  # 按 Windows 不区分大小写去重。
        result[name] = {'name': name, 'kind': row['kind'], 'parent': row.get('parent') or None, 'is_parent': bool(row.get('is_parent', False))}  # 单独记住用户设定的父标签，包括暂时没有子类的情况。
    for name, row in result.items():  # 所有名称就绪后检查父子关系。
        if row['kind'] == 'major' and row['parent']:  # 根节点与子节点的存储类型必须一致。
            raise ValueError('有上级的标签必须是子标签：' + name)  # 父标签身份由独立标记保存。
        if row['kind'] == 'minor' and row['parent'] not in result:  # 子标签必须归属一个实际存在的标签。
            raise ValueError('请为子标签指定有效父标签：' + name)  # 不保存悬空引用。
        if row['parent']:  # 旧版已经有子类的大类仍然是父标签。
            result[row['parent']]['is_parent'] = True  # 保留既有父子关系。
    for name in result:  # 全部关系就绪后逐条检查祖先链。
        tag_chain(name, result)  # 父标签可嵌套，但不能形成循环。
    return result  # 返回可持久化的完整结构。

def tag_chain(name, layout):  # 返回从根标签到当前标签的完整层级。
    chain, seen = [], set()  # 同时记录路径与已访问标签。
    while name:  # 沿父级向上遍历，不使用无限递归。
        if name in seen:  # 自身或间接互为父子都会形成循环。
            raise ValueError('标签不能放入自身或其子孙标签。')  # 在文件操作之前阻止循环。
        seen.add(name)  # 当前标签只允许访问一次。
        chain.append(name)  # 保留完整中文名称。
        name = layout.get(name, {}).get('parent')  # 旧版未知标签作为独立根节点。
    return tuple(reversed(chain))  # 文件目录按根到叶顺序排列。

def canonical_tags(tags, layout):  # 小类隐含所属大类，避免同一视频增加冗余父级入口。
    selected = set(tags)  # 合并重复勾选。
    parents = {parent for name in selected for parent in tag_chain(name, layout)[:-1]}  # 任意深度的祖先都由叶子隐含选择。
    return sorted(selected - parents, key=natural)  # 保留叶子选择与独立大类，自然排序不受拖动时序影响。

def tag_parts(tags, layout):  # 同时生成真实目录片段和文件名前缀。
    selected = canonical_tags(tags, layout)  # 父子同时勾选时仅使用小类入口。
    groups, independent, folders = {}, [], []  # 合并同根子树，同时保存全部叶子路径。
    for name in selected:  # 遍历该视频真正选择的分类。
        chain = tag_chain(name, layout)  # 嵌套父标签也保留全部祖先路径。
        folders.append(chain)  # 每个已选叶子只建立一个硬链接入口。
        if len(chain) > 1:  # 同一根标签的多个分支合并为一个文件名前缀。
            branch = groups.setdefault(chain[0], {})  # 收集根下的选中分支。
            for part in chain[1:]:  # 任意深度都沿相同树结构合并。
                branch = branch.setdefault(part, {})  # 不重复显示公共祖先名称。
        else:  # 没有选中小类的大类仍使用单层目录。
            independent.append(name)  # 不为其他视频强制增加无关标签。
    def render(name, children):  # 把选中子树表示为父标签（子标签）。
        return name + ('（' + '、'.join(render(child, children[child]) for child in sorted(children, key=natural)) + '）' if children else '')  # 多层使用嵌套括号且保持自然排序。
    tokens = []  # 层级分组仍放在独立标签之前。
    for parent in sorted(groups, key=natural):  # 带小类的大类放在文件名最前面。
        tokens.append(render(parent, groups[parent]))  # 旧两级命名不变，新增层级继续嵌套。
    tokens.extend(sorted(independent, key=natural))  # 独立标签保留自然排序。
    return folders or [('未分类',)], tokens or ['未分类']  # 清空标签仍保留一个可恢复的真实视频入口。

def archive_name(original):
    # Metadata determines directories and UI only. Never strip apparent prefixes.
    if (not isinstance(original, str) or not original or original in {'.', '..'}
            or original[-1:] in {'.', ' '} or re.search(r'[<>:"/\\|?*\x00-\x1f]', original)
            or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', original, re.I)):
        raise ValueError('记录的原文件名无效，未更改文件。')
    result = original
    if len(result.encode('utf-16-le')) // 2 > 255:
        raise ValueError('原文件名超过 Windows 文件名长度限制。')
    return result

class Store:  # 管理持久视频身份和元数据。
    def __init__(self, directory):  # 在便携程序旁创建数据目录。
        self.directory = Path(directory)  # 保留数据目录路径。
        self.directory.mkdir(parents=True, exist_ok=True)  # 确保数据库目录存在。
        self.lock = threading.RLock()  # 允许同一操作内部再次取得数据库锁。
        self.file_lock = threading.RLock()  # 文件发现与迁移/删除串行，防止扫描把刚移走的旧路径重新登记。
        self.db = sqlite3.connect(self.directory / 'library.sqlite3', check_same_thread=False)  # 允许受锁保护的工作线程访问。
        self.db.row_factory = sqlite3.Row  # 使用可读的列名访问结果。
        self.db.execute('PRAGMA journal_mode=WAL')  # 保持读写并发和事务恢复能力。
        self.db.execute('PRAGMA synchronous=FULL')  # 每次提交保证日志落盘。
        self.db.executescript('CREATE TABLE IF NOT EXISTS videos(id TEXT PRIMARY KEY,name TEXT,score INTEGER,star INTEGER DEFAULT 0,position INTEGER DEFAULT 0,played REAL DEFAULT 0,archived INTEGER DEFAULT 0,tags TEXT DEFAULT "[]"); CREATE TABLE IF NOT EXISTS paths(path TEXT PRIMARY KEY COLLATE NOCASE,id TEXT,identity TEXT); CREATE INDEX IF NOT EXISTS path_identity ON paths(identity); CREATE TABLE IF NOT EXISTS folders(path TEXT PRIMARY KEY,time REAL); CREATE TABLE IF NOT EXISTS tags(name TEXT PRIMARY KEY COLLATE NOCASE); CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,video TEXT,state TEXT,plan TEXT,error TEXT,updated REAL);')  # 建立视频、路径、历史和恢复任务表。
        self.db.commit()  # 完成首次初始化。
        self.execute('CREATE TABLE IF NOT EXISTS deletion_jobs(id TEXT PRIMARY KEY,video TEXT,state TEXT,plan TEXT,error TEXT,updated REAL)')  # 删除任务独立记账，不让归档恢复误处理。
        self.execute('CREATE TABLE IF NOT EXISTS tag_layout(name TEXT PRIMARY KEY COLLATE NOCASE,kind TEXT,parent TEXT)')  # 全局保存大类、小类与父级关系。
        self.execute('CREATE TABLE IF NOT EXISTS tag_parents(name TEXT PRIMARY KEY COLLATE NOCASE)')  # 记住右键指定的空父标签。
        self.execute('CREATE TABLE IF NOT EXISTS hierarchy_jobs(id TEXT PRIMARY KEY,state TEXT,plan TEXT,error TEXT,updated REAL)')  # 跨多个视频迁移分类时保留可恢复批次。
        self.execute('CREATE TABLE IF NOT EXISTS archive_setting_jobs(id TEXT PRIMARY KEY,state TEXT,plan TEXT,error TEXT,updated REAL)')
        if 'original_name' not in {row['name'] for row in self.query('PRAGMA table_info(videos)')}:  # 兼容已有便携数据库并保留历史身份。
            self.execute('ALTER TABLE videos ADD COLUMN original_name TEXT')  # 独立保存原文件名，旧记录首次归档时补全。
        migrate(self.db)

    def query(self, sql, args=()):  # 提供线程安全查询。
        with self.lock:  # 避免连接交叉使用。
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]  # 在锁内读取完整结果。

    def execute(self, sql, args=()):  # 执行独立元数据事务。
        with self.lock, self.db:  # 出错自动回滚本次变更。
            self.db.execute(sql, args)  # 使用参数绑定防止 SQL 注入。

    def register(self, path):  # 将同一个文件的多个入口映射到稳定视频 ID。
        with self.file_lock:  # 扫描不得在文件操作和数据库提交之间创建过期身份。
            return self._register(path)  # 完成身份校验和登记后才释放共享文件锁。

    def _register(self, path):  # 仅在共享文件锁保护下执行真实登记。
        path = str(Path(path).absolute())  # 统一数据库记录为绝对路径。
        key = identity(path)  # 查询真实文件身份。
        with self.lock, self.db:  # 原子登记避免扫描线程重复创建身份。
            retired = self.db.execute('SELECT c.video FROM cleanup_jobs c JOIN videos v ON v.id=c.video WHERE c.path=? AND c.identity=? AND c.state<>"done" LIMIT 1',(path,key)).fetchone()
            active = self.db.execute('SELECT id FROM paths WHERE path=? AND identity=?',(path,key)).fetchone()
            if retired and not active:
                return retired['video']  # 已提交分类的旧入口不是新的可播放位置，扫描不将其重新登记。
            row = self.db.execute('SELECT id FROM paths WHERE identity=? LIMIT 1', (key,)).fetchone()  # 优先按硬链接身份查找。
            if not row:  # 跨卷归档入口可能先于元数据提交被扫描到。
                for pending in self.db.execute('SELECT video,plan FROM jobs WHERE state<>"done"').fetchall():  # 查找正在提交的归档身份。
                    if json.loads(pending['plan']).get('anchor_identity') == key:  # 使用已验证的暂存身份关联原视频。
                        row = {'id': pending['video']}  # 避免扫描归档目标时产生重复视频身份。
                        break  # 一个文件实体只能对应一个进行中的归档任务。
            vid = row['id'] if row else uuid.uuid4().hex  # 仅真正的新文件获得新 ID。
            if not row:  # 新视频初始化为未评分且未播放。
                self.db.execute('INSERT INTO videos(id,name,original_name) VALUES(?,?,?)', (vid, Path(path).name, Path(path).name))  # 原名与当前显示名分别保存。
            self.db.execute('INSERT OR REPLACE INTO paths VALUES(?,?,?)', (path, vid, key))  # 路径被外部替换时重新绑定真实身份。
            return vid  # 返回跨历史和收藏共享的 ID。

    def video(self, vid):  # 查询一个视频的状态。
        return self.query('SELECT * FROM videos WHERE id=?', (vid,))[0]  # 由内部已登记 ID 访问。

    def tag_layout(self):  # 兼容旧库中尚未指定类型的平级标签。
        result = {row['name']: {'name': row['name'], 'kind': 'major', 'parent': None} for row in self.query('SELECT name FROM tags')}  # 旧标签默认作为独立大类。
        result.update({row['name']: row for row in self.query('SELECT * FROM tag_layout')})  # 已确认的全局结构优先。
        parents = {row['name'] for row in self.query('SELECT name FROM tag_parents')} | {row['parent'] for row in result.values() if row.get('parent')}  # 合并显式父标签和旧版已存在的父级。
        for name, row in result.items():  # 普通根标签无需显示成父类。
            row['is_parent'] = name in parents  # 界面直接识别父标签身份。
        return result  # 返回独立字典供界面创建草稿。

    def resolve(self, vid):  # 只返回已知且身份仍匹配的路径。
        for row in self.query('SELECT * FROM paths WHERE id=? ORDER BY path', (vid,)):  # 检查全部已登记入口。
            try:  # 无权限或消失的入口不能阻止其他有效入口。
                if identity(row['path']) == row['identity']:  # 不把同名替换文件当成原视频。
                    return Path(row['path'])  # 返回可用的真实位置。
            except OSError:  # 忽略单个失效入口。
                continue  # 尝试同身份的其他已知位置。
        raise FileNotFoundError('视频已删除、被替换或当前位置无法访问；不会自动关联同名文件。')  # 明确说明无法定位。

    def progress(self, vid, position):  # 保存视频进度与最近播放时间。
        self.execute('UPDATE videos SET position=?,played=? WHERE id=?', (max(0, position), time.time(), vid))  # 毫秒进度不允许负数。

class ScanRequired(Exception):  # 标识尚未异步读取的相邻目录。
    pass  # 由播放协调层在工作线程补充目标子树。

class Snapshot:  # 独立保存播放顺序，不随浏览目录和归档改变。
    def __init__(self, root, folders, outer_siblings=None):  # 接收目录数据和导入根的一层同级边界。
        self.root = str(root)  # 保存本次扫描边界。
        self.folders = folders  # 每个目录存放子目录和视频条目。
        self.outer_siblings = outer_siblings or []  # 导入根内视频也能按规则进入下一同级目录。
        self.excluded = set()  # 删除只排除视频身份，不改变原播放快照的索引。
        self.visible_cache = {}  # 缓存每个目录的可见原索引，避免绘制大目录时反复遍历。

    def visible_files(self, folder):  # 让目录显示与导航共同跳过已删除身份。
        version = frozenset(self.excluded)  # 删除身份变更时才失效该目录缓存。
        cached = self.visible_cache.get(folder)  # 获取上次计算的目录可见列表。
        if cached is None or cached[0] != version:  # 首次绘制或删除后重新计算一次。
            cached = (version, [(index, entry) for index, entry in enumerate(self.folders[folder][1]) if entry[0] not in self.excluded])  # 保留播放上下文的原始索引。
            self.visible_cache[folder] = cached  # 同一目录后续行查询直接复用。
        return cached[1]  # 不在每次行数及索引查询时重新扫描全部视频。

    def first(self, folder):  # 先直接视频，再自然顺序递归子目录。
        if folder not in self.folders:  # 相邻导入根不在左侧已扫描目录树内。
            raise ScanRequired(folder)  # 不在界面线程同步读取未知子树。
        children, files = self.folders[folder]  # 获取当前逻辑目录。
        available = self.visible_files(folder)  # 已删除条目不再成为递归目标。
        if available:  # 优先使用直接视频。
            return folder, available[0][0]  # 返回原始快照中的逻辑位置。
        for child in children:  # 子目录已经自然排序。
            result = self.first(child)  # 递归寻找首个视频。
            if result:  # 跳过完全为空的目录。
                return result  # 保留实际视频所在目录。
        return None  # 当前子树没有候选视频。

    def step(self, location, direction):  # 实现严格的 X 和 Z 边界。
        folder, index = location  # 解包当前视频逻辑位置。
        files = self.folders[folder][1]  # 获取开始播放时保存的文件列表。
        if direction < 0:  # Z 仅允许同目录后退。
            return next(((folder, number) for number in range(index - 1, -1, -1) if files[number][0] not in self.excluded), None)  # 跳过删除项，但仍不跨目录。
        following = next((number for number in range(index + 1, len(files)) if files[number][0] not in self.excluded), None)  # 优先寻找同目录剩余视频。
        if following is not None:  # 存在有效的后续视频。
            return folder, following  # 保留原播放上下文和自然排序。
        parent = str(Path(folder).parent)  # 只检查一层父目录。
        siblings = self.folders[parent][0] if parent in self.folders else self.outer_siblings if parent == str(Path(self.root).parent) else []  # 最多额外考虑导入根的一层同级，不再攀升祖先。
        if folder not in siblings:  # 无可用父目录信息时停止。
            return None  # 不推断未知目录顺序。
        for sibling in siblings[siblings.index(folder) + 1:]:  # 仅搜索后续同级目录。
            found = self.first(sibling)  # 按约定顺序递归寻找目标视频。
            if found:  # 跳过无视频的整个子树。
                return found  # 返回第一个有效目标。
        return None  # 不回绕，也不继续向祖先攀升。

    def step_loaded(self, location, direction, store, cancel):  # 在工作线程补齐跨导入根的同级目标。
        while True:  # 空的同级目录可能需要连续跳过。
            try:  # 已加载目标直接复用原快照。
                return self.step(location, direction)  # 所有切换仍执行同一规则。
            except ScanRequired as needed:  # 只扫描实际即将访问的目标目录。
                snapshot, errors = scan(needed.args[0], store, cancel)  # 使用可取消的正式异步扫描流程。
                self.folders.update(snapshot.folders)  # 将目标子树固定到原播放上下文。

def scan(root, store, cancel):  # 在线程中递归扫描并支持取消。
    folders, errors, seen = {}, [], set()  # 收集目录快照、错误和已访问身份。
    def visit(path):  # 扫描一个普通目录。
        if cancel.is_set():  # 每层进入前检查取消。
            raise InterruptedError('扫描已取消')  # 让调用方丢弃未完成结果。
        key = identity(path)  # 检查目录实际身份。
        if key in seen:  # 防止重复路径造成循环。
            return  # 已访问目录不再递归。
        seen.add(key)  # 登记目录身份。
        children, files = [], []  # 分别保留子目录与视频。
        folders[str(path)] = (children, files)  # 空目录也保留层级。
        try:  # 单目录无权限不终止其他目录扫描。
            with os.scandir(path) as iterator:  # 及时关闭目录句柄。
                entries = sorted(iterator, key=lambda e: natural(e.name))  # 文件和文件夹各自维持自然顺序。
            for entry in entries:  # 逐项检查候选文件。
                if cancel.is_set():  # 大目录内部也及时响应取消。
                    raise InterruptedError('扫描已取消')  # 不发布部分树。
                try:  # 捕获单文件访问失败。
                    info = entry.stat(follow_symlinks=False)  # 不跟随目录链接。
                    if getattr(info, 'st_file_attributes', 0) & 0x400 or entry.is_symlink():  # 跳过所有重解析点包括 junction。
                        continue  # 不沿链接遍历到其他位置。
                    if entry.is_dir(follow_symlinks=False):  # 递归普通子目录。
                        visit(Path(entry.path))  # 扫描子树。
                        if entry.path in folders:  # 只加入已建立的目录节点。
                            children.append(entry.path)  # 保留原始目录层级。
                    elif Path(entry.name).suffix.lower() in EXTENSIONS:  # 扩展名只决定是否列为候选。
                        files.append((store.register(entry.path), entry.name))  # 使用稳定 ID 连接实际路径。
                except InterruptedError:  # 取消信号也是 OSError 子类，必须优先向外传播。
                    raise  # 防止把取消误判为普通文件访问失败并发布部分结果。
                except OSError as error:  # 记录无权限或扫描期间被删除的文件。
                    errors.append(f'{entry.path}: {error}')  # 向用户报告未成功扫描的条目。
        except InterruptedError:  # 保持扫描途中取消的控制流。
            raise  # 让界面继续保留旧浏览树。
        except OSError as error:  # 处理整个目录不可访问。
            errors.append(f'{path}: {error}')  # 继续保留空节点和错误信息。
    visit(Path(root).absolute())  # 从明确的导入根目录开始。
    siblings = []  # 捕获根目录同一父级下的目录自然顺序。
    try:  # 父目录无权限时保留已成功扫描的根目录。
        with os.scandir(Path(root).absolute().parent) as entries:  # 只枚举一层，不递归祖先或无关子树。
            for entry in entries:  # 检查可能的同级切换目标。
                try:  # 单个目录访问失败不影响导入。
                    if entry.is_dir(follow_symlinks=False) and not getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:  # 跳过同级重解析目录。
                        siblings.append(entry.path)  # 保存普通同级目录路径。
                except OSError:  # 忽略无法读取的单个同级项。
                    continue  # 继续检查其他同级目录。
    except OSError as error:  # 父目录枚举失败只影响跨根切换。
        errors.append(f'同级目录读取失败：{error}')  # 将限制记录到扫描结果。
    return Snapshot(Path(root).absolute(), folders, sorted(siblings, key=lambda p: natural(Path(p).name))), errors  # 返回独立快照和一层同级边界。

def require_ntfs(root):  # 在归档前检查目标卷及硬链接能力。
    root.mkdir(parents=True, exist_ok=True)  # 先确认目标根目录可写。
    if os.name == 'nt':  # Windows 上明确校验文件系统类型。
        volume = ctypes.create_unicode_buffer(32768)  # 接收挂载卷路径。
        fs = ctypes.create_unicode_buffer(256)  # 接收文件系统名称。
        if not ctypes.windll.kernel32.GetVolumePathNameW(str(root), volume, len(volume)):  # 支持挂载目录而非仅按盘符判断。
            raise OSError('无法读取归档卷信息')  # 无法验证时拒绝归档。
        if not ctypes.windll.kernel32.GetVolumeInformationW(volume.value, None, 0, None, None, None, fs, len(fs)) or fs.value != 'NTFS':  # 仅接受已验证的 NTFS 卷。
            raise OSError(f'归档要求 NTFS；实际文件系统：{fs.value or "未知"}，未改为多份复制。')  # 不静默降级。
    probe = root / ('.probe-' + uuid.uuid4().hex)  # 创建独立能力探针。
    linked = probe.with_suffix('.link')  # 使用不同名字测试硬链接。
    try:  # 无论成功失败都清理探针。
        probe.write_bytes(b'probe')  # 创建极小的测试文件。
        os.link(probe, linked)  # 实际验证硬链接权限。
        if identity(probe) != identity(linked):  # 检查确实共用文件实体。
            raise OSError('硬链接身份验证失败')  # 拒绝不可靠文件系统。
    finally:  # 仅删除本次随机探针。
        linked.unlink(missing_ok=True)  # 移除测试入口。
        probe.unlink(missing_ok=True)  # 移除测试内容。

class Archiver:  # 使用可重放任务协调数据库和文件系统。
    def __init__(self, store, root=ARCHIVE_ROOT, fault=None, *, folders=ArchiveFolders()):  # 测试可注入独立归档根目录和故障点。
        self.store, self.root, self.fault = store, Path(root) if root is not None else None, fault  # 未配置时不默认创建开发机器上的目录。
        self.folders = folders
        self.lock = threading.RLock()  # 归档任务串行运行。

    def checkpoint(self, job, plan, state):  # 持久记录每个可恢复阶段。
        self.store.execute('UPDATE jobs SET state=?,plan=?,error=NULL,updated=? WHERE id=?', (state, json.dumps(plan, ensure_ascii=False), time.time(), job))  # 提交后才进入下一阶段。
        if self.fault:  # 测试覆盖断电式中断位置。
            self.fault(state)  # 故障注入不参与正式运行。

    def submit(self, vid, score, tags, layout=None, hierarchy_job=None, *, folders=None, favorite=None, settings_job=None, preserve_directories=False, defer_cleanup=False):  # 创建单视频归档或全局结构迁移的子任务。
        with self.lock, self.store.file_lock:  # 文件操作与目录扫描的身份登记共用串行边界。
            if any(row['id'] != settings_job for row in self.store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done"')):
                raise RuntimeError('有未完成的归档设置整理，请先在文件任务中恢复。')
            if self.root is None:  # 新安装必须先明确选择存储路径。
                raise RuntimeError('请先在右上角“设置 → 归档设置”选择视频存储文件夹。')  # 禁止静默归档到旧固定位置。
            if any(row['id'] != hierarchy_job for row in self.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"')):  # 全局迁移未完成时禁止独立归档覆盖目标。
                raise RuntimeError('有未完成的标签结构迁移，请先在文件任务中恢复。')  # 不让新操作破坏恢复计划。
            if self.store.query('SELECT id FROM deletion_jobs WHERE video=? AND state<>"done"', (vid,)):  # 不在待重试删除期间重新创建归档入口。
                raise RuntimeError('此视频有未完成的删除任务，请先通过任务列表重试。')  # 避免归档与删除互相覆盖。
            if score is not None and (type(score) is not int or not 0 <= score <= 10):  # 允许未评分并拒绝非整数。
                raise ValueError('评分必须为 0～10 的整数或未评分')  # 不把未评分转换为零。
            tags = sorted({validate_tag(x) for x in tags}, key=natural)  # 验证并去除完全重复标签。
            if len({x.casefold() for x in tags}) != len(tags):  # Windows 路径不区分大小写。
                raise ValueError('标签不能仅大小写不同')  # 防止同目录重复目标。
            layout = self.store.tag_layout() if layout is None else layout  # 评分修改也必须沿用已确认的全局层级。
            layout = validate_layout(layout.values())  # 即使单独评分也不使用损坏或越级的父级路径。
            tags = canonical_tags(tags, layout)  # 小类隐含父级，不生成重复的大类入口。
            if self.store.query('SELECT id FROM jobs WHERE state<>"done"'):  # 失败任务需先恢复以避免相互覆盖。
                raise RuntimeError('有未完成归档，请先通过“归档任务”重试。')  # 显示真实状态。
            source = self.store.resolve(vid)  # 只使用已验证视频位置。
            record = self.store.video(vid)  # 保存原始状态和名称。
            original_name = record['original_name'] or record['name']  # 老版本数据使用原显示名初始化，之后始终复用该原名。
            name = archive_name(original_name)  # 文件操作之前校验记录的原名。
            job = uuid.uuid4().hex  # 为归档分配稳定任务标识。
            stage = self.root / '.moplayer-staging' / job  # 独立暂存目录保证中断可定位。
            old = []  # 保存允许清理的已知入口。
            for row in self.store.query('SELECT * FROM paths WHERE id=?', (vid,)):  # 枚举当前已知入口。
                try:  # 跳过已失效路径。
                    if identity(row['path']) == row['identity']:  # 只有身份一致才允许未来清理。
                        old.append(row)  # 记录原始身份以防外部替换。
                except OSError:  # 不把失效记录当成有效来源。
                    pass  # 后续 resolve 已确保至少存在一个可用来源。
            targets = []  # 保存提前确定的目标名字。
            tag_paths, _ = tag_parts(tags, layout)
            folder_policy = self.folders if folders is None else folders
            star = record['star'] if favorite is None else int(bool(favorite))
            directories = ([Path(row['path']).parent for row in old] if preserve_directories else
                           [self.root.joinpath(*segments) for segments in folder_policy.directories(score, star, tag_paths)])
            for folder in dict.fromkeys(directories):
                for component in (folder, *folder.parents):
                    if component.exists() and getattr(component.lstat(), 'st_file_attributes', 0) & 0x400:
                        raise OSError(f'归档目录含重解析点，拒绝写入：{component}')
                target = folder / name  # 每个分类入口都保留同一原文件名。
                counter = 0  # 冲突时追加稳定标识和序号。
                while target.exists() and identity(target) != identity(source):  # 不覆盖同名不同视频。
                    counter += 1  # 防止重复后缀仍然碰撞。
                    target = folder / f'{Path(name).stem} [{vid[:8]}-{counter}]{Path(name).suffix}'  # 同名不同身份追加稳定标识，保留扩展名且不覆盖其他文件。
                    if len(target.name.encode('utf-16-le')) // 2 > 255:  # 冲突后缀也不能超出 Windows 文件名上限。
                        raise ValueError('增加同名冲突后缀后文件名过长，请缩短标签后重试。')  # 来源文件和原有入口继续保留。
                targets.append(str(target))  # 固化任务目标路径。
            if defer_cleanup and record['archived'] and {os.path.normcase(p) for p in targets}=={os.path.normcase(row['path']) for row in old}:
                with self.store.lock,self.store.db:
                    self.store.db.execute('UPDATE videos SET score=?,tags=? WHERE id=?',(score,json.dumps(tags,ensure_ascii=False),vid))
                    if favorite is not None:
                        self.store.db.execute('UPDATE videos SET star=? WHERE id=?',(star,vid))
                    for tag in tags:
                        self.store.db.execute('INSERT OR IGNORE INTO tags VALUES(?)',(tag,))
                return vid  # 目录未变化时只提交元数据，不创建文件任务日志或暂存入口。
            require_ntfs(self.root)  # 真正需要文件操作时才检查卷与硬链接能力。
            stage.mkdir(parents=True, exist_ok=True)
            plan = dict(video=vid, source=str(source), source_identity=identity(source), size=source.stat().st_size, mtime=source.stat().st_mtime_ns, anchor=str(stage / original_name), targets=targets, old=old, score=score, tags=tags, name=name, original_name=original_name)  # 恢复日志同时固化新文件名与永久原名。
            if favorite is not None:
                plan['favorite'] = star
            if defer_cleanup:
                plan['defer_cleanup'] = True
            self.store.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (job, vid, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))  # 先持久化计划再修改视频文件。
            return self.run(job)  # 执行幂等归档流程。

    def run(self, job):  # 重放任意未完成任务。
        with self.lock, self.store.file_lock:  # 恢复期间也不允许扫描重新登记将被清理的旧路径。
            row = self.store.query('SELECT * FROM jobs WHERE id=?', (job,))[0]  # 载入最后一次持久状态。
            plan = json.loads(row['plan'])  # 读取原始任务而非当前界面选择。
            source, anchor = Path(plan['source']), Path(plan['anchor'])  # 解析源和暂存入口。
            try:  # 任意失败均保留任务和已存在的有效文件。
                if row['state'] == 'done':  # 已完成任务无需再次执行。
                    return plan['video']  # 保持重试幂等。
                if not plan.get('anchor_identity'):  # 只有未完成内容准备时才读取来源。
                    if identity(source) != plan['source_identity'] or source.stat().st_size != plan['size'] or source.stat().st_mtime_ns != plan['mtime']:  # 防止任务中断后来源被替换或改写。
                        raise OSError('来源身份或内容状态已改变，保留文件并等待人工检查。')  # 不删除不确定内容。
                    if same_volume(source, anchor.parent):  # 同卷只创建硬链接不复制视频内容。
                        if not anchor.exists():  # 重试复用之前已建立的入口。
                            os.link(source, anchor)  # 暂存入口确保最后一份数据始终存在。
                        if identity(anchor) != identity(source):  # 拒绝被外部替换的暂存入口。
                            raise OSError('暂存文件身份冲突')  # 不覆盖未知文件。
                    else:  # 跨卷执行完整复制和校验。
                        if anchor.exists() and plan.get('sha256') and digest(anchor) == plan['sha256']:  # 恢复复制验证后、身份提交前的中断。
                            plan['anchor_identity'] = identity(anchor)  # 用完整内容摘要确认暂存数据身份。
                            self.checkpoint(job, plan, 'prepared')  # 持久记录已恢复的安全锚点。
                            return self.run(job)  # 从已准备阶段继续幂等执行。
                        if anchor.exists():  # 未经完整校验的现有文件不覆盖。
                            raise OSError('存在未确认暂存文件，请检查任务目录。')  # 保留来源和暂存文件供诊断。
                        partial = anchor.with_name(anchor.name + '.partial')  # 半成品不伪装为已完成视频。
                        if partial.exists():  # 仅重建本任务自己的不完整文件。
                            partial.unlink()  # 原视频在该阶段从未删除。
                        if shutil.disk_usage(anchor.parent).free < plan['size'] + 16 * 1024 * 1024:  # 提前检查空间余量。
                            raise OSError('归档卷剩余空间不足')  # 源文件保持原样。
                        with open(source, 'rb') as src, open(partial, 'xb') as dst:  # 独占创建任务半成品。
                            shutil.copyfileobj(src, dst, 4 * 1024 * 1024)  # 大文件流式复制。
                            dst.flush()  # 刷新 Python 缓冲。
                            os.fsync(dst.fileno())  # 要求系统刷新复制内容。
                        plan['sha256'] = digest(source)  # 校验原始数据。
                        if digest(partial) != plan['sha256'] or source.stat().st_mtime_ns != plan['mtime']:  # 验证完整复制且复制期间来源未变。
                            raise OSError('跨卷复制校验失败，来源未删除')  # 保留可诊断半成品。
                        self.checkpoint(job, plan, 'copy_verified')  # 在重命名前保存完整内容摘要。
                        os.rename(partial, anchor)  # Windows 上不覆盖现有目标。
                    plan['anchor_identity'] = identity(anchor)  # 保存归档卷的新文件身份。
                    self.checkpoint(job, plan, 'prepared')  # 内容准备完成后允许建立目标入口。
                if anchor.exists():  # 清理之前必须检查锚点未被替换。
                    if identity(anchor) != plan['anchor_identity']:  # 拒绝外部替换的暂存文件。
                        raise OSError('归档暂存文件已被替换')  # 保护未知内容。
                    for target in map(Path, plan['targets']):  # 先建立所有新入口。
                        target.parent.mkdir(parents=True, exist_ok=True)  # 恢复可能被删除的空目录。
                        if not target.exists():  # 已建立入口可直接验证。
                            os.link(anchor, target)  # 每个标签只增加硬链接。
                        if identity(target) != plan['anchor_identity']:  # 确保没有同名冲突覆盖。
                            raise OSError(f'目标被其他文件占用：{target}')  # 保留原始视频并等待处理。
                for target in plan['targets']:  # 即使锚点已清理仍需验证最终入口。
                    if identity(target) != plan['anchor_identity']:  # 确认每个入口确实存在且正确。
                        raise OSError('目标入口验证失败')  # 未验证不提交分类状态。
                self.checkpoint(job, plan, 'linked')  # 所有新入口已建立。
                with self.store.lock, self.store.db:  # 分类和路径映射在同一数据库事务内提交。
                    self.store.db.execute('UPDATE videos SET score=?,tags=?,archived=1,name=COALESCE(?,name),original_name=COALESCE(original_name,?,name) WHERE id=?', (plan['score'], json.dumps(plan['tags'], ensure_ascii=False), plan.get('name'), plan.get('original_name'), plan['video']))  # 名称、评分、标签和路径同事务提交，也兼容旧版本未完成任务。
                    if 'favorite' in plan:
                        self.store.db.execute('UPDATE videos SET star=? WHERE id=?', (plan['favorite'], plan['video']))
                    for target in plan['targets']:  # 登记归档卷实际文件身份。
                        self.store.db.execute('INSERT OR REPLACE INTO paths VALUES(?,?,?)', (target, plan['video'], plan['anchor_identity']))  # 复用原视频 ID。
                    for tag in plan['tags']:  # 成功确认的标签进入公共标签库。
                        self.store.db.execute('INSERT OR IGNORE INTO tags VALUES(?)', (tag,))  # 重复标签只保留一份。
                    if plan.get('defer_cleanup'):
                        target_keys = {os.path.normcase(path) for path in plan['targets']}
                        retired = [old for old in plan['old'] if os.path.normcase(old['path']) not in target_keys]
                        if anchor.exists():
                            stat = anchor.stat()
                            retired.append(dict(path=str(anchor),identity=plan['anchor_identity'],size=stat.st_size,mtime=stat.st_mtime_ns))
                        for index,old in enumerate(retired):
                            self.store.db.execute('INSERT OR IGNORE INTO cleanup_jobs VALUES(?,?,?,?,?,?,?,?,?)',
                                (f'{job}:{index}',plan['video'],old['path'],old['identity'],old.get('size',plan['size']),old.get('mtime',plan['mtime']),'pending',None,time.time()))
                            self.store.db.execute('DELETE FROM paths WHERE path=? AND id=?',(old['path'],plan['video']))
                self.checkpoint(job, plan, 'committed')  # 数据库已指向有效新入口。
                if plan.get('defer_cleanup'):
                    self.checkpoint(job,plan,'done')
                    return plan['video']
                target_keys = {os.path.normcase(x) for x in plan['targets']}  # Windows 路径比较忽略大小写。
                for old in plan['old']:  # 最后清理之前已登记的入口。
                    path = Path(old['path'])  # 转换可操作路径。
                    if os.path.normcase(str(path)) in target_keys:  # 保留目标中仍在使用的入口。
                        continue  # 防止删除当前有效标签。
                    if path.exists():  # 已清理的入口无需重试删除。
                        if identity(path) != old['identity']:  # 外部替换的同名文件不属于本任务。
                            raise OSError(f'旧入口被替换，未删除：{path}')  # 明确留下待处理状态。
                        if path.stat().st_size != plan['size'] or path.stat().st_mtime_ns != plan['mtime']:  # 防止跨卷期间源数据发生改变。
                            raise OSError('旧入口内容已变化，未删除')  # 保留可能的新内容。
                        path.unlink()  # 此时所有新入口和数据库记录均已确认。
                    self.store.execute('DELETE FROM paths WHERE path=? AND id=?', (str(path), plan['video']))  # 清理失效映射。
                if anchor.exists():  # 最终移除额外的安全锚点。
                    anchor.unlink()  # 正常标签入口仍保存同一视频内容。
                self.checkpoint(job, plan, 'done')  # 任务真正完成后才报告成功。
                return plan['video']  # 供界面刷新和安全续播。
            except Exception as error:  # 记录文件和数据库异常供重试。
                self.store.execute('UPDATE jobs SET error=?,updated=? WHERE id=?', (str(error), time.time(), job))  # 不把失败任务标为完成。
                raise  # 界面显示原始失败原因。

    def recover(self):  # 启动时恢复所有未完成任务。
        errors = []  # 汇总无法自动恢复的任务。
        for row in self.store.query('SELECT id,plan FROM jobs WHERE state<>"done" ORDER BY updated'):  # 按提交顺序恢复。
            try:  # 单个失败不丢失其他任务信息。
                if json.loads(row['plan']).get('action') == 'rename':
                    continue  # 重命名由专属服务恢复，不按归档计划解释。
                self.run(row['id'])  # 使用持久计划幂等重放。
            except Exception as error:  # 保留待人工处理的任务。
                errors.append(f'{row["id"]}: {error}')  # 返回实际失败状态。
        return errors  # 界面提示并允许再次重试。
