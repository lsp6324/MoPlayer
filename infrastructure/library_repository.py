"""The application-facing query boundary around the existing SQLite Store.

    Store and the recoverable file services retain their existing transactions
    and lock order. Views do not issue SQL or borrow the connection.
"""
import json
import time
from pathlib import Path

from application.tag_drafts import TagValues
from core import media_kind


class LibraryRepository:
    BLOCKING_TABLES = ('jobs', 'hierarchy_jobs', 'deletion_jobs', 'archive_setting_jobs')
    TASK_TABLES = (*BLOCKING_TABLES, 'cleanup_jobs')

    def __init__(self, store):
        self.store = store

    def video(self, video_id):
        rows = self.store.query('SELECT * FROM videos WHERE id=?', (video_id,))
        return rows[0] if rows else None

    @staticmethod
    def presented(rows):
        """Attach the display fields every list row needs, from one record.

        kind and tag_names are derived, so no consumer may depend on which
        query happened to write them last; a raw SELECT row alone is enough.
        """
        return [dict(row, kind=media_kind(row['name']),
                     tag_names=tuple(json.loads(row['tags'] or '[]'))) for row in rows]

    def videos(self, mode):
        condition = {'videos': 'played>0', 'stars': 'star=1', 'archived': 'archived=1',
                     'catalog': 'in_library=1', 'all': '1'}[mode]
        return self.presented(self.store.query('SELECT * FROM videos WHERE ' + condition + ' ORDER BY played DESC'))

    def video_details(self, video_ids):
        ids = list(dict.fromkeys(video_ids))
        rows = []
        for offset in range(0, len(ids), 900):
            batch = ids[offset:offset + 900]
            placeholders = ','.join('?' for _ in batch)
            rows.extend(self.store.query(f'SELECT * FROM videos WHERE id IN ({placeholders})', batch))
        return {row['id']: row for row in self.presented(rows)}

    def catalog_data(self):
        # Query stable identities, never paths: hard links cannot duplicate rows.
        with self.store.lock:
            rows = self.videos('catalog')
            schema = self.store.tag_layout()
        return rows, schema

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

    def clear_history(self):
        """Drop the recent-play history; files, tags, scores, stars and progress stay."""
        self.store.execute('UPDATE videos SET played=0')

    def remember_folder(self, folder):
        self.store.execute('INSERT OR REPLACE INTO folders VALUES(?,?)', (str(Path(folder).absolute()), time.time()))

    def folders(self):
        return self.store.query('SELECT * FROM folders ORDER BY time DESC')

    def progress(self, video_id, position):
        self.store.progress(video_id, position)

    def resolve(self, video_id):
        return self.store.resolve(video_id)

    def archive_locations(self, video_id, root):
        """Display committed active directories relative to the archive root."""
        video = self.video(video_id)
        if video is None or not video['archived']:
            return ()
        root = Path(root)
        locations = set()
        for row in self.store.query('SELECT path FROM paths WHERE id=? ORDER BY path', (video_id,)):
            try:
                relative = Path(row['path']).parent.relative_to(root)
            except ValueError:
                continue
            locations.add(' / '.join(relative.parts) if relative.parts else root.name)
        return tuple(sorted(locations))

    def media_directories(self, video_id):
        """Compare active directory membership without resolving files or old cleanup paths."""
        return frozenset(str(Path(row['path']).parent).casefold() for row in
                         self.store.query('SELECT path FROM paths WHERE id=?', (video_id,)))

    def register(self, path):
        return self.store.register(path)

    def pending_tasks(self, table=None):
        tables = (table,) if table else self.BLOCKING_TABLES
        if any(name not in self.TASK_TABLES for name in tables):
            raise ValueError('Unknown task kind')
        return [dict(row, kind=name) for name in tables for row in
                self.store.query(f'SELECT * FROM {name} WHERE state<>"done" ORDER BY updated')]

    def task_history(self):
        return [dict(row, kind=name) for name in self.TASK_TABLES
                for row in self.store.query(f'SELECT * FROM {name} ORDER BY updated DESC')]
