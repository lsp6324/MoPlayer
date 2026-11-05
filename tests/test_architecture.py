"""Executable dependency rules: parse production code without loading Qt/VLC."""
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = {
    'appearance', 'background_work', 'file_open', 'floating_surface', 'heart_rating',
    'hover_panel', 'layout', 'library_views', 'playback_controls', 'playback_options',
    'score_editor', 'seek_notice', 'seek_slider', 'tag_editor', 'tag_popover',
    'theme', 'thumbnail_cache', 'ui', 'video_cursor', 'video_fullscreen', 'window_chrome',
}
LEGACY = {'core', 'tag_migration', 'video_delete', 'storage_settings'}
BOOTSTRAP = {'app', 'runtime'}
TOOLS = {
    'make_icon', 'package_release', 'refresh_icon', 'regenerate_shell_thumbnail',
    'register_player', 'repair_thumbnails', 'run_isolated_desktop', 'setup_explorer_thumbnails',
}
FOUNDATION_IMPORTS = {
    'ui': {'heart_rating'},
    'floating_surface': set(),
    'hover_panel': {'floating_surface'},
    'heart_rating': set(),
    'background_work': set(),
    'thumbnail_cache': {'background_work'},
}


def production_modules():
    paths = [*ROOT.glob('*.py'), *ROOT.glob('application/**/*.py'), *ROOT.glob('infrastructure/**/*.py')]
    return {'.'.join(p.relative_to(ROOT).parent.parts if p.name == '__init__.py' else p.relative_to(ROOT).with_suffix('').parts): ast.parse(p.read_text(encoding='utf-8-sig'))
            for p in paths if not p.stem.startswith('verify') and p.stem not in TOOLS}


def imports(tree, module):
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            package = module.split('.') if (ROOT.joinpath(*module.split('.')) / '__init__.py').is_file() else module.split('.')[:-1]
            prefix = package[:len(package) - node.level + 1] if node.level else []
            dependency = '.'.join([*prefix, *([node.module] if node.module else [])])
            result.add(dependency)
            result.update(dependency + '.' + alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result


def test_every_production_module_has_an_explicit_layer():
    for path in ROOT.iterdir():
        if path.is_dir() and path.name not in {'application', 'infrastructure', 'tests', 'test-evidence', 'dist', 'build', 'release', '.git', '.venv', '__pycache__'}:
            assert not list(path.rglob('*.py')), f'Classify new production package {path.name} in the architecture rules'
    unknown = set(production_modules()) - UI - LEGACY - BOOTSTRAP
    unknown = {name for name in unknown if name not in {'application', 'infrastructure'} and not name.startswith(('application.', 'infrastructure.'))}
    assert not unknown, f'Classify modules and document their ownership: {sorted(unknown)}'


def test_application_has_no_ui_native_storage_or_dynamic_import_dependency():
    modules = production_modules()
    for name, tree in modules.items():
        if name != 'application' and not name.startswith('application.'):
            continue
        dependencies = imports(tree, name)
        forbidden = {dep for dep in dependencies if dep.split('.')[0] in
                     (UI | BOOTSTRAP | {'infrastructure', 'PySide6', 'vlc', 'sqlite3', 'ctypes', 'subprocess', 'importlib'})}
        assert not forbidden, f'{name} imports {sorted(forbidden)}; inject an application protocol'
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '__import__' for n in ast.walk(tree)), name


def test_foundation_components_only_depend_downward():
    modules = production_modules()
    for name, allowed in FOUNDATION_IMPORTS.items():
        local = imports(modules[name], name) & set(modules)
        assert local <= allowed, f'{name} has forbidden upward dependencies: {sorted(local - allowed)}'
    for name, tree in modules.items():
        if name == 'infrastructure' or name.startswith('infrastructure.'):
            forbidden = imports(tree, name) & (UI | {'app', 'PySide6.QtWidgets'})
            assert not forbidden, f'{name} must not access views: {sorted(forbidden)}'


def test_production_import_graph_has_no_cycles_including_function_local_imports():
    modules = production_modules()
    graph = {name: imports(tree, name) & set(modules) for name, tree in modules.items()}
    visited, active = set(), []
    def visit(name):
        assert name not in active, 'Import cycle: ' + ' -> '.join(active + [name])
        if name in visited:
            return
        active.append(name)
        for dependency in sorted(graph[name]):
            visit(dependency)
        active.pop()
        visited.add(name)
    for name in sorted(graph):
        visit(name)


def test_views_and_application_do_not_issue_sql():
    for name, tree in production_modules().items():
        if name not in UI | {'app'} and not name.startswith('application.'):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'query', 'execute', 'executemany', 'executescript'}:
                raise AssertionError(f'{name}:{node.lineno}: route data operations through the repository')
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not re.match(r'^\s*(SELECT\s.+\sFROM\s|INSERT\s+INTO\s|UPDATE\s+\w+\s+SET\s|DELETE\s+FROM\s|CREATE\s+TABLE\s)', node.value, re.I), f'{name}:{node.lineno}: SQL belongs in a storage adapter'


def test_native_runtime_only_loads_at_explicit_bootstrap():
    for name, tree in production_modules().items():
        if name != 'runtime':
            assert 'vlc' not in imports(tree, name), f'{name} must obtain VLC through explicit runtime bootstrap'
        if name.startswith('application.'):
            assert 'core' not in imports(tree, name) or name == 'application.tag_drafts', f'{name}: add a port for legacy services'


def test_window_does_not_reclaim_application_or_thumbnail_owned_state():
    owned = {'resume', 'resume_paused', '_pending_seek', 'ended', 'last_save',
             'thumbnail_guard', 'thumbnail_processes', 'file_task_thumbnail_pause',
             'deleting_ids', 'deleted_ids'}
    for node in ast.walk(production_modules()['app']):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assert node.attr not in owned, f'app:{node.lineno}: {node.attr} belongs to its application/thumbnail owner'


def test_item_painting_never_performs_repository_queries():
    for name in UI:
        for node in ast.walk(production_modules()[name]):
            if isinstance(node, ast.FunctionDef) and node.name in {'paint', 'paintEvent'}:
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                        assert call.func.attr not in {'query', 'execute', 'video', 'resolve', 'register', 'work'}, f'{name}:{call.lineno}: prepare presentation data before painting'
