# macOS DMG 构建与验收结果

日期：2026-10-18　目标：Apple Silicon / macOS 13.5+

## 交付物

- DMG：`dist/macos/归藏-1.2.2-arm64.dmg`（约 449 MB）
- SHA256：见 `dist/macos/归藏-1.2.2-arm64.dmg.sha256`
- 构建入口：`desktop/build_macos.sh`
- 安装验收：`desktop/test_installed.py`
- 数据导入：`desktop/migrate_source_data.py`

## 测试证据

### 源码回归（`tests/run_all.sh --fast`）

- 静态门禁：233 项通过，0 失败。
- 覆盖 Python 语法、内联 JS、控件、跨平台口径、XPC 环境、路由对表、打包清单、架构地图、门禁接线、沙盒隔离等。

### 桌面运行时单测（`tests/test_desktop_runtime.py`）

- 6 项通过：解释器分发（脚本 / `-c` / `-m`）、忽略旧 `.venv`、内置组件不可卸载、内置 Node/EJS、随机端口与配置保留、父进程退出清理后代。

### Rust 壳层单测（`cargo test --release`）

- 3 项通过：桥接来源校验、导出目录与同名保护、旧书库无覆盖迁移。

### 冻结后端自检（`guizang-backend --desktop-self-test`）

- 依赖导入：Playwright、genanki、pypdf、feedparser、yt-dlp、psutil 及全部业务模块。
- 证书：内置 certifi CA（121 张）。
- JavaScript 运行时：Playwright Node 与 EJS solver。
- 解释器分发：脚本、模块、子进程。
- 浏览器：Chromium 156.0.8078.4，无头 PDF 10,957 字节，有头模式可启动。
- 媒体：FFmpeg / FFprobe 8.0，音频生成与时长读取通过。

### 原生资源审计（`desktop/audit_native.py`）

- 应用内 76 个原生文件全部通过 arm64 架构、最低 macOS 版本、动态库、执行位与签名检查。
- Chromium framework 符号链接保持完整，签名有效。
- 后端 50 个原生文件通过严格签名审计。

### DMG 完整性

- `hdiutil verify` 校验通过。
- 挂载后 `ditto` 安装到独立目录，`codesign --verify --deep --strict` 通过。

### 真实安装验收（从 DMG 安装副本，仅系统 PATH）

使用独立数据根，预置损坏的 `.venv/bin/python`、`cache/tools/ffmpeg`、`cache/tools/ffprobe`，确认包内依赖优先：

| 检查项 | 结果 |
| --- | --- |
| DMG 挂载、拷贝、签名 | 通过 |
| 旧虚拟环境与缓存媒体工具被忽略 | 通过 |
| 冻结运行时依赖 | 通过 |
| 证书与 JavaScript 运行时 | 通过 |
| 内置 Chromium 无头 PDF / 有头 | 通过 |
| 内置 FFmpeg / FFprobe | 通过 |
| Playwright 视频录制（VP9，1.04 秒，3,470 字节） | 通过 |
| UI 导入 Markdown、导出 EPUB/PDF/ZIP、配置导出目录 | 通过 |
| 应用内重启保持后端监管 | 通过 |
| 宿主 SIGTERM 后端清理 | 通过 |
| 重启后数据与配置持久化 | 通过 |
| 强制退出后端清理 | 通过 |
| 强制退出 Chromium 自动化子进程回收 | 通过 |

## 数据与进程

- 默认数据目录：`~/Library/Application Support/归藏/`。
- 更新或重装只替换 `.app`，不删除 Application Support。
- 旧文稿书库复制导入，原文件保留；冲突另存 `source-imports/<时间>/conflicts/`。
- 关闭窗口、Cmd+Q、宿主信号或强制退出都会清理后端与自动化后代进程。

## 发布边界

- 本机产物使用 ad-hoc 签名，未使用 Developer ID，未经 Apple 公证。
- 在其它 Mac 上通过浏览器下载后，Gatekeeper 可能要求用户在「隐私与安全性」中手动允许；本次未绕过系统安全设置。
- 公开分发需 Developer ID 证书、Apple 公证，并在另一台 Mac 上复验。
- 内置 FFmpeg/FFprobe 启用 GPL 与额外编解码器，公开再分发需提供精确二进制对应的完整源码与构建资料；版本、构建选项、来源与 SHA256 见 `dist/desktop/media/provenance.json`。

## 复现

```bash
bash desktop/build_macos.sh
python3 desktop/test_installed.py dist/macos/归藏-1.2.2-arm64.dmg \
  --output /private/tmp/guizang-installed-acceptance
```
