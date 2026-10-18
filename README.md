<div align="center">
  <img src="docs/assets/readme-hero.svg" alt="归藏 · 让阅读归于一处，让想法生长成文" width="100%">
  <p>
    <a href="https://github.com/aritosi/weread-guizang/releases/tag/v1.2.3"><img alt="版本 1.2.3" src="https://img.shields.io/badge/归藏-1.2.3-2860A4?style=flat-square"></a>
    <img alt="macOS 13.5 及以上" src="https://img.shields.io/badge/macOS-13.5%2B-58677A?style=flat-square">
    <img alt="Apple Silicon" src="https://img.shields.io/badge/芯片-Apple_Silicon-58677A?style=flat-square">
  </p>
  <p><strong>微信读书导出 · 本地阅读 · 知识整理 · 写作</strong></p>
  <p>把书籍、划线、网页、订阅和视频笔记收进自己的书库，从阅读走到表达。</p>
  <p>
    <a href="https://github.com/aritosi/weread-guizang/releases/download/v1.2.3/归藏-1.2.3-arm64.dmg"><strong>下载 macOS 1.2.3</strong></a> ·
    <a href="https://github.com/aritosi/weread-guizang/releases/latest">全部发布与校验文件</a> ·
    <a href="docs/macOS独立安装.md">安装文档</a> ·
    <a href="CHANGELOG.md">更新记录</a>
  </p>
</div>

归藏运行在本机，将微信读书中有权阅读的内容导出为 Markdown，也能导入 EPUB、PDF、TXT 和 Markdown。阅读、划线、剪藏、思维导图与写作共享同一个本地工作空间，服务仅监听 `127.0.0.1`。

> **当前成品：1.2.3 · macOS 13.5+ · Apple Silicon · 448.4 MiB。** 包内已包含 Python、Node、Chromium、FFmpeg/FFprobe，用户无需另装这些运行环境。当前采用 ad-hoc 签名，**未经 Apple 公证**；其他 Mac 上可能受到 Gatekeeper 拦截，安装前请了解这一发布状态。

## 看看归藏

<p align="center"><img src="docs/shots/home.png" alt="归藏书架：本地管理书籍与阅读内容" width="960"></p>

<table>
  <tr>
    <td width="50%"><img src="docs/shots/reader.png" alt="阅读器：正文、目录与笔记"><br><sub>阅读器 · 在正文旁留下自己的理解</sub></td>
    <td width="50%"><img src="docs/shots/pick.png" alt="为我推荐：发现书籍并加入微信读书书架"><br><sub>为我推荐 · 发现下一本想读的书</sub></td>
  </tr>
  <tr>
    <td><img src="docs/shots/search.png" alt="书城搜索：搜索微信读书书籍"><br><sub>书城搜索 · 找书、查看详情、加入书架</sub></td>
    <td><img src="docs/shots/mindmap.png" alt="思维导图：整理阅读结构"><br><sub>思维导图 · 把读过的内容组织起来</sub></td>
  </tr>
</table>

## 从读书到写作

| 模块 | 可以做什么 |
| --- | --- |
| **微信读书** | 微信读书会员可整本导出 Markdown，图文按阅读顺序排列、断点续传；导出 EPUB/PDF、划线与想法、Anki 卡包；书城搜索与加入书架 |
| **本地书库** | 导入 Markdown、TXT、EPUB、PDF；文件夹、标签与排序；瀑布流与叠卡；阅读位置、批注和阅读计划 |
| **网页剪藏** | 解析微信公众号、知乎、小红书和 X 的内容，保存正文、入库阅读并导出 |
| **订阅阅读** | RSS、Atom、JSON Feed；三栏阅读、标签和搜索；OPML 导入导出、单篇入库 |
| **视频笔记** | 哔哩哔哩、YouTube 音频转写；编辑分段、重建章节、导出 SRT；结合 AI 整理笔记和导图 |
| **笔记与导图** | 汇集微信读书与本机划线；随机漫步；括号图、辐射图、鱼骨图、概念图及 SVG 导出；自由画板 |
| **便签与写作** | 导入 flomo 导出包、标签检索、富文本便签；书与章节管理、拖动归册、版本历史，导出 Markdown/EPUB/PDF/图片 |
| **AI 与 Agent** | 阅读小结、翻译、查词、问答、辅助写作；通过 MCP 与配套 Skills 接入自己的 Agent |

AI 与云转写需要自备接口、密钥及相应额度；本地导入、阅读和写作无需配置 AI。第三方内容获取受平台、网络和账号权限影响。

## 1.2.3，打磨每天会用到的交互

- **书架回滚更稳定。** 卡片离开视口后继续保持绘制，移除回滚时的透明化与动画重播，减少不必要的 GPU 合成层和持续背景动画。
- **封面能补齐。** 推荐、搜书结果挂载后即触发封面加载；远端图床失败时使用带校验和本地缓存的代理回退，清理加载骨架。
- **写作整理更完整。** 支持拖入书本、书内上下排序、跨书移动、移回散稿及散稿排序；拖动取消不保存，编辑后拖动先保存正文，刷新后保留归属与顺序。

本轮记录：**234 项回归门禁通过、76 个原生文件审计通过**；DMG 复制安装后，包内运行时、本地导入导出、重启持久化与进程回收通过。600 本书的双向滚动测试中，2028 次可见卡采样未发现透明卡。

上述 UI 测试使用真实浏览器、鼠标事件与本地后端，微信数据和图床故障使用固定测试数据；不代表所有第三方账号业务已验证，也不承诺恒定帧率。方法、环境和完整结果见 [验收记录](desktop/TEST_RESULTS.md)。

## 安装与第一次使用

1. 下载 [归藏-1.2.3-arm64.dmg](https://github.com/aritosi/weread-guizang/releases/download/v1.2.3/归藏-1.2.3-arm64.dmg)，在 [Release 页面](https://github.com/aritosi/weread-guizang/releases/tag/v1.2.3) 获取对应校验文件。
2. 打开 DMG，将 **归藏.app** 拖入“应用程序”，弹出磁盘镜像后从“应用程序”启动。
3. 导入一本本地书即可开始阅读；需要微信读书功能时，再在设置中连接账号并配置对应接口。

首次启动无需下载 Python、Chromium 或媒体工具。当前包未经 Apple 公证；若系统阻止打开，请先核对来源与校验文件，并参考系统“隐私与安全性”中的提示判断是否继续。完整说明见 [macOS 独立安装](docs/macOS独立安装.md)。

不同设置负责不同用途，按需填写即可：

| 配置 | 使用场景 |
| --- | --- |
| **微信读书账号 / 数据接口 Key** | 账号登录用于网页端取书与加入书架；数据接口用于书架、划线、阅读信息等微信读书数据功能，按界面提示配置 |
| **阅读 AI** | 章节/全文小结与 AI 思维导图，使用独立的兼容 OpenAI 接口配置 |
| **小 Agent / 辅助写作** | 划词翻译、查词、追问及写作续写、灵感、润色，与阅读 AI 分开配置 |
| **视频转写** | 自备兼容 OpenAI 的语音转写接口（`/audio/transcriptions`）、Key 与模型；转写在所配置的服务端完成 |
| **flomo / 云同步** | 需要对应服务时再配置；导入 flomo 导出包无需外发笔记 |

## 升级与数据

桌面版默认将书库、配置、缓存、浏览器登录态与日志统一保存在：

```text
~/Library/Application Support/归藏/
```

升级时**退出归藏，再替换应用程序中的 App**。替换或重装 App 不会删除该数据目录。首次迁移旧版 `~/Documents/归藏/` 书库时，只复制缺失内容，保留原文件，不覆盖已有目标。

从源码版迁入桌面版，请先关闭旧程序，再按 [桌面构建与迁移说明](desktop/README.md) 使用无覆盖导入工具。备份时请保留整个数据目录；其中包含登录态与密钥，应妥善保管。

本地服务仅监听本机回环地址。使用微信读书、剪藏、订阅、视频、AI 或云同步时，会请求相应平台或你配置的服务；调用 AI/云转写时，相关文本或音频会发送到所配置的接口。

## 从源码运行与构建

开发建议使用 **Python 3.11+**。源码可在不同系统上运行，需自行准备适用依赖；这不等于已经提供 1.2.3 Windows 或 Intel Mac 成品。

```bash
git clone https://github.com/aritosi/weread-guizang.git
cd weread-guizang
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python ui_server.py --port 8770
```

浏览器打开 `http://127.0.0.1:8770`。Windows 将 `.venv/bin/python`、`.venv/bin/pip` 替换为 `.venv\Scripts\python.exe`、`.venv\Scripts\pip.exe`。源码版视频功能还需在系统中准备 FFmpeg/FFprobe；Node.js 用于 MCP 接入。

构建当前 macOS 独立包：

```bash
bash desktop/build_macos.sh
```

构建需 Apple Silicon Mac、Command Line Tools、Rust stable、Node/npm 与 Python 3.11+。产物位于 `dist/macos/`，详见 [构建说明](desktop/README.md)。历史 `1.0.9` 安装包与当前 `1.2.3` 独立包不是同一套运行方案；旧 Windows 包仅作历史存档。

### 接入 AI Agent（MCP）

仓库提供零依赖 Node 适配器 [guizang-mcp.mjs](mcp/guizang-mcp.mjs)，通过 stdio 暴露书架、导出、划线、剪藏、订阅、视频与写作等工具。将路径替换为实际源码目录，合并到客户端的 `mcpServers` 配置中：

```json
{
  "mcpServers": {
    "guizang": {
      "command": "node",
      "args": ["/path/to/weread-guizang/mcp/guizang-mcp.mjs"],
      "env": { "GUIZANG_REPO": "/path/to/weread-guizang" }
    }
  }
}
```

适配器会在服务未启动时启动源码服务，需要先完成源码依赖安装。配套 [归藏 Skill](skills/guizang/SKILL.md) 用于书籍与笔记操作，[Book Speedrun](skills/book-speedrun/SKILL.md) 用于读书讲解与学习整理。

## 使用边界

- 微信读书导出需要自己的有效会员账号及目标内容的阅读权限；部分书籍限制网页端阅读，正文抓取也可能不完整。
- 网页剪藏、第三方找书和视频下载依赖站点规则、账号权限与网络状态，平台变化可能导致失败。
- RSS 当前手动刷新；视频转写质量由所选模型决定，AI 输出需自行核对。
- WebDAV 与 Microsoft Graph 云同步尚未使用真实网盘账号完成端到端验收。
- 1.2.3 桌面包面向 Apple Silicon；最低系统要求为 macOS 13.5，未在每个旧系统版本或其他 Mac 上逐一实测。Windows 成品尚未完成本轮真实设备验收。

## 文档导航

| 我想了解 | 入口 |
| --- | --- |
| 安装、数据迁移与发布状态 | [macOS 独立安装](docs/macOS独立安装.md) · [桌面构建说明](desktop/README.md) |
| 版本改动与验收证据 | [更新记录](CHANGELOG.md) · [1.2.3 验收记录](desktop/TEST_RESULTS.md) |
| 源码部署与功能细节 | [部署说明](docs/部署说明.md) |
| 代码结构与开发约定 | [架构与模块地图](docs/架构与模块地图.md) · [开发规范](docs/开发规范.md) |
| Agent 工作流 | [归藏 Skill](skills/guizang/SKILL.md) · [Book Speedrun](skills/book-speedrun/SKILL.md) · [MCP 适配器](mcp/guizang-mcp.mjs) |

部分历史文档记录旧版启动器与数据路径；当前桌面包的安装、构建和数据行为，以桌面说明及本页为准。

## 来源、许可与致谢

抓取工具 `export_precise.py` 与图片下载能力源自 [lbq110/weread-exporter](https://github.com/lbq110/weread-exporter)。感谢上游作者，以及 Playwright、Tauri、PyInstaller、FFmpeg 等开源项目。

**授权需按组成部分分别确认。** 抓取与图片下载上游未明确声明许可证，因此本仓库未放置覆盖全仓的根 `LICENSE`；原项目将后续新增的界面、官方接口集成、MCP 与 Skills 标注为按 MIT 使用。这不代表所有上游代码或整个安装包均可统一按 MIT 再分发。

包内第三方组件遵循各自许可与来源清单。FFmpeg/FFprobe 的构建启用了 GPL，分发时需满足对应版本的源码及构建资料等义务，详见 [桌面发布边界](desktop/README.md#发布边界) 与包内 licenses/provenance 文件。

该项目仅仅为学习和交流而开发，请在下载后24h内进行删除，请仅在自身内容权限与平台条款允许的范围内使用，尊重作者与出版方的权益。
