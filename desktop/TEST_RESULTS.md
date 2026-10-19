# 归藏 1.2.5 界面优化版验收记录

日期：2026-10-19。实机：macOS 26.6.2、Apple Silicon。最低系统声明为 macOS 13.5，未在每个旧系统版本或其它 Mac 上逐一实测。

## 本地产物

- DMG：`dist/macos/归藏-1.2.5-arm64.dmg`，449 MiB。
- SHA256：`57261f25eb0ab9d4825fb1b5a303c9428a4408c4d784d92a8e69355da93103b5`。
- 该哈希对应本机构建；GitHub 重建产物请使用对应 Release 的 `SHA256SUMS.txt` 校验。
- 1.2.4 与 1.2.3 历史记录见 [1.2.4 验收记录](TEST_RESULTS_1.2.4.md)、[1.2.3 验收记录](TEST_RESULTS_1.2.3.md)。

## 本轮改动

设置入口移到主界面右上角；新增古典金、水墨、Notion 三套主题；本地书架改为木质书柜并支持左右切换；设置页重新分组；微信读书 Key 的命名与获取说明收口。详细说明见 [更新记录](../CHANGELOG.md)。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 完整门禁 | 291 项通过，0 失败 |
| 界面真机检查 | 本地书架翻页、六套主题、设置弹层与无横向溢出通过 |
| 原生资源 | 76 个文件；arm64、动态库、最低系统与严格签名无错误 |
| Python.framework 故障重现 | 隔离样本复现缺资源封印；签署整个 framework 后严格审计通过 |
| DMG 实际安装 | 挂载、复制安装、卸载镜像后独立启动；签名验证通过 |
| 冻结运行时 | 依赖、CA、Node/EJS、脚本分派、有头/无头浏览器、PDF、媒体处理通过 |
| 冻结笔记读取 | 异常 list/dict 标签安全收口，2 条划线及 1 条条目完整保留，使用包内模块 |
| 安装后功能 | Markdown 导入、EPUB/PDF/ZIP 导出、配置、重启及持久化通过 |
| 进程回收 | SIGTERM、强制宿主退出、真实 Chromium 后代清理通过 |
| 600 本书双向滚动 | 2202 张卡检查，透明卡 0 次 |
| 推荐与搜索封面 | 6 张推荐、12 张搜索封面全部加载，页内滚动 top=662 |
| 图床故障 | 模拟 403 后，200 次代理回退成功 |
| 写作拖动 | 归册、书内上下、跨书、散稿排序、取消、正文先保存、刷新持久化通过 |
| JavaScript | 未捕获异常 0 |
| 包内代码一致性 | 安装副本 HTML 的 SHA256 与本轮源码一致 |

滚动观测 P95 为 50.0 ms，未记录长任务。这是自动化环境观测，包含软件渲染及取样成本，不代表其它机器帧率，不承诺恒定 60 FPS。

## 沿用能力与历史问题

Python.framework 资源签名修复、冻结运行时与安装包审计沿用 1.2.4 已验证的实现。1.2.3 发布时两次 GitHub 构建曾因 framework 缺资源签名中断；现构建入口会在 Tauri 封装前修复并严格审计，隔离复现脚本仍为 `desktop/test_native_signing.py`。

## 证据与复验

- `dist/macos/test-results/1.2.5-installation-result.json`
- `dist/macos/test-results/1.2.5-runtime-self-test.json`
- `dist/macos/test-results/app-native-1.2.5.json`
- `dist/macos/test-results/source-full-1.2.5.log`

```bash
bash tests/run_all.sh
bash desktop/build_macos.sh
.build-desktop-venv/bin/python desktop/test_installed.py dist/macos/归藏-1.2.5-arm64.dmg --output /private/tmp/guizang-installed-test
.build-desktop-venv/bin/python desktop/test_native_signing.py
```

测试均使用隔离数据；微信及图床网络采用固定测试数据，云同步、AI、视频账号实际业务需另行配置验收。默认用户数据仍在 `~/Library/Application Support/归藏/`，替换 App 不清理该目录。

本包为 ad-hoc 签名，未经 Apple 公证。第三方许可证与媒体来源清单随包保留，FFmpeg 再分发义务需按精确版本确认。
