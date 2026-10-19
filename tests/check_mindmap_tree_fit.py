# -*- coding: utf-8 -*-
"""括号图（tree）布局：父框比孩子那一摞还高时，整支要挪进自己的格子。

为什么单开一条：`tests/check_mindmap.py` 那条「任意两个框都不重叠」用的是短文字的
固定夹具，走不到这一格。用户真报过的形状（1.2.0「节点文字一多，框就挤在一起」）
在括号图里有更细的一种：**父节点文字很长、名下一个短孩子**时，父框自己比孩子那一摞
高得多。老写法把父框「居中」到孩子中点，于是它的顶边跑到这一支的起点上面去，直接
压在上一支的框上（实测 190px 高的父框压住下一个分支的 37px 框，重叠 28px，两行字
糊在一起）。新写法把整支一起下移，并把「这一支占到哪里」按父框底重新算。

这条门禁钉三件事：
  ① 触发形状下老算法**确实重叠**（对照，证明这一格不是空转）；
  ② 触发形状与随机树上，新算法一个重叠都没有，同列相邻框仍留 ≥20px 的缝；
  ③ 老算法本来就不重叠的图，新算法坐标**逐字相同** —— 修的是坏形状，好形状一个
     像素都不许动（四种形态的差分断言、用户手里已有的图都靠这条）。

跑法：`.venv/bin/python tests/check_mindmap_tree_fit.py`
"""
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import mindmap as mm  # noqa: E402

FAIL = []
COUNT = [0]


def chk(name, cond, extra=""):
    COUNT[0] += 1
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if not cond:
        FAIL.append(name)


def _overlaps(a, b):
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def _overlap_pairs(boxes):
    return [(boxes[i]["id"], boxes[j]["id"])
            for i in range(len(boxes)) for j in range(i + 1, len(boxes))
            if _overlaps(boxes[i], boxes[j])]


def _same_col_min_gap(boxes):
    """同一列（同 depth、横向重叠）相邻两框之间的最小缝；量不到回 None。"""
    gaps = []
    for depth in {b["depth"] for b in boxes}:
        col = sorted([b for b in boxes if b["depth"] == depth], key=lambda b: b["y"])
        for a, b in zip(col, col[1:]):
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]:
                gaps.append(b["y"] - (a["y"] + a["h"]))
    return min(gaps) if gaps else None


def _by(boxes, bid):
    return next(b for b in boxes if b["id"] == bid)


def _old_tree_boxes(doc):
    """修复前 `_place_tree` 的算法原文（照抄，只把闭包拆成参数）。

    拿它当对照：同一份文档老算法排出重叠、新算法排不出来，才说明这一格真的修到了。
    返回值里的 `fixed` 是「老算法需要纠正几次」：父框顶边高过这一支的起点、或父框
    底边比孩子那一摞还低，各算一次。一次都不需要纠正的图，新算法必须逐字相同。
    """
    d = mm.normalize(doc)
    entries = mm._visible(d)
    boxes = mm._make_boxes(entries)
    kids = mm._kids_of(boxes)
    byid = {b["id"]: b for b in boxes}
    roots = [b["id"] for b in boxes if b["parent"] is None]
    cols = []
    fixed = [0]

    def rec(bid, depth, y):
        b = byid[bid]
        while len(cols) <= depth:
            cols.append(0.0)
        cols[depth] = max(cols[depth], b["w"])
        ck = kids.get(bid) or []
        if not ck:
            b["y"] = y
            return y + b["h"] + mm._V_GAP
        cur = y
        for kid in ck:
            cur = rec(kid, depth + 1, cur)
        first, last = byid[ck[0]], byid[ck[-1]]
        b["y"] = (mm._center(first)[1] + mm._center(last)[1]) / 2.0 - b["h"] / 2.0
        if b["y"] < y or b["y"] + b["h"] + mm._V_GAP > cur:
            fixed[0] += 1
        return cur

    y = 0.0
    for root in roots:
        y = rec(root, 0, y) + mm._ROOT_GAP
    x = 0.0
    for depth in range(len(cols)):
        for b in boxes:
            if b["depth"] == depth:
                b["x"] = x
        x += (cols[depth] if cols[depth] else 120.0) + mm._COL_GAP
    mm._fit(boxes, d["title"])
    return boxes, fixed[0]


def _new_tree_boxes(doc):
    return mm.layout(doc, "tree")["boxes"]


def _coords(boxes):
    # layout() 把坐标统一收到 0.1 像素（浮点尾巴不写进给前端的 JSON），
    # 对照那一份得按同一把尺子收一遍，否则比的是「有没有四舍五入」而不是布局。
    return {b["id"]: (round(b["x"], 1), round(b["y"], 1)) for b in boxes}


def node(nid, text, kids=None):
    return {"id": nid, "text": text, "children": kids or []}


# ── 触发形状：一个长文字的父节点 + 一个短孩子，后面还有别的分支 ──────────
_LONG = "这是一个很长很长的节点文字" * 12
TRIGGER = {"title": "", "form": "tree", "nodes": [
    node("r", "根", [
        node("a", _LONG, [node("a1", "短")]),
        node("b", "第二个分支", [node("b1", "短2"), node("b2", "短3")]),
        node("c", "第三个分支", [node("c1", "短4")]),
    ]),
]}

_old, _old_fixed = _old_tree_boxes(TRIGGER)
_new = _new_tree_boxes(TRIGGER)
_bad_old = _overlap_pairs(_old)
chk("对照：老写法在这个形状下确实把父框压到下一支身上", bool(_bad_old), _bad_old[:3])
chk("对照：压住的是长文字那个父框与它后面那一支（不是别的巧合）",
    any({x, y} == {"a", "b"} for x, y in _bad_old), _bad_old[:3])
chk("新写法：同一个形状一个重叠都没有", not _overlap_pairs(_new), _overlap_pairs(_new)[:3])
_gap = _same_col_min_gap(_new)
chk("新写法：同列相邻框仍留 ≥20px 的缝（不是把框贴成一摞）",
    _gap is not None and _gap >= 20.0 - 0.01, _gap)
chk("新写法：孩子仍在父节点正中间（父框挪动时整支一起走）",
    abs(mm._center(_by(_new, "a"))[1] - mm._center(_by(_new, "a1"))[1]) < 0.11,
    (mm._center(_by(_new, "a"))[1], mm._center(_by(_new, "a1"))[1]))
chk("新写法：父框把这一支的底也管住（下一支从父框底下开始，不从孩子底下）",
    _by(_new, "b")["y"] >= _by(_new, "a")["y"] + _by(_new, "a")["h"],
    (_by(_new, "b")["y"], _by(_new, "a")["y"] + _by(_new, "a")["h"]))
chk("新写法：别的支内部相对位置一字不动",
    abs((_by(_new, "b1")["y"] - _by(_new, "b")["y"])
        - (_by(_old, "b1")["y"] - _by(_old, "b")["y"])) < 0.11, None)


# ── 好形状一个像素都不许动：老算法排得开的图，新算法坐标逐字相同 ──────────
def _gen_docs(seed=20261019, n=60):
    """固定种子的随机树：宽 / 窄 / 深 / 浅都有，专门覆盖「父框高于孩子摞」这一面。"""
    rnd = random.Random(seed)
    texts = ["短", "中等长度的节点", _LONG, _LONG[:40], "A B C d e f", "一句话……"]
    docs = []
    for _ in range(n):
        counter = [0]

        def build(depth):
            counter[0] += 1
            nid = "n%d" % counter[0]
            kids = []
            if depth < 4:
                for _k in range(rnd.randint(0, 3)):
                    kids.append(build(depth + 1))
            return node(nid, rnd.choice(texts), kids)

        docs.append({"title": rnd.choice(["", "图"]), "form": "tree",
                     "nodes": [build(0) for _ in range(rnd.randint(1, 2))]})
    return docs


_DOCS = _gen_docs()
_same_bad, _fixed_ok, _fixed_bad, _not_inside, _moved_up, _no_fix_same = [], 0, [], [], [], 0
for _i, _doc in enumerate(_DOCS):
    _o, _fixed = _old_tree_boxes(_doc)
    _n = _new_tree_boxes(_doc)
    if _fixed == 0:
        _no_fix_same += 1
        if _coords(_o) != _coords(_n):
            _same_bad.append((_i, [(k, _coords(_o)[k], _coords(_n)[k])
                                   for k in _coords(_o) if _coords(_o)[k] != _coords(_n)[k]][:2]))
    elif _overlap_pairs(_o):
        if _overlap_pairs(_n):
            _fixed_bad.append((_i, _overlap_pairs(_n)[:2]))
        else:
            _fixed_ok += 1
    for _k in _coords(_n):
        if _coords(_n)[_k][1] < _coords(_o)[_k][1] - 0.01:
            _moved_up.append((_i, _k))
    _lay = mm.layout(_doc, "tree")
    for _b in _lay["boxes"]:
        if not (_b["w"] > 0 and _b["h"] > 0 and _b["x"] >= 0 and _b["y"] >= 0
                and _b["x"] + _b["w"] <= _lay["width"] + 0.01
                and _b["y"] + _b["h"] <= _lay["height"] + 0.01):
            _not_inside.append((_i, _b["id"]))

chk("随机 %d 份图：老算法一次都不用纠正的那些，新算法坐标逐字相同（%d 份）"
    % (len(_DOCS), _no_fix_same), not _same_bad and _no_fix_same >= 10, _same_bad[:2])
chk("随机 %d 份图：老算法压在一起的都真被碰到了（对照不是空转，%d 份）"
    % (len(_DOCS), _fixed_ok), _fixed_ok >= 3, _fixed_ok)
chk("随机 %d 份图：新算法排完一个重叠都没有" % len(_DOCS), not _fixed_bad, _fixed_bad[:2])
chk("随机 %d 份图：没有任何框被往上挪（只把挤住的往下让）" % len(_DOCS),
    not _moved_up, _moved_up[:3])
chk("随机 %d 份图：框都是有限正数且落在画布内" % len(_DOCS), not _not_inside, _not_inside[:3])

# 多根：几棵互不相干的树竖着排，一支变高不许压到下一棵树
_MULTI = {"title": "", "form": "tree", "nodes": [
    node("t1", _LONG, [node("t1a", "孩子")]),
    node("t2", "第二棵", [node("t2a", "另一支")]),
]}
_mb = _new_tree_boxes(_MULTI)
chk("多根：几棵树之间也不重叠", not _overlap_pairs(_mb), _overlap_pairs(_mb)[:3])
chk("多根：老算法在这一份上同样需要纠正（多根走的是同一条修法）",
    _old_tree_boxes(_MULTI)[1] > 0)
chk("多根：第二棵从第一棵的父框底下开始",
    _by(_mb, "t2")["y"] >= _by(_mb, "t1")["y"] + _by(_mb, "t1")["h"],
    (_by(_mb, "t2")["y"], _by(_mb, "t1")["y"] + _by(_mb, "t1")["h"]))

# ── 收摊 ───────────────────────────────────────────────────────────
print()
print("括号图父亲档位：%d 项通过，失败 %d 项" % (COUNT[0] - len(FAIL), len(FAIL)))
if FAIL:
    print("失败：%s" % "、".join(FAIL))
    sys.exit(1)
print("全部通过")
