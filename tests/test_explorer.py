from pathlib import Path
from unittest.mock import Mock
import pytest
from infrastructure import explorer


def test_explorer_receives_resolved_file_as_a_single_argument_without_shell(tmp_path, monkeypatch):
    target = tmp_path / '中文 & $, 文件.png'
    target.write_bytes(b'image')
    process = Mock()
    launch = Mock(return_value=process)
    monkeypatch.setattr(explorer.subprocess, 'Popen', launch)
    assert explorer.reveal_file(target) is process
    assert launch.call_args.args[0] == ['explorer.exe', '/select,', str(target.absolute())]
    assert 'shell' not in launch.call_args.kwargs
    assert launch.call_args.kwargs['creationflags'] == explorer.subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize('name', ['missing.png', '.'])
def test_explorer_does_not_launch_for_missing_file_or_directory(tmp_path, monkeypatch, name):
    launch = Mock()
    monkeypatch.setattr(explorer.subprocess, 'Popen', launch)
    with pytest.raises(FileNotFoundError):
        explorer.reveal_file(tmp_path / name)
    launch.assert_not_called()
