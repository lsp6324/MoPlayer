"""Immutable directory policy; independent of files, databases and UI."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ArchiveFolders:
    tags: bool = True
    score: bool = True
    favorite: bool = False
    favorite_first: bool = True  # Frozen jobs retain the directory order they started with.

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValueError('归档分类选项必须为勾选或未勾选。')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value, *, legacy_job=False):
        if not isinstance(value, dict) or set(value) not in (
                {'tags', 'score', 'favorite'}, {'tags', 'score', 'favorite', 'favorite_first'}):
            raise ValueError('归档分类设置无效。')
        return cls(**({'favorite_first': not legacy_job} | value))

    def directories(self, score, favorite, tag_paths):
        score_part = ('未评分' if score is None else f'{score}分',) if self.score else ()
        favorite_part = ('已收藏' if favorite else '未收藏',) if self.favorite else ()
        prefix = favorite_part + score_part if self.favorite_first else score_part + favorite_part
        return tuple(prefix + tuple(path) for path in (tag_paths if self.tags else [()]))
