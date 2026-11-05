"""The application-facing query boundary around the existing SQLite Store.

    Store and the recoverable file services retain their existing transactions
    and lock order. Views do not issue SQL or borrow the connection.
"""
import json
import time
from pathlib import Path

from application.tag_drafts import TagValues


class LibraryRepository:
    TASK_TABLES = ('jobs', 'hierarchy_jobs', 'deletion_jobs', 'archive_setting_jobs')

    def __init__(self, store):
        self.store = store

    def video(self, video_id):
        rows = self.store.query('SELECT * FROM videos WHERE id=?', (video_id,))
        return rows[0] if rows else None

    def videos(self, mode):
        condition = {'videos': 'played>0', 'stars': 'star=1', 'archived': 'archived=1', 'all': '1'}[mode]
        return self.store.query('SELECT * FROM videos WHERE ' + condition + ' ORDER BY played DESC')

    def video_details(self, video_ids):
        ids = list(dict.fromkeys(video_ids))
        rows = []
        for offset in range(0, len(ids), 900):
            batch = ids[offset:offset + 900]
            placeholders = ','.join('?' for _ in batch)
            rows.extend(self.store.query(f'SELECT * FROM videos WHERE id IN ({placeholders})', batch))
        return {row['id']: row for row in rows}

    def tag_values(self, video_id):
        video = self.video(video_id)
        if video is None:
            raise FileNotFoundError('当前视频记录已不存在。')
        return TagValues(json.loads(video['tags']), self.store.tag_layout())

    def set_favorite(self, video_id, value):
        self.store.execute('UPDATE videos SET star=? WHERE id=?', (int(value), video_id))

    def set_score(self, video_id, score):
        self.store.execute('UPDATE videos SET score=? WHERE id=?', (score, video_id))

    def mark_played(self, video_id):
        self.store.execute('UPDATE videos SET played=? WHERE id=?', (time.time(), video_id))

    def remember_folder(self, folder):
        self.store.execute('INSERT OR REPLACE INTO folders VALUES(?,?)', (str(Path(folder).absolute()), time.time()))

    def folders(self):
        return self.store.query('SELECT * FROM folders ORDER BY time DESC')

    def progress(self, video_id, position):
        self.store.progress(video_id, position)

    def resolve(self, video_id):
        return self.store.resolve(video_id)

    def register(self, path):
        return self.store.register(path)

    def pending_tasks(self, table=None):
        tables = (table,) if table else self.TASK_TABLES
        if any(name not in self.TASK_TABLES for name in tables):
            raise ValueError('Unknown task kind')
        return [dict(row, kind=name) for name in tables for row in
                self.store.query(f'SELECT * FROM {name} WHERE state<>"done" ORDER BY updated')]

    def task_history(self):
        return [dict(row, kind=name) for name in self.TASK_TABLES
                for row in self.store.query(f'SELECT * FROM {name} ORDER BY updated DESC')]
