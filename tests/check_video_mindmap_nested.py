# -*- coding: utf-8 -*-
"""视频思维导图：提示词示例那种 `nodes` 列表 + 嵌套 children 也要照用（离线验收）。

`MINDMAP_USER` 的「输出格式示例」写的是 `nodes:[root]`，而 root 的 `children`
是**对象数组**，不是 id 字符串：

    {"root":"root","nodes":[{"id":"root",...,"children":[{...主题...}]}]}

`_normalize_mindmap` 原来的判据只看「有没有节点带 children」：只要有一个，就当成
「已经是扁平 + children id 的写法」交给 `_normalize_nodes` —— 于是示例里的每个孩子
被 `str()` 成一段字典文本，谁也匹配不上节点 id；`_mindmap_top_branches` 数到 0 个
一级分支，重问一次仍是同一形状，`build_mindmap` 只好退成摘要兜底那张。模型完全照
提示词写，用户拿到的却是「模型两次给的导图一级分支都不够，已用摘要兜了一张」。

这一条把四件事钉住：

  P1 照示例写的嵌套 children 走 `_flatten_tree`，一级分支数得出来（>=3）。
  P2 模型给的标签与层级一个不少，children 里存的是真节点的 id。
  P3 `build_mindmap` 端到端不再退成兜底（warn 为空、没有「知识分支 N」占位）。
  P4 扁平 id 列表仍走 `_normalize_nodes`，id 不被改名（好数据一个字不改）。
  P5 对照：旧判据（只看有没有 children）确实把示例判成 0 个一级分支 —— 这条门禁
     不是空转。

全程离线、不联网、不开浏览器，也不碰用户真实书库（数据目录指进临时沙盒）。
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 先指进临时沙盒再 import video_note：免得导入期真去动用户真实缓存。
SANDBOX = pathlib.Path(tempfile.mkdtemp(prefix="guizang-vidmap-nested-"))
os.environ["GUIZANG_DATA"] = str(SANDBOX / "cache")
os.environ["GUIZANG_BOOKS"] = str(SANDBOX / "books")
os.makedirs(os.environ["GUIZANG_DATA"], exist_ok=True)

import video_note as vn  # noqa: E402

PASSED = 0
FAILED = []


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:220]))


def call(fn, *a, **kw):
    """跑一次；抛了就把异常文本还回来，好让失败信息可读。"""
    try:
        return fn(*a, **kw), None
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


SUMMARY = {"overview": "一句话总览", "bulletPoints": ["要点一", "要点二", "要点三"],
           "chapters": [{"title": "第一章", "start": 0, "summary": "一"},
                        {"title": "第二章", "start": 30, "summary": "二"},
                        {"title": "第三章", "start": 60, "summary": "三"}]}
CFG = {"url": "https://example.invalid/v1", "key": "k", "model": "fake-model"}


def theme(i, label, kids=()):
    return {"id": "theme-%d" % i, "label": label, "type": "theme", "summary": label,
            "children": list(kids), "time_anchor": 0}


# 提示词示例的形状：nodes 是列表，root 的 children 是对象数组。
PROMPT_PAYLOAD = {
    "version": 1, "title": "示例视频总结", "root": "root",
    "nodes": [{
        "id": "root", "label": "整支视频的主题", "type": "root", "summary": "",
        "children": [
            theme(1, "学习要点", [{"id": "l1", "label": "叶一", "type": "leaf",
                                 "summary": "结论", "children": [], "time_anchor": 12}]),
            theme(2, "方法步骤"),
            theme(3, "结论风险"),
        ],
        "time_anchor": None,
    }]}


# ── P1 / P2：示例形状走得通、一层不丢 ──────────────────────────────
mm, err = call(vn._normalize_mindmap, PROMPT_PAYLOAD, "示例视频总结", SUMMARY)
ids = {n["id"] for n in (mm or {}).get("nodes", [])}
chk("P1 照示例写的嵌套 children：不抛、一级分支 >= 3",
    err is None and vn._mindmap_top_branches(mm or {}) >= vn.MIN_MINDMAP_BRANCHES,
    err if err else (mm or {}).get("nodes"))

labels = {n["label"] for n in (mm or {}).get("nodes", [])}
chk("P2a 模型给的标签一个不少（root 不再被摘要兜底顶掉）",
    {"整支视频的主题", "学习要点", "方法步骤", "结论风险", "叶一"} <= labels,
    err if err else sorted(labels))

root_node = next((n for n in (mm or {}).get("nodes", []) if n["id"] == mm.get("root")), None)
chk("P2b children 里存的是真节点的 id（不是 str(dict) 的文本）",
    root_node is not None and root_node["children"]
    and all(c in ids for c in root_node["children"]),
    err if err else root_node)


# ── P3：build_mindmap 端到端不再退成兜底 ────────────────────────────
saved_chat = vn.llm_chat
try:
    vn.llm_chat = lambda cfg, msgs, timeout=180: json.dumps(PROMPT_PAYLOAD, ensure_ascii=False)
    built, berr = call(vn.build_mindmap, CFG, "示例视频总结", SUMMARY, "笔记正文")
finally:
    vn.llm_chat = saved_chat

chk("P3a 照示例回话的回包被照用：warn 为空（没有「一级分支都不够」）",
    berr is None and isinstance(built, tuple) and built[1] == "",
    berr if berr else built)
built_labels = {n["label"] for n in (built[0].get("nodes", []) if isinstance(built, tuple) else [])}
chk("P3b 落下来的是模型那张图，不是「知识分支 N」占位兜底",
    "学习要点" in built_labels and not any("知识分支" in l for l in built_labels),
    berr if berr else sorted(built_labels))


# ── P4：扁平 id 列表仍走老路，id 不被改名 ──────────────────────────
FLAT_PAYLOAD = {"version": 1, "title": "示例视频总结", "root": "root", "nodes": [
    {"id": "root", "label": "总", "type": "root", "children": ["t1", "t2", "t3"],
     "time_anchor": None},
    {"id": "t1", "label": "概念", "type": "theme", "children": [], "time_anchor": 0},
    {"id": "t2", "label": "方法", "type": "theme", "children": [], "time_anchor": 0},
    {"id": "t3", "label": "结论", "type": "theme", "children": [], "time_anchor": 0}]}
flat_mm, ferr = call(vn._normalize_mindmap, FLAT_PAYLOAD, "示例视频总结", SUMMARY)
flat_root = next((n for n in (flat_mm or {}).get("nodes", []) if n["id"] == "root"), None)
chk("P4 扁平 id 列表照旧：id 一字不改、一级分支 3",
    ferr is None and flat_root is not None
    and flat_root["children"] == ["t1", "t2", "t3"]
    and vn._mindmap_top_branches(flat_mm or {}) == 3,
    ferr if ferr else flat_root)


# ── P5：对照 —— 旧判据确实会误判（证明这条门禁不是空转）────────────
old_nodes = vn._normalize_nodes(PROMPT_PAYLOAD["nodes"])
old_ids = {n["id"] for n in old_nodes}
old_root = next((n for n in old_nodes if n["id"] == "root"), None)
old_map = {"version": 1, "title": "示例视频总结", "root": "root", "nodes": old_nodes}
chk("P5 对照：只看「有没有 children」的旧判据把示例判成 0 个一级分支",
    vn._mindmap_top_branches(old_map) == 0
    and old_root is not None and bool(old_root["children"])
    and all(c not in old_ids for c in old_root["children"]),
    old_root)

print()
print("视频导图嵌套 children：通过 %d 项，失败 %d 项" % (PASSED, len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  ✗ " + f)
    shutil.rmtree(str(SANDBOX), ignore_errors=True)
    sys.exit(1)
shutil.rmtree(str(SANDBOX), ignore_errors=True)
print("ok  提示词示例那种嵌套 children 不再被误判成扁平表、不再退成摘要兜底")
