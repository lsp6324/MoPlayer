"""Shared hierarchy labels; stored selections continue to use leaf names."""


def tag_path(name, schema):
    chain, seen = [], set()
    while name and name not in seen:
        chain.append(name)
        seen.add(name)
        name = schema.get(name, {}).get('parent')
    return tuple(reversed(chain))


def tag_label(name, schema):
    return ' › '.join(tag_path(name, schema))


def tag_labels(names, schema):
    names = tuple(dict.fromkeys(names))
    ancestors = {parent for name in names for parent in tag_path(name, schema)[:-1]}
    return tuple(tag_label(name, schema) for name in names if name not in ancestors)
