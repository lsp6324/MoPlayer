"""Archived-library queries and frozen playback order, independent of disk/UI."""
from dataclasses import dataclass, replace
import re


SORTS = ('name', 'score', 'played', 'added_desc', 'added_asc')


def natural_name(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', value))


@dataclass(frozen=True)
class CatalogFilter:
    search: str = ''
    favorite: str = 'all'
    score: object = 'all'
    kind: str = 'all'
    tags: tuple = ()
    untagged: bool = False
    sort: str = 'name'
    score_mode: str = 'exact'
    tag_mode: str = 'and'

    def __post_init__(self):
        if not isinstance(self.search, str) or len(self.search) > 4096:
            raise ValueError('无效搜索')
        if self.favorite not in ('all', 'yes', 'no') or self.kind not in ('all', 'video', 'image'):
            raise ValueError('无效筛选')
        if self.score not in ('all', 'none') and (type(self.score) is not int or not 0 <= self.score <= 10):
            raise ValueError('无效评分')
        if self.sort not in SORTS or type(self.untagged) is not bool:
            raise ValueError('无效排序')
        if self.score_mode not in ('exact', 'gte') or self.tag_mode not in ('and', 'or'):
            raise ValueError('无效匹配规则')
        if not isinstance(self.tags, tuple) or not all(isinstance(tag, str) for tag in self.tags):
            raise ValueError('无效标签')

    def updated(self, **values):
        return replace(self, **values)

    def to_dict(self):
        return dict(search=self.search, favorite=self.favorite, score=self.score, kind=self.kind,
                    tags=list(self.tags), untagged=self.untagged, sort=self.sort,
                    score_mode=self.score_mode, tag_mode=self.tag_mode)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('无效资料库偏好')
        data = {key: value[key] for key in cls.__dataclass_fields__ if key in value}
        if 'tags' in data:
            if not isinstance(data['tags'], list):
                raise ValueError('无效标签')
            data['tags'] = tuple(dict.fromkeys(data['tags']))
        return cls(**data)


def select_rows(rows, schema, filters, cancel):
    """Match numeric ratings and a tag group; ancestors include descendants."""
    descendants = {}
    for selected in filters.tags:
        included = {selected}
        for name in schema:
            chain, parent = set(), name
            while parent and parent not in chain:
                chain.add(parent)
                if parent == selected:
                    included.add(name)
                    break
                parent = schema.get(parent, {}).get('parent')
        descendants[selected] = included
    result, seen = [], set()
    search = filters.search.strip().casefold()
    for number, row in enumerate(rows):
        if number % 128 == 0 and cancel.is_set():
            raise InterruptedError('查询已取消')
        if not row['archived'] or row['id'] in seen:
            continue
        seen.add(row['id'])
        if search and search not in row['name'].casefold():
            continue
        if filters.favorite != 'all' and bool(row['star']) != (filters.favorite == 'yes'):
            continue
        if filters.score == 'none' and row['score'] is not None:
            continue
        if type(filters.score) is int:
            score = row['score']
            if score is None or (score < filters.score if filters.score_mode == 'gte' else score != filters.score):
                continue
        if filters.kind != 'all' and row['kind'] != filters.kind:
            continue
        tags = set(row['tag_names'])
        matches = [bool(tags.intersection(included)) for included in descendants.values()]
        if filters.untagged:
            matches.append(not tags)
        if matches and not (all(matches) if filters.tag_mode == 'and' else any(matches)):
            continue
        result.append(row)
    result.sort(key=lambda row: (natural_name(row['name']), row['id']))
    if filters.sort == 'score':
        result.sort(key=lambda row: (row['score'] is None, -(row['score'] or 0)))
    elif filters.sort == 'played':
        result.sort(key=lambda row: -row['played'])
    elif filters.sort.startswith('added_'):
        direction = -1 if filters.sort == 'added_desc' else 1
        result.sort(key=lambda row: (row.get('archived_at') is None, direction * (row.get('archived_at') or 0)))
    if cancel.is_set():
        raise InterruptedError('查询已取消')
    return result


class CatalogContext:
    """A single immutable order of IDs. Metadata/path resolution stays live."""
    root = 'catalog://queue'

    def __init__(self, rows):
        self.folders = {self.root: ([], [(row['id'], row['name']) for row in rows])}
        self.excluded = set()
        self.visible_cache = {}

    def step(self, location, direction):
        _, index = location
        files = self.folders[self.root][1]
        numbers = range(index - 1, -1, -1) if direction < 0 else range(index + 1, len(files))
        return next(((self.root, n) for n in numbers if files[n][0] not in self.excluded), None)
