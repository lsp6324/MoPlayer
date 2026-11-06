"""Durable whole-library directory migration, reusing safe per-video jobs."""
import json
from pathlib import Path
import time
import uuid

from moplayer.application.archive_folders import ArchiveFolders
from moplayer.core import Archiver, archive_name, validate_layout
from moplayer.storage_settings import validate_storage_path


class ArchiveConfiguration:
    def __init__(self, store, settings, archiver, fault=None):
        self.store, self.settings, self.archiver = store, settings, archiver
        self.fault = fault

    def checkpoint(self, job, plan, state):
        self.store.execute('UPDATE archive_setting_jobs SET state=?,plan=?,error=NULL,updated=? WHERE id=?',
                           (state, json.dumps(plan, ensure_ascii=False), time.time(), job))
        if self.fault:
            self.fault(state)

    def restore_original_names(self):
        with self.archiver.lock, self.store.file_lock:
            if not self.settings.enabled:
                return []
            for table in ('jobs','hierarchy_jobs','deletion_jobs','archive_setting_jobs'):
                if self.store.query(f'SELECT id FROM {table} WHERE state<>"done"'):
                    raise RuntimeError('请先恢复未完成文件任务，再恢复原文件名。')
            videos=[]
            for video in self.store.query('SELECT * FROM videos WHERE archived=1 AND original_name IS NOT NULL'):
                if not video['original_name'] or video['name']==video['original_name']:
                    continue
                videos.append(dict(video=video['id'],score=video['score'],tags=json.loads(video['tags']),
                                   favorite=video['star'],root=str(self.store.resolve(video['id']).parent),done=False))
            if not videos:
                return []
            plan=dict(restore_original_names=True,archive_folders=self.archiver.folders.to_dict(),
                      layout=list(self.store.tag_layout().values()),videos=videos)
            job=uuid.uuid4().hex
            self.store.execute('INSERT INTO archive_setting_jobs VALUES(?,?,?,?,?)',
                               (job,'planned',json.dumps(plan,ensure_ascii=False),None,time.time()))
            return self.run(job)

    def submit(self, root, folders, *, enabled=True):
        if type(enabled) is not bool:
            raise ValueError('归档开关必须为布尔值。')
        folders = ArchiveFolders.from_dict(folders.to_dict())
        with self.archiver.lock, self.store.file_lock:
            for table in ('jobs', 'hierarchy_jobs', 'deletion_jobs', 'archive_setting_jobs'):
                if self.store.query(f'SELECT id FROM {table} WHERE state<>"done"'):
                    raise RuntimeError('有未完成文件任务，请先恢复，再修改归档设置。')
            if not enabled:
                # Disabling never probes an unavailable volume or reorganizes files.
                root = self.settings.root or self.settings.default_root
                self.settings.save(root, folders, enabled=False)
                self.archiver.root, self.archiver.folders = Path(root), folders
                return []
            root = validate_storage_path(root)
            layout = self.store.tag_layout()
            videos = []
            for video in self.store.query('SELECT * FROM videos WHERE archived=1 ORDER BY id'):
                tags = json.loads(video['tags'])
                archive_name(video['original_name'] or video['name'])
                self.store.resolve(video['id'])
                videos.append(dict(video=video['id'], score=video['score'], tags=tags,
                                   favorite=video['star'], done=False))
            plan = dict(archive_root=str(root), archive_folders=folders.to_dict(),
                        archive_enabled=True, layout=list(layout.values()), videos=videos)
            job = uuid.uuid4().hex
            self.store.execute('INSERT INTO archive_setting_jobs VALUES(?,?,?,?,?)',
                               (job, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))
            return self.run(job)

    def run(self, job):
        with self.archiver.lock, self.store.file_lock:
            row = self.store.query('SELECT * FROM archive_setting_jobs WHERE id=?', (job,))[0]
            plan = json.loads(row['plan'])
            if row['state'] == 'done':
                return [entry['video'] for entry in plan['videos']]
            try:
                restoring = plan.get('restore_original_names',False)
                root = None if restoring else validate_storage_path(plan['archive_root'])
                folders = ArchiveFolders.from_dict(plan['archive_folders'], legacy_job=True)
                layout = validate_layout(plan['layout'])
                errors = self.archiver.recover()
                if errors:
                    raise RuntimeError('\n'.join(errors))
                for entry in plan['videos']:
                    if entry['done']:
                        continue
                    target_root=validate_storage_path(entry['root']) if restoring else root
                    target = Archiver(self.store, target_root, self.archiver.fault, folders=folders)
                    target.submit(entry['video'], entry['score'], entry['tags'], layout=layout,
                                  folders=folders, favorite=entry['favorite'], settings_job=job,
                                  preserve_directories=restoring)
                    entry['done'] = True
                    self.checkpoint(job, plan, 'migrating')
                # Configuration becomes effective only once every video is organized.
                # If the JSON write fails, completed entries remain replayable in this job.
                if not restoring:
                    self.settings.save(root, folders, enabled=plan.get('archive_enabled', True))
                    self.archiver.root, self.archiver.folders = Path(root), folders
                self.checkpoint(job, plan, 'done')
                return [entry['video'] for entry in plan['videos']]
            except Exception as error:
                self.store.execute('UPDATE archive_setting_jobs SET error=?,updated=? WHERE id=?',
                                   (str(error), time.time(), job))
                raise

    def recover(self):
        errors = []
        for row in self.store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done" ORDER BY updated'):
            try:
                self.run(row['id'])
            except Exception as error:
                errors.append(f'{row["id"]}: {error}')
        return errors
