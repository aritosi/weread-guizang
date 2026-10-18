#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：便签标签「认得出就要摘得掉」，以及两把 drop_lone_surrogates 的字典键。

两块都是「一把尺子只留一份」那一族，各修一处真跑得出来的毛病。

一、标签的收尾字符
    `extract_tags` 认标签时，收尾用的是 `PUNCT_TAIL` 加斜杠 —— `#灵感】` 里的 `】`、
    `#灵感/` 里的 `/` 都会被摘掉，标签记成「灵感」。而 `strip_inline_tags` 摘标签时
    那句 lookahead 是从 `PUNCT_TAIL` **手抄**的一份子集，漏了 `】」』>/` 与制表空格。
    于是同一个 `#灵感】`：标签账上收下了它，正文里却摘不掉 —— 收成书时它进了书名与
    正文（同一条里出现三遍），MCP / Agent 读到的 `plain` 也带着它。这一条要求
    「抽得出来 ⟺ 摘得掉」，并逐字符钉住 `PUNCT_TAIL` 与 `/` `#` 的每一种收尾。

二、字典键上的坏码
    `flomo_notes.drop_lone_surrogates` 与 `book_layout.drop_lone_surrogates` 逐层洗
    字典时只洗了值、没洗键。`json.dump(..., ensure_ascii=False)` 编码的是整份对象，
    键上带一个落单的代理码点，两个写口都当场 `UnicodeEncodeError`：便签的
    `add_memo` / `save` 全抛，整屏便签变成只读；`ui_server._write_json` 那条
    「抛了就拿 `book_layout.drop_lone_surrogates` 再写一遍」的兜底也照样抛。脏键来自
    手改 / 云同步落回来的账 —— 合法 JSON 里的 `"\\ud800"` 转义读得进来。

    成对的代理码点在 `json.load` 那一步早合成一个真字符了，这里只会摘到落单的坏码。

跑法：纯函数 + 系统临时目录，不联网、不起服务、不碰真实 cache/，归 --fast 静态段。
"""
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flomo_notes as fn      # noqa: E402
import book_layout as bl      # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


HI = "\ud800"          # 落单的高位代理码点
LO = "\udfff"          # 落单的低位代理码点
EMOJI = "\U0001f600"   # 成对合成后的真 emoji（不该被动）
ROOT = tempfile.mkdtemp(prefix="guizang-flomo-tagkeys-")


# ── A：标签认得出与摘得掉必须是同一把尺子 ───────────────────────────
print("── A：认得出的标签，必须摘得掉 ──")

# A1 逐字符覆盖 extract_tags 的收尾集合：每一个都该「认出来」并且「摘掉」。
for ch in fn.PUNCT_TAIL + "/#":
    text = "记一笔 #读书" + ch
    recognized = fn.extract_tags(text) == ["读书"]
    stripped = "#读书" not in fn.strip_inline_tags(text, ["读书"])
    chk("A1 收尾 %r：认得出来（%s）且摘得掉" % (ch, recognized),
        recognized and stripped, fn.strip_inline_tags(text, ["读书"]))

# A2 名字里带斜杠的层级标签照旧整段摘掉；`#/读书` 那种前导斜杠也认。
chk("A2 层级标签 `#读书/小说` 整段摘掉",
    "#读书" not in fn.strip_inline_tags("结尾 #读书/小说", ["读书/小说"]),
    fn.strip_inline_tags("结尾 #读书/小说", ["读书/小说"]))
chk("A2 前导斜杠 `#/读书` 也摘掉（extract_tags 会 strip 掉它）",
    "#/读书" not in fn.strip_inline_tags("结尾 #/读书", ["读书"]),
    fn.strip_inline_tags("结尾 #/读书", ["读书"]))

# A3 不在账上的「标签」一个字不动：句末序号 `#3`、以及只是以它开头的长标签。
chk("A3 序号 `#3` 不在账上，一个字不动",
    fn.strip_inline_tags("记一笔 #3", ["灵感"]) == "记一笔 #3")
chk("A3 只是以它开头、其实是另一个标签的 `#读书笔记` 不动",
    fn.strip_inline_tags("#读书笔记", ["读书"]) == "#读书笔记")

# A4 对照：改前那串 lookahead（手抄的子集）确实摘不掉 `#灵感】` —— 证明这组不是空转。
_old = re.sub(r"(^|\s)#" + re.escape("灵感") + r"(?=\s|$|[，。、；：！？,.;:!?）)])",
              r"\1", "记一笔 #灵感】")
chk("A4 对照：改前那串 lookahead 留下了 `#灵感】`", "#灵感" in _old, _old)

# A5 收成书：标签不再三遍。正文那句该摘掉，标签行照旧留着。
_m = {"id": "x", "date": "2026-01-01", "clock": "09:00:00",
      "md": "记一笔 #灵感】", "tags": ["灵感"], "atts": [], "words": 1}
_md = fn.memo_markdown(_m)
chk("A5 memo_markdown：`#灵感` 只出现一次（不再三遍）",
    _md.count("#灵感") == 1, _md)
chk("A5 memo_markdown：正文里那枚内联标签已经摘掉",
    "#灵感】" not in _md, _md)


# ── B：字典键上的落单代理码点也要摘下 ───────────────────────────────
print("── B：字典键上的落单代理码点也要摘 ──")


def encodes_ok(obj):
    """这份对象能不能像写口那样 `json.dump(ensure_ascii=False)` 到 utf-8。"""
    try:
        json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


# B1 对照：键上的坏码真的会让整份编不出 utf-8 —— 证明这一组不是空转。
chk("B1 对照：键上带坏码的对象，ensure_ascii=False 编不成 utf-8",
    not encodes_ok({HI + "k": 1}))

# B2 两把同名尺子：键与值一起摘干净，编得成 utf-8，且对象里再也搜不到坏码。
for _name, _mod in (("flomo_notes", fn), ("book_layout", bl)):
    _out = _mod.drop_lone_surrogates({HI + "k": [LO + "v", {HI + "n": "x"}]})
    _s = json.dumps(_out, ensure_ascii=False)
    chk("B2 %s：键与值里的坏码都摘掉、编得成 utf-8" % _name,
        encodes_ok(_out) and HI not in _s and LO not in _s, _out)

chk("B2 flomo_notes：键本身洗成了 `k`",
    list(fn.drop_lone_surrogates({HI + "k": 1}).keys()) == ["k"])
chk("B2 book_layout：键本身洗成了 `k`",
    list(bl.drop_lone_surrogates({HI + "k": 1}).keys()) == ["k"])

# B3 回归：值上的坏码照旧按 `check_clip_surrogate` 的口径摘（形状不变）。
chk("B3 回归：值上的坏码照旧摘、形状不变",
    bl.drop_lone_surrogates({"t": [HI + "x", {"y": LO}]}) == {"t": ["x", {"y": ""}]},
    bl.drop_lone_surrogates({"t": [HI + "x", {"y": LO}]}))

# B4 成对的代理码点（真 emoji）不受影响：键与值都一个字不动。
_ek, _ev = EMOJI + "键", EMOJI + "值"
_eout = bl.drop_lone_surrogates({_ek: _ev})
chk("B4 真 emoji（成对）在键与值上都一个字不动",
    list(_eout.keys()) == [_ek] and _eout[_ek] == _ev, _eout)

# B5 幂等：洗两遍与洗一遍同值。
_d = {HI + "k": [LO + "v", {HI + "n": 1}]}
chk("B5 幂等：洗两遍与洗一遍同值",
    fn.drop_lone_surrogates(fn.drop_lone_surrogates(_d)) == fn.drop_lone_surrogates(_d))

# B6 端到端：脏键账本还能手记 / 还能保存，落盘后键上不再有坏码。
_D = os.path.join(ROOT, "flomo")
os.makedirs(_D, exist_ok=True)
with open(fn.path_in(_D), "w", encoding="utf-8") as _f:
    _f.write('{"\\ud800k": 1, "memos": [{"id": "a", "md": "hi"}]}')
try:
    fn.add_memo(_D, "手记一条")
    _ok = True
except Exception as _e:                                    # noqa: BLE001
    _ok = False
    chk("B6 add_memo：脏键账本不再让手记整条抛", False, _e)

if _ok:
    with open(fn.path_in(_D), encoding="utf-8") as _f:
        _raw = json.load(_f)
    chk("B6 add_memo：脏键账本还能手记，落盘后键上不再有坏码",
        not any(fn.SURROGATE.search(str(k)) for k in _raw), list(_raw.keys()))

try:
    fn.save(_D, {HI + "k": 1, "memos": []})
    _sok = True
except Exception as _e:                                    # noqa: BLE001
    _sok = False
    chk("B6 flomo_notes.save：脏键也过一遍、不再整份抛", False, _e)

if _sok:
    with open(fn.path_in(_D), encoding="utf-8") as _f:
        _raw2 = json.load(_f)
    chk("B6 flomo_notes.save：脏键落盘后洗成 `k`、不再有坏码",
        "k" in _raw2 and not any(fn.SURROGATE.search(str(k)) for k in _raw2),
        list(_raw2.keys()))

# B7 抄一遍 ui_server._write_json 的兜底：第一次 encode 抛，用这把尺子重写就写得成。
try:
    json.dumps({HI + "k": "v"}, ensure_ascii=False).encode("utf-8")
    chk("B7 ui_server._write_json 兜底那一路：脏键 meta 现在写得成", False, "第一次就没抛？")
except UnicodeEncodeError:
    chk("B7 ui_server._write_json 兜底那一路：脏键 meta 现在写得成",
        encodes_ok(bl.drop_lone_surrogates({HI + "k": "v"})))


shutil.rmtree(ROOT, ignore_errors=True)
print()
print("便签标签收尾 / 字典键坏码：通过 %d 项，失败 %d 项" % (PASSED, len(FAIL)))
if FAIL:
    for _f in FAIL:
        print("  ✗ " + _f)
    sys.exit(1)
print("ok  认得出的标签都摘得掉；键上的坏码再也卡不住两个写口")
