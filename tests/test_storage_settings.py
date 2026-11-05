"""Portable defaults and legacy preferences without touching real media."""
import json
import shutil
from unittest.mock import patch

import pytest

from application.archive_folders import ArchiveFolders
from storage_settings import StorageSettings


def test_new_install_defaults_to_video_without_creating_files(tmp_path):
    data = tmp_path / '解压目录' / 'data'
    settings = StorageSettings(data)
    assert settings.root == data.parent / 'video'
    assert settings.folders == ArchiveFolders()
    assert not data.parent.exists()


def test_saved_default_follows_extracted_folder_and_retains_folder_choices(tmp_path):
    original, moved = tmp_path / 'old', tmp_path / '新位置'
    settings = StorageSettings(original / 'data')
    policy = ArchiveFolders(False, False, True)
    settings.save(settings.root, policy)
    assert json.loads(settings.file.read_text(encoding='utf-8'))['archive_root'] == 'video'
    shutil.copytree(original, moved)
    restored = StorageSettings(moved / 'data')
    assert restored.root == moved / 'video'
    assert restored.folders == policy


def test_existing_explicit_location_is_never_changed_on_upgrade(tmp_path):
    settings = StorageSettings(tmp_path / 'data')
    settings.save(tmp_path / '自选目录')
    before = settings.file.read_bytes()
    restored = StorageSettings(settings.file.parent)
    assert restored.root == tmp_path / '自选目录'
    assert restored.file.read_bytes() == before


@pytest.mark.parametrize('value', ['../video', 'other', '', 1, None])
def test_corrupt_or_unsupported_relative_path_is_not_silently_replaced(tmp_path, value):
    data = tmp_path / 'data'
    data.mkdir()
    config = data / 'storage.json'
    config.write_text(json.dumps({'archive_root': value}), encoding='utf-8')
    before = config.read_bytes()
    settings = StorageSettings(data)
    assert settings.root is None and settings.error
    assert config.read_bytes() == before and not (tmp_path / 'video').exists()


def test_failed_default_settings_save_preserves_existing_location(tmp_path):
    settings = StorageSettings(tmp_path / 'data')
    old = tmp_path / 'custom'
    settings.save(old)
    before = settings.file.read_bytes()
    with patch('storage_settings.os.replace', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            settings.save(settings.default_root)
    assert settings.root == old and settings.file.read_bytes() == before
