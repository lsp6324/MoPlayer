"""Executable dependency rules: parse production code without loading Qt/VLC."""
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = {
    'catalog_panel', 'catalog_filter_popup', 'catalog_delegate', 'media_badges',
    'action_notice', 'media_context_menu',
    'accent_colors', 'color_picker', 'appearance_dialog', 'archive_settings_dialog', 'appearance', 'background_region', 'background_work', 'file_open', 'floating_surface', 'heart_rating',
    'hover_panel', 'folder_navigation', 'image_view', 'layout', 'library_view', 'library_views', 'media_header', 'player_view', 'playback_controls', 'playback_options',
    'rating_editor', 'score_editor', 'seek_notice', 'seek_slider', 'tag_editor', 'tag_popover', 'tag_flow',
    'theme', 'thumbnail_cache', 'ui', 'video_cursor', 'video_fullscreen', 'window_chrome', 'wordmark',
}
LEGACY = {'core', 'tag_migration', 'video_delete', 'storage_settings'}
BOOTSTRAP = {'app', 'runtime'}
TOOLS = {
    'make_icon', 'package_release', 'refresh_icon', 'regenerate_shell_thumbnail',
    'register_player', 'repair_thumbnails', 'run_isolated_desktop', 'setup_explorer_thumbnails',
}
FOUNDATION_IMPORTS = {
    'action_notice': {'floating_surface'},
    'folder_navigation': {'ui'},
    'background_region': set(),
    'accent_colors': set(),
    'color_picker': {'accent_colors'},
    'ui': {'heart_rating'},
    'floating_surface': set(),
    'hover_panel': {'floating_surface'},
    'heart_rating': set(),
    'rating_editor': {'heart_rating'},
    'media_header': {'heart_rating', 'ui', 'media_badges'},
    'media_badges': {'ui'},
    'background_work': set(),
    'thumbnail_cache': {'background_work'},
    'image_view': set(),
    'wordmark': set(),
    'tag_flow': set(),
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


def test_portable_paths_are_configured_before_qapplication_without_machine_paths():
    main = next(node for node in production_modules()['app'].body
                if isinstance(node, ast.FunctionDef) and node.name == 'main')
    calls = [node for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    configure = next(node for node in calls if node.func.id == 'configure_portable')
    application = next(node for node in calls if node.func.id == 'QApplication')
    assert configure.lineno < application.lineno, 'Configure portable runtime before initializing Qt'
    for name in ('runtime.py', 'storage_settings.py', 'setup_explorer_thumbnails.py', 'register_thumbnail_component.ps1'):
        text = (ROOT / name).read_text(encoding='utf-8-sig')
        assert not re.search(r'(?i)[a-z]:[\\/]+(?:tools|users|codex)[\\/]+', text), f'{name}: remove machine-specific runtime paths'


def test_window_does_not_reclaim_application_or_thumbnail_owned_state():
    owned = {'resume', 'resume_paused', '_pending_seek', 'ended', 'last_save',
             'thumbnail_guard', 'thumbnail_processes', 'file_task_thumbnail_pause',
             'deleting_ids', 'deleted_ids', 'browsing', 'video_details',
             'scan_cancel', 'scan_serial', 'navigation_cancel', 'navigation_pending',
             'tree', 'current_folder', '_folder_positions', 'folder_navigation', 'sidebar', 'sidebar_mode', 'sidebar_list', 'sidebar_tabs',
             'folder_label', 'file_count', 'library_stack', 'cancel_button', 'remove_favorite',
             'clear_history_button'}
    modules = production_modules()
    for name in ('app', 'layout'):
        for node in ast.walk(modules[name]):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                assert node.attr not in owned, f'{name}:{node.lineno}: {node.attr} belongs to its application/library/thumbnail owner'


def test_library_controls_and_task_state_stay_with_their_owners():
    modules = production_modules()
    for name in ('layout', 'app'):
        for node in ast.walk(modules[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {'DropTree', 'TreeModel', 'DropList', 'FolderModel', 'FolderNavigation', 'VideoListModel', 'VideoDelegate', 'ScanButton'}, f'{name}:{node.lineno}: library controls belong to LibraryView'
    for name in ('library_view', 'library_views'):
        dependencies = imports(modules[name], name)
        assert not any(dep.split('.')[0] in {'core', 'infrastructure', 'threading'} for dep in dependencies), f'{name}: use the library application protocol'


def test_player_widgets_and_rendering_are_not_owned_by_window_or_layout():
    controls = {'surface', 'player_header', 'header', 'now', 'metadata', 'media_badge',
                'player_empty', 'empty_import', 'image_view', 'wordmark', 'playback_panel', 'seekbar', 'time_label',
                'control_row', 'transport_buttons', 'play_button', 'playback_options',
                'volume', 'volume_button', 'speed_button', 'sidebar_toggle', 'fullscreen_button',
                'classify_bar', 'classify_buttons', 'tags_button', 'rating_button', 'favorite_button',
                'video_fullscreen', 'seek_notice'}
    modules = production_modules()
    for name in ('app', 'layout'):
        for node in ast.walk(modules[name]):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {'self', 'window'}:
                assert node.attr not in controls, f'{name}:{node.lineno}: {node.attr} belongs to PlayerView'
            if isinstance(node, ast.FunctionDef):
                assert node.name not in {'sync_play_button', 'preview_seek', 'seek_slider'}, f'{name}:{node.lineno}: remove the old rendering/slider path'
    assert not ({'PlaybackControls', 'PlaybackOptions', 'PlaybackTimeline', 'VideoFullscreen', 'SeekNotice'} &
                {node.func.id for node in ast.walk(modules['layout']) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}), 'Build player children inside PlayerView'


def test_player_presentation_has_no_backend_or_repository_access():
    modules = production_modules()
    for name in ('media_header', 'player_view', 'playback_options', 'video_fullscreen', 'seek_notice', 'image_view', 'wordmark', 'action_notice'):
        dependencies = imports(modules[name], name)
        assert not any(dep.split('.')[0] in {'app', 'core', 'infrastructure', 'runtime', 'vlc', 'sqlite3'} for dep in dependencies), name
        for node in ast.walk(modules[name]):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {'catalog', 'store', 'player'}, f'{name}:{node.lineno}: inject presentation data and emit an intent'
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'audio_set_mute', 'audio_set_volume', 'get_state', 'get_time', 'get_length', 'set_media', 'set_hwnd', 'set_pause'}, f'{name}:{node.lineno}: native playback belongs to the adapter'


def test_item_painting_never_performs_repository_queries():
    for name in UI:
        for node in ast.walk(production_modules()[name]):
            if isinstance(node, ast.FunctionDef) and node.name in {'paint', 'paintEvent'}:
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                        assert call.func.attr not in {'query', 'execute', 'video', 'resolve', 'register', 'work'}, f'{name}:{call.lineno}: prepare presentation data before painting'


def test_file_workflow_decisions_are_not_reintroduced_into_window_callbacks():
    window = next(node for node in production_modules()['app'].body
                  if isinstance(node, ast.ClassDef) and node.name == 'Window')
    obsolete = {'apply_tags', 'archive', 'retry_jobs', '_delete_video', 'after_deleted_current',
                '_file_work', '_report_file_result', 'refresh_names'}
    for method in window.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        assert method.name not in obsolete, f'{method.name}: use the application workflow, not a forwarding window API'
        if method.name == '__init__':
            continue  # Explicit service ports are connected at composition.
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'submit', 'recover'}, f'app:{node.lineno}: submit/recover belongs to its application workflow'
                if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'file_tasks':
                    assert node.func.attr != 'run', f'app:{node.lineno}: file task admission belongs to the workflow'
                if method.name == '_file_notice':
                    assert node.func.attr not in {'video', 'videos', 'pending_tasks', 'reconcile', 'refresh_deleted', 'start'}, f'app:{node.lineno}: render the workflow result without deciding recovery or playback'


def test_archive_settings_view_uses_only_explicit_application_ports():
    tree = production_modules()['archive_settings_dialog']
    dependencies = imports(tree, 'archive_settings_dialog')
    assert not any(dep.split('.')[0] in {'app', 'core', 'storage_settings', 'infrastructure', 'vlc', 'sqlite3'} for dep in dependencies)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {'storage', 'archiver', 'store', 'catalog', 'work', 'file_tasks'}, 'Settings view submits values; the workflow owns migration and persistence'


def test_filename_editor_cannot_rename_files_or_reach_storage_directly():
    tree=production_modules()['media_header']
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in {'rename','replace','unlink','link','stat','exists','open','submit','recover'}, 'The inline editor submits presentation intent through its injected port'


def test_file_workflows_publish_reconciled_completion_to_navigation():
    for name,tree in production_modules().items():
        if not name.startswith('application.') or name=='application.file_results':
            continue
        parents={child:parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='complete_file_task':
                parent=parents[node]
                assert isinstance(parent,ast.Call) and isinstance(parent.func,ast.Attribute) and parent.func.attr=='track', f'{name}: navigation must await reconciled completion'
