import zipfile

import pytest

from package_release import package_portable, package_source


def test_release_excludes_existing_library_videos_and_runtime_caches(tmp_path):
    source = tmp_path / 'installed'
    source.mkdir()
    (source / 'MoPlayer.exe').write_bytes(b'program')
    (source / '_internal').mkdir()
    (source / '_internal' / 'lib.dll').write_bytes(b'library')
    for directory in ('data', 'video', 'portable', 'Data'):
        (source / directory).mkdir(exist_ok=True)
        (source / directory / 'private').write_bytes(b'private user content')
    target = package_portable(source, tmp_path / 'release.zip')
    with zipfile.ZipFile(target) as package:
        assert set(package.namelist()) == {'MoPlayer/video/', 'MoPlayer/portable/',
                                          'MoPlayer/MoPlayer.exe', 'MoPlayer/_internal/lib.dll'}


def test_source_release_includes_modules_and_excludes_local_evidence(tmp_path):
    for directory in ('application', 'infrastructure', 'tests', 'test-evidence', 'data'):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / 'example.py').write_text('example', encoding='utf-8')
    with zipfile.ZipFile(package_source(tmp_path, tmp_path / 'source.zip')) as package:
        assert set(package.namelist()) == {'MoPlayer-source/' + name + '/example.py'
                                          for name in ('application', 'infrastructure', 'tests')}


def test_invalid_release_input_does_not_create_an_empty_zip(tmp_path):
    output = tmp_path / 'release.zip'
    with pytest.raises(ValueError):
        package_portable(tmp_path, output)
    assert not output.exists()
