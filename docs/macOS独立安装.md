# macOS 独立安装包

新桌面包使用 Tauri 2 与 PyInstaller，复用原 Web 界面和 Python 业务代码，目标为 Apple Silicon、macOS 13.5+。用户不需要安装 Python、Node、Playwright 或 FFmpeg。

构建、安装、升级与发布边界见 [桌面构建说明](../desktop/README.md)。构建入口为 [build_macos.sh](../desktop/build_macos.sh)，实际安装验收使用 [test_installed.py](../desktop/test_installed.py)。运行 `bash desktop/build_macos.sh` 生成 `dist/macos/` 下的 DMG。最终验收记录写在 `desktop/TEST_RESULTS.md`。

## 实现与资源索引

- [冻结后端入口与进程守护](../desktop/backend_entry.py)
- [PyInstaller 规格](../desktop/guizang-backend.spec)
- [依赖与资源打包](../desktop/package_backend.py)
- [精确版本的 Python 构建依赖](../desktop/requirements-build.txt)
- [原生架构、动态库、签名与最低系统审计](../desktop/audit_native.py)
- [Tauri 原生壳与生命周期](../desktop/src-tauri/src/main.rs)
- [Tauri 资源映射与安装声明](../desktop/src-tauri/tauri.conf.json)
- [Rust 依赖](../desktop/src-tauri/Cargo.toml)
- [macOS 权限声明](../desktop/src-tauri/Info.plist)
- [JIT 签名权限](../desktop/src-tauri/Entitlements.plist)
- [桌面桥权限范围](../desktop/src-tauri/capabilities/desktop.json)
- [原界面的桥接与偏好持久化](../desktop/frontend/bridge.js)
- [启动状态页面](../desktop/frontend/index.html)
- [Node 构建依赖](../desktop/package.json)
- [安装包内说明](../desktop/INSTALL.txt)
- [源码数据无覆盖导入工具](../desktop/migrate_source_data.py)
- [桌面后端生命周期回归测试](../tests/test_desktop_runtime.py)
- [原项目回归测试入口](../tests/run_all.sh)

## 迁移边界

应用包不含个人缓存、书籍、登录状态或 API Key。默认数据位于 `~/Library/Application Support/归藏/`，升级和重装仅替换应用包。旧版文稿书库采用一次复制迁移，原文件保留；已有目标不会被覆盖。测试使用独立数据根，不接管用户的源码服务。

内置浏览器及媒体工具保留许可信息和来源清单。本机构建采用 ad-hoc 签名；公开分发仍需 Developer ID 签名、Apple 公证以及 FFmpeg 精确对应源码等许可交付。
