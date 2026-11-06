"""Read-only takeover plans and an atomic, metadata-only import workflow."""
from dataclasses import dataclass
from threading import Event
from moplayer.application.archive_folders import ArchiveFolders
from moplayer.application.file_tasks import FileTaskPolicy
from moplayer.application.operations import Operation, Outcome, Status


@dataclass(frozen=True)
class TakeoverRules:
    mode: str = 'library'
    first_level: int = 1
    last_level: int = 0
    folders: ArchiveFolders = ArchiveFolders()

    def __post_init__(self):
        if self.mode not in ('library', 'tags', 'archive'):
            raise ValueError('请选择有效的识别方式。')
        if self.mode == 'tags' and (self.first_level < 1 or self.last_level < 0 or self.last_level and self.last_level < self.first_level):
            raise ValueError('标签结束层级不能小于开始层级。')


@dataclass(frozen=True)
class TagSpec:
    name: str
    parent: str | None = None
    is_parent: bool = False


@dataclass(frozen=True)
class Markers:
    score: int | None = None
    favorite: bool = False
    tags: tuple = ()
    in_library: bool = False


@dataclass(frozen=True)
class TakeoverPath:
    path: str
    directories: tuple
    size: int
    mtime: int
    binding: tuple | None = None


@dataclass(frozen=True)
class TakeoverFile:
    identity: str
    paths: tuple[TakeoverPath, ...]
    video_id: str | None = None
    baseline: Markers | None = None


@dataclass(frozen=True)
class TakeoverItem:
    file: TakeoverFile
    markers: Markers
    labels: tuple
    conflicts: tuple = ()
    kept_existing: bool = False


@dataclass(frozen=True)
class TakeoverPlan:
    root: str
    rules: TakeoverRules
    items: tuple[TakeoverItem, ...]
    baseline_schema: tuple[TagSpec, ...]
    schema: tuple[TagSpec, ...]
    warnings: tuple = ()


def infer(directories, rules):
    """Directory meaning is explicit; filenames are never interpreted."""
    parts = list(directories)
    score, favorite, tags = None, None, ()
    if rules.mode == 'tags':
        tags = tuple(parts[rules.first_level - 1:rules.last_level or None])
    elif rules.mode == 'archive':
        order = ('favorite', 'score') if rules.folders.favorite_first else ('score', 'favorite')
        for field in order:
            if not getattr(rules.folders, field):
                continue
            if not parts:
                raise ValueError('缺少' + ('收藏' if field == 'favorite' else '评分') + '目录层。')
            name = parts.pop(0)
            if field == 'favorite':
                if name not in ('已收藏', '未收藏'):
                    raise ValueError('收藏目录应为“已收藏”或“未收藏”：' + name)
                favorite = name == '已收藏'
            else:
                if name == '未评分':
                    score = None
                elif name in tuple(f'{number}分' for number in range(11)):
                    score = int(name[:-1])
                else:
                    raise ValueError('评分目录应为 0～10 分或“未评分”：' + name)
        if rules.folders.tags:
            tags = () if parts == ['未分类'] else tuple(parts)
        elif parts:
            raise ValueError('关闭标签层后仍有额外目录，请检查识别规则。')
    return score, favorite, tags


def make_plan(root, files, baseline_schema, rules, warnings, *, validate_name):
    """Ambiguous global tag identities make all affected files explicit conflicts."""
    existing = {tag.name.casefold(): tag for tag in baseline_schema}
    proposed, problems, parsed = {}, {}, []
    for file in files:
        paths, errors = [], []
        for path in file.paths:
            try:
                score, favorite, names = infer(path.directories, rules)
                chain = []
                for name in names:
                    validate_name(name)
                    old = existing.get(name.casefold())
                    name = old.name if old else name
                    chain.append(name)
                if len(set(chain)) != len(chain):
                    raise ValueError('同一标签在路径中重复，不能作为自己的子标签。')
                for number, name in enumerate(chain):
                    proposed.setdefault(name, set()).add(chain[number - 1] if number else None)
                paths.append((score, favorite, tuple(chain)))
            except ValueError as error:
                errors.append(str(error))
        parsed.append((file, paths, errors))
    for name, parents in proposed.items():
        old = existing.get(name.casefold())
        if len(parents) != 1 or old and parents != {old.parent}:
            choices = parents | ({old.parent} if old else set())
            problems[name] = '同名标签的父级不一致：' + name + '（' + '／'.join(sorted(parent or '根层' for parent in choices)) + '）'
    # Names differing only in case share the existing global identity rule.
    spellings = {}
    for name in proposed:
        spellings.setdefault(name.casefold(), set()).add(name)
    for names in spellings.values():
        if len(names) > 1:
            for name in names:
                problems[name] = '标签名称仅大小写不同：' + '、'.join(sorted(names))
    schema = {tag.name: tag for tag in baseline_schema}
    for name, parents in proposed.items():
        if name not in problems:
            schema.setdefault(name, TagSpec(name, next(iter(parents))))
    items = []
    for file, paths, errors in parsed:
        names = {name for _, _, chain in paths for name in chain}
        errors.extend(problems[name] for name in sorted(names) if name in problems)
        scores = {score for score, _, _ in paths}
        favorites = {favorite for _, favorite, _ in paths if favorite is not None}
        if len(scores) > 1:
            errors.append('同一文件的多个入口对应不同评分。')
        if len(favorites) > 1:
            errors.append('同一文件的多个入口对应不同收藏状态。')
        parents = {name for _, _, chain in paths for name in chain[:-1]}
        tags = tuple(sorted({chain[-1] for _, _, chain in paths if chain} - parents))
        inferred = Markers(next(iter(scores)) if len(scores) == 1 else None,
                           next(iter(favorites)) if len(favorites) == 1 else False, tags, True)
        old = file.baseline
        kept = bool(old and (old.in_library or old.tags or old.score is not None or old.favorite))
        labels = tuple(' › '.join(chain) for _, _, chain in paths if chain)
        if kept and rules.mode != 'library' and (old.score, old.favorite, set(old.tags)) != (inferred.score, inferred.favorite, set(inferred.tags)):
            current = '标签：' + ('、'.join(old.tags) or '无') + '；评分：' + (str(old.score) + ' 分' if old.score is not None else '未评分')
            current += '；' + ('已收藏' if old.favorite else '未收藏')
            errors.append('识别结果与现有标记不同；保留现有标记（' + current + '）。')
        items.append(TakeoverItem(file, inferred, tuple(dict.fromkeys(labels)), tuple(dict.fromkeys(errors)), kept))
    return TakeoverPlan(root, rules, tuple(items), tuple(baseline_schema), tuple(schema.values()), tuple(warnings))


class Takeover:
    def __init__(self, service, tasks, dispatch, *, available, refresh, drafts):
        self.service, self.tasks, self.dispatch = service, tasks, dispatch
        self.available, self.refresh = available, refresh
        self.drafts = drafts
        self.scanning = None
        self._cancel = None

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()

    def preview(self, root, rules):
        if self.scanning is not None or not self.available():
            return Operation.cancelled()
        operation = self.scanning = Operation()
        token = self._cancel = Event()
        def ready(value, error):
            self.scanning, self._cancel = None, None
            status = Status.CANCELLED if token.is_set() or isinstance(error, InterruptedError) else Status.FAILED if error else Status.SUCCEEDED
            operation.finish(Outcome(status, value if status is Status.SUCCEEDED else None,
                                     error if status is Status.FAILED else None))
        try:
            self.dispatch(lambda: self.service.preview(root, rules, token), ready)
        except Exception as error:
            ready(None, error)
        return operation

    def apply(self, plan, identities, *, include_conflicts=False):
        if not self.available() or self.scanning is not None:
            return Operation.cancelled()
        identities = frozenset(identities)
        if self.drafts.dirty_ids:
            return Operation.completed(Outcome(Status.FAILED, error=ValueError('有未保存的标签草稿，请先保存后重新扫描，避免覆盖全局标签结构。')))
        source = self.tasks.run(lambda: self.service.apply(plan, identities, include_conflicts=include_conflicts),
                                policy=FileTaskPolicy(release_media=False))
        operation = Operation()
        def ready(outcome):
            if outcome.succeeded:
                try:
                    for video_id in outcome.value:
                        self.drafts.discard(video_id)
                    self.refresh(outcome.value)
                except Exception as error:
                    operation.finish(Outcome(Status.FAILED, outcome.value, error))
                    return
            operation.finish(outcome)
        source.on_finished(ready)
        return self.tasks.track(operation)
