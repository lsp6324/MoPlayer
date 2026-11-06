import ctypes  # 使用 Windows 原生回收站接口释放文件入口。
import json  # 持久保存删除计划和逐入口状态。
import logging  # 记录删除失败和恢复步骤。
import threading  # 串行处理同一库中的删除请求。
import time  # 保存可追踪的任务更新时间。
import uuid  # 分配独立删除任务身份。
from pathlib import Path  # 检查真实文件位置。
from ctypes import wintypes  # 保持 Windows COM 参数的正确位宽。
from moplayer.core import identity  # 只处理与登记身份一致的文件。

class GUID(ctypes.Structure):  # 表示 Windows COM 标识。
    _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]  # 使用十六字节标准布局。

def guid(value):  # 把标准 GUID 文本转换成系统结构。
    result = GUID()  # 创建标识缓冲区。
    ctypes.windll.ole32.CLSIDFromString(value, ctypes.byref(result))  # 让 Windows 处理字段字节序。
    return result  # 返回 COM 调用参数。

def method(pointer, index, *arguments):  # 为指定 COM 方法声明完整调用签名。
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents  # 读取接口虚函数表。
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(table[index])  # HRESULT 与六十四位指针保持正确。

def checked(result):  # 将 HRESULT 失败转换成明确异常。
    if result < 0:  # HRESULT 失败值为负数。
        raise OSError(f'Windows 回收站操作失败：0x{result & 0xffffffff:08x}')  # 保留权限、占用或空间不足的真实错误码。

def recycle_file(path):  # 请求 Windows 将一个文件移入回收站，不自行永久删除。
    path = Path(path).absolute()  # 保留原路径以检查符号链接而不先跟随目标。
    if not path.is_file() or path.is_symlink():  # 不递归删除文件夹或沿符号链接操作其他对象。
        raise ValueError('删除目标必须是普通视频文件。')  # 不扩大快捷键的删除范围。
    ole, shell = ctypes.windll.ole32, ctypes.windll.shell32  # 使用系统自带组件，不引入安装依赖。
    initialized = ole.CoInitializeEx(None, 2)  # 在后台线程中使用 COM 单线程单元。
    checked(initialized)  # COM 初始化失败时不执行文件操作。
    operation, item = ctypes.c_void_p(), ctypes.c_void_p()  # 持有原生文件操作和 Shell 文件对象。
    try:  # 无论操作结果如何都释放接口。
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]  # 防止六十四位参数截断。
        ole.CoCreateInstance.restype = ctypes.c_long  # 使用标准 HRESULT。
        checked(ole.CoCreateInstance(ctypes.byref(guid('{3ad05575-8857-4850-9277-11b85bdb8e09}')), None, 1, ctypes.byref(guid('{947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8}')), ctypes.byref(operation)))  # 创建 IFileOperation。
        flags = 0x00080000 | 0x00100000 | 0x40 | 0x400 | 0x4 | 0x10  # 强制回收、遇错即停、保留撤销，抑制重复进度及错误窗口。
        checked(method(operation, 5, wintypes.DWORD)(operation, flags))  # 配置 Windows 8+ 明确回收语义。
        shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]  # 支持中文及带空格路径。
        shell.SHCreateItemFromParsingName.restype = ctypes.c_long  # 检查 Shell 文件对象创建结果。
        checked(shell.SHCreateItemFromParsingName(str(path), None, ctypes.byref(guid('{43826D1E-E718-42EE-BC55-A1E261C37BFE}')), ctypes.byref(item)))  # 获取 IShellItem。
        checked(method(operation, 18, ctypes.c_void_p, ctypes.c_void_p)(operation, item, None))  # 将这个文件排入删除队列。
        checked(method(operation, 21)(operation))  # 真正执行原生回收站操作。
        aborted = wintypes.BOOL()  # 接收用户取消或系统终止状态。
        checked(method(operation, 22, ctypes.POINTER(wintypes.BOOL))(operation, ctypes.byref(aborted)))  # 不把部分终止当成成功。
        if aborted.value or path.exists():  # 文件仍在原处时必须报告失败。
            raise OSError('文件尚未移入回收站，可能仍被其他程序占用或回收站不可用。')  # 不改用永久删除兜底。
    finally:  # 及时释放原生句柄与 COM 状态。
        for pointer in [item, operation]:  # 每个接口各释放一次。
            if pointer.value:  # 失败路径可能没有返回接口。
                method(pointer, 2)(pointer)  # 调用 IUnknown.Release。
        ole.CoUninitialize()  # 平衡本线程的 COM 初始化。

class DeletionManager:  # 用持久任务协调文件回收和元数据提交。
    def __init__(self, store, recycle=recycle_file, fault=None):  # 可注入隔离回收器和故障点做验证。
        self.store, self.recycle, self.fault = store, recycle, fault  # 不依赖绝对路径作为视频永久身份。
        self.lock = threading.RLock()  # 避免并发删除同一组入口。

    def checkpoint(self, job, plan, state):  # 每个阶段落盘后再继续。
        self.store.execute('UPDATE deletion_jobs SET state=?,plan=?,error=NULL,updated=? WHERE id=?', (state, json.dumps(plan, ensure_ascii=False), time.time(), job))  # 删除日志独立于归档任务。
        logging.info('删除任务 %s 阶段 %s', job, state)  # 写入可追踪应用日志。
        if self.fault:  # 仅测试环境注入异常退出。
            self.fault(state)  # 正式运行不改变控制流。

    def submit(self, vid):  # 删除一个视频在数据库中登记的全部入口。
        with self.lock, self.store.file_lock:  # 回收与扫描登记串行，避免扫描复活即将删除的身份。
            if self.store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done"'):
                raise RuntimeError('有未完成的归档设置整理，请先恢复。')
            if self.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"'):  # 全局分类迁移期间不能删除它仍保护的视频入口。
                raise RuntimeError('有未完成的标签结构迁移，请先在文件任务中恢复。')  # 不破坏跨视频迁移的恢复计划。
            pending = self.store.query('SELECT id FROM deletion_jobs WHERE video=? AND state<>"done" ORDER BY updated LIMIT 1', (vid,))  # 同一视频失败后继续原计划。
            if pending:  # 不为重试创建重复任务。
                plan = json.loads(self.store.query('SELECT plan FROM deletion_jobs WHERE id=?', (pending[0]['id'],))[0]['plan'])
                if plan.get('delete_files', True) is False:
                    raise RuntimeError('此视频有未完成的仅删除记录任务，请先恢复。')
                return self.run(pending[0]['id'])  # 按逐入口记录恢复。
            if self.store.query('SELECT id FROM jobs WHERE video=? AND state<>"done"', (vid,)):  # 避免删除尚在归档日志保护中的内容。
                raise RuntimeError('此视频有未完成归档，请先通过任务列表恢复。')  # 不删除归档的最后安全入口。
            record = self.store.video(vid)  # 保存当前元数据以供审计与恢复诊断。
            paths = self.store.query('SELECT * FROM paths WHERE id=? ORDER BY path', (vid,))  # 只处理明确登记的入口。
            known = {str(Path(row['path'])).casefold() for row in paths}
            for retired in self.store.query('SELECT * FROM cleanup_jobs WHERE video=? AND state<>"done"',(vid,)):
                if retired['path'].casefold() not in known and not self.store.query('SELECT id FROM paths WHERE path=?',(retired['path'],)):
                    paths.append(retired)
                    known.add(retired['path'].casefold())
            valid = []  # 计划中仅包含当前确实匹配的文件。
            for row in paths:  # 提交前完整预检，避免删了一半才发现同名替换。
                path = Path(row['path'])  # 不使用文件名搜索其他视频。
                if not path.exists():  # 外部已删除的失效映射不触碰其他路径。
                    continue  # 仍可处理同视频的其他有效入口。
                if identity(path) != row['identity'] or path.is_symlink():  # 不误删原位置上的新文件或链接目标。
                    raise OSError('原位置的文件身份已改变，已取消删除：' + str(path))  # 不按相同文件名判断身份。
                valid.append({'path': str(path), 'identity': row['identity'], 'state': 'pending'})  # 固定本次操作目标和原始身份。
            if not valid:  # 完全无法定位时不得作用于其他视频。
                raise FileNotFoundError('视频已不存在或无法定位，没有执行删除。')  # 明确说明未发生文件操作。
            job = uuid.uuid4().hex  # 分配独立可重试任务。
            plan = {'video': vid, 'record': record, 'paths': valid}  # 保留所有标签入口的操作记录。
            self.store.execute('INSERT INTO deletion_jobs VALUES(?,?,?,?,?,?)', (job, vid, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))  # 首次文件操作前先保存计划。
            return self.run(job)  # 正式处理回收和数据库提交。

    def forget(self, vid):
        """Forget this identity and its metadata without touching local files."""
        with self.lock, self.store.file_lock:
            for table in ('archive_setting_jobs', 'hierarchy_jobs'):
                if self.store.query(f'SELECT id FROM {table} WHERE state<>"done"'):
                    raise RuntimeError('有未完成的全局文件任务，请先恢复。')
            pending = self.store.query('SELECT * FROM deletion_jobs WHERE video=? AND state<>"done" ORDER BY updated LIMIT 1', (vid,))
            if pending:
                if json.loads(pending[0]['plan']).get('delete_files', True):
                    raise RuntimeError('此视频有未完成的本地文件删除任务，请先恢复。')
                return self.run(pending[0]['id'])
            if self.store.query('SELECT id FROM jobs WHERE video=? AND state<>"done"', (vid,)):
                raise RuntimeError('此视频有未完成的文件任务，请先恢复。')
            record = self.store.video(vid)
            plan = {'video': vid, 'record': record, 'paths': [], 'delete_files': False}
            job = uuid.uuid4().hex
            self.store.execute('INSERT INTO deletion_jobs VALUES(?,?,?,?,?,?)',
                               (job, vid, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))
            return self.run(job)

    def _commit(self, job, plan):
        with self.store.lock, self.store.db:
            self.store.db.execute('DELETE FROM paths WHERE id=?', (plan['video'],))
            self.store.db.execute('DELETE FROM videos WHERE id=?', (plan['video'],))
            self.store.db.execute('UPDATE cleanup_jobs SET state="done",error=NULL,updated=? WHERE video=?', (time.time(), plan['video']))
            self.store.db.execute('UPDATE deletion_jobs SET state="done",error=NULL,updated=? WHERE id=?', (time.time(), job))

    def run(self, job):  # 幂等恢复中断或部分完成的删除任务。
        with self.lock, self.store.file_lock:  # 恢复也与路径发现共用文件锁。
            row = self.store.query('SELECT * FROM deletion_jobs WHERE id=?', (job,))[0]  # 按持久任务读取状态。
            plan = json.loads(row['plan'])  # 不依赖上次进程的内存。
            if row['state'] == 'done':  # 已完成任务不重复文件操作。
                return plan  # 返回原审计记录。
            try:  # 任意失败都保留任务和尚存元数据。
                self.checkpoint(job, plan, 'planned')  # 统一从已保存的路径状态继续。
                if plan.get('delete_files', True) is False:
                    self._commit(job, plan)
                    logging.info('仅删除软件记录 %s，保留本地文件', plan['video'])
                    return plan
                for entry in plan['paths']:  # 每次只处理一个受身份校验保护的入口。
                    if entry['state'] != 'pending':  # 已回收入口不重复操作。
                        if Path(entry['path']).exists():  # 用户恢复的入口或新同名文件不能被悄悄丢弃元数据。
                            raise OSError('已处理路径重新出现，停止删除：' + entry['path'])  # 保留身份与记录供人工处理。
                        continue  # 同名新文件不会被当成旧路径再次删除。
                    path = Path(entry['path'])  # 固定本次任务中的目标路径。
                    if path.exists():  # 崩溃可能发生在回收完成但阶段尚未写入时。
                        if identity(path) != entry['identity'] or path.is_symlink():  # 恢复时重新验证文件身份。
                            raise OSError('文件身份变化，停止删除：' + str(path))  # 保护外部替换文件。
                        self.recycle(path)  # Windows 无法回收时保留文件并抛出错误。
                        if path.exists():  # 回收器必须真正移走文件。
                            raise OSError('文件仍在原处，未完成删除：' + str(path))  # 不允许只更新数据库伪报成功。
                    entry['state'] = 'recycled'  # 路径已不在原处，更新逐入口进度。
                    self.checkpoint(job, plan, 'recycling')  # 中断后可从剩余入口继续。
                self.checkpoint(job, plan, 'files_recycled')  # 所有登记入口完成后才移除元数据。
                if any(Path(item['path']).exists() for item in self.store.query('SELECT path FROM paths WHERE id=?', (plan['video'],))):  # 防止并发登记的新入口被遗漏。
                    raise OSError('仍有登记入口存在，保留元数据并停止提交。')  # 不把部分删除伪报为完成。
                self._commit(job, plan)  # 文件已回收时，数据库删除一次性提交。
                logging.info('视频已移至回收站 %s 共 %s 个入口', plan['video'], len(plan['paths']))  # 不记录虚假的成功状态。
                return plan  # 返回显示所需的名字和入口数。
            except Exception as error:  # 其他程序占用、磁盘或数据库故障均可重试。
                self.store.execute('UPDATE deletion_jobs SET error=?,updated=? WHERE id=?', (str(error), time.time(), job))  # 保留实际失败阶段。
                raise  # 交给界面显示并安全恢复播放。

    def recover(self):  # 启动或用户要求时恢复先前明确提交的删除。
        errors = []  # 单个任务失败不丢失其他任务。
        for row in self.store.query('SELECT id FROM deletion_jobs WHERE state<>"done" ORDER BY updated'):  # 仅处理未完成任务。
            try:  # 逐任务幂等重放。
                self.run(row['id'])  # 沿用原始路径和文件身份。
            except Exception as error:  # 保留错误供任务列表展示。
                errors.append(f'{row["id"]}: {error}')  # 不假装删除已完成。
        return errors  # 返回可见错误列表。
