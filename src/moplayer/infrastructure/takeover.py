"""Read-only discovery followed by one atomic metadata transaction; no file writes."""
import json
import os
from pathlib import Path
import stat
import time
import uuid
from dataclasses import replace
from moplayer.application.takeover import (Markers, TagSpec, TakeoverFile, TakeoverPath, make_plan)
from moplayer.core import EXTENSIONS, identity, natural, validate_tag, validate_layout, canonical_tags


class TakeoverService:
    def __init__(self, store, *, fault=None):
        self.store, self.fault = store, fault

    def _pending(self):
        return any(self.store.query(f'SELECT id FROM {table} WHERE state<>"done" LIMIT 1')
                   for table in ('jobs', 'hierarchy_jobs', 'deletion_jobs', 'archive_setting_jobs'))

    def _schema(self):
        return tuple(TagSpec(row['name'], row['parent'], bool(row['is_parent']))
                     for row in self.store.tag_layout().values())

    @staticmethod
    def _markers(row):
        return Markers(row['score'], bool(row['star']), tuple(sorted(json.loads(row['tags']))), bool(row['in_library']))

    def _binding(self, key):
        ids = {row['id'] for row in self.store.query('SELECT id FROM paths WHERE identity=?', (key,))}
        if len(ids) > 1:
            raise ValueError('同一文件身份对应多份软件记录，请先检查现有资料库。')
        video_id = next(iter(ids), None)
        rows = self.store.query('SELECT * FROM videos WHERE id=?', (video_id,)) if video_id else []
        if video_id and not rows:
            raise ValueError('文件路径对应的软件记录已缺失。')
        return video_id, self._markers(rows[0]) if rows else None

    def _retired(self, path, key):
        return bool(self.store.query('SELECT c.video FROM cleanup_jobs c JOIN videos v ON v.id=c.video '
            'WHERE c.path=? AND c.identity=? AND c.state<>"done" '
            'AND NOT EXISTS(SELECT 1 FROM paths p WHERE p.path=c.path AND p.identity=c.identity) LIMIT 1', (path, key)))

    def _path_binding(self, path):
        rows = self.store.query('SELECT id,identity FROM paths WHERE path=?', (path,))
        return (rows[0]['id'], rows[0]['identity']) if rows else None

    def preview(self, root, rules, cancel):
        root = Path(root)
        if not root.is_absolute():
            raise ValueError('请选择完整的文件夹路径。')
        info = root.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or root.is_symlink():
            raise ValueError('请选择普通文件夹，不能接管链接或重解析目录。')
        if self._pending():
            raise RuntimeError('请先恢复未完成文件任务，再接管旧目录。')
        grouped, warnings, stack, seen = {}, [], [root], set()
        while stack:
            if cancel.is_set():
                raise InterruptedError('接管扫描已取消。')
            directory = stack.pop()
            try:
                key = identity(directory)
                if key in seen:
                    continue
                seen.add(key)
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: natural(entry.name))
                for entry in entries:
                    if cancel.is_set():
                        raise InterruptedError('接管扫描已取消。')
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if getattr(info, 'st_file_attributes', 0) & 0x400 or entry.is_symlink():
                            warnings.append('跳过链接：' + entry.path)
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if entry.name.casefold() != '.moplayer-staging':
                                stack.append(Path(entry.path))
                        elif stat.S_ISREG(info.st_mode) and Path(entry.name).suffix.lower() in EXTENSIONS:
                            key = identity(entry.path)
                            if self._retired(entry.path, key):
                                warnings.append('跳过待清理旧入口：' + entry.path)
                                continue
                            relative = Path(entry.path).relative_to(root).parent.parts
                            grouped.setdefault(key, []).append(TakeoverPath(entry.path, relative, info.st_size, info.st_mtime_ns))
                    except InterruptedError:
                        raise
                    except OSError as error:
                        warnings.append(f'{entry.path}：{error}')
            except InterruptedError:
                raise
            except OSError as error:
                if directory == root:
                    raise
                warnings.append(f'{directory}：{error}')
        if cancel.is_set():
            raise InterruptedError('接管扫描已取消。')
        with self.store.lock:
            schema = self._schema()
            files = [TakeoverFile(key, tuple(replace(path, binding=self._path_binding(path.path))
                                           for path in sorted(paths, key=lambda path: natural(path.path))), *self._binding(key))
                     for key, paths in grouped.items()]
        for file in files:
            for path in file.paths:
                if path.binding and path.binding[1] != file.identity:
                    warnings.append('当前位置已是另一个文件，将建立独立记录并保留旧记录的标记：' + path.path)
        files.sort(key=lambda file: natural(file.paths[0].path))
        plan = make_plan(str(root), files, schema, rules, warnings, validate_name=validate_tag)
        if cancel.is_set():
            raise InterruptedError('接管扫描已取消。')
        return plan

    def apply(self, plan, identities, *, include_conflicts=False):
        by_key = {item.file.identity: item for item in plan.items}
        if not identities or not identities <= by_key.keys():
            raise ValueError('请先选择预览中的文件。')
        selected = [item for item in plan.items if item.file.identity in identities]
        if not include_conflicts and any(item.conflicts for item in selected):
            raise ValueError('冲突项目未确认，请取消选择或启用“冲突项仅纳入库”。')
        with self.store.file_lock:
            if self._pending():
                raise RuntimeError('请先恢复未完成文件任务，再接管旧目录。')
            # Slow file checks precede the database transaction and never hold
            # the metadata lock used by the player's progress/time updates.
            for item in selected:
                for path in item.file.paths:
                    info = os.stat(path.path, follow_symlinks=False)
                    if (getattr(info, 'st_file_attributes', 0) & 0x400 or not stat.S_ISREG(info.st_mode)
                            or identity(path.path) != item.file.identity or (info.st_size, info.st_mtime_ns) != (path.size, path.mtime)):
                        raise ValueError('预览后的文件已变化，请重新扫描：' + path.path)
                    if self._retired(path.path, item.file.identity):
                        raise ValueError('预览后的入口已进入清理队列，请重新扫描。')
            with self.store.lock, self.store.db:
                self.store.db.execute('BEGIN IMMEDIATE')
                if self._schema() != plan.baseline_schema:
                    raise ValueError('预览后的标签结构已变化，请重新扫描。')
                for item in selected:
                    if self._binding(item.file.identity) != (item.file.video_id, item.file.baseline):
                        raise ValueError('预览后的库记录或标记已变化，请重新扫描。')
                    for path in item.file.paths:
                        if self._path_binding(path.path) != path.binding:
                            raise ValueError('路径对应的文件记录已变化，请重新扫描：' + path.path)
                schema = {tag.name: tag for tag in plan.schema}
                needed = set()
                for item in selected:
                    if item.conflicts or item.kept_existing:
                        continue
                    for name in item.markers.tags:
                        while name and name not in needed:
                            needed.add(name)
                            name = schema[name].parent
                layout = {tag.name: dict(name=tag.name, parent=tag.parent, kind='minor' if tag.parent else 'major', is_parent=tag.is_parent)
                          for tag in plan.baseline_schema}
                for name in needed:
                    tag = schema[name]
                    layout[name] = dict(name=name, parent=tag.parent, kind='minor' if tag.parent else 'major', is_parent=tag.is_parent)
                layout = validate_layout(layout.values())
                for name in needed:
                    row = layout[name]
                    self.store.db.execute('INSERT OR IGNORE INTO tags VALUES(?)', (name,))
                    self.store.db.execute('INSERT OR REPLACE INTO tag_layout VALUES(?,?,?)', (name, row['kind'], row['parent']))
                completed, now = [], time.time()
                for item in selected:
                    file = item.file
                    video_id = file.video_id or uuid.uuid4().hex
                    if file.video_id is None:
                        name = Path(file.paths[0].path).name
                        self.store.db.execute('INSERT INTO videos(id,name,original_name) VALUES(?,?,?)', (video_id, name, name))
                    for path in file.paths:
                        self.store.db.execute('INSERT OR REPLACE INTO paths VALUES(?,?,?)', (path.path, video_id, file.identity))
                    if not item.conflicts and not item.kept_existing:
                        tags = canonical_tags(item.markers.tags, layout)
                        self.store.db.execute('UPDATE videos SET score=?,star=?,tags=? WHERE id=?',
                            (item.markers.score, int(item.markers.favorite), json.dumps(tags, ensure_ascii=False), video_id))
                    self.store.db.execute('UPDATE videos SET library_added_at=CASE WHEN in_library=0 THEN COALESCE(library_added_at,?) ELSE library_added_at END,in_library=1 WHERE id=?', (now, video_id))
                    completed.append(video_id)
                    if self.fault:
                        self.fault(len(completed))
                return tuple(completed)
