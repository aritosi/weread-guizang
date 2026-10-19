# 归藏 1.2.3 优化版验收记录

日期：2026-10-18。实机：macOS 26.6.2、Apple Silicon。最低系统声明：macOS 13.5；未在每个旧系统版本或其它 Mac 上逐一实测。

## 交付

- 安装包：`dist/macos/归藏-1.2.3-arm64.dmg`，448.4 MiB。
- SHA256：`de164560b09d8c9f7d184312033196a0ed1bfb1e94d3058513e4570b2a8b5c6a`。
- 构建入口：`desktop/build_macos.sh`；安装验收：`desktop/test_installed.py`。
- 本轮 UI 验收：`desktop/test_ui_optimizations.py`。

## 本轮改动

1. 书架卡片保持绘制，移除离开视口后透明化和回滚重播动画；只保留打开的操作条的合成提示，停止装饰背景的持续动画。
2. 采用 IntersectionObserver 预取视口附近的封面，覆盖页内滚动区域；推荐和书城搜索在挂载卡片后启动封面加载。移除加载骨架时逐个清理，避免空卡残留。
3. 远端封面失败后退到有安全校验的腾讯图床代理。代理提供本地缓存、同图并发合并、失败短暂退避和图像大小/格式检查。
4. 写作文章支持拖入书本、书内上下排序、跨书移动、移回未归册及散稿排序。一次原子操作保存归属和顺序；拖动取消不保存，编辑后立刻拖动会先保存正文。修复失焦自动保存重绘文章行会打断拖动的问题。
5. 状态轮询合并重复请求，后台页面暂停常规轮询；书架 ID 索引缓存，列表仅插入变更节点；写作列表内容未变时不重建。
6. 回归脚本的语法检查排除构建产物，防止 compileall 在已签名 App 内生成字节码、破坏资源签名。

## 验收结果

| 验收 | 结果 |
| --- | --- |
| `tests/run_all.sh --fast` | 234 项门禁通过，0 失败 |
| 封面代理新回归 | 8 项通过，覆盖缓存、并发合并、失败退避、限流、大小/类型与 URL 校验 |
| 写作后端 | 真实 HTTP 验证；包含线程及跨进程并发移动，章节未丢失、正文不改写 |
| 原生资源审计 | 76 个原生文件：架构、最低系统、动态库、执行位与签名无错误 |
| DMG | hdiutil 校验通过；挂载后复制安装、卸载镜像再运行，严格签名通过 |
| 冻结运行时 | Python、CA、Node/EJS、Playwright 有头/无头、PDF、FFmpeg/FFprobe 全部通过 |
| 安装后本地功能 | Markdown 导入、EPUB/PDF/ZIP 导出、配置、重启和数据保留通过 |
| 进程退出 | SIGTERM、强制退出及真实 Chromium 后代回收通过 |
| 新版 UI：600 本书 | 2028 次可见卡检查，透明卡 0 次 |
| 推荐、搜书 | 6 张推荐、12 张搜索封面全部加载，页内滚动实际 scrollTop=662 |
| 封面网络故障 | 模拟部分 CDN 403，200 次代理回退恢复，未残留加载骨架 |
| 鼠标拖动 | 拖入、向上/向下、跨书、散稿排序、取消、未保存正文、刷新持久化均通过 |
| JavaScript | 未捕获异常 0 |
| 产物一致性 | 已安装 App 的 HTML SHA256 与最终 ui.html 一致 |

UI 验收使用真实 Chromium、真实鼠标事件和真实写作后端，微信数据及图床响应使用固定测试数据，避免修改真实账号和书库。第三方账号业务与真实网络速度不属于本轮固定数据验收的保证范围。

## 同机滚动观察

相同 600 本测试数据，旧版可见卡检查中透明卡 996 次；新版为 0。旧版记录 3 次长任务，新版为 0 次。安装副本采样帧间隔 P95 约 50.1 ms。此数据来自浏览器自动化环境，包含测试取样和软件渲染成本，不代表所有机器的帧率，也不宣称恒定 60 FPS。

## 证据

- `dist/macos/test-results/source-regression-1.2.3.log`
- `dist/macos/test-results/app-native-1.2.3.json`
- `dist/macos/test-results/1.2.3-installation-result.json`
- `dist/macos/test-results/ui-optimizations-baseline/ui-result.json`
- `dist/macos/test-results/ui-optimizations-installed/ui-result.json` 及同目录界面截图

## 重建与复验

```bash
bash desktop/build_macos.sh
python3 desktop/test_installed.py dist/macos/归藏-1.2.3-arm64.dmg --output /private/tmp/guizang-installed-test
.build-desktop-venv/bin/python desktop/test_ui_optimizations.py --backend /path/to/归藏.app/Contents/Resources/backend/guizang-backend --browser-path /path/to/归藏.app/Contents/Resources/browsers
```

默认用户数据仍在 `~/Library/Application Support/归藏/`。升级替换 App，不清理数据目录。本次安装和写入测试使用独立临时目录。

本包为 ad-hoc 签名，未做 Apple 公证；公开分发仍需发行签名及公证。第三方许可证与媒体来源清单保留在包内，FFmpeg 的再分发条件见 `media/provenance.json` 及许可证。
