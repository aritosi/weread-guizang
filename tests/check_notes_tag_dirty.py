#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：notes.json 里 `tag` 字段的形状脏了，不许把整份笔记打不开。

`book_notes._mark_row` / `_entry_row` 是读盘（`load_notes`）与存盘（`_normalize`）
共用的字段收口尺子。同一处别的字段早就各有收口（`kind` 走元组、`ch` / `text` /
`color` 走 `_clip` / `_hex`、时间戳走 `_stamp`），只有 `tag` 是裸的

    m.get("tag") if m.get("tag") in TAG_BY_KEY else ""

`TAG_BY_KEY` 是 dict，成员测试要求键可哈希。notes.json 就住在这本书的目录里，
用户手改得动，云同步也会整份回写 —— `"tag": []`（或 `{}`）一次就抛
`TypeError: unhashable type: 'list'`。这一句跑在 `load_notes` 里**文件读盘那段
try 的外面**（形状收口是那之后的事），于是异常一路穿到 `/api/mynotes`：用户看到
的是「这本书的笔记一屏打不开」，而盘上那份数据其实是好的。

这一条钉四层：
  A 对照：`[] in TAG_BY_KEY` / `{} in TAG_BY_KEY` 确实 TypeError（证明不是空想）；
  B 读盘：list / dict 形状的 tag 读得开、条目一条不少、认得出的 tag 照认、
    认不出的回空串（不编一支）；
  C 下游：export_markdown / note_tree（tag 与 chapter 两种切法）/ mindmap 都不抛；
  D 写盘与好值回归：`_normalize` 收到脏 tag 不抛；好 tag / `tag_name` 中文名回退
    一个字不改。

纯函数 + 临时书目录，不 import 服务、不联网、不开浏览器，归 --fast。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import book_notes as bn  # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:220]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def write_raw(book_dir, doc):
    with open(os.path.join(book_dir, bn.NOTES_FILE), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def try_call(fn):
    try:
        fn()
        return True, ""
    except Exception as e:                           # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def field_at(seq, i, key):
    """第 i 条的某个字段；越界 / 不是对象回 None（这样修前的空表也能走成干净的 FAIL，
    而不是在断言里 IndexError 中断整条门禁）。"""
    if not isinstance(seq, list) or not (0 <= i < len(seq)) or not isinstance(seq[i], dict):
        return None
    return seq[i].get(key)


# ── A. 对照：旧写法遇到不可哈希的 tag 确实抛 ────────────────────
for _bad in ([], {}, ["point"], {"key": "point"}):
    _ok, _err = try_call(lambda v=_bad: v in bn.TAG_BY_KEY)
    chk("A 对照：`%r in TAG_BY_KEY` 确实 TypeError" % (_bad,),
        not _ok and "TypeError" in _err, _err)

DIRTY = {
    "marks": [
        {"id": "m1", "text": "第一句", "ch": "0001.md", "tag": []},
        {"id": "m2", "text": "第二句", "ch": "0001.md", "tag": {"key": "point"}},
        {"id": "m3", "text": "第三句", "ch": "0001.md", "tag": "point"},
        {"id": "m4", "text": "第四句", "ch": "0001.md", "tag": 5},
        {"id": "m5", "text": "第五句", "ch": "0001.md", "tag": None},
        # 中文名回退：tag 坏了也应该照旧能靠 tag_name 认回来
        {"id": "m6", "text": "第六句", "ch": "0001.md", "tag": [], "tag_name": "疑问"},
    ],
    "entries": [
        {"id": "n1", "title": "条目", "body": "正文", "tag": {}},
        {"id": "n2", "title": "条目2", "body": "正文", "tag": "doubt"},
        {"id": "n3", "title": "条目3", "body": "正文", "tag": ["doubt"]},
        {"id": "n4", "title": "条目4", "body": "正文", "tag": "不存在的那个标签"},
    ],
}

# ── B. 读盘：脏 tag 读得开、一条不丢、认得出的照认 ──────────────
with tempfile.TemporaryDirectory(prefix="gz-notes-tag-") as td:
    write_raw(td, DIRTY)
    try:
        doc = bn.load_notes(td)
        chk("B1 脏 tag 不抛：load_notes 读得开", True)
    except Exception as e:                           # noqa: BLE001
        doc = {"marks": [], "entries": []}
        chk("B1 脏 tag 不抛：load_notes 读得开", False, "%s: %s" % (type(e).__name__, e))

    chk("B2 六条划线一条不少（一个坏 tag 不带走整条）",
        [m.get("id") for m in doc["marks"]] == ["m1", "m2", "m3", "m4", "m5", "m6"],
        doc["marks"])
    chk("B3 四条条目一条不少",
        [e.get("id") for e in doc["entries"]] == ["n1", "n2", "n3", "n4"], doc["entries"])
    chk("B4 读回来的 tag 全是字符串（下游 TAG_BY_KEY.get 才不抛）",
        all(isinstance(m.get("tag"), str) for m in doc["marks"])
        and all(isinstance(e.get("tag"), str) for e in doc["entries"]),
        [m.get("tag") for m in doc["marks"]] + [e.get("tag") for e in doc["entries"]])
    chk("B5 认得出的 tag 照认（point / doubt 原样）",
        field_at(doc["marks"], 2, "tag") == "point"
        and field_at(doc["entries"], 1, "tag") == "doubt",
        (field_at(doc["marks"], 2, "tag"), field_at(doc["entries"], 1, "tag")))
    chk("B6 认不出的 tag 回空串（不编一支笔）",
        [field_at(doc["marks"], i, "tag") for i in (0, 1, 3, 4)] == ["", "", "", ""]
        and field_at(doc["entries"], 0, "tag") == ""
        and field_at(doc["entries"], 2, "tag") == ""
        and field_at(doc["entries"], 3, "tag") == "",
        ([m.get("tag") for m in doc["marks"]], [e.get("tag") for e in doc["entries"]]))
    chk("B7 中文名回退不受影响：tag 坏了也能靠 tag_name 认回疑问",
        field_at(doc["marks"], 5, "tag") == "doubt", doc["marks"][5:6])
    chk("B8 坏 tag 不影响同条别的字段（正文 / 章节照旧）",
        field_at(doc["marks"], 0, "text") == "第一句"
        and field_at(doc["marks"], 0, "ch") == "0001.md", doc["marks"][:1])

# ── C. 下游：导出与导图都不许被一个坏 tag 带走 ──────────────────
with tempfile.TemporaryDirectory(prefix="gz-notes-tag-down-") as td:
    write_raw(td, DIRTY)
    try:
        doc = bn.load_notes(td)
    except Exception as e:                           # noqa: BLE001
        doc = {"marks": [], "entries": []}
        chk("C0 读盘这一步本身不抛（下游才有得跑）", False,
            "%s: %s" % (type(e).__name__, e))
    for label, fn in (
        ("C1 export_markdown 不抛", lambda: bn.export_markdown(doc)),
        ("C2 note_tree(cut=tag) 不抛", lambda: bn.note_tree(doc, cut="tag")),
        ("C3 note_tree(cut=chapter) 不抛", lambda: bn.note_tree(doc, cut="chapter")),
        ("C4 mindmap 不抛", lambda: bn.mindmap(td, doc)),
        ("C5 export_notes 不抛且真的落盘",
         lambda: bn.export_notes(td, doc)),
    ):
        ok, err = try_call(fn)
        chk(label, ok, err)
    chk("C6 notes.md 真的生成了", os.path.isfile(os.path.join(td, bn.EXPORT_MD)))

# ── D. 写盘同口径 + 好值一个字不改 ──────────────────────────────
ok, err = try_call(lambda: bn._normalize({
    "marks": [{"text": "x", "tag": []}, {"text": "y", "tag": {"a": 1}},
              {"text": "z", "tag": "quote"}],
    "entries": [{"id": "n", "title": "t", "body": "b", "tag": []}]}))
chk("D1 _normalize 收到脏 tag 不抛", ok, err)
if ok:
    out = bn._normalize({"marks": [{"text": "x", "tag": []},
                                   {"text": "y", "tag": {"a": 1}},
                                   {"text": "z", "tag": "quote"}]})
    chk("D2 写盘那一侧脏 tag 也回空串、好 tag 照留",
        [m["tag"] for m in out["marks"]] == ["", "", "quote"],
        [m["tag"] for m in out["marks"]])

with tempfile.TemporaryDirectory(prefix="gz-notes-tag-good-") as td:
    write_raw(td, {"marks": [{"id": "ok", "text": "原样", "ch": "0002.md",
                              "created_at": 1756864800, "tag": "quote",
                              "kind": "bold", "color": "#AABBCC", "memo": "备注"}],
                   "entries": [{"id": "n", "title": "题", "body": "正文",
                                "tag": "idea"}]})
    doc = bn.load_notes(td)
    m = doc["marks"][0]
    chk("D3 好数据一个字不改（tag / 类型 / 颜色 / 备注 / 时间戳）",
        m["tag"] == "quote" and m["kind"] == "bold" and m["color"] == "#AABBCC"
        and m["memo"] == "备注" and m["text"] == "原样"
        and m["created_at"] == 1756864800 and doc["entries"][0]["tag"] == "idea", m)

print()
print("笔记 tag 脏形状收口：通过 %d 项，失败 %d 项" % (PASSED, len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
print("ok  tag 脏形状读得开、条目不丢、认得出的照认、下游不抛")
