#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频转笔记：换了云端 ASR 模型之后，整份暂存不许再被当成「上回那份」复用。

为什么单开一条：`video_note.run()` 的 `resume` 默认是 True，而界面**没有任何开关**
能关掉它（`ui_server` 起 `video_note.py --task` 时只塞 `asr` 与 `language`）。于是
「上一趟转写还算不算数」全凭两份暂存自己的判据：

  · 分片级 `_part_cached`：凭据是真正发给接口的 `cloud.model`（会认模型变化）；
  · 整份级 `_staged_transcript`：凭据取自 `_asr_model(asr_cfg)`，而这一把原先**只读
    顶层 `asr_cfg["model"]`**。界面（`#asrModel` → `cache/config.json` 的
    `asr_model` → `ui_server.asr_opts_for_task`）只填 `asr.cloud.model`，顶层那一格
    从来不存在 —— 暂存里写下的模型永远是空串，对比两边都是空串，换模型形同没换：

      用户在设置里把模型从 A 改成 B → 重跑同一条视频 → 界面上写着
      「沿用上回转好的 N 段，不用再转一遍」，拿到的还是 A 转的那份，而且没有
      任何按钮能把这一趟掰回来（只能去删 `cache/…/tmp/<当期目录>`）。

这一条钉三层：
  A 尺子：`_asr_model` 认 `cloud.model`（顶层仍优先），`_cloud_model` 与它同源；
  B 暂存：同模型复用、换模型 / 换语言不复用，暂存里如实记下这次用的模型；
  C 端到端：真跑 `run()` 三趟（m1 挂在 AI 那一步 → m2 重转 → m2 复用），
    钉住「换模型那一趟真的重新转写了」、「同模型那一趟仍然复用」这两件事。

不起服务、不联网、不碰真实 cache/ 与书库，纯离线沙盒，归 --fast 静态段。
跑法：.venv/bin/python tests/check_video_resume_model.py
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# GUIZANG_DATA 必须在 import video_note 之前设好：模块导入时就把 DATA_DIR / TMP_ROOT
# 定下来了，设晚了流水线的临时音频会写进用户真实的缓存目录。
SANDBOX = tempfile.mkdtemp(prefix="gz-video-resume-model-")
atexit.register(lambda: shutil.rmtree(SANDBOX, ignore_errors=True))
os.environ["GUIZANG_DATA"] = os.path.join(SANDBOX, "data")
os.makedirs(os.environ["GUIZANG_DATA"], exist_ok=True)

import video_note as vn  # noqa: E402

FAIL = []
TOTAL = [0]


def chk(name, cond, extra=""):
    TOTAL[0] += 1
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if not cond:
        FAIL.append(name)


def asr_cfg(model, language="zh"):
    """界面真正喂进来的形状（ui_server.asr_opts_for_task）：模型只在 cloud 那一格里。"""
    return {"engine": "cloud", "language": language,
            "cloud": {"url": "https://example.invalid/v1", "key": "k", "model": model}}


# ── A 尺子：暂存凭据与上线名字读同一格 ─────────────────────────────
chk("凭据读界面那一格：顶层没有 model 也认 cloud.model",
    vn._asr_model(asr_cfg("m2")) == "m2", vn._asr_model(asr_cfg("m2")))
chk("顶层 model 仍优先（MCP / 自测显式点名的那一项不被 cloud 覆盖）",
    vn._asr_model({"model": "top", "cloud": {"model": "cloud"}}) == "top",
    vn._asr_model({"model": "top", "cloud": {"model": "cloud"}}))
chk("两处都没填时凭据是空串（默认模型两边同一口径，不算「换过」）",
    vn._asr_model({}) == "" and vn._asr_model({"cloud": {}}) == "",
    (vn._asr_model({}), vn._asr_model({"cloud": {}})))
chk("cloud 写成脏形状也不抛（当没填）",
    vn._asr_model({"cloud": "m1"}) == "" and vn._asr_model({"cloud": ["m1"]}) == "",
    vn._asr_model({"cloud": ["m1"]}))
chk("上线用的名字与凭据同源：配了就照用，没配才落默认那个",
    vn._cloud_model(asr_cfg("m2")) == "m2"
    and vn._cloud_model({}) == vn.DEFAULT_CLOUD_MODEL,
    (vn._cloud_model(asr_cfg("m2")), vn._cloud_model({})))
# 对照：旧写法（只读顶层 model）在这个形状下量不出模型，这正是本条要收的口子。
_old = str({"engine": "cloud", "cloud": {"model": "m2"}}.get("model") or "")
chk("对照：旧尺子（只读顶层）在界面形状下永远是空串 —— 换模型看不出来",
    _old == "", _old)

# ── B 暂存：同模型复用、换模型 / 换语言不复用 ──────────────────────
STAGE = tempfile.mkdtemp(prefix="stage-", dir=SANDBOX)
vn._stage_transcript(STAGE, {"text": "上一趟的转写", "engine": "cloud",
                             "language": "zh",
                             "segments": [{"start": 0.0, "end": 1.0, "text": "上一趟"}]},
                     asr_cfg("m1"))
_meta = vn._read_json(os.path.join(STAGE, "transcript.json"))
chk("暂存里如实记下这次用的模型（不再永远是空串）",
    isinstance(_meta, dict) and _meta.get("model") == "m1", _meta)
chk("同一个模型：暂存照旧复用（没把正常续跑一并关掉）",
    vn._staged_transcript(STAGE, asr_cfg("m1")) is not None, None)
chk("换了模型：暂存不再复用（本条修复点；旧尺子这里会认下旧那份）",
    vn._staged_transcript(STAGE, asr_cfg("m2")) is None, None)
chk("换了语言：暂存也不复用（原有这一档不许被这次改动带坏）",
    vn._staged_transcript(STAGE, asr_cfg("m1", language="en")) is None, None)
chk("模型与语言都一致时才认（空格不算换模型）",
    vn._staged_transcript(STAGE, asr_cfg(" m1 ")) is not None, None)

# ── C 端到端：run() 三趟 ───────────────────────────────────────────
CALLS = {"transcribe": [], "download": []}
BOOM = {"ai": True}
NOTES = []
URL = "https://www.bilibili.com/video/BVresumemodel"


def fake_plan(url, page=None):
    return {"title": "示例视频・换模型", "url": url, "platform": "bilibili",
            "vid": "BVresumemodel", "page": page, "uploader": "示例UP主",
            "duration": 48, "cover": "",
            "pages": [{"i": 1, "title": "示例视频・换模型", "duration": 48}]}


def fake_download(url, task_dir, progress=None, should_stop=None):
    os.makedirs(task_dir, exist_ok=True)
    path = os.path.join(task_dir, "audio.m4a")
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypM4A ")
    CALLS["download"].append(task_dir)
    return path


def fake_transcribe(audio_path, cfg, progress=None, should_stop=None, resume=False):
    CALLS["transcribe"].append({"model": vn._asr_model(cfg), "resume": bool(resume)})
    return {"text": "这是一段假转写，用来判断这一趟到底转没转。",
            "segments": [{"start": 0.0, "end": 2.0, "text": "假转写"}],
            "engine": "cloud", "language": "zh"}


def fake_ai_bundle(cfg, title, text, segments, progress):
    if BOOM["ai"]:
        raise RuntimeError("假装 AI 那一步挂了")
    return {"summary": {"title": title, "overview": "一句话概述。",
                        "bulletPoints": ["要点一"], "chapters": []},
            "note": "", "mindmap": None, "warnings": []}


def fake_save_book(out_dir, plan_info, spoken, summary, note, mindmap, cfg, ai_error):
    return {"id": "bk_fake_resume", "meta": {
        "id": "bk_fake_resume", "title": plan_info["title"], "dir": out_dir,
        "source": "video", "chapters": 1, "words": 8, "segments": 1, "duration": 48,
        "language": "zh", "url": plan_info.get("url") or ""},
        "transcript_path": "", "transcript_json": "", "merged_path": "",
        "note_path": "", "mindmap_path": ""}


vn.plan = fake_plan
vn.download_audio = fake_download
vn.transcribe = fake_transcribe
vn._ai_bundle = fake_ai_bundle
vn._save_book = fake_save_book

TASK_DIR = os.path.join(vn.TMP_ROOT, "bilibili_BVresumemodel")


def run_once(model, boom, language="zh"):
    BOOM["ai"] = boom
    got = []
    opts = {"asr": asr_cfg(model, language), "llm": {}, "language": language}
    result = None
    try:
        result = vn.run(URL, os.path.join(SANDBOX, "books"), opts,
                        lambda s, p, n: got.append((s, n)))
    except Exception as e:  # noqa: BLE001 —— 这里要的就是「挂在那一步」这条路径
        return {"error": e, "notes": got}
    return {"result": result, "notes": got}


# 第一趟：m1 转写成功，挂在 AI 那一步 —— 暂存留在临时目录里（正常续跑的前提）
first = run_once("m1", boom=True)
chk("第一趟：AI 挂了如实抛错，暂存留在临时目录里",
    first.get("error") is not None
    and os.path.isfile(os.path.join(TASK_DIR, "transcript.json")),
    (first.get("error"), os.path.isdir(TASK_DIR)))
chk("第一趟：确实转了一遍，暂存里记的是 m1",
    [c["model"] for c in CALLS["transcribe"]] == ["m1"]
    and vn._read_json(os.path.join(TASK_DIR, "transcript.json")).get("model") == "m1",
    CALLS["transcribe"])

# 第二趟：只在设置里把模型换成 m2 —— 必须重新转写（这正是修复前不会发生的事）
second = run_once("m2", boom=True)
chk("换模型那一趟：真的重新转了一遍（不再拿 m1 的暂存凑数）",
    [c["model"] for c in CALLS["transcribe"]] == ["m1", "m2"], CALLS["transcribe"])
chk("换模型那一趟：转写这一步的进度里没有「沿用上回」（不会骗用户）",
    not any("沿用" in n for s, n in second.get("notes") or [] if s == "asr"),
    second.get("notes"))
chk("换模型那一趟：暂存里跟着换成 m2",
    vn._read_json(os.path.join(TASK_DIR, "transcript.json")).get("model") == "m2", None)

# 第三趟：模型还是 m2 —— 这时才该复用（续跑没被这次改动关掉）
third = run_once("m2", boom=False)
chk("同模型那一趟：不再重转（断点续跑本身照旧有效）",
    len(CALLS["transcribe"]) == 2, CALLS["transcribe"])
chk("同模型那一趟：转写这一步说清了是沿用的",
    any("沿用" in n for s, n in third.get("notes") or [] if s == "asr"),
    third.get("notes"))
chk("同模型那一趟：书照常落成（复用这份暂存仍然能走完整条流水线）",
    (third.get("result") or {}).get("book", {}).get("title") == "示例视频・换模型",
    third.get("result"))
chk("跑成功后临时目录才清干净（与既有口径一致）",
    not os.path.isdir(TASK_DIR), os.listdir(vn.TMP_ROOT))

print("\n共 %d 项检查" % TOTAL[0])
if FAIL:
    print("失败 %d 项：" % len(FAIL))
    for name in FAIL:
        print("  - " + name)
    sys.exit(1)
print("全部通过")
