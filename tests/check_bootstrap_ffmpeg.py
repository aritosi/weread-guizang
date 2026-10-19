#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：首启第 4 步「ffmpeg 装没装」的判据必须是**两份都在**。

`ffmpeg_tool` 要的是 ffmpeg 与 ffprobe 各一份（`BINARIES = ("ffmpeg", "ffprobe")`），
下载时一前一后；网络断在第二份，盘上就留下「ffmpeg 有了、ffprobe 没有」的半装状态。
这时如果首启只问 `status()["found"]`（那是**ffmpeg 在不在**，不含 ffprobe），它会说
「已有，跳过」并报「环境已就绪」——ffprobe 再也没人自动补。

为什么这不是理论问题：ffprobe 是量时长的那一份。长视频切段上传时
`video_note._transcribe_cloud` 用 `_audio_seconds(part)` 累加时间轴偏移，量不出时长
就每一段都从 0 开始，转写稿里的时间戳叠在一起，而界面从头到尾不报一个错。冻结版
那条路（`main` 里的 frozen 分支）一直问的是两样，这个套件把普通那条路也钉在同一把
尺子上，并留一面「旧写法确实会跳过」的镜子。

全程离线：不起服务、不联网、不真去下 ffmpeg —— `main()` 的重活（建 venv / 装依赖 /
下 Chromium）全部用桩顶掉，量的是它走到第 4 步时**问的是哪一把尺子、有没有真去补**。
"""
import os
import pathlib
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 先指进沙盒再 import：bootstrap 自己只用标准库，但万一以后加了导入期读写，也不该
# 碰用户真实的 cache/ 与书库。
_SB = tempfile.mkdtemp(prefix="guizang-boot-ffmpeg-")
os.environ["GUIZANG_DATA"] = os.path.join(_SB, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(_SB, "books")

import bootstrap  # noqa: E402
import ffmpeg_tool  # noqa: E402
import platform_compat as pc  # noqa: E402

FAILED = []
PASSED = 0
SRC_BOOT = (ROOT / "bootstrap.py").read_text(encoding="utf-8")


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:300]))


# ── 1. 判据本身：两样都在才算就绪 ──────────────────────────────
chk("两份都在 → 就绪",
    bootstrap.media_ready({"found": True, "ffprobe": "/data/tools/ffprobe"}) is True)
chk("ffmpeg 在、ffprobe 缺 → **没就绪**（本次修的那一格，旧写法在这儿说「已有」）",
    bootstrap.media_ready({"found": True, "ffprobe": None}) is False,
    bootstrap.media_ready({"found": True, "ffprobe": None}))
chk("只有 ffprobe、没有 ffmpeg → 没就绪",
    bootstrap.media_ready({"found": False, "ffprobe": "/x/ffprobe"}) is False)
chk("空表 → 没就绪", bootstrap.media_ready({}) is False)
chk("None → 没就绪（status() 万一回空也不抛）", bootstrap.media_ready(None) is False)
chk("非表 → 没就绪（不抛）", bootstrap.media_ready("found") is False)
chk("ffprobe 空串也算没有（不是「有值就真」）",
    bootstrap.media_ready({"found": True, "ffprobe": ""}) is False)

# 对照：旧那把尺子（只看 found）在半装状态下会判成「已有」——这条证明上面不是在测空气。
chk("对照：旧写法只看 found，半装状态会判成「已有」（所以非修不可）",
    bool({"found": True, "ffprobe": None}.get("found")) is True)


# ── 2. 行为级：main() 走到第 4 步时问的是哪把尺子、有没有真去补 ──
def run_main(status, ensure_calls):
    """把 main() 的前三步全用桩顶掉，只让它走到第 4 步。→ (退出码, 说出来的话)。"""
    spoken = []

    def fake_say(text=""):
        spoken.append(str(text))

    with mock.patch.object(pc, "IS_MAC", True), \
            mock.patch.object(bootstrap, "child_env", lambda: {}), \
            mock.patch.object(bootstrap, "say", fake_say), \
            mock.patch.object(pc, "venv_python_only", lambda root: "/fake/python"), \
            mock.patch.object(bootstrap, "python_works", lambda *a, **k: True), \
            mock.patch.object(bootstrap, "browser_ready", lambda: True), \
            mock.patch.object(ffmpeg_tool, "status", lambda: status), \
            mock.patch.object(ffmpeg_tool, "ensure",
                              lambda progress=None: ensure_calls.append(1)):
        code = bootstrap.main()
    return code, "\n".join(spoken)


def ff_section(out):
    """只看第 4 步那一段（前三步自己也说「已有，跳过」，不截出来就量不出这一格）。"""
    i = out.find("[4/4] ffmpeg")
    return out[i:] if i >= 0 else ""


calls = []
code, out = run_main({"found": True, "ffprobe": None}, calls)
chk("半装（ffmpeg 在 / ffprobe 缺）：真的去补了一次",
    len(calls) == 1, calls)
chk("半装：第 4 步不再说「已有，跳过」", "已有，跳过" not in ff_section(out), ff_section(out))
chk("半装：如实说缺的是 ffprobe", "ffprobe 缺了一份" in out, out)
chk("半装：没下成也不拦门（退出码 0）", code == 0, code)

calls = []
code, out = run_main({"found": True, "ffprobe": "/data/tools/ffprobe"}, calls)
chk("两份都在：一次都不去下（第二次点是一秒过）", calls == [], calls)
chk("两份都在：第 4 步说的是「已有，跳过」",
    "已有，跳过" in ff_section(out), ff_section(out))

calls = []
code, out = run_main({"found": False, "ffprobe": None}, calls)
chk("两份都没有：照旧去下一份", len(calls) == 1, calls)
chk("两份都没有：说的是「正在下一份」", "正在下一份" in out, out)

# ── 3. 接线：两处判据共用一把尺子，旧的「只看 found」不许回来 ──
chk("接线：普通那条路用的是 media_ready(status)",
    "if media_ready(st):" in SRC_BOOT)
chk("接线：冻结版那条路也用 media_ready（原来各写各的）",
    "browser_ready() and media_ready(media)" in SRC_BOOT)
chk("接线：旧写法 `ffmpeg_tool.status().get(\"found\")` 不再出现",
    'ffmpeg_tool.status().get("found")' not in SRC_BOOT)
chk("一把尺子：media_ready 只此一处定义",
    SRC_BOOT.count("def media_ready(") == 1)

print("\n首启 ffmpeg 组件判据门禁：%d 项通过，失败 %d 项" % (PASSED, len(FAILED)))
for f in FAILED:
    print("  ✗ " + f)
sys.exit(1 if FAILED else 0)
