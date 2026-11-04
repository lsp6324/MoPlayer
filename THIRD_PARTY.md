# 第三方组件

本项目以可替换动态库形式分发第三方运行库，不修改 VLC、Qt 或 FFmpeg 源码。保留第三方版权与许可证；应用自有源码见源码包。

| 组件 | 版本 | 作用 | 来源与许可 |
|---|---|---|---|
| CPython | 3.12.10 x64 | 随包解释器 | https://www.python.org/downloads/release/python-31210/ ，PSF License |
| PySide6 Essentials / Shiboken6 / Qt | 6.8.3 | 原生界面 | https://download.qt.io/official_releases/QtForPython/ ，LGPLv3/GPL/商业多重许可，采用开源许可及可替换 DLL |
| python-vlc | 3.0.21203 | libVLC Python 绑定 | https://pypi.org/project/python-vlc/ ，LGPL 2.1+ |
| VLC / libVLC | 3.0.21 | 视频解码与播放 | https://download.videolan.org/pub/videolan/vlc/3.0.21/ ，VLC GPLv2+、libVLC LGPL 2.1+，具体插件遵循其各自许可证 |
| FFmpeg（imageio-ffmpeg 分发） | 7.1 essentials / gyan.dev | 内部缩略图与测试样例 | https://github.com/imageio/imageio-ffmpeg ，打包二进制启用了 GPLv3；原始构建来源见该项目发布说明和二进制 -version |
| PyInstaller | 6.16.0 | 开发打包工具 | https://pyinstaller.org/ ，GPL + bootloader exception |

VLC 对应源代码：https://download.videolan.org/pub/videolan/vlc/3.0.21/vlc-3.0.21.tar.xz 。

Qt/PySide 对应源代码：https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/ 。

FFmpeg 对应发布源码：https://ffmpeg.org/releases/ 。请以随包二进制版本与构建配置确定对应源码；发布包包含 `ffmpeg-version.txt`。涉及对外再分发时，应保留完整适用许可证及相应源码获取条件。

普通运行不安装 Shell 扩展。「系统缩略图」是明确选择后才启用的独立系统集成功能：从 [Icaros 官方发布页](https://github.com/Xanashi/Icaros/releases/tag/v3.3.6) 下载原样便携包，验证 SHA256 `18854b445420e7167b5f54696009c9ffbc0e7917da9d9a686eac71ea3c81d47a`，部署到 `E:\tools\videoplayerenv\plugins\Icaros-3.3.6`。Icaros 是免费闭源组件，原许可和 FFmpeg/dav1d 许可随官方包保留在其 `Licenses` 目录；本项目不将其当作自有开源源码。IcarosConfig GUI 不会被自动运行，也不自动安装 .NET；本功能只加载原生缩略图 DLL 及原生运行依赖。

组件需要独立 COM 注册，Windows 自己的 Shell 缓存和注册表位置由系统管理，不属于完全免安装部署。组件文件不写到 Windows、Program Files 或其他盘。播放器本身的必要播放依赖仍随便携包提供；未启用系统缩略图时，播放与软件内部缩略图仍可运行。
