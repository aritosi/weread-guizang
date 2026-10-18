# 归藏

归藏是一个本地运行的微信读书导出与阅读工具。它将微信读书中的书籍导出为 Markdown，并将导出内容、导入书籍、网页剪藏、RSS 订阅、视频转写、便签和写作稿统一存放在本地书库中。

服务仅监听 `127.0.0.1`，数据保存在本机。

## 功能

### 微信读书

- 将整本书导出为 Markdown，正文与插图按阅读顺序排列，支持断点续传。
- 导出 EPUB、PDF，或将划线导出为 Anki 卡包。
- 搜索微信读书书城，查看书籍详情、作者、出版社、阅读进度和最近阅读时间。
- 查看推荐书籍，并将书籍加入微信读书书架。
- 查看微信读书的划线、想法和阅读统计。

### 本地书库

- 导入并阅读 Markdown、TXT、EPUB、PDF。
- 书架分为读书、本地书架、剪藏、订阅、视频、便签、写作七类。
- 支持瀑布流与叠卡两种布局，以及文件夹、标签和排序。
- 阅读器提供目录、章节跳转、上次阅读位置恢复、划线、批注和笔记。
- 每本书可设置每日或每周阅读页数，记录阅读进度和完成记录。
- 支持通过“安娜的档案”搜索并下载书籍。下载文件会自动识别格式并加入本地书架。

### 剪藏

- 支持微信公众号、知乎、小红书和 X 的文章解析。
- 复制链接后点击按钮，从剪贴板读取链接并解析正文。
- 解析结果可加入书库、阅读，并导出 EPUB 或 PDF。

### 订阅

- 支持 RSS、Atom 和 JSON Feed。
- 三栏阅读界面分别显示订阅源、条目列表和正文。
- 支持 OPML 导入导出、标签、搜索、批量操作和单条入库。

### 视频转笔记

- 支持哔哩哔哩和 YouTube。
- 下载音频后，通过用户配置的云端转写接口生成文字，再由 AI 生成笔记和思维导图。
- 支持分段查看、编辑、重建章节和导出 SRT。

### 笔记与思维导图

- 划线笔记支持微信读书与本机笔记两个来源。
- 思维导图支持括号图、辐射图、鱼骨图和概念图，可编辑并导出 SVG。
- 画板支持绘图、文字、形状、缩放和导出。

### 便签

- 导入 flomo 导出包。
- 两栏布局，左侧为富文本编辑器，右侧按时间线显示笔记。
- 支持标签、搜索、Markdown 复制，单条笔记可转为书籍。

### 写作

- 富文本编辑，内容以 Markdown 保存。
- 支持书与章节管理、续写、灵感、润色和版本历史。
- 支持导出图片、PDF、EPUB 和 Markdown。

### AI 与 Agent

- 阅读器支持翻译、查词和问答。
- AI 小结提供学习理解与归纳两种模式。
- 提供 MCP 适配器，包含 61 个工具。
- 提供配套 Skills，用于读书与学习流程。

## 版本说明

当前源码版本为 `1.2.2`。

- 剪藏与视频转笔记统一使用按钮触发，并显示环形进度。
- 视频转写支持分页读取和解析缓存。
- 思维导图支持双指缩放，并调整了节点间距和尺寸。
- 划线笔记改为书籍卡片瀑布流，同时合并本机笔记。
- 推荐页和书城搜索结果支持加入微信读书书架。
- 内置浏览器支持 YouTube 静态目录。
- “安娜的档案”简化为搜索框和搜索按钮。
- 修复取书任务卡住、部分封面加载失败和页面切换位置异常等问题。

## 环境要求

- Python 3.9 或更高版本。从源码运行建议使用 Python 3.10 或更高版本。
- Node.js 为可选项，仅 MCP 适配器需要。
- 微信读书账号为可选项，仅导出微信读书书籍、查看划线和统计时需要。
- 视频转笔记需要 ffmpeg。macOS 安装过程中会自动准备，Windows 和 Linux 需自行安装并加入 `PATH`。

## 安装

### macOS

1. 下载 [归藏-1.0.9.dmg](安装包/归藏-1.0.9.dmg)。
2. 将应用拖入“应用程序”并打开。
3. 首次启动会自动安装依赖、Chromium 和 ffmpeg，然后打开登录窗口。

安装包版本为 `1.0.9`，当前源码版本为 `1.2.2`。如需使用最新源码，请从源码运行或重新构建安装包。

如果 macOS 提示应用“已损坏”，可移除隔离属性：

```bash
xattr -dr com.apple.quarantine /Applications/归藏.app
```

### Windows

1. 下载 [归藏-Windows-1.0.9.zip](安装包/归藏-Windows-1.0.9.zip)。
2. 解压后双击 `安装归藏.bat`。

安装脚本会将程序复制到 `%USERPROFILE%\归藏`，并在桌面创建快捷方式。首次启动会自动创建虚拟环境、安装依赖和 Chromium。

也可直接双击 `启动归藏.bat` 在解压目录中运行。此方式不会复制程序，数据也保存在解压目录中。

Windows 版本需要 Python 3.10 或更高版本，并在安装时勾选 `Add python.exe to PATH`。

### 从源码运行

```bash
git clone https://github.com/aritosi/weread-guizang.git
cd weread-guizang
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python ui_server.py --port 8770
```

打开 `http://127.0.0.1:8770`。

Windows 使用以下命令：

```bat
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe ui_server.py --port 8770
```

也可运行 `启动归藏.command`（macOS）或 `启动归藏.bat`（Windows）。脚本会自动创建虚拟环境、安装依赖并启动服务。

构建 macOS 应用和安装包：

```bash
./shell/build_macos.sh
./shell/make_dmg.sh
```

## 首次使用

1. 打开设置，选择“连接账号”，在浏览器窗口中扫描微信读书登录二维码。
2. 填写微信读书接口 Key。Key 可在微信读书网页版的“设置 → 开放 API”中获取，格式为 `wrk-...`。
3. 如需使用翻译、查词、问答或 AI 小结，在设置中填写兼容 OpenAI 接口格式的地址、Key 和模型名。
4. 如需使用视频转笔记，在“视频转写”中填写兼容 OpenAI 的语音转写接口地址和 Key。
5. 如需将划线转入 flomo，可填写 flomo API，或在划线笔记中导出 CSV 后手动导入。

## 命令行

以下命令可在不启动界面的情况下使用。

```bash
.venv/bin/python export_precise.py <书籍链接或 ID>
.venv/bin/python export_precise.py <书籍 ID> --headed
EXPORT_DEBUG=1 .venv/bin/python export_precise.py <书籍 ID>
```

其他功能：

```bash
.venv/bin/python login.py                          # 登录与登录态检测
.venv/bin/python shelf_add.py <书城 ID>             # 加入微信读书书架
.venv/bin/python clip_article.py <文章链接>         # 解析文章
.venv/bin/python web_parse.py <链接>                # 识别站点并输出正文摘要
.venv/bin/python feed.py <站点或订阅地址>           # 查找订阅源
.venv/bin/python feed.py --list                    # 查看订阅
.venv/bin/python feed.py --refresh                 # 刷新全部订阅
.venv/bin/python video_note.py <视频链接>           # 生成视频笔记
.venv/bin/python ffmpeg_tool.py --status           # 查看 ffmpeg 状态
.venv/bin/python ffmpeg_tool.py --ensure           # 下载 ffmpeg
```

Windows 将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。

## MCP 接入

仓库提供零依赖的 Node MCP 适配器 `mcp/guizang-mcp.mjs`，使用 stdio 和 JSON-RPC 2.0。

在 MCP 配置中加入：

```json
"guizang": {
  "type": "stdio",
  "command": "node",
  "args": ["<归藏目录>/mcp/guizang-mcp.mjs"],
  "timeout": 180000,
  "env": { "GUIZANG_REPO": "<归藏目录>" }
}
```

适配器按以下顺序查找项目目录：

1. 环境变量 `GUIZANG_REPO`
2. 根据当前文件位于项目 `mcp/` 目录下推断
3. 常见路径回退

服务未启动时，适配器会自行启动服务。

工具共 61 个，覆盖书架、取书、笔记、导出、剪藏、订阅、视频、思维导图、画板、便签和写作。

## 配套 Skills

`skills/` 目录包含用于读书与学习的 Skill。将对应文件夹复制到本机 skills 目录即可使用。

| Skill | 用途 |
| --- | --- |
| `skills/guizang/` | 将归藏接入为读书助手，包含找书、取书、检索划线、抽卡和导出 Anki 的流程 |
| `skills/book-speedrun/` | 将一本书整理为前导地图、核心讲义、全书串讲和一页速记 |

需要内容讲解时使用 `book-speedrun`；需要书籍数据和笔记操作时使用 `guizang`。

## 数据与隐私

- 书库、笔记、思维导图和画板保存在 `~/Documents/归藏/`。
- 运行时数据、虚拟环境、缓存和登录态保存在 `~/Library/Application Support/归藏/`。
- 微信读书登录态保存在 `cache/browser_profile/`。
- 配置保存在 `cache/config.json`，文件权限为 `600`。界面只显示密钥末四位。
- 服务仅监听本机回环地址，不经过第三方中转。
- 外部请求仅发送到用户自行配置或主动打开的地址，包括 AI 接口、转写接口和“安娜的档案”站点。
- 设置中的“清除本地数据”不会删除书库文件。

## 已知限制

- 导出微信读书书籍需要有效账号，并且对目标书有阅读权限。
- 部分出版社限制网页端阅读，此类书籍无法导出。
- 正文抓取不保证 100% 完整。阅读器会复用已绘制的缓存，部分内容可能未被捕获。
- 抓取速度约为每页 1.1 秒。进一步压缩等待时间会增加丢字风险。
- “安娜的档案”需要登录后才能下载，站点域名可能变化，下载成功率受账号额度和镜像可用性影响。
- RSS 仅支持手动刷新，不进行后台定时轮询和双向同步。
- 视频转笔记目前仅支持哔哩哔哩和 YouTube，转写准确度取决于所选模型。
- AI 功能需要用户自行配置兼容 OpenAI 的接口。
- 云同步基于 WebDAV 和 Microsoft Graph 公开接口实现，尚未在真实网盘账号上完成端到端验证。
- Windows 安装包和启动脚本尚未在真实 Windows 设备上完成端到端验证。

## 许可

本项目使用 MIT 许可证。

本项目仅用于个人学习、研究和备份自己已购买的内容。请勿传播导出成果或用于商业用途，并遵守著作权和平台服务条款。
