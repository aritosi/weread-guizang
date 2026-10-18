# 归藏 macOS 独立安装包

现有 `ui.html` 与 Python 业务模块继续使用。Tauri 2 只负责窗口、原生导出交互、启动和退出；PyInstaller onedir 提供完整 Python 运行环境与脚本分发。Playwright 的 Node、Chromium 与 headless shell、FFmpeg/FFprobe 都位于应用资源目录，用户不需要安装开发环境。

## 构建

目标系统为 macOS 13.5+、Apple Silicon（包内 Node 的最低版本为 13.5）。使用 Command Line Tools、Rust stable、Node/npm 和 Python 3.11+ 构建；不需要完整 Xcode。构建机首次需联网下载依赖。脚本优先使用项目 `.venv/bin/python`，可用 `GUIZANG_BUILD_PYTHON` 指定 Python。

```bash
bash desktop/build_macos.sh
```

脚本创建隔离的 `.build-desktop-venv` 并安装 `requirements-build.txt` 中的精确版本，准备与 Playwright 匹配的浏览器，构建 Python 后端和 Tauri 应用，再用系统 `hdiutil` 生成 DMG。它预检本机 SDK 可用性，默认限制 Rust 编译并发为 2，避免挤占桌面资源。JavaScript 和 Rust 依赖分别通过 `package-lock.json` 与 `Cargo.lock` 锁定。

- 安装包：`dist/macos/归藏-<版本>-arm64.dmg`，以及 `.sha256`。
- 应用：`desktop/src-tauri/target/release/bundle/macos/归藏.app`。
- 中间资源：`dist/desktop/{backend,browsers,media,licenses}`。
- 版本取自 `ui_server.py`，构建时同步至 Tauri。

本地已有浏览器仅在 revision 完全匹配时复用；媒体工具需通过 arm64、系统动态库和签名审计。`desktop/audit_native.py <资源目录> --repair-signatures` 会在资源副本中自内向外修复无效 Chromium 签名，保留有效上游签名，并给予 Chromium V8 所需 JIT 权限。原始源码目录的浏览器缓存不被修改。

Tauri 封包后，`restore_native_resources.py` 使用 `ditto` 恢复原生资源树的符号链接并重新签署外层 App，避免 framework 布局被通用资源复制器展平。最终原生审计是 DMG 构建的强制门禁。Playwright 的录像辅助程序复用经过录像测试的内置 FFmpeg，避免原辅助二进制把最低系统版本提高到 macOS 15。

## 数据与升级

默认所有可写数据都在 `~/Library/Application Support/归藏/`：`cache/`、`output/`、浏览器 profile、`desktop-web-state.json`、`logs/`。旧版已有的数据继续使用；默认用户首次启动时，把 `~/Documents/归藏/` 中缺失的书复制到新书库，保留来源、已有目标和迁移清单。不会把用户缓存、书籍、Cookie、API Key 或 `runtime.json` 打进安装包。

更新时退出应用、替换 `.app`；删除或重装 `.app` 不会删除 Application Support。不要主动删除该数据目录。

源码运行版本的数据可以在关闭旧服务后导入：

```bash
python3 desktop/migrate_source_data.py --source /path/to/weread-exporter
```

导入不删除原文件、不覆盖已有应用文件；相同路径但内容不同的源文件会保存到 `source-imports/<时间>/conflicts/`，清单记录具体位置。应先关闭旧程序，以保持浏览器数据库快照一致。

## 安装验收

```bash
python3 desktop/test_installed.py dist/macos/归藏-1.2.2-arm64.dmg \
  --output dist/macos/installed-test
```

验收会挂载 DMG、用 `ditto` 安装到单独目录、卸载磁盘镜像，给安装后的 App 设置仅含系统目录的 PATH，清除 Python/虚拟环境注入，在独立数据目录启动原生窗口和真实后端。它验证冻结依赖、CA、Node/EJS、Playwright、PDF、媒体生成、书籍导入/导出、配置与重启持久化，以及宿主退出和自动化后代清理。测试不使用真实账号、不写用户书库。日志和 JSON 证据保留在指定输出目录。

`tests/run_all.sh --fast` 包含冻结运行入口的源码回归测试。完整 GUI 关闭、剪贴板和系统目录选择应在原生窗口另行验证；测试结果见本目录的 `TEST_RESULTS.md`。

## 发布边界

当前本机产物使用 ad-hoc 签名，未使用 Developer ID 发行证书，未经 Apple 公证。严格签名验证和本机运行通过不等于其它 Mac 的 Gatekeeper 放行；公开分发需要签名身份、Apple 公证并在另一台 Mac 验证。没有通过修改系统安全设置掩盖这一差异。

资源内保留第三方许可、版本和来源。所用 FFmpeg/FFprobe 启用了 GPL 及额外编解码器，公开再分发时需要为所分发的精确二进制提供相应完整源码及构建资料；`media/provenance.json` 保存版本、构建选项、来源和 SHA256。上游应用源码许可沿用原项目说明。

微信、第三方网页、AI、云转写与同步依赖网络及用户配置。离线安装验收覆盖运行环境与本地功能；第三方账号的真实业务操作需使用用户账号另验。
