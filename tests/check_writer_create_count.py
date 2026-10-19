# -*- coding: utf-8 -*-
"""归藏门禁：新建稿子那一刻，正文的「字数」与「字符数」就得是同一个数。

为什么单开这一条
    `writer.create()` 有两条来路，一条真的会带正文进来：

      · 写作屏点「新建」——正文是空的，字数当然是 0；
      · 还没点「新建」就先在空白编辑器里落下第一句（`ui.html` 的 `wrStartDoc`，
        以及 MCP 的 `writer_create(title, text)`）——建稿时就带着几百字正文。

    稿子建出来之后，「这篇多少字」有两处读者、读的却是两个字段：

      · 写作屏自己走 `meta.words`（`writer.brief` / `writer_read` 的 count）；
      · 书库清单走 `meta.chars`（`ui_server.list_books()` 只读 `chars`，`/api/state`
        的 `books` 与 MCP 的 `shelf_list` / `search_books` 都从这一份来）。

    `save()` 一直把两个数写成同一个（见 `writer.py` 里那句注释），`create()` 却只补了
    `words`、把 `chars` 留在 `blank_meta` 的 0 上。于是同一篇刚起笔的稿子，写作屏说
    「15 字」、书架与 Agent 的 `shelf_list` 说「0 字」—— 直到用户再存一次才自己修好。
    这类「同一件事两个数」不报错、也不丢稿，最不容易被发现，所以钉一条门禁。

钉五面
  A. 建稿带上正文：返回的 meta 与**落盘的** meta 里 words == chars，且等于
     `writer.words()` 的数；
  B. 对照：同一段正文随后的 `save()` 写出来的还是同一个数（口径没有第二套）；
  C. 空稿：两个数都是 0（没有正文时不凭空造字数）；
  D. 用户真正读到的那口：`/api/writer` 的 `do=create` 建完，`list_books()`（也就是
     `/api/state` 的 `books`）里那一本的 chars 与 words 一致、且非 0；
  E. 接线：`writer.create` 里确实写了 `chars`（删掉那一行的改动会被点名）。

跑法：纯函数 + 系统临时目录沙盒书库，不联网、不开浏览器、不起服务，归 --fast 静态段。
"""
import atexit
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="guizang-wcreate-")
atexit.register(lambda: shutil.rmtree(SANDBOX, ignore_errors=True))
os.environ["GUIZANG_DATA"] = os.path.join(SANDBOX, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(SANDBOX, "books")

import writer      # noqa: E402
import ui_server   # noqa: E402  —— 只为走一遍用户真正读到的那口（/api/state 的 books）

FAIL = []
PASSED = 0

TEXT = "今天起笔写第一段。\n\n再补一句，凑够十几个字。\n"


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:300]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def disk_meta(books_root, book_id):
    p = os.path.join(writer.dir_of(books_root, book_id), "meta.json")
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


want = writer.words(TEXT)["total"]

# ── A 建稿带上正文：两个数当场就对得上 ────────────────────────────
LIB = os.path.join(SANDBOX, "books")
bid, meta = writer.create(LIB, title="起笔", text=TEXT)
chk("A1 建稿带着正文（字数不为 0，否则这条门禁空转）", want > 0 and bool(bid), (want, bid))
chk("A2 返回的 meta：words == chars", meta.get("words") == meta.get("chars"),
    (meta.get("words"), meta.get("chars")))
chk("A3 返回的 meta 与 words() 同一个数", meta.get("words") == want, (meta, want))
dm = disk_meta(LIB, bid)
chk("A4 落盘的 meta 也是 words == chars（不是只改了回执）",
    dm.get("words") == dm.get("chars") == want, dm)

# ── B 对照：随后 save 写出来的还是同一个数（没有第二套口径） ────────
ok, saved = writer.save(LIB, bid, TEXT)
chk("B1 save 之后两个数仍然一致、仍是同一个字数",
    ok and saved.get("words") == saved.get("chars") == want, saved)

# ── C 空稿：两个数都是 0，不凭空造字数 ────────────────────────────
bid0, meta0 = writer.create(LIB, title="空稿", text="")
chk("C1 空稿的 words / chars 都是 0",
    meta0.get("words") == 0 and meta0.get("chars") == 0, meta0)

# ── D 用户真正读到的那口：/api/state 的 books ─────────────────────
r = ui_server.writer_do({"do": "create", "title": "从接口建的", "text": TEXT})
chk("D1 /api/writer do=create 建出来了", r.get("ok") and r.get("id"), r.get("msg"))
row = next((b for b in ui_server.list_books() if b["id"] == r.get("id")), None)
chk("D2 书库清单里看得到这一本", row is not None, r.get("id"))
chk("D3 清单里的 chars 与写作屏的 words 是同一个数",
    bool(row) and row.get("chars") == want and row.get("chars") != 0,
    (row or {}).get("chars"))

# ── E 接线：create 里确实写了 chars ───────────────────────────────
src = open(os.path.join(ROOT, "writer.py"), encoding="utf-8").read()
chk("E1 源码：create 与 save 都用同一个口径写 chars",
    src.count('meta["chars"] = meta["words"]') >= 2,
    src.count('meta["chars"] = meta["words"]'))

print()
print("写作建稿字数口径取证：" + ("全部通过" if not FAIL
                                else "%d 项未过：%s" % (len(FAIL), FAIL)))
sys.exit(1 if FAIL else 0)
