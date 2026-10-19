# 归藏 1.2.4 整合版验收记录

日期：2026-10-19。实机：macOS 26.6.2、Apple Silicon。最低系统声明为 macOS 13.5，未在每个旧系统版本或其它 Mac 上逐一实测。

## 本地产物

- DMG：`dist/macos/归藏-1.2.4-arm64.dmg`，449.0 MiB。
- SHA256：`4495c0bb104ff2ecf2b721d0233c83c8a37fc123a0683cc636e23795d726bdb3`。
- 该哈希对应本机构建；GitHub 重建产物请使用对应 Release 的 `SHA256SUMS.txt` 校验。
- 1.2.3 历史记录见 [原验收记录](TEST_RESULTS_1.2.3.md)。

## 合并与审查

整合 #219–#246 共 28 个 PR，保留原提交祖先；解决架构地图和测试入口冲突，并修复审查发现的缓存失效、PNG 临时文件类型、封面并发清理及地址协议边界。详细标准轴与规格轴结论见 [PR 整合记录](../docs/PR整合验收-2026-10-19.md)。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 离线回归 | 261 项通过，0 失败 |
| 完整浏览器门禁 | 最终复验进行中；前两轮暴露的旧夹具与等待条件均已修正并单独通过 |
| 原生资源 | 76 个文件；arm64、动态库、最低系统与严格签名无错误 |
| Python.framework 故障重现 | 隔离样本复现缺资源封印；签署整个 framework 后严格审计通过 |
| DMG 实际安装 | 挂载、复制安装、卸载镜像后独立启动；签名验证通过 |
| 冻结运行时 | 依赖、CA、Node/EJS、脚本分派、有头/无头浏览器、PDF、媒体处理通过 |
| 安装后功能 | Markdown 导入、EPUB/PDF/ZIP 导出、配置、重启及持久化通过 |
| 进程回收 | SIGTERM、强制宿主退出、真实 Chromium 后代清理通过 |
| 600 本书双向滚动 | 2136 次可见卡采样，透明卡 0 次 |
| 推荐与搜索封面 | 6 张推荐、12 张搜索封面全部加载，页内滚动 top=662 |
| 图床故障 | 模拟 403 后，200 次代理回退成功 |
| 写作拖动 | 归册、书内上下、跨书、散稿排序、取消、正文先保存、刷新持久化通过 |
| JavaScript | 未捕获异常 0 |
| 包内代码一致性 | 安装副本 HTML 的 SHA256 与本轮源码一致 |

滚动观测 P95 为 50.0 ms，未记录长任务。这是自动化环境观测，包含软件渲染及取样成本，不代表其它机器帧率，不承诺恒定 60 FPS。

## 昨日发布故障与修复

两次 GitHub 构建在原生审计处发现 Python.framework 缺少资源签名，后续上传步骤均被跳过。构建入口现先对冻结后端修复无效的 framework 签名并严格审计，再进行 Tauri 封装及最终审计；保留隔离复现脚本 `desktop/test_native_signing.py`。

## 证据与复验

- `dist/macos/test-results/1.2.4-installation-result.json`
- `dist/macos/test-results/1.2.4-runtime-self-test.json`
- `dist/macos/test-results/app-native-1.2.4.json`
- `dist/macos/test-results/ui-optimizations-installed-1.2.4/ui-result.json`
- `dist/macos/test-results/source-full-1.2.4.log`

```bash
bash tests/run_all.sh
bash desktop/build_macos.sh
.build-desktop-venv/bin/python desktop/test_installed.py dist/macos/归藏-1.2.4-arm64.dmg --output /private/tmp/guizang-installed-test
.build-desktop-venv/bin/python desktop/test_native_signing.py
```

测试均使用隔离数据；微信及图床网络采用固定测试数据，云同步、AI、视频账号实际业务需另行配置验收。默认用户数据仍在 `~/Library/Application Support/归藏/`，替换 App 不清理该目录。

本包为 ad-hoc 签名，未经 Apple 公证。第三方许可证与媒体来源清单随包保留，FFmpeg 再分发义务需按精确版本确认。
