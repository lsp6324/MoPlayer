import json  # 固化全局结构与各视频的迁移计划。
import threading  # 同一分类批次串行执行。
import time  # 为任务状态记录更新时间。
import uuid  # 分配独立批次身份。
from application.archive_folders import ArchiveFolders
from core import validate_layout, validate_tag, canonical_tags, tag_parts, archive_name, Archiver  # 恢复时沿用任务冻结的归档根目录。

class TagMigration:  # 在现有逐视频归档日志之上协调全局分类迁移。
    def __init__(self, store, archiver, fault=None):  # 测试可注入持久检查点故障。
        self.store, self.archiver, self.fault = store, archiver, fault  # 使用同一视频库和安全归档器。
        self.lock = threading.RLock()  # 防止同时确认两套标签结构。

    def checkpoint(self, job, plan, state):  # 完成一个视频后先记录批次进度。
        self.store.execute('UPDATE hierarchy_jobs SET state=?,plan=?,error=NULL,updated=? WHERE id=?', (state, json.dumps(plan, ensure_ascii=False), time.time(), job))  # 重启后仅继续未完成部分。
        if self.fault:  # 故障注入只用于隔离验收。
            self.fault(state)  # 正式运行不会主动中断。

    def submit(self, vid, score, tags, rows):  # 明确确认后才创建全库迁移意图。
        with self.archiver.lock, self.lock, self.store.file_lock:  # 与归档设置保持相同锁顺序。
            if self.store.query('SELECT id FROM archive_setting_jobs WHERE state<>"done"'):
                raise RuntimeError('有未完成的归档设置整理，请先恢复。')
            if self.archiver.root is None:  # 路径未设置时不留下无法执行的新批次。
                raise RuntimeError('请先在“设置 → 归档设置”选择视频存储文件夹。')  # 当前草稿和来源文件保持原状。
            if self.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done"') or self.store.query('SELECT id FROM jobs WHERE state<>"done"'):  # 不覆盖先前尚未完成的文件意图。
                raise RuntimeError('有未完成文件任务，请先通过“文件任务”恢复。')  # 已完成的中间状态仍由日志保护。
            layout = validate_layout(rows)  # 全部小类必须有有效的大类父级。
            old = self.store.tag_layout()  # 保存当前已确认的全局关系。
            removed = set(old) - set(layout)  # 草稿中删除的标签需要从所有视频移除。
            entries = []  # 收集当前视频与结构确实发生变化的其他视频。
            for video in self.store.query('SELECT * FROM videos'):  # 未归档且不是当前视频的记录无需移动。
                previous = json.loads(video['tags'])  # 保留其他视频原有选择以判断全局删除影响。
                chosen = [name for name in (tags if video['id'] == vid else previous) if name not in removed]  # 全局移除已删除标签，保留其他选择。
                metadata_only = video['id'] != vid and not video['archived']  # 未归档的其他视频只更新元数据。
                if video['id'] != vid and (chosen == previous if metadata_only else chosen == previous and tag_parts(previous, old) == tag_parts(chosen, layout)):  # 不为无关视频创建迁移任务。
                    continue  # 保留无关视频的磁盘入口和播放数据。
                target_score = score if video['id'] == vid else video['score']  # 全局分类迁移不改变其他视频的评分。
                for name in chosen:  # 在创建批次之前验证每个被选择的路径片段。
                    validate_tag(name)  # 不给非法标签留下无法恢复的已提交意图。
                    if name not in layout:  # 确认草稿必须包含相关视频使用的全局标签。
                        raise ValueError('全局标签结构缺少：' + name)  # 不猜测用户希望删除或保留的分类。
                chosen = canonical_tags(chosen, layout)  # 子类的父级从全局关系隐含获取。
                archive_name(video['original_name'] or video['name'], target_score, chosen, layout)  # 在任何文件变动前检查所有目标名称长度。
                if self.store.query('SELECT id FROM deletion_jobs WHERE video=? AND state<>"done"', (video['id'],)):  # 删除与全局迁移不能争夺同一视频。
                    raise RuntimeError('受影响视频有未完成删除，请先在文件任务中恢复。')  # 不提交不完整的结构迁移。
                entries.append({'video': video['id'], 'score': target_score, 'tags': chosen, 'done': False, 'metadata_only': metadata_only})  # 冻结归档或纯元数据更新意图。
            if not any(entry['video'] == vid for entry in entries):  # 当前身份已被外部删除时不得作用于其他视频。
                raise FileNotFoundError('当前视频记录已不存在，未提交标签修改。')  # 保留原全局结构。
            plan = {'layout': list(layout.values()), 'videos': entries, 'current': vid, 'archive_root': str(self.archiver.root), 'archive_folders': self.archiver.folders.to_dict()}  # 冻结根目录，重启后不使用后来修改的设置。
            job = uuid.uuid4().hex  # 分配本次迁移身份。
            self.store.execute('INSERT INTO hierarchy_jobs VALUES(?,?,?,?,?)', (job, 'planned', json.dumps(plan, ensure_ascii=False), None, time.time()))  # 任何文件修改之前记录恢复批次。
            return self.run(job)  # 开始逐视频安全归档。

    def run(self, job):  # 从持久计划继续中断的全局迁移。
        with self.archiver.lock, self.lock, self.store.file_lock:  # 外层归档锁先于文件身份锁。
            row = self.store.query('SELECT * FROM hierarchy_jobs WHERE id=?', (job,))[0]  # 不依赖先前进程的内存状态。
            plan = json.loads(row['plan'])  # 读取冻结的目标结构与任务进度。
            batch_archiver = Archiver(self.store, plan['archive_root'], self.archiver.fault, folders=ArchiveFolders.from_dict(plan['archive_folders']) if 'archive_folders' in plan else ArchiveFolders()) if plan.get('archive_root') else self.archiver  # 旧批次兼容原行为，新批次严格恢复到原目标。
            if row['state'] == 'done':  # 已完成批次不再次移动文件。
                return [entry['video'] for entry in plan['videos']]  # 返回需要刷新显示的身份。
            try:  # 所有失败都保持可恢复任务。
                errors = self.archiver.recover()  # 先完成可能中断的单视频归档子任务。
                if errors:  # 子任务未完成不能跳到后续视频。
                    raise RuntimeError('\n'.join(errors))  # 原文件或安全锚点仍由归档日志保护。
                layout = validate_layout(plan['layout'])  # 恢复时也校验固化的两级关系。
                for entry in plan['videos']:  # 按原计划顺序处理相关视频。
                    if entry['done']:  # 已完成的文件不重复建立和清理入口。
                        continue  # 同一视频的收藏与历史始终保留原 ID。
                    if entry.get('metadata_only'):  # 全局删除不让原本未归档的视频突然归档。
                        self.store.execute('UPDATE videos SET tags=? WHERE id=?', (json.dumps(entry['tags'], ensure_ascii=False), entry['video']))  # 仍由持久批次记录进度以便恢复。
                    else:  # 已归档视频或本次主动确认的视频同步实际目录。
                        batch_archiver.submit(entry['video'], entry['score'], entry['tags'], layout=layout, hierarchy_job=job)  # 使用冻结根目录创建入口，最后才清理旧路径。
                    entry['done'] = True  # 单视频归档真正完成后再记录完成。
                    self.checkpoint(job, plan, 'migrating')  # 断电后从下一条继续。
                with self.store.lock, self.store.db:  # 所有视频完成后一次提交公共标签结构。
                    self.store.db.execute('DELETE FROM tag_layout')  # 用完整确认草稿替换旧关系。
                    self.store.db.execute('DELETE FROM tag_parents')  # 父标签身份与全局关系一起提交。
                    self.store.db.execute('DELETE FROM tags')  # 同时移除公共字典中的已删除标签，避免重开复活。
                    for tag in layout.values():  # 未勾选的新建标签也保存到公共标签库。
                        self.store.db.execute('INSERT INTO tag_layout VALUES(?,?,?)', (tag['name'], tag['kind'], tag['parent']))  # 持久化明确的大类、小类与父级。
                        self.store.db.execute('INSERT OR IGNORE INTO tags VALUES(?)', (tag['name'],))  # 保留旧标签库的唯一名称约束。
                        if tag['is_parent']:  # 暂时没有子类的父标签也要保留身份。
                            self.store.db.execute('INSERT INTO tag_parents VALUES(?)', (tag['name'],))  # 不改变原有归档路径生成规则。
                    self.store.db.execute('UPDATE hierarchy_jobs SET state="done",error=NULL,updated=? WHERE id=?', (time.time(), job))  # 全局关系与批次成功状态原子提交。
                return [entry['video'] for entry in plan['videos']]  # 所有相关视频都完成才反馈成功。
            except Exception as error:  # 不将部分完成误报为全库同步成功。
                self.store.execute('UPDATE hierarchy_jobs SET error=?,updated=? WHERE id=?', (str(error), time.time(), job))  # 保留当前批次与真实错误。
                raise  # 界面提供明确失败和恢复入口。

    def recover(self):  # 启动或手动恢复尚未完成的全局分类迁移。
        errors = []  # 单个批次失败仍保留可见记录。
        for row in self.store.query('SELECT id FROM hierarchy_jobs WHERE state<>"done" ORDER BY updated'):  # 按确认顺序执行恢复。
            try:  # 每个批次使用原始冻结计划。
                self.run(row['id'])  # 重放具有身份校验的逐视频归档。
            except Exception as error:  # 占用、空间和数据库问题都保留待重试。
                errors.append(f'{row["id"]}: {error}')  # 不隐瞒部分迁移状态。
        return errors  # 供文件任务窗口展示恢复结果。
