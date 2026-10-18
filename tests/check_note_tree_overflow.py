# -*- coding: utf-8 -*-
"""笔记树封顶不许静默丢条目（book_notes.note_tree 的 `笔记条目` 分支与 `cut=entry`）。

为什么单开这一条：`_LEAF_PER_BRANCH = 14` 是「图太密就没法看」的封顶，但封顶必须
在图上说出「还有 N 条」。标签分组那一支一直有这么一句，笔记条目那两支却是直接
`entries[:14]` / `entries[:28]` —— 用户的第 15 条（`cut=entry` 是第 29 条）以后
凭空消失，界面上也看不出是「本来就没有」还是「被裁掉了」。两种表现属于同一件事，
尺子只留一处真相（`_more_node`）。

这条门禁钉三件事：
  A 默认切法下 20 条 = 14 片叶子 + 一句「还有 6 条」，剩余数必须是真的；
  B `cut=entry` 下 40 条 = 28 个分支 + 一句「还有 12 条」；
  C **对照**：把旧写法（直接切片、不补那句）在同一份输入上跑一遍，它确实少条目 ——
    这条门禁不是空转，量得到「旧代码把一个真实用户条目吞掉」。

外加：不足封顶时不该凭空多一句「还有 0 条」；标签分组那一支的同类那半句照旧；
生成到 SVG 里那句也真的看得见、且仍是合法 XML。

纯逻辑套件：不起服务、不开浏览器、不联网，不碰用户书库。
跑法：.venv/bin/python tests/check_note_tree_overflow.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SANDBOX = tempfile.mkdtemp(prefix="gz-note-overflow-check-")
atexit.register(lambda: shutil.rmtree(SANDBOX, ignore_errors=True))

import book_notes as bn  # noqa: E402

FAIL = []
N = 0


def chk(name, cond, extra=""):
    global N
    N += 1
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:220]))
    if not cond:
        FAIL.append(name)


def entries(n, title="条"):
    return [{"id": "n%d" % i, "title": title + str(i), "body": ""} for i in range(n)]


def branch(tree, label):
    return next((k for k in tree["kids"] if k["label"] == label), None)


def leaf_labels(node):
    return [k["label"] for k in node["kids"]]


# ── 对照：旧写法（直接切片）确实把条目吞掉 ─────────────────────────
def old_entry_branch(doc):
    """复刻改动前的写法：`entries[:_LEAF_PER_BRANCH]` 直接进树，不补那句。"""
    es = [bn._node(bn._clip(e.get("title") or "无标题", 40),
                   [bn._node(h) for h in bn._headings(e.get("body"))])
          for e in doc["entries"][:bn._LEAF_PER_BRANCH]]
    return bn._node("笔记条目", es, color="#8fb7a6")


doc20 = {"marks": [], "entries": entries(20)}
old = old_entry_branch(doc20)
chk("对照：旧写法在 20 条时只画得出 14 个条目节点（少了 6 条，也没说少）",
    len(old["kids"]) == bn._LEAF_PER_BRANCH
    and not any("还有" in k["label"] for k in old["kids"]),
    leaf_labels(old)[-1:])

# ── A 默认切法（tag / chapter）：封顶 + 如实报剩余 ────────────────
tree = bn.note_tree(doc20)
b = branch(tree, "笔记条目")
chk("默认切法：`笔记条目` 分支被建出来了", b is not None)
chk("默认切法：20 条里画出的叶子数就是封顶数 14",
    b is not None and len([k for k in b["kids"] if "还有" not in k["label"]])
    == bn._LEAF_PER_BRANCH, leaf_labels(b) if b else None)
chk("默认切法：末尾补了一句「还有 6 条」",
    b is not None and b["kids"][-1]["label"] == "还有 6 条",
    leaf_labels(b) if b else None)
chk("默认切法：14 片叶子 + 1 句剩余 = 15 个节点（第 15 条以后没被静默吞掉）",
    b is not None and len(b["kids"]) == bn._LEAF_PER_BRANCH + 1,
    len(b["kids"]) if b else None)

# chapter 切法走同一条条目分支，剩余那句必须一样在
tree_ch = bn.note_tree(doc20, cut="chapter")
bch = branch(tree_ch, "笔记条目")
chk("chapter 切法：同样补出「还有 6 条」",
    bch is not None and bch["kids"][-1]["label"] == "还有 6 条",
    leaf_labels(bch) if bch else None)

# ── B cut=entry：条目自己就是一级分支，同样封顶 + 报剩余 ──────────
tree40 = bn.note_tree({"marks": [], "entries": entries(40)}, cut="entry")
chk("cut=entry：40 条里画出 28 个分支（2 x _LEAF_PER_BRANCH）",
    len([k for k in tree40["kids"] if "还有" not in k["label"]])
    == bn._LEAF_PER_BRANCH * 2, len(tree40["kids"]))
chk("cut=entry：末尾补了一句「还有 12 条」",
    tree40["kids"][-1]["label"] == "还有 12 条", leaf_labels(tree40)[-2:])

# ── 不足封顶：不许凭空多一句「还有 0 条」 ─────────────────────────
for n in (0, 1, bn._LEAF_PER_BRANCH - 1, bn._LEAF_PER_BRANCH):
    t = bn.note_tree({"marks": [], "entries": entries(n)})
    bb = branch(t, "笔记条目")
    if n == 0:
        chk("0 条：连「笔记条目」分支都不建（不留一句空话）", bb is None)
        continue
    chk("%d 条（封顶 %d 以内）：画出全部 %d 条、且没有多余的「还有」"
        % (n, bn._LEAF_PER_BRANCH, n),
        bb is not None and len(bb["kids"]) == n
        and not any("还有" in k["label"] for k in bb["kids"]),
        leaf_labels(bb) if bb else None)
t14 = bn.note_tree({"marks": [], "entries": entries(bn._LEAF_PER_BRANCH)}, cut="entry")
chk("cut=entry：正好 %d 条时也没有「还有」" % bn._LEAF_PER_BRANCH,
    len(t14["kids"]) == bn._LEAF_PER_BRANCH
    and not any("还有" in k["label"] for k in t14["kids"]), leaf_labels(t14)[-1:])

# ── 标签分组那一支的同类那半句照旧（同一把尺子，不是只改了条目）──
marks20 = {"marks": [{"id": "m%d" % i, "text": "划线%d" % i, "tag": "quote"}
                     for i in range(20)], "entries": []}
tm = bn.note_tree(marks20)
g = tm["kids"][0]
chk("划线分组：仍然补「还有 6 条」（改动没有把它带坏）",
    g["kids"][-1]["label"] == "还有 6 条", leaf_labels(g)[-1:])

# ── C 真的走到 SVG：那句在成品里看得见，且仍是合法 XML ───────────
svg = bn.build_mindmap_svg(tree, "一本书")
chk("生成的 SVG 里看得见「还有 6 条」（不是只活在 Python 对象里）",
    "还有 6 条" in svg)
try:
    ET.fromstring(svg)
    chk("补了剩余那句之后 SVG 仍是合法 XML", True)
except Exception as e:                                     # noqa: BLE001
    chk("补了剩余那句之后 SVG 仍是合法 XML", False, e)

# ── D 一处真相：三处都从 _more_node 取，不再各写各的字符串 ───────
src = (REPO / "book_notes.py").read_text(encoding="utf-8")
chk("源码：`还有 %d 条` 这个格式只在 _more_node 里出现一次",
    src.count('"还有 %d 条"') == 1, src.count('"还有 %d 条"'))
chk("源码：三处封顶（标签分组 / 笔记条目 / cut=entry）都调 _more_node",
    src.count("_more_node(") >= 4, src.count("_more_node("))

print()
print("笔记树封顶不静默丢条目：跑了 %d 条断言" % N)
if FAIL:
    print("失败 %d 项：%s" % (len(FAIL), "、".join(FAIL)))
    sys.exit(1)
print("全部通过")
