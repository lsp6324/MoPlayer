"""Retire obsolete entries without changing current metadata or playback."""
import os
from pathlib import Path
import time

from core import identity


class ArchiveCleanup:
    def __init__(self, store, unlink=lambda path: path.unlink()):
        self.store, self.unlink = store, unlink

    def drain(self, protected=()):
        protected = {os.path.normcase(str(path)) for path in protected}
        completed = 0
        with self.store.file_lock:
            # A committed job may have enqueued retirements before its final
            # checkpoint. Recovery must finish that frozen intent first.
            if any(self.store.query(f'SELECT id FROM {table} WHERE state<>"done"') for table in
                   ('jobs','hierarchy_jobs','archive_setting_jobs','deletion_jobs')):
                return 0
            for row in self.store.query('SELECT * FROM cleanup_jobs WHERE state<>"done" ORDER BY updated'):
                path = Path(row['path'])
                if os.path.normcase(str(path)) in protected:
                    continue
                try:
                    active = self.store.query('SELECT * FROM paths WHERE path=?',(str(path),))
                    if not active:
                        for part in (path,*path.parents):
                            if part.is_symlink() or (part.exists() and getattr(part.lstat(),'st_file_attributes',0)&0x400):
                                raise OSError('路径已变为链接或重解析点，未清理。')
                        if path.exists():
                            stat = path.stat()
                            if identity(path)!=row['identity'] or stat.st_size!=row['size'] or stat.st_mtime_ns!=row['mtime']:
                                raise OSError('旧入口的身份或内容已改变，未清理。')
                            self.unlink(path)
                    # A later classification may have reused this path. Its
                    # current mapping wins; never replay an old deletion intent.
                    self.store.execute('UPDATE cleanup_jobs SET state="done",error=NULL,updated=? WHERE id=?',(time.time(),row['id']))
                    completed += 1
                except OSError as error:
                    self.store.execute('UPDATE cleanup_jobs SET error=?,updated=? WHERE id=?',(f'{path}: {error}',time.time(),row['id']))
        return completed
