"""Source relocation must preserve resources, data roots and development commands."""
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_installed_source_resources_do_not_follow_current_working_directory(tmp_path):
    script = '''
import json
from moplayer.runtime import BASE, BUNDLE
from moplayer.storage_settings import StorageSettings
from pathlib import Path
import sys
settings=StorageSettings(Path(sys.argv[1])/'unused-data')
print(json.dumps(dict(base=str(BASE),bundle=str(BUNDLE),archive=str(settings.default_root))))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=tmp_path,
                            capture_output=True, text=True, check=True, timeout=15)
    data = json.loads(result.stdout)
    assert Path(data['base']) == ROOT and Path(data['bundle']) == ROOT
    assert Path(data['archive']) == tmp_path / 'video'
    assert not (tmp_path / 'unused-data').exists()


def test_short_readme_keeps_resolvable_documentation_links():
    text = (ROOT / 'README.md').read_text(encoding='utf-8')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if not target.startswith(('https://', 'http://')):
            assert (ROOT / target).is_file(), target


def test_release_tool_can_be_invoked_as_a_module_from_another_directory(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'tools.package_release', '--help'], cwd=tmp_path,
                            capture_output=True, text=True, check=True, timeout=15)
    assert '--portable-directory' in result.stdout and '--output-directory' in result.stdout
    assert not list(tmp_path.iterdir())
