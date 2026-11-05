# MoPlayer 架构与演进规则

本文件与 `AGENTS.md` 是后续开发约束。架构边界纳入 `tests/test_architecture.py`，与普通 pytest 一起执行；纯应用协议另有不加载 Qt/VLC 的测试。文档描述真实实现，尚未迁出的职责明确列为待办。

## 依赖方向

`窗口装配 / UI → application 协议与状态`；`窗口装配 → infrastructure 适配器 → 既有 Store / 文件服务`。

应用流程通过构造参数接收数据查询、任务调度和 UI 生命周期的适配入口，不反向导入具体窗口。视图只绘制、收集输入、表达意图。低层 UI 基础组件不导入布局、主题应用、主窗口或功能浮层。

| 模块 | 所有权与职责 |
|---|---|
| application/operations.py | 异步操作完成结果，以及提交草稿后继续用户动作的协调。 |
| application/tag_drafts.py | 按视频 ID 管理标签基线、工作草稿和正在提交的值；成功才确认基线。 |
| application/file_tasks.py | 文件操作的准入、开始/结束生命周期、完成结果和可恢复失败分类。 |
| application/playback.py | 播放会话中的续播、未确认跳转、终态和进度持久化规则。 |
| infrastructure/library_repository.py | 面向应用和 UI 的视频、收藏、进度、目录及任务查询/写入；集中使用 SQL。 |
| infrastructure/thumbnails.py | 缩略图磁盘缓存、FFmpeg 子进程和文件任务期间的暂停/删除屏障，不访问控件。 |
| ui.py / floating_surface.py / hover_panel.py | UI 基础图形、透明工具窗、共享悬停与焦点规则。 |
| library_views.py / thumbnail_cache.py / background_work.py | 树模型与列表绘制、Qt 图像缓存、工作线程结果交付。绘制只读取准备好的元数据。 |
| layout.py / playback_controls.py / playback_options.py / tag_popover.py | 布局、控件和功能浮层。 |
| video_fullscreen.py / video_cursor.py / window_chrome.py | 全屏展示与 Windows 原生窗口、光标适配。 |
| app.py | 程序装配、Qt 事件入口与现有列表/媒体展示的适配。 |
| runtime.py | 资源路径与显式 VLC 装配；导入 app 不加载原生运行库，创建播放器时才加载。 |
| core.py / tag_migration.py / video_delete.py | 既有文件身份、SQLite、扫描、归档、标签批次与回收恢复实现。 |

## 状态与完成协议

- `TagDrafts` 拥有草稿；编辑器保存可编辑视图，提交时复制快照。提交期间不修改已提交快照，失败不会确认基线。
- `Operation` 在应用线程完成一次。`Outcome` 明确成功、取消或失败，失败携带是否已有持久恢复任务。工作线程负责计算，Qt 调度适配负责交付结果。
- `UserActions` 协调保存与后续动作；待保存时合并选择请求，关闭请求优先。成功执行后续动作，失败或取消保留草稿并取消依赖动作。
- `FileTasks` 协调暂停缩略图、释放文件、运行文件服务和恢复媒体的统一生命周期；媒体恢复与文件任务成功分别核对。
- 文件任务开始时需要释放媒体的规则继续保留，标签分类仍可能出现短暂重载。无闪动播放需要独立验证文件句柄与归档并发方案，不能用移除 stop() 的方式绕过文件安全规则。
- `PlaybackSession` 拥有续播意图和未确认跳转；UI 时间轴只负责平滑显示，不能成为播放器实际状态的来源。
- 结束后的进度统一为零；连续相对跳转基于尚未确认的目标累加。窗口关闭、换片与周期保存使用同一进度策略。

## 后续修改检查

1. 指明业务责任模块、状态所有者、外部依赖和错误结果。
2. 先复现用户问题，再在所有权边界内改实现，移除被取代的路径。
3. 对照依赖方向检查新 import、跨模块写入、SQL 和原生 API；禁止为绕过边界使用动态导入或窗口属性注入。
4. 验证正常、失败、取消、重入和过期结果中与改动相关的情形。UI 原生行为使用独立桌面验收。
5. 更新本文的实际模块职责和剩余迁移项。运行 `pytest tests/test_architecture.py` 及相关行为测试，检查最终 diff 后再提交。

## 渐进迁移范围

既有模块允许在当前边界内继续工作，新增业务应进入对应应用模块。列表模型、窗口控件的历史属性注入，以及既有文件服务内部的数据库/锁使用需要按具体功能逐步整理；不能通过新增窗口方法、混入类或扩大遗留许可把新逻辑继续堆入这些位置。

底层文件操作已经有事务和恢复顺序。迁移查询接口时保留这一顺序，不能把同一原子过程拆为互不协调的存储对象。数据库模式发生实质变化时，需建立独立、有版本的迁移入口及旧库升级验证。

## 自动守卫与验证

`tests/test_architecture.py` 检查模块归类、应用层依赖、基础组件依赖方向、完整生产导入图（包含函数内导入）、UI SQL、绘制中的资料库访问，以及已迁出状态的所有权。不得为新增功能放宽这些规则来保留错误依赖。

GitHub workflow `.github/workflows/architecture.yml` 在 push 和 pull request 时运行架构守卫、纯应用协议及资料库适配器测试，无需安装 Qt 或 VLC。该 workflow 提供持续检查；是否将其设为受保护分支的必需检查属于仓库管理设置，当前未变更该设置。

本机完整 pytest 继续覆盖 UI、文件恢复、数据库提交失败、扫描互斥等行为。真实 UI 和 VLC 集成继续通过独立桌面检查，构建后检查打包程序。构建使用显式 `--hidden-import vlc`，对应 runtime.py 的动态原生加载入口。
