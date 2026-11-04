import hashlib  # 为交付包生成完整性校验值。
import zipfile  # 生成 Windows 标准 ZIP 便携与源码包。
from pathlib import Path  # 使用明确的项目内交付路径。

BASE = Path(__file__).parent  # 定位完整源码目录。
OUTPUT = BASE / 'release'  # 压缩包交付到独立输出目录。
OUTPUT.mkdir(exist_ok=True)  # 保留已有文件且确保输出目录存在。
portable = BASE / 'dist' / 'MoPlayer'  # 使用已测试的目录部署产物。
archives = []  # 汇总本次产生的文件以计算摘要。
with zipfile.ZipFile(OUTPUT / 'MoPlayer-portable-win64.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:  # 生成包含 EXE 与所有运行库的便携包。
    for path in sorted(portable.rglob('*')):  # 按稳定顺序收集完整目录部署。
        if path.is_file() and 'data' not in path.relative_to(portable).parts:  # 不将用户数据库或测试历史带入交付包。
            package.write(path, Path('MoPlayer') / path.relative_to(portable))  # 解压后保留一层清晰的应用目录。
archives.append(OUTPUT / 'MoPlayer-portable-win64.zip')  # 登记便携交付物。
with zipfile.ZipFile(OUTPUT / 'MoPlayer-source.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as package:  # 生成完整可构建源码包。
    paths = list(BASE.glob('*.py')) + list(BASE.glob('*.ps1')) + list(BASE.glob('*.md')) + list(BASE.glob('*.txt')) + [BASE / 'LICENSE']  # 收集应用、构建、文档和版本清单。
    for directory in ['tests', 'third_party_licenses', 'test-evidence', 'assets']:  # 加入测试、图标源素材与授权证据目录。
        paths.extend(path for path in (BASE / directory).rglob('*') if path.is_file() and '__pycache__' not in path.parts)  # 排除解释器缓存。
    for path in sorted(set(paths)):  # 去重后以稳定顺序写入。
        package.write(path, Path('MoPlayer-source') / path.relative_to(BASE))  # 源码包解压到独立根目录。
archives.append(OUTPUT / 'MoPlayer-source.zip')  # 登记源码交付物。
lines = []  # 构建可供用户校验的摘要清单。
for path in archives:  # 对最终 ZIP 而非中间目录计算摘要。
    with path.open('rb') as stream:  # 分块读取避免占用大量内存。
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()  # 计算完整文件 SHA256。
    with zipfile.ZipFile(path) as package:  # 交付前重新检查 ZIP 内部 CRC。
        if package.testzip() is not None:  # 任意成员损坏都应终止发布。
            raise RuntimeError(f'压缩包校验失败：{path}')  # 不交付损坏档案。
    lines.append(f'{checksum}  {path.name}')  # 使用通用摘要清单格式。
    print(f'{path.name}: {path.stat().st_size} bytes')  # 输出实际交付体积。
(OUTPUT / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')  # 保存包的完整性校验清单。
