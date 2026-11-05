"""Immutable directory policy; independent of files, databases and UI."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ArchiveFolders:
    tags: bool = True
    score: bool = True
    favorite: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValueError('归档分类选项必须为勾选或未勾选。')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {'tags', 'score', 'favorite'}:
            raise ValueError('归档分类设置无效。')
        return cls(**value)

    def directories(self, score, favorite, tag_paths):
        prefix = (() if not self.score else ('未评分' if score is None else f'{score}分',))
        if self.favorite:
            prefix += ('已收藏' if favorite else '未收藏',)
        return tuple(prefix + tuple(path) for path in (tag_paths if self.tags else [()]))
