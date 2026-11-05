"""Recoverable in-place rename of registered entries; never reclassifies video."""
import json
import os
from pathlib import Path
import time
import uuid

from core import archive_name, identity


class FileRenaming:
    def __init__(self, store, fault=None):
        self.store, self.fault = store, fault

    def checkpoint(self, job, state):
        self.store.execute('UPDATE jobs SET state=?,error=NULL,updated=? WHERE id=?',
                           (state, time.time(), job))
        if self.fault:
            self.fault(state)

    @staticmethod
    def validate_path(path):
        for part in (path, *path.parents):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
                raise OSError(f'路径含链接或重解析点，未执行重命名：{part}')

    @classmethod
    def verify(cls, path, entry):
        cls.validate_path(path)
        stat = path.stat()
        if (identity(path) != entry['identity'] or stat.st_size != entry['size']
                or stat.st_mtime_ns != entry['mtime']):
            raise OSError(f'文件身份或内容已改变，未继续重命名：{path}')

    def validate(self, video_id, name):
        """Read-only preflight; submit repeats it under the same file lock."""
        with self.store.file_lock:
            try:
                archive_name(name)
            except ValueError as error:
                raise ValueError('文件名无效：不能使用路径、保留名称、非法字符、末尾空格或点，长度不能超过 255 个字符。') from error
            if any(self.store.query(f'SELECT id FROM {table} WHERE state<>"done"')
                   for table in ('jobs', 'hierarchy_jobs', 'archive_setting_jobs', 'deletion_jobs')):
                raise RuntimeError('有未完成的文件任务，请先在“更多 → 文件任务”恢复。')
            record = self.store.video(video_id)
            if Path(name).suffix.casefold() != Path(record['name']).suffix.casefold():
                raise ValueError(f'请保留文件扩展名 {Path(record["name"]).suffix}。')
            if name == record['name'] and name == record['original_name']:
                return None
            entries = []
            for row in self.store.query('SELECT * FROM paths WHERE id=? ORDER BY path', (video_id,)):
                source = Path(row['path'])
                self.validate_path(source)
                if not source.exists():
                    continue
                stat = source.stat()
                entry = dict(source=str(source), target=str(source.with_name(name)), identity=row['identity'],
                             size=stat.st_size, mtime=stat.st_mtime_ns)
                self.verify(source, entry)
                target = Path(entry['target'])
                self.validate_path(target)
                if target.exists() and os.path.normcase(str(source)) != os.path.normcase(str(target)):
                    raise FileExistsError(f'该文件夹已有同名文件，请换一个名称：{target.name}')
                if any(row['id'] != video_id for row in self.store.query('SELECT id FROM paths WHERE path=?',(str(target),))):
                    raise FileExistsError(f'该名称已有其他视频记录，请换一个名称：{target.name}')
                entries.append(entry)
            if not entries:
                raise FileNotFoundError('视频已不存在或无法定位，未执行重命名。')
            if len({os.path.normcase(entry['target']) for entry in entries}) != len(entries):
                raise ValueError('同一文件夹中登记了此视频的多个入口，无法将它们改为同一个文件名。')
            return dict(action='rename', video=video_id, name=name, entries=entries)

    def submit(self, video_id, name):
        with self.store.file_lock:
            plan = self.validate(video_id, name)
            if plan is None:
                return video_id
            job = uuid.uuid4().hex
            self.store.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                               (job, video_id, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))
            self.checkpoint(job, 'planned')
            return self.run(job)

    def run(self, job):
        with self.store.file_lock:
            row = self.store.query('SELECT * FROM jobs WHERE id=?', (job,))[0]
            plan = json.loads(row['plan'])
            if plan.get('action') != 'rename':
                raise ValueError('不是重命名任务。')
            if row['state'] == 'done':
                return plan['video']
            try:
                for index, entry in enumerate(plan['entries']):
                    source, target = Path(entry['source']), Path(entry['target'])
                    if row['state'] != 'committed' and source.exists():
                        self.verify(source, entry)
                        self.validate_path(target)
                        if str(source) != str(target):
                            # Windows rename refuses existing destinations. A case-only
                            # rename is allowed only for this exact registered entry.
                            if target.exists() and os.path.normcase(str(source)) != os.path.normcase(str(target)):
                                raise FileExistsError(f'目标已存在，未覆盖：{target}')
                            os.rename(source, target)
                    self.verify(target, entry)
                    if row['state'] != 'committed':
                        self.checkpoint(job, f'renamed-{index}')
                if row['state'] == 'committed':
                    self.checkpoint(job, 'done')
                    return plan['video']
                with self.store.lock, self.store.db:
                    for entry in plan['entries']:
                        self.store.db.execute('DELETE FROM paths WHERE path=? AND id=?', (entry['source'], plan['video']))
                    for entry in plan['entries']:
                        mapped = self.store.db.execute('SELECT id FROM paths WHERE path=?',(entry['target'],)).fetchone()
                        if mapped and mapped['id'] != plan['video']:
                            raise OSError('目标路径已登记为其他视频，未覆盖资料库记录。')
                        # A scan after interruption may already have registered this
                        # verified entry under the same stable video identity.
                        self.store.db.execute('INSERT OR REPLACE INTO paths VALUES(?,?,?)', (entry['target'], plan['video'], entry['identity']))
                    self.store.db.execute('UPDATE videos SET name=?,original_name=? WHERE id=?',
                                          (plan['name'], plan['name'], plan['video']))
                    self.store.db.execute('UPDATE jobs SET state="committed",error=NULL,updated=? WHERE id=?', (time.time(), job))
                if self.fault:
                    self.fault('committed')
                self.checkpoint(job, 'done')
                return plan['video']
            except Exception as error:
                self.store.execute('UPDATE jobs SET error=?,updated=? WHERE id=?', (str(error), time.time(), job))
                raise

    def recover(self):
        errors = []
        for row in self.store.query('SELECT id,plan FROM jobs WHERE state<>"done" ORDER BY updated'):
            try:
                if json.loads(row['plan']).get('action') == 'rename':
                    self.run(row['id'])
            except Exception as error:
                errors.append(f'{row["id"]}: {error}')
        return errors
