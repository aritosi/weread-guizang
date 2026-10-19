# -*- coding: utf-8 -*-
"""平铺书的「归入夹子 / 删书」也要认对格子。

这一条修的是什么
    一本书住哪一格，全仓只有一把尺子：`ui_server.book_module()`（先看目录、目录不在
    模块文件夹里时按 meta / 前缀认）。`book.tag` / `book.order` / `/api/book_state`
    都走它，唯独 `book.move` 与两条删路（`book.delete` 与 `/api/delete_many`
    批量删缓存）是拿「父目录叫什么」去 `MODULE_OF.get(...)` 猜，猜不中一律落回
    `weread`。

    平铺书（书号目录直接躺在书库根下）是**受支持**的状态：`book_layout.resolve()`
    专门把平铺的旧位置列进候选，`migrate()` 的说明也写着「命令行跑出来的平铺新书」——
    而《部署说明》§六 就是让人直接 `.venv/bin/python export_precise.py <ID>`，
    `export_precise.main` 写的是 `OUTPUT_DIR/<书号>`（平铺，不建模块文件夹）。
    只要后端还在跑（没重启、没跑 `migrate()`），这类书就是平铺的：
      · 在剪藏那一屏给它「归入分类」→ 旧写法按父目录猜成 weread，回一句
        「这个模块里没有这个文件夹」，用户按多少次都归不进去；
      · 删它 → `lib_forget(lib, bid, "weread")` 销错了格，书真正住的剪藏那一格里
        `assign` / `tags` 留下幽灵记录（而 `prune_lib` 只在 `/api/state` 的读路径上
        内存裁一刀，落盘那份一直是脏的）。

这一条钉三层
  A 对照：同一本平铺的剪藏书，「父目录名」那把旧尺子量出 `weread`，`book_module()`
    量出 `clip` —— 两者确实分叉，这条门禁不是空转；格子里的书两种量法同值，
    说明改动不改变正常书的行为。
  B 行为：进程内真起一个 `ThreadingHTTPServer`，对平铺的剪藏书打 `/api/action`：
    `book.move` 必须成、归入要落在剪藏那一格；删书（`book.delete`）与批量删缓存
    （`/api/delete_many`）之后**磁盘上那份账本**里剪藏格不留任何幽灵。
  C 护栏与回归：平铺的本地书归进剪藏的夹子照样拒绝（认对格不等于跨格放行）；
    住在模块文件夹里的书，归入 / 删除照旧。

全离线、只碰临时沙盒，不联网、不开浏览器，归静态段，--fast 也得带上。
"""
import atexit
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

# 自带一份沙盒：绝不碰用户真实的 cache/ 与书库，也不和别的套件共用共享沙盒。
SB = pathlib.Path(tempfile.mkdtemp(prefix="gz-flat-module-"))
atexit.register(lambda: shutil.rmtree(SB, ignore_errors=True))
for _d in ("data", "books", "shots"):
    (SB / _d).mkdir(parents=True, exist_ok=True)
os.environ["GUIZANG_DATA"] = str(SB / "data")
os.environ["GUIZANG_BOOKS"] = str(SB / "books")
os.environ["GUIZANG_SHOT_DIR"] = str(SB / "shots")
os.environ["GUIZANG_ANNA_NO_WINDOW"] = "1"

import ui_server  # noqa: E402  —— 必须在环境变量设好之后 import
import book_layout  # noqa: E402

FAIL = []


def chk(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   " + repr(extra)[:220]))
    if not ok:
        FAIL.append(name)


BOOKS = pathlib.Path(ui_server.OUT_DIR)
CLIP_DIR = BOOKS / book_layout.DIR_OF["clip"]

# 三本一次性取证用的书：两本平铺（剪藏 / 本地），一本住在模块文件夹里（回归用）。
FLAT_CLIP = "clip_flat00000001"
FLAT_LOCAL = "imp_flat00000002"
MOD_CLIP = "clip_norm00000003"
FLAT_CLIP_MANY = "clip_flat00000005"   # 走 /api/delete_many（批量删缓存）的平铺书


def make_book(root, bid, meta):
    d = pathlib.Path(root) / bid
    (d / "chapters").mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (d / "chapters" / "0001.md").write_text("# 第一章\n\n正文\n", encoding="utf-8")
    return d


make_book(BOOKS, FLAT_CLIP, {"title": "平铺的剪藏", "source": "clip", "done": True})
make_book(BOOKS, FLAT_LOCAL, {"title": "平铺的本地书", "source": "local", "done": True})
make_book(BOOKS, FLAT_CLIP_MANY, {"title": "平铺的剪藏（批量删）", "source": "clip", "done": True})
make_book(CLIP_DIR, MOD_CLIP, {"title": "格子里的剪藏", "source": "clip", "done": True})


# ── A. 对照：旧尺子确实在这类书上分叉 ────────────────────────────────────────
def old_guess(bid):
    """改之前 `book.move` / `book.delete` 逐字同形的量法：只看父目录叫什么。"""
    d = ui_server.safe_book_dir(bid)
    return book_layout.MODULE_OF.get(os.path.basename(os.path.dirname(d)), "weread")


chk("对照：平铺的剪藏书，旧尺子（父目录名）量出 weread —— 确实会走错格",
    old_guess(FLAT_CLIP) == "weread", old_guess(FLAT_CLIP))
chk("book_module：同一本平铺的剪藏书认得出 clip（唯一那把尺子）",
    ui_server.book_module(FLAT_CLIP) == "clip", ui_server.book_module(FLAT_CLIP))
chk("对照：住在模块文件夹里的书，两种量法同值（改动不碰正常书）",
    old_guess(MOD_CLIP) == ui_server.book_module(MOD_CLIP) == "clip",
    (old_guess(MOD_CLIP), ui_server.book_module(MOD_CLIP)))


# ── B/C. 真服务：走 /api/action 的 HTTP 契约 ─────────────────────────────────
srv = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post(payload):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/action" % PORT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def post_many(ids):
    """走只认 do_POST 的 /api/delete_many（批量删本地缓存）。"""
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/delete_many" % PORT,
        data=json.dumps({"books": ids}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def raw_lib():
    """直接读盘上那份账本 —— 不走 `load_lib()` 的规整，幽灵记录藏不住。"""
    return json.loads(pathlib.Path(ui_server.LIB_PATH).read_text(encoding="utf-8"))


try:
    f = post({"action": "folder.new", "module": "clip", "name": "平铺取证夹"})
    chk("建一个剪藏夹子（后面归入用）", f.get("ok") and f.get("id"), f)
    fid = f.get("id")

    tag = post({"action": "book.tag", "book": FLAT_CLIP, "add": ["重磅"]})
    chk("贴标签走的就是 book_module：平铺的剪藏书认对剪藏格", tag.get("ok") is True, tag)

    mv = post({"action": "book.move", "book": FLAT_CLIP, "folder": fid})
    chk("book.move：平铺的剪藏书能归进剪藏的夹子"
        "（旧写法回「这个模块里没有这个文件夹」）", mv.get("ok") is True, mv)
    chk("book.move：归入落在剪藏那一格，不是 weread",
        raw_lib()["modules"]["clip"]["assign"].get(FLAT_CLIP) == fid,
        raw_lib()["modules"]["clip"]["assign"])

    bad = post({"action": "book.move", "book": FLAT_LOCAL, "folder": fid})
    chk("护栏：平铺的本地书归进剪藏夹子照样拒绝（认对格不等于跨格放行）",
        bad.get("ok") is False and "文件夹" in str(bad.get("msg")), bad)

    mv2 = post({"action": "book.move", "book": MOD_CLIP, "folder": fid})
    chk("回归：住在剪藏文件夹里的书照旧能归入", mv2.get("ok") is True, mv2)

    dele = post({"action": "book.delete", "book": FLAT_CLIP})
    chk("book.delete：平铺的剪藏书删得掉", dele.get("ok") is True, dele)
    chk("book.delete：书目录真的没了", not (BOOKS / FLAT_CLIP).exists())
    clip_scope = raw_lib()["modules"]["clip"]
    chk("book.delete：剪藏那一格不留幽灵（assign / tags 都清干净）",
        FLAT_CLIP not in clip_scope["assign"] and FLAT_CLIP not in clip_scope["tags"],
        clip_scope)

    dele2 = post({"action": "book.delete", "book": MOD_CLIP})
    after = raw_lib()["modules"]["clip"]
    chk("回归：住在剪藏文件夹里的书照旧删得掉、也不留幽灵",
        dele2.get("ok") is True and MOD_CLIP not in after["tags"]
        and MOD_CLIP not in after["assign"], (dele2, after))

    # /api/delete_many 是与 book.delete 并列的另一条删路（界面上的批量删除），
    # 旧写法同样是拿父目录名猜格：平铺的剪藏书在这里也会留幽灵。
    post({"action": "book.tag", "book": FLAT_CLIP_MANY, "add": ["待批"]})
    dm = post_many([FLAT_CLIP_MANY])
    chk("book.delete_many：批量删缓存时平铺的剪藏书照旧删得掉", dm.get("ok") is True, dm)
    chk("book.delete_many：书目录真的没了", not (BOOKS / FLAT_CLIP_MANY).exists())
    many_scope = raw_lib()["modules"]["clip"]
    chk("book.delete_many：剪藏那一格不留幽灵"
        "（旧写法销在 weread，assign / tags 会留在剪藏格）",
        FLAT_CLIP_MANY not in many_scope["assign"] and FLAT_CLIP_MANY not in many_scope["tags"],
        many_scope)
finally:
    srv.shutdown()

print()
if FAIL:
    print("平铺书认格门禁：%d 项未过：%s" % (len(FAIL), FAIL))
    sys.exit(1)
print("平铺书认格门禁：全部通过")
