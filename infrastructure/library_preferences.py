"""Portable browsing preferences, atomically saved without touching media."""
import json
import os
from pathlib import Path
from application.catalog import CatalogFilter


class LibraryPreferences:
    def __init__(self, directory):
        self.path = Path(directory) / 'library.json'

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            page = data['page']
            if page not in ('files', 'catalog', 'videos', 'stars'):
                raise ValueError('无效页面')
            view = data.get('view', 'list')
            return page, CatalogFilter.from_dict(data['filters']), view if view in ('list', 'grid') else 'list'
        except (OSError, ValueError, KeyError, TypeError):
            return 'files', CatalogFilter(), 'list'

    def save(self, page, filters, view='list'):
        if view not in ('list', 'grid'):
            raise ValueError('无效库视图')
        temporary = self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(dict(page=page, filters=filters.to_dict(), view=view),
                                        ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
