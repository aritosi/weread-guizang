#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 导图的深度上限：MAP_SYS 对模型说的「最深 MAX_DEPTH 层」，`_clean_node` 就得真削到那么多层。

为什么要单开一条
    `tests/check_ai_sum.py` 里早有一条「超过最大深度的那几层直接削掉」，但它喂的
    深树是 `{"label": "L1", "kids": [...]}` —— **没有 `root` 键**。`parse_map` 于是
    走「模型没给出导图」那条路，退回 `head_tree` 的兜底树（最多三层），`_clean_node`
    一次都没被调用，那条断言永远为真。真喂一棵带 `root` 的深树，旧判据
    `if depth >= MAX_DEPTH: return node` 配「根节点是第 0 层」就多留了一层：
    MAX_DEPTH=4 时画出 5 层，与 MAP_SYS 对模型说的「整棵树最深 4 层」、以及
    mindmap.py 那把尺子（`MAX_DEPTH = 8`，注释写明「留 depth 0..7」）都不是同一个数。

这一条钉住
  · **对照（不是空转）**：把老判据在本地重抄一遍，同一棵带 `root` 的深树喂进去
    确实得到 MAX_DEPTH+1 层 —— 证明上面那条既有断言量不到它；
  · **既有断言为什么量不到**：它喂的那棵深树没有 `root` 键，`parse_map` 走兜底树，
    警告非空、根标签是标题而不是树自己的；
  · **新写法**：`parse_map` 出来的树正好 MAX_DEPTH 层；第 MAX_DEPTH 层那个节点还在
    （是叶子，内容不丢），它下面没有孩子，更深的标签一个都不剩；
  · 层数没到上限的好树一个字不改（分支名与顺序全保留、warn 为空）；
  · 模型没给导图、退回 `head_tree` 的兜底树照旧不超过 MAX_DEPTH。

全离线、只碰内存，不联网、不起服务，归静态段。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_sum as A  # noqa: E402

FAIL = []


def chk(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if not cond:
        FAIL.append(name)


def depth(node):
    """树的层数：只有一个节点算 1 层（与 check_ai_sum.py 同一把尺子）。"""
    kids = (node or {}).get("kids") or []
    return 1 + max([depth(k) for k in kids], default=0)


def labels(node):
    """把整棵树的 label 收成一个列表，用来验「更深那几层一个都不剩」。"""
    return [node.get("label")] + [x for k in (node.get("kids") or []) for x in labels(k)]


def old_clean(raw, d):
    """老判据的镜子：与修之前 `_clean_node` 逐行同形（根传 0，收尾写 `d >= MAX_DEPTH`）。"""
    if not isinstance(raw, dict):
        return None
    label = re.sub(r"\s+", " ", str(raw.get("label") or raw.get("text") or "")).strip()
    if not label:
        return None
    node = {"label": label[:A.MAP_LEAF * 2], "kids": []}
    if d >= A.MAX_DEPTH:
        return node
    kids = raw.get("kids")
    if not isinstance(kids, list):
        kids = raw.get("children")
    if isinstance(kids, list):
        for k in kids:
            built = old_clean(k, d + 1)
            if built is not None:
                node["kids"].append(built)
    return node


def deep_root(levels):
    """造一棵带 `root` 键、主链正好 levels 层的深树。

    根上另外挂两个兄弟，凑够 MIN_BRANCHES —— 否则会掉进「分支太少」的兜底 / 合并
    支路，量的就不是 `_clean_node` 自己的截断了。
    """
    root = {"label": "L0", "kids": []}
    cur = root
    for i in range(1, levels):
        nxt = {"label": "L%d" % i, "kids": []}
        cur["kids"] = [nxt]
        cur = nxt
    root["kids"].append({"label": "B1", "kids": []})
    root["kids"].append({"label": "B2", "kids": []})
    return root


DEEP = deep_root(A.MAX_DEPTH + 3)          # 比上限深三层的模型树

# ── 1. 对照：老判据确实多留一层（这条门禁不是空转） ──────────────────────
old_tree = old_clean(DEEP, 0)
chk("对照：老判据把带 root 的深树留到 MAX_DEPTH+1 层（多一层）",
    depth(old_tree) == A.MAX_DEPTH + 1, (depth(old_tree), A.MAX_DEPTH))

# ── 2. 既有那条断言喂的深树没有 root 键，量的是兜底树 ────────────────────
vac = {"label": "L0", "kids": [{"label": "L1", "kids": []}]}
vac_tree, vac_warn = A.parse_map(json.dumps(vac, ensure_ascii=False), "标题", "")
chk("既有断言那种形状（没有 root 键）走的是兜底树：警告非空、根标签是标题",
    vac_warn != "" and vac_tree.get("label") == "标题" and "L0" not in labels(vac_tree),
    (vac_warn, vac_tree.get("label")))

# ── 3. 新写法：带 root 的深树削到正好 MAX_DEPTH 层，末层节点留着当叶子 ────
tree, warn = A.parse_map(json.dumps({"root": DEEP}, ensure_ascii=False), "标题", "")
chk("新写法：模型给的超深树削到正好 MAX_DEPTH 层",
    depth(tree) == A.MAX_DEPTH, (depth(tree), A.MAX_DEPTH))
chk("新写法：第 MAX_DEPTH 层那个节点还在（是叶子，内容不丢）",
    "L%d" % (A.MAX_DEPTH - 1) in labels(tree)
    and tree["kids"][0]["kids"][0]["kids"][0]["kids"] == [],
    labels(tree))
chk("新写法：更深那几层的标签一个都不剩",
    all(("L%d" % i) not in labels(tree) for i in range(A.MAX_DEPTH, A.MAX_DEPTH + 3)),
    labels(tree))
chk("新写法：合格的深树不报「模型没给出导图」（走的不是兜底支路）",
    warn == "" and len(tree["kids"]) == A.MIN_BRANCHES, (warn, tree.get("kids")))

# ── 4. 层数没到上限的好树一个字不改 ─────────────────────────────────────
good = {"root": {"label": "中心", "kids": [
    {"label": "甲", "kids": [{"label": "甲一", "kids": []}]},
    {"label": "乙", "kids": []},
    {"label": "丙", "kids": []}]}}
gt, gw = A.parse_map(json.dumps(good, ensure_ascii=False), "标题", "")
chk("回归：三层的好树分支名与顺序一字不改、无警告",
    [k["label"] for k in gt["kids"]] == ["甲", "乙", "丙"]
    and gt["kids"][0]["kids"][0]["label"] == "甲一" and gw == "",
    (gt, gw))

# ── 5. 兜底树照旧不超过上限 ────────────────────────────────────────────
fb_tree, fb_warn = A.parse_map("这一轮不是 JSON，模型没给出导图。", "标题",
                               "# 第一节\n讲点甲。\n\n# 第二节\n讲点乙。\n\n# 第三节\n讲点丙。\n")
chk("回归：模型没给导图时退回的原文目录树不超过 MAX_DEPTH 层、且出声",
    depth(fb_tree) <= A.MAX_DEPTH and len(fb_tree["kids"]) >= A.MIN_BRANCHES and fb_warn != "",
    (depth(fb_tree), fb_warn))

# ── 6. 提示词里对模型说的层数与这把尺子是同一个数 ──────────────────────
chk("接线：MAP_SYS 对模型说的「最深 MAX_DEPTH 层」用的就是 MAX_DEPTH",
    ("最深 %d 层" % A.MAX_DEPTH) in A.MAP_SYS, A.MAP_SYS)

print()
print("AI 导图深度上限体检：" + ("全部通过" if not FAIL else "%d 项未过：%s" % (len(FAIL), FAIL)))
sys.exit(1 if FAIL else 0)
