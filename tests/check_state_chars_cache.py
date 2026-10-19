# -*- coding: utf-8 -*-
"""书架字数的「没变就不重算」：`/api/state` 每 2.6 秒一轮，不该每轮重读整库的 raw 账。

为什么这条值得一个离线门禁
    一本取回来的书，正文字数是把 `raw/0001.json` … 逐份 `text_len` 加出来的
    （`ui_server.list_books`）。而 `/api/state` 是界面**每 2.6 秒**打一次的轮询，
    它每次都调 `list_books()` —— 也就是每轮把整库每一章的 raw 账重开重解一遍。
    实测 30 本 × 300 章（9000 份）光这一句就要 80ms，整趟 `list_books` 才 86ms：
    书越厚，书架越卡，而这两次轮询之间什么都没变。

    现在签名取「这份 raw 目录里 JSON 的份数 + 各自 mtime」：签名没变就直接复用上次的
    和，签名变了（补章改份数、重取某章改那份的 mtime、删章改份数）才重读。这一条钉住
    四件事：
      · 和算得对（BOM / 坏记录 / 非对象 / 数字串 text_len 都与「逐份读」的对照同值）；
      · 没变时真的不再开文件（行为级间谍数 json.load 次数，不是看源码字面量）；
      · 变了时一定重算（新章 / 重写一章 / 删一章三条路各来一次）；
      · 没有 raw/ 的本地书仍退回 meta.chars（这条退路没被缓存带歪）。
    纯函数 + 临时沙盒，不联网、不起服务、不开浏览器，归 --fast 静态段。
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = tempfile.mkdtemp(prefix="guizang-raw-chars-")
os.environ["GUIZANG_DATA"] = os.path.join(ROOT, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(ROOT, "books")
os.makedirs(os.environ["GUIZANG_DATA"], exist_ok=True)
os.makedirs(os.environ["GUIZANG_BOOKS"], exist_ok=True)

import book_layout                                            # noqa: E402
import ui_server                                              # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:200]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


BOOKS = os.environ["GUIZANG_BOOKS"]


def mkbook(bid, raw_files, meta=None):
    d = os.path.join(book_layout.book_dir(BOOKS, "weread"), bid)
    os.makedirs(os.path.join(d, "raw"), exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta if meta is not None else {"title": bid, "done": True}, f)
    for name, blob in (raw_files or {}).items():
        with open(os.path.join(d, "raw", name), "wb") as f:
            f.write(blob if isinstance(blob, bytes) else blob.encode("utf-8"))
    return bid


def raw_dir(bid):
    return os.path.join(book_layout.book_dir(BOOKS, "weread"), bid, "raw")


def chars_of(bid):
    return {b["id"]: b for b in ui_server.list_books()}.get(bid, {}).get("chars")


def j(**kw):
    return json.dumps(kw)


class LoadSpy:
    """数一数 `json.load` 被喂了哪几个文件，其余属性照旧转给真的 json 模块。"""

    def __init__(self, real):
        self.real = real
        self.calls = []

    def load(self, f, *a, **k):
        self.calls.append(str(getattr(f, "name", "")))
        return self.real.load(f, *a, **k)

    def __getattr__(self, key):
        return getattr(self.real, key)

    def raw_loads(self):
        return [c for c in self.calls if os.sep + "raw" + os.sep in c]


# ── A. 和算得对：好值相加，坏记录只跳过自己 ─────────────────────────────
mkbook("wr_a", {
    "0001.json": j(text_len=10),
    "0002.json": "\ufeff" + j(text_len=20),          # 带 BOM（记事本另存为 UTF-8）
    "0003.json": j(text_len="30"),                   # 数字写成字符串
    "0004.json": "{坏 json",                         # 解不动
    "0005.json": j(text_len=None),                   # 没有可用的 text_len
    "notes.txt": "不是 json，也不算读书的字",
})
chk("A 逐份 text_len 相加（BOM / 数字串都算对，坏记录只跳自己）",
    chars_of("wr_a") == 60, chars_of("wr_a"))
# 没有 raw/ 的本地书：字数仍退回 meta.chars（缓存不该把这条退路带歪）
mkbook("wr_meta", {}, meta={"title": "导入的", "done": True, "chars": 123})
chk("A 没有 raw/ 的书退回 meta.chars", chars_of("wr_meta") == 123, chars_of("wr_meta"))
# 空 raw/ 目录：和是 0，不抛
mkbook("wr_empty", {}, meta={"title": "空的", "done": True, "chars": 7})
chk("A 空 raw/ 目录：和 0，退回 meta.chars", chars_of("wr_empty") == 7, chars_of("wr_empty"))
chk("A 签名：目录不在回 (None, [])",
    ui_server._raw_chars_key(os.path.join(ROOT, "never-existed", "raw")) == (None, []),
    ui_server._raw_chars_key(os.path.join(ROOT, "never-existed", "raw")))
sig, names = ui_server._raw_chars_key(raw_dir("wr_a"))
chk("A 签名：份数与清单对得上（5 份 .json，非 .json 不算）",
    sig is not None and sig[0] == 5 and len(names) == 5, (sig, names))

# ── B. 没变就不重算：行为级间谍数 json.load ─────────────────────────────
mkbook("wr_b", {"0001.json": j(text_len=10), "0002.json": j(text_len=20),
                "0003.json": j(text_len=30)})
spy = LoadSpy(json)
ui_server.json = spy
try:
    first = chars_of("wr_b")
    n_first = len(spy.raw_loads())
    spy.calls = []
    second = chars_of("wr_b")
    n_second = len(spy.raw_loads())
    chk("B 首次要真读文件（这条不是空转）", n_first >= 3, n_first)
    chk("B 没变时第二次一份都不再读", n_second == 0, n_second)
    chk("B 复用回来的和与首次一致", first == second == 60, (first, second))

    # ── C. 新章 → 份数变了，必须重算 ────────────────────────────────
    with open(os.path.join(raw_dir("wr_b"), "0006.json"), "w", encoding="utf-8") as f:
        f.write(j(text_len=100))
    spy.calls = []
    chk("C 补了一章重新算（100 + 60）", chars_of("wr_b") == 160, chars_of("wr_b"))
    chk("C 补章这一趟真的又读了文件", len(spy.raw_loads()) > 0, spy.calls)

    # ── D. 重写一章 → mtime 变了，必须重算 ──────────────────────────
    p = os.path.join(raw_dir("wr_b"), "0001.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(j(text_len=1))
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns + 10 ** 9, st.st_mtime_ns + 10 ** 9))   # 把时间推后
    spy.calls = []
    chk("D 重取某一章重新算（把 10 改成 1：160 - 9）", chars_of("wr_b") == 151,
        chars_of("wr_b"))
    chk("D 重写这一趟真的又读了文件", len(spy.raw_loads()) > 0, spy.calls)

    # ── E. 删章 → 份数变了，必须重算 ────────────────────────────────
    os.remove(os.path.join(raw_dir("wr_b"), "0003.json"))          # 去掉那份 30
    spy.calls = []
    chk("E 删掉一章重新算（151 - 30）", chars_of("wr_b") == 121, chars_of("wr_b"))
    chk("E 删章这一趟真的又读了文件", len(spy.raw_loads()) > 0, spy.calls)
finally:
    ui_server.json = json

# 旧章节仍早于最新章节：只取 max(mtime) 会把这次更新漏掉。
mkbook("wr_older", {"0001.json": j(text_len=10), "0002.json": j(text_len=20)})
older = os.path.join(raw_dir("wr_older"), "0001.json")
newer = os.path.join(raw_dir("wr_older"), "0002.json")
stamp = 1_700_000_000_000_000_000
os.utime(older, ns=(stamp, stamp))
os.utime(newer, ns=(stamp + 1000, stamp + 1000))
chk("F 边界对照：缓存前两章相加为 30", chars_of("wr_older") == 30)
with open(older, "w", encoding="utf-8") as f:
    f.write(j(text_len=200))
os.utime(older, ns=(stamp + 1, stamp + 1))
chk("F 旧章节更新但最大 mtime 不变也重算", chars_of("wr_older") == 220)
os.remove(older)
replacement = os.path.join(raw_dir("wr_older"), "0009.json")
with open(replacement, "w", encoding="utf-8") as f:
    f.write(j(text_len=300))
os.utime(replacement, ns=(stamp + 1, stamp + 1))
chk("F 等数量、等大小、等时间的换章也重算", chars_of("wr_older") == 320)

shutil.rmtree(ROOT, ignore_errors=True)
print()
print("书架字数缓存：通过 %d 项，失败 %d 项" % (PASSED, len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
print("ok  书架字数：没变不重算、变了立刻重算，坏账本仍只跳自己")
