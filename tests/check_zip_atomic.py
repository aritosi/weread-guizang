#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：打包下载（单本 / 多本）的成品落盘收口 —— 临时件一次一个名字。

为什么单开这一条
    `ui_server.build_zip` / `build_zip_multi` 是把书库里一本（或一批）打成 zip 的地方，
    两条 `/api/zip`、`/api/zip-multi` 路由都在**请求线程里直接调**它们（不是
    `start_task`），服务又是 ThreadingHTTPServer ——

      · 单本：同一本书被点两下（双击 / 两个标签页），两条线程往同一个
        `cache/downloads/<书号>.zip` 上落；
      · 多本：`dest` 是个**固定名** `归藏-多本打包.zip`（不随选的书变），两台窗口
        各选一批「多本打包」点下去，撞的是同一个包。

    旧写法 `zipfile.ZipFile(dest, "w", …)` 直写终稿，同属「落盘临时件」那一族
    《交接说明》§2 那本账里已收干净的一格（与 `book_export` 的 EPUB / PDF 同一形状，
    见 `tests/check_book_export_atomic.py`）：

      · 两个写者交替写同一个终稿 → 落下的是一份两份内容交织的坏包；
      · 写一半被杀 / 盘满 → `dest` 上留一个存在却打不开的半截包，还顶掉了上一份完整包。

修法与仓库里其它格同一把尺子：临时件写成同目录的 `<目标>.<pid>.<八位随机>.part`，
成功了再 `os.replace` 顶上，失败 / 中止（`BaseException`）在 `finally` 里收残件。

这一条钉住
  A. 单本本体：产物照旧是一份合法 zip（里面有合并稿），不留 `.part`；
  B. 单本并发：两个写者同时打同一本，一个都不扑空、第一刀改名那一刻盘上确实有
     **两份**不同的 `.part`，收尾后落下的是一整份、不留残件；
  C. 单本失败路径：改名失败（ENOSPC）与中止信号（KeyboardInterrupt）都照旧往上抛，
     旧成品一个字不动、旁边不留 `.part`；
  D. 多本：固定名下两个写者同时打都成、失败留旧档；没内容时返回 n=0 也不留残件；
  E. 源码口径：两个写口都从 `os.getpid()` + `uuid4` 拼临时名（一处真相），
     不再有 `zipfile.ZipFile(dest, "w"` 这种直写终稿的写法。

沙盒在系统临时目录里，不碰用户真实书库、不联网、不开浏览器，故归 --fast 静态段。

跑法：.venv/bin/python tests/check_zip_atomic.py
"""
import atexit
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = tempfile.mkdtemp(prefix="guizang-zip-atomic-")
atexit.register(lambda: shutil.rmtree(ROOT, ignore_errors=True))
os.environ["GUIZANG_DATA"] = os.path.join(ROOT, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(ROOT, "books")

import ui_server                                              # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:220]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def seed(book_id, title="正常一本"):
    d = os.path.join(ui_server.OUT_DIR, book_id)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    with io.open(os.path.join(d, "chapters", "0001.md"), "w", encoding="utf-8") as f:
        f.write("# 第一章\n\n这一章有正文。\n")
    with io.open(os.path.join(d, "chapters", "0002.md"), "w", encoding="utf-8") as f:
        f.write("# 第二章\n\n第二章的正文。\n")
    with io.open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"title": title, "author": "作者"}, f, ensure_ascii=False)
    return d


def parts_in(dest):
    folder = os.path.dirname(dest)
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if n.endswith(".part"))


def good_zip(path, want_md=True):
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return False
            names = z.namelist()
            return bool(names) and (any(n.endswith(".md") for n in names) if want_md else True)
    except Exception:
        return False


# ─────────────────────── A / B：单本 build_zip ───────────────────────
seed("bk0001", "我的书")
DEST1 = os.path.join(ui_server.DOWNLOAD_DIR, "bk0001.zip")

got = ui_server.build_zip("bk0001")
chk("A1 正常打包照旧是合法 zip（里面有合并稿），收尾后不留 .part",
    got == DEST1 and good_zip(DEST1) and parts_in(DEST1) == [],
    (got, good_zip(DEST1), parts_in(DEST1)))
chk("A2 没有章节的书返回 None，也不在盘上留 .part",
    ui_server.build_zip("no_such_book") is None
    and parts_in(os.path.join(ui_server.DOWNLOAD_DIR, "no_such_book.zip")) == [])

# 两个写者同时打同一本：卡在 os.replace 入口，两边都写完临时件、都还没改名。
RACE1 = os.path.join(ui_server.DOWNLOAD_DIR, "race.zip")
race_res = {}
race_snap = []
race_lock = threading.Lock()
arrive1 = threading.Barrier(2)
orig_r1 = ui_server.os.replace


def racy_zip(src, dst):
    arrive1.wait(timeout=30)                     # 两边都写完各自的临时件
    with race_lock:
        race_snap.append(parts_in(dst))
    return orig_r1(src, dst)


# 单本并发：直接调 build_zip，dest 由书号决定，不用另给目标。
seed("racebook", "并发一本")
RACE1 = os.path.join(ui_server.DOWNLOAD_DIR, "racebook.zip")
race_res = {}
ui_server.os.replace = racy_zip
try:
    def zip_worker(i):
        try:
            ui_server.build_zip("racebook")
            race_res[i] = "ok"
        except BaseException as e:               # noqa: BLE001
            race_res[i] = "%s: %s" % (type(e).__name__, e)

    ts = [threading.Thread(target=zip_worker, args=(i,)) for i in (1, 2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(40)
finally:
    ui_server.os.replace = orig_r1

chk("B1 同一个目标两个写者同时打，两个都回 ok（直写终稿必有一个扑空 / 打成混血）",
    race_res.get(1) == "ok" and race_res.get(2) == "ok", race_res)
chk("B2 第一刀改名那一刻，盘上确实有两份不同的 .part（名字一次一个）",
    race_snap and max(len(s) for s in race_snap) == 2, (race_snap, parts_in(RACE1)))
chk("B3 并发收尾之后不留任何 .part，落下的是一份合法 zip",
    parts_in(RACE1) == [] and good_zip(RACE1), (parts_in(RACE1), good_zip(RACE1)))


# C：失败 / 中止：旧成品必须原样，旁边不留残件，异常照旧往上抛。
OLD = b"OLD-ZIP-CONTENT"
for marker, exc, label in (("C1", OSError(28, "No space left on device"), "改名失败"),
                           ("C2", KeyboardInterrupt(), "中止信号")):
    dest = os.path.join(ui_server.DOWNLOAD_DIR, ("fail-%s.zip" % marker))
    with open(dest, "wb") as f:
        f.write(OLD)
    orig = ui_server.os.replace

    def boom(src, dst, _exc=exc):
        raise _exc

    ui_server.os.replace = boom
    thrown = None
    try:
        ui_server.build_zip("bk0001")
    except BaseException as e:                   # noqa: BLE001
        thrown = e
    finally:
        ui_server.os.replace = orig
    unchanged = open(dest, "rb").read() == OLD
    chk("C%s %s：异常照旧往上抛、旧成品一字不动、不留 .part" % (marker[1], label),
        isinstance(thrown, type(exc)) and unchanged and parts_in(dest) == [],
        (type(thrown).__name__ if thrown else None, unchanged, parts_in(dest)))

# 打包过程本身抛（不是改名那一步）：临时件已经落了一半，也要收掉。
dest = os.path.join(ui_server.DOWNLOAD_DIR, "halfway.zip")
with open(dest, "wb") as f:
    f.write(OLD)
thrown = None


class _HalfZip:
    """ZipFile 的假身：真的在 tmp 上落半截字节，再当场中止。"""

    def __init__(self, path, *a, **k):
        self.path = path
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 half-written")
        raise KeyboardInterrupt()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


saved_zf = ui_server.zipfile.ZipFile
ui_server.zipfile.ZipFile = _HalfZip
try:
    ui_server.build_zip("bk0001")
except BaseException as e:                       # noqa: BLE001
    thrown = e
finally:
    ui_server.zipfile.ZipFile = saved_zf
chk("C3 打包写到一半中止：异常照抛、旧成品一字不动、留下的半截 .part 也收掉",
    isinstance(thrown, KeyboardInterrupt)
    and open(dest, "rb").read() == OLD and parts_in(dest) == [],
    (type(thrown).__name__ if thrown else None, parts_in(dest)))


# ─────────────────────── D：多本 build_zip_multi ───────────────────────
seed("m1", "第一本")
seed("m2", "第二本")
MDEST = os.path.join(ui_server.CACHE_DIR, "downloads", "归藏-多本打包.zip")

dest, n = ui_server.build_zip_multi(["m1", "m2"])
chk("D1 多本打包照旧是合法 zip（两本都在），收尾后不留 .part",
    dest == MDEST and n == 2 and good_zip(dest)
    and parts_in(dest) == [], (dest, n, parts_in(dest)))

chk("D2 一本都没有内容时 n=0、也不在固定名旁边留 .part",
    ui_server.build_zip_multi(["no_such"])[1] == 0 and parts_in(MDEST) == [],
    (ui_server.build_zip_multi(["no_such"]), parts_in(MDEST)))

# 固定名下两个写者同时打：卡在 os.replace 那一刻，两边都写完各自的临时件。
msnap = []
mlock = threading.Lock()
arrive_m = threading.Barrier(2)
orig_m = ui_server.os.replace


def racy_multi(src, dst):
    arrive_m.wait(timeout=30)
    with mlock:
        msnap.append(parts_in(dst))
    return orig_m(src, dst)


mres = {}
ui_server.os.replace = racy_multi
try:
    def multi_worker(i):
        try:
            ui_server.build_zip_multi(["m1", "m2"])
            mres[i] = "ok"
        except BaseException as e:               # noqa: BLE001
            mres[i] = "%s: %s" % (type(e).__name__, e)

    ts = [threading.Thread(target=multi_worker, args=(i,)) for i in (1, 2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(40)
finally:
    ui_server.os.replace = orig_m

chk("D3 固定名（归藏-多本打包.zip）两个写者同时打：都回 ok",
    mres.get(1) == "ok" and mres.get(2) == "ok", mres)
chk("D4 第一刀改名那一刻盘上有两份不同的 .part，收尾后不留残件、落下一整份",
    msnap and max(len(s) for s in msnap) == 2
    and parts_in(MDEST) == [] and good_zip(MDEST), (msnap, parts_in(MDEST)))

# 多本失败路径：旧成品原样、不留残件、异常照抛。
with open(MDEST, "wb") as f:
    f.write(OLD)


def boom_multi(src, dst):
    raise OSError(28, "No space left on device")


ui_server.os.replace = boom_multi
thrown = None
try:
    ui_server.build_zip_multi(["m1", "m2"])
except BaseException as e:                       # noqa: BLE001
    thrown = e
finally:
    ui_server.os.replace = orig_m
chk("D5 多本改名失败：异常照抛、旧成品一字不动、不留 .part",
    isinstance(thrown, OSError) and open(MDEST, "rb").read() == OLD
    and parts_in(MDEST) == [], (type(thrown).__name__ if thrown else None, parts_in(MDEST)))


# ─────────────────────── E：源码口径（旧尺子量不到）───────────────────────
SRC = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ui_server.py"), encoding="utf-8").read()
LIT = 'tmp = "%s.%d.%s.part" % (dest, os.getpid(), uuid.uuid4().hex[:8])'
chk("E1 两个打包写口都从 os.getpid() + uuid 拼临时名（一处真相）",
    SRC.count(LIT) == 2, SRC.count(LIT))
chk("E2 不再有 `zipfile.ZipFile(dest, \"w\"` 这种直写终稿的写法",
    'zipfile.ZipFile(dest, "w"' not in SRC, "旧写法还在")

print()
print("打包下载成品落盘：%d 项通过，失败 %d 项" % (PASSED, len(FAIL)))
if FAIL:
    print("未过：" + " / ".join(FAIL))
sys.exit(1 if FAIL else 0)
