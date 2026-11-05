"""Process-local runtime setup, isolated from the pytest Qt application."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


def test_portable_bootstrap_contains_python_qt_temporary_files_and_settings(tmp_path):
    script = '''
import json, os, tempfile
from pathlib import Path
from runtime import configure_portable
root = Path(__import__('sys').argv[1])
before = {key: os.environ.get(key) for key in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE')}
configure_portable(root)
from PySide6.QtCore import QCoreApplication, QSettings, QTemporaryFile, QDir, Qt
app = QCoreApplication([])
app.setOrganizationName('PortableTest')
app.setApplicationName('Qt')
settings = QSettings()
settings.setValue('filedialog/probe', 'portable')
settings.sync()
with tempfile.NamedTemporaryFile() as python_file:
    qt_file = QTemporaryFile()
    assert qt_file.open()
    result = dict(python=python_file.name, qt=qt_file.fileName(), settings=settings.fileName(),
                  qt_temp=QDir.tempPath(), disabled=QCoreApplication.testAttribute(Qt.AA_DisableShaderDiskCache),
                  profiles_unchanged=before == {key: os.environ.get(key) for key in before})
print(json.dumps(result))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / '便携目录')],
                            check=True, capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    report = json.loads(result.stdout)
    root = tmp_path / '便携目录'
    assert report['disabled'] and report['profiles_unchanged']
    for key in ('python', 'qt', 'settings', 'qt_temp'):
        assert Path(report[key]).is_relative_to(root / 'data'), report
    assert (root / 'portable').is_dir()


def test_setup_import_has_no_filesystem_or_profile_side_effects(tmp_path):
    script = '''
import os
from pathlib import Path
import runtime
root=Path(__import__('sys').argv[1])
runtime.BASE=root
import setup_explorer_thumbnails as setup
assert setup.ENVIRONMENT.is_relative_to(root/'data')
assert not root.exists()
'''
    subprocess.run([sys.executable, '-c', script, str(tmp_path/'not-created')],
                   check=True, capture_output=True, text=True, timeout=20)


def test_registration_command_preserves_arbitrary_portable_path():
    import base64
    from setup_explorer_thumbnails import registration_command
    script = Path("E:/解压 $目录/O'Brien (test)/register.ps1")
    command = registration_command('powershell.exe', script)
    outer = base64.b64decode(command[-1]).decode('utf-16le')
    payload = outer.split('-EncodedCommand ', 1)[1].split("'", 1)[0]
    inner = base64.b64decode(payload).decode('utf-16le')
    assert inner == "& '" + str(script).replace("'", "''") + "'"
    assert '-Verb RunAs -WindowStyle Hidden' in outer


def test_encoded_registration_payload_executes_from_space_unicode_and_apostrophe_path(tmp_path):
    import base64
    from setup_explorer_thumbnails import registration_command
    directory = tmp_path / "解压 $目录 O'Brien (test)"
    directory.mkdir()
    script = directory / 'register.ps1'
    script.write_text("[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'result.txt'), 'ok')", encoding='utf-8-sig')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    outer = base64.b64decode(registration_command(powershell, script)[-1]).decode('utf-16le')
    payload = outer.split('-EncodedCommand ', 1)[1].split("'", 1)[0]
    # Only execute the harmless payload, never elevation or real registration.
    subprocess.run([str(powershell), '-NoProfile', '-EncodedCommand', payload], check=True,
                   capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    assert (directory / 'result.txt').read_text(encoding='utf-8') == 'ok'


def test_component_download_and_extract_stay_in_selected_portable_data(tmp_path, monkeypatch):
    import hashlib
    import shutil
    import zipfile
    import setup_explorer_thumbnails as setup
    archive = tmp_path / 'official-fixture.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('64-bit/IcarosThumbnailProvider.dll', b'isolated component fixture')
    environment = tmp_path / '解压目录/data/integrations/explorer-thumbnails'
    directory = environment / 'plugins' / f'Icaros-{setup.VERSION}'
    monkeypatch.setattr(setup, 'ENVIRONMENT', environment)
    monkeypatch.setattr(setup, 'DIRECTORY', directory)
    monkeypatch.setattr(setup, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest())
    downloads = []
    def retrieve(url, target):
        downloads.append(target)
        shutil.copyfile(archive, target)
    monkeypatch.setattr(setup.urllib.request, 'urlretrieve', retrieve)
    provider = setup.prepare()
    assert provider.is_relative_to(environment) and provider.read_bytes() == b'isolated component fixture'
    assert len(downloads) == 1 and downloads[0].is_relative_to(environment)
    assert setup.prepare() == provider and len(downloads) == 1


def test_unwritable_portable_directory_fails_without_profile_fallback(tmp_path, monkeypatch):
    from runtime import configure_portable
    before = dict(os.environ)
    def denied(*args, **kwargs):
        raise PermissionError('unwritable extracted folder')
    monkeypatch.setattr(Path, 'mkdir', denied)
    with pytest.raises(PermissionError):
        configure_portable(tmp_path / 'readonly')
    assert dict(os.environ) == before


def test_overlong_frozen_process_path_cannot_fall_back_to_vlc_appdata(tmp_path, monkeypatch):
    import runtime
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(runtime.sys, 'executable', 'E:/' + 'x' * 260 + '/MoPlayer.exe')
    with pytest.raises(OSError, match='260'):
        runtime.configure_portable(tmp_path / 'not-created')
    assert not (tmp_path / 'not-created').exists()
