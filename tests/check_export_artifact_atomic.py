#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：导出成品（单本 zip / 多本 zip / Anki 卡包）落盘收口 —— 临时件一次一个名字。

为什么单开这一条
    这三种跟 EPUB / PDF 同属「点一下就生成一份可下载的整包」，落点都在 `cache/` 下
    （`cache/downloads`、`cache/apkg`），而 `/api/zip` / `/api/zip-multi` / `/api/apkg`
    是在**请求线程里直接调**它们的（服务是 `ThreadingHTTPServer`）。旧写法把这三种都
    直接写成终稿：

      · `build_zip` / `build_zip_multi`：`zipfile.ZipFile(dest, "w", …)` 一进去就把
        上一趟那份好导出截断；两个窗口 / 两个标签页各点一次同一本（多本打包那份的
        `dest` 还是不区分书单的固定名 `归藏-多本打包.zip`）就是两只手往同一个 `dest`
        上落，顶成正式包的是两份内容交织的字节；
      · `build_apkg`：`genanki.Package(deck).write_to_file(dest)` 同样直写终稿，同一本
        被点两下写的是同一个 `<书名>.apkg`。

    打包中途被强杀（关窗 / 断电 / 活动监视器里杀进程）更直接：`dest` 上留下一份半截
    zip，而它已经顶掉了上一份完整的导出 —— 读口只按「文件在不在」认，用户下到的是一份
    打不开的包。

    修法与仓库里其它写口（`_write_json` / `_write_bytes` / `_write_text`、以及
    `book_export` 那格的 EPUB / PDF）同一把尺子：临时件写成同目录的
    `<目标>.<pid>.<八位随机>.part`，成功了再 `os.replace` 顶上，失败 / 中止
    （`BaseException`）在收尾里把残件删干净再原样往上抛。三种成品都从
    `ui_server._atomic_artifact` 这一个出口走。

这一条钉住
  A. 单本打包：产物照旧是一份合法 zip；`zipfile.ZipFile` 拿到的 path 是
     `<dest>.<pid>.<随机>.part` 而不是 `dest`；同一本两个写者同时打包，一个都不扑空、
     第一刀改名那一刻盘上确实有**两份**不同的 `.part`，收尾后不留残件；
  B. 多本打包：`dest` 不区分书单（固定名），同样先写随机 `.part` 再改名；
  C. Anki 卡包：`genanki.Package.write_to_file` 拿到的 path 是随机 `.part` 而不是 `dest`，
     产物仍是一份能拆出 collection 的合法 apkg，旁边不留残件；
  D. 失败 / 中止：改名失败（ENOSPC）与中止信号（KeyboardInterrupt）都照旧往上抛，
     旧成品一字不动、旁边不留 `.part`；写到一半失败（磁盘满）同样保住旧成品；
     对照：旧写法「直写终稿 + 半路抛」确实把上一份导出顶成了半截（这一刀不是空转）；
  E. 接线与口径：三个写口都从 `_atomic_artifact` 出去、`.part` 的名字格式只有一处真相；
     进程内起真服务发一次 `/api/zip-multi` 与 `/api/apkg`，回的路径真能打开、不留残件。

沙盒在系统临时目录里，不碰用户真实书库 / cache、不联网、不开浏览器，故归 --fast 静态段。

跑法：.venv/bin/python tests/check_export_artifact_atomic.py
"""
import atexit
import http.server
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

# 自带沙盒：必须在 import ui_server 之前设好，模块级那几条路径是 import 时定下的。
SB = pathlib.Path(tempfile.mkdtemp(prefix="gz-artifact-atomic-"))
atexit.register(lambda: shutil.rmtree(SB, ignore_errors=True))
os.environ["GUIZANG_DATA"] = str(SB / "cache")
os.environ["GUIZANG_BOOKS"] = str(SB / "books")

import ui_server  # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:240]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def seed(bid, title="我的书名", images=0):
    """造一本有章节（可选插图）的书目录，返回目录路径。"""
    d = os.path.join(ui_server.OUT_DIR, bid)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    with open(os.path.join(d, "chapters", "0001.md"), "w", encoding="utf-8") as f:
        f.write("# %s\n\n第一章正文。\n" % title)
    if images:
        img = os.path.join(d, "images")
        os.makedirs(img, exist_ok=True)
        for i in range(images):
            with open(os.path.join(img, "ch%04d.png" % i), "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"title": title}, f, ensure_ascii=False)
    return d


def parts_in(dest):
    folder = os.path.dirname(dest)
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if n.endswith(".part"))


def zip_names(path, suffix=".md"):
    """zip 里以 suffix 收尾的条目名；打不开就回 None。"""
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return None
            return [n for n in z.namelist() if n.endswith(suffix)]
    except Exception:
        return None


def apkg_ok(path):
    """这份 apkg 是个能打开的 zip、且里面真有 genanki 的 collection 库。"""
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None and any(
                n.endswith((".anki2", ".anki21")) for n in z.namelist())
    except Exception:
        return False


class _ZipSpy(zipfile.ZipFile):
    """记下 `ZipFile` 被要求写到哪个 path —— 行为级间谍，不靠源码字面量。"""
    seen = []

    def __init__(self, file, *a, **k):
        _ZipSpy.seen.append(file)
        super().__init__(file, *a, **k)


def with_zip_spy(fn):
    _ZipSpy.seen = []
    orig = zipfile.ZipFile
    zipfile.ZipFile = _ZipSpy
    try:
        out = fn()
    finally:
        zipfile.ZipFile = orig
    return out, list(_ZipSpy.seen)


# ─────────────────────── A. 单本打包（build_zip）───────────────────────
seed("zb001", "单本的书")
DEST1 = os.path.join(ui_server.DOWNLOAD_DIR, "zb001.zip")
dest, seen = with_zip_spy(lambda: ui_server.build_zip("zb001"))
chk("A1 单本打包照旧是一份合法 zip，里面有合并稿",
    dest == DEST1 and zip_names(dest) == ["单本的书.md"], (dest, zip_names(dest)))
chk("A2 zip 是写到同目录的随机 .part，不是终稿（改完名才有正式成品）",
    len(seen) == 1 and seen[0] != DEST1 and seen[0].endswith(".part")
    and os.path.dirname(seen[0]) == os.path.dirname(DEST1), seen)
chk("A3 收尾之后旁边不留 .part", parts_in(DEST1) == [], parts_in(DEST1))

# 两个写者同时打同一本：卡在 os.replace 入口，两边都写完各自的临时件、都还没改名。
seed("zb002", "并发的书")
RACE = os.path.join(ui_server.DOWNLOAD_DIR, "zb002.zip")


def run_two(build):
    res, lock, srcs = {}, threading.Lock(), []
    arrive = threading.Barrier(2)
    orig = os.replace

    def racy(src, dst):
        with lock:
            srcs.append(os.path.basename(src))
        arrive.wait(timeout=30)                     # 两边都写完各自的临时件
        return orig(src, dst)

    os.replace = racy
    try:
        def worker(i):
            try:
                build()
                res[i] = "ok"
            except BaseException as e:              # noqa: BLE001
                res[i] = "%s: %s" % (type(e).__name__, e)
        ts = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(40)
    finally:
        os.replace = orig
    return res, srcs


res, srcs = run_two(lambda: ui_server.build_zip("zb002"))
chk("A4 同一本两个写者同时打包，两个都回 ok（固定名必有一个扑空）",
    res.get(1) == "ok" and res.get(2) == "ok", res)
chk("A5 改名那一刻盘上确实有两份不同的 .part（名字一次一个）",
    len(srcs) == 2 and len(set(srcs)) == 2 and all(s.endswith(".part") for s in srcs), srcs)
chk("A6 并发收尾之后不留 .part，落下的是一份完整 zip",
    parts_in(RACE) == [] and zip_names(RACE) == ["并发的书.md"],
    (parts_in(RACE), zip_names(RACE)))

# ───────────────────── B. 多本打包（build_zip_multi）─────────────────────
seed("zb003", "第三本")
DESTM = os.path.join(ui_server.CACHE_DIR, "downloads", "归藏-多本打包.zip")
(dm, mcount), seenm = with_zip_spy(lambda: ui_server.build_zip_multi(["zb001", "zb003"]))
names = zip_names(dm)
chk("B1 多本打包一份合法 zip，每本一个目录、图不互相覆盖",
    dm == DESTM and mcount == 2 and names is not None and len(names) == 2
    and all(n.count("/") <= 1 for n in names), (dm, mcount, names))
chk("B2 多本那份 dest 不区分书单（固定名），照样先写随机 .part 再改名",
    len(seenm) == 1 and seenm[0] != DESTM and seenm[0].endswith(".part")
    and os.path.dirname(seenm[0]) == os.path.dirname(DESTM), seenm)
chk("B3 多本打包收尾后不留 .part", parts_in(DESTM) == [], parts_in(DESTM))

# ───────────────────────── C. Anki 卡包（build_apkg）─────────────────────────
import genanki  # noqa: E402

ITEMS = [{"text": "第一条划线", "kind": "划线", "at": 1700000000},
         {"text": "第二条想法", "kind": "想法", "at": 1700000001}]
ui_server.notes_for_book = lambda any_id, title="", author="": (ITEMS, "zb001", "index")

apkg_seen = []
_orig_wtf = genanki.Package.write_to_file


def _spy_wtf(self, path, *a, **k):
    apkg_seen.append(path)
    return _orig_wtf(self, path, *a, **k)


genanki.Package.write_to_file = _spy_wtf
try:
    apath, acount = ui_server.build_apkg("zb001", "卡包书")
finally:
    genanki.Package.write_to_file = _orig_wtf
chk("C1 卡包照旧是一份合法 apkg（zip 里拆得出 collection），卡数对得上",
    acount == 2 and apkg_ok(apath), (apath, acount))
chk("C2 卡包写到同目录的随机 .part，不是终稿",
    len(apkg_seen) == 1 and apkg_seen[0] != apath and apkg_seen[0].endswith(".part")
    and os.path.dirname(apkg_seen[0]) == os.path.dirname(apath), apkg_seen)
chk("C3 卡包收尾后不留 .part", parts_in(apath) == [], parts_in(apath))

# ──────────────────── D. 失败 / 中止路径（旧档必须保住）───────────────────
OLD = b"OLD-ARTIFACT-CONTENT"
for marker, exc, label in (("D1", OSError(28, "No space left on device"), "改名失败"),
                           ("D2", KeyboardInterrupt(), "中止信号")):
    bid = "zfail%s" % marker
    seed(bid, "失败一本")
    dest = os.path.join(ui_server.DOWNLOAD_DIR, bid + ".zip")
    with open(dest, "wb") as f:
        f.write(OLD)
    orig = os.replace

    def boom(src, dst, _exc=exc):
        raise _exc

    os.replace = boom
    thrown = None
    try:
        ui_server.build_zip(bid)
    except BaseException as e:
        thrown = e
    finally:
        os.replace = orig
    same = open(dest, "rb").read() == OLD
    chk("%s %s：异常照旧往上抛、旧成品一字不动、不留 .part" % (marker, label),
        isinstance(thrown, type(exc)) and same and parts_in(dest) == [],
        (type(thrown).__name__ if thrown else None, same, parts_in(dest)))


# 打包写到一半失败（磁盘满）：临时件收干净，旧成品原样。
class _HalfZip(zipfile.ZipFile):
    def writestr(self, *a, **k):
        raise OSError(28, "No space left on device")


seed("zhalf", "写到一半")
HALF = os.path.join(ui_server.DOWNLOAD_DIR, "zhalf.zip")
with open(HALF, "wb") as f:
    f.write(OLD)
orig_zf = zipfile.ZipFile
zipfile.ZipFile = _HalfZip
thrown = None
try:
    ui_server.build_zip("zhalf")
except BaseException as e:
    thrown = e
finally:
    zipfile.ZipFile = orig_zf
chk("D3 打包写到一半磁盘满：异常照抛、旧成品一字不动、不留 .part",
    isinstance(thrown, OSError) and open(HALF, "rb").read() == OLD and parts_in(HALF) == [],
    (type(thrown).__name__ if thrown else None, parts_in(HALF)))


# 对照：旧写法「直写终稿 + 半路抛」确实把上一份导出顶成了半截 —— 这一刀不是空转。
def _old_direct_write(dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("first.md", "第一笔写进去了")
        raise OSError(28, "No space left on device")


CONTRAST = os.path.join(ui_server.DOWNLOAD_DIR, "zcontrast.zip")
with open(CONTRAST, "wb") as f:
    f.write(OLD)
try:
    _old_direct_write(CONTRAST)
except OSError:
    pass
after = open(CONTRAST, "rb").read()
chk("D4 对照：旧写法直写终稿，半路抛已把上一份导出顶成半截",
    after != OLD and OLD not in after, (len(after), after[:24]))

# ───────────────────── E. 接线与口径（一处真相）─────────────────────
SRC = (REPO / "ui_server.py").read_text(encoding="utf-8")
CALLS = SRC.count("_atomic_artifact(dest,") - SRC.count("def _atomic_artifact(dest,")
chk("E1 三种成品都从 _atomic_artifact 这一个出口走",
    CALLS == 3, CALLS)
chk("E2 `.part` 临时名格式在 ui_server 里只有一处真相",
    SRC.count('tmp = "%s.%d.%s.part" % (dest, os.getpid(), uuid.uuid4().hex[:8])') == 1,
    SRC.count('tmp = "%s.%d.%s.part" % (dest, os.getpid(), uuid.uuid4().hex[:8])'))
chk("E3 两个 zip 写口与卡包写口都落进临时件（旧写法直写终稿已不在代码里）",
    SRC.count('zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)') == 2
    and "genanki.Package(deck).write_to_file(tmp)" in SRC,
    (SRC.count('zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)'),
     "genanki.Package(deck).write_to_file(tmp)" in SRC))

# 进程内起一个真服务：两条没有别的门禁走到的路由各真发一次。
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
srv.daemon_threads = True
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def get_json(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=20) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


try:
    st, body = get_json("/api/zip-multi?books=zb001,zb003&json=1")
    chk("E4 /api/zip-multi 回 200，路径真能打开成一份合法 zip、不留残件",
        st == 200 and body.get("ok") and body.get("count") == 2
        and zip_names(body["path"]) is not None and parts_in(body["path"]) == [],
        (st, body if not isinstance(body, dict) else {k: body.get(k) for k in ("ok", "count", "path")}))
    st, body = get_json("/api/apkg?book=zb001&title=%E5%8D%A1%E5%8C%85&json=1")
    chk("E5 /api/apkg 回 200，路径真能打开成一份合法 apkg、不留残件",
        st == 200 and body.get("ok") and apkg_ok(body["path"]),
        (st, body if not isinstance(body, dict) else {k: body.get(k) for k in ("ok", "count", "path")}))
    chk("E6 两条路由跑完都不留 .part",
        parts_in(os.path.join(ui_server.CACHE_DIR, "downloads")) == []
        and parts_in(os.path.join(ui_server.CACHE_DIR, "apkg")) == [],
        (parts_in(os.path.join(ui_server.CACHE_DIR, "downloads")),
         parts_in(os.path.join(ui_server.CACHE_DIR, "apkg"))))
except Exception as e:                               # noqa: BLE001
    chk("E4 /api/zip-multi 回 200，路径真能打开成一份合法 zip、不留残件", False,
        "%s: %s" % (type(e).__name__, e))
    chk("E5 /api/apkg 回 200，路径真能打开成一份合法 apkg、不留残件", False, "见 E4")
    chk("E6 两条路由跑完都不留 .part", False, "见 E4")
finally:
    srv.shutdown()
    srv.server_close()

print()
print("导出成品落盘（单本 / 多本 / 卡包）：%d 项通过，失败 %d 项" % (PASSED, len(FAIL)))
if FAIL:
    print("  ✗ " + "、".join(FAIL))
sys.exit(1 if FAIL else 0)
