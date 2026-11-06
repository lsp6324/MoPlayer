# 开发与验证

## 目录

```text
app.py                     源码／PyInstaller 启动入口
build.ps1                  便携包构建入口
src/moplayer/
  app.py                   窗口装配与命令行分派
  runtime.py               程序根目录、资源与原生运行时
  application/             应用流程和状态协议
  infrastructure/          文件、数据库和运行库适配
  gui/                     界面与基础组件
  core.py 等               既有底层规则
tools/                     打包和可选系统集成工具
  verify/                  独立桌面原生验收
tests/                     pytest 行为与架构检查
docs/                      使用、开发、架构与验收文档
assets/                    图标与图片
```

`dist/`、`release/`、`test-evidence/`、用户数据与缓存不进入 Git。历史截图、日志仍可保存在本地 `test-evidence/`。根目录只保留一个 Python 启动入口，新增功能应放入相应包。

## 开发环境

使用 Python 3.12 或更高版本，在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python app.py
# 可编辑安装后也可使用：python -m moplayer
```

Windows 播放还需要 VLC 3 的完整运行库目录。源码运行默认读取 `dist/MoPlayer-startup-preview/_internal/vlc`，也可通过 `MOPLAYER_VLC_DIR` 指定。源码的资源和便携数据目录始终相对项目根目录；打包后相对 EXE，不随当前工作目录变化。

`tools/bootstrap.ps1` 保留既有独立环境准备方式；脚本内的环境目录需按开发机器调整。源码 ZIP 可直接运行根目录 `app.py`；可编辑安装用于模块入口、开发工具和子进程测试。

## 自动化检查

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:MOPLAYER_VLC_DIR = 'C:/path/to/vlc'
python -m pytest tests -vv
```

pytest 的源码路径配置位于 `pyproject.toml`。架构检查解析完整源码包，并把物理包名归一成原逻辑模块名，继续检查层间依赖、导入环、SQL、窗口职责和媒体宿主边界；不通过路径重排放宽许可。

原生 UI／VLC 验收必须使用独立 Windows 桌面：

```powershell
$env:QT_SCALE_FACTOR = '1'
python -m tools.run_isolated_desktop python app.py --catalog-test test-evidence/ui-refresh/native-catalog
$env:QT_SCALE_FACTOR = '1.5'
python -m tools.run_isolated_desktop python app.py --takeover-test test-evidence/ui-refresh/native-takeover-150
```

不要直接在用户桌面运行带系统指针操作的验收脚本。产物和独立样例放在 `test-evidence/ui-refresh/`，不使用用户数据库。

## 打包

```powershell
./build.ps1 -EnvironmentRoot C:/build/moplayer -PythonExecutable C:/path/to/python.exe -VlcDirectory C:/path/to/vlc -PortableDirectory C:/build/candidate
python -m tools.package_release --portable-directory C:/build/candidate --output-directory release
```

构建显式收集 `src/moplayer`、验收模块、VLC、FFmpeg、资源和许可证；源码包包含新目录结构，不包含用户数据、验收证据、字节码和可编辑安装元数据。确认构建成功后，再在独立桌面验收候选包。更新现用预览需要保留 `data`、`video`、`portable`，核对数据哈希；播放器运行时先请求用户正常退出。

开发约束见 [AGENTS.md](../AGENTS.md)，依赖边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，历史验收见 [TEST_RESULTS.md](TEST_RESULTS.md)。历史记录中未带目录前缀的旧脚本名，按本页目录映射理解。
