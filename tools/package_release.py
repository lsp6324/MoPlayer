"""Create release archives without bundling local user data or caches."""
import argparse
import hashlib
from pathlib import Path
import zipfile


BASE = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORIES = {'data', 'video', 'portable', '__pycache__'}


def package_portable(directory, output):
    directory, output = Path(directory), Path(output)
    if not (directory / 'MoPlayer.exe').is_file() or not (directory / '_internal').is_dir():
        raise ValueError('请选择包含 MoPlayer.exe 和 _internal 的已验证程序目录。')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for name in ('video', 'portable'):
            package.writestr('MoPlayer/' + name + '/', b'')
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(directory)
            if relative.parts[0].casefold() in RUNTIME_DIRECTORIES or path.is_symlink():
                continue
            if path.is_file():
                package.write(path, Path('MoPlayer') / relative)
    verify_zip(output)
    return output


def package_source(directory, output):
    directory, output = Path(directory), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = [path for pattern in ('*.py', '*.ps1', '*.md', '*.txt', 'LICENSE', '.gitignore')
             for path in directory.glob(pattern)]
    paths.extend(directory.glob('*.toml'))
    for name in ('src', 'tools', 'tests', 'docs', 'assets', 'third_party_licenses', '.github'):
        paths.extend((directory / name).rglob('*'))
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(set(paths)):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and not any(part.endswith('.egg-info') for part in path.parts):
                package.write(path, Path('MoPlayer-source') / path.relative_to(directory))
    verify_zip(output)
    return output


def verify_zip(path):
    with zipfile.ZipFile(path) as package:
        if package.testzip() is not None:
            raise RuntimeError(f'压缩包校验失败：{path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable-directory', type=Path, default=BASE / 'dist' / 'MoPlayer-startup-preview')
    parser.add_argument('--output-directory', type=Path, default=BASE / 'release')
    arguments = parser.parse_args()
    outputs = [package_portable(arguments.portable_directory, arguments.output_directory / 'MoPlayer-portable-win64.zip'),
               package_source(BASE, arguments.output_directory / 'MoPlayer-source.zip')]
    lines = []
    for path in outputs:
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        lines.append(f'{checksum}  {path.name}')
        print(f'{path.name}: {path.stat().st_size} bytes')
    (arguments.output_directory / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
