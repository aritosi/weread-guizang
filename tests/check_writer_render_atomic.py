#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作导出 PNG / PDF：渲染产物原子落盘（不留半张图、不截掉上一份导出）。

为什么单开这一条
    `ui_server.writer_export(kind, …)` 的四档导出里，epub 走
    `book_export.build_epub`、md 走 `ui_server._write_text`，两条都已经是
    「先写同目录随机临时件、成功了再 `os.replace`」那一套；png / pdf 这两档
    先前没有：`writer.export_image` / `export_pdf` 把铬内核的产物直接写到终稿上

        page.screenshot(path=dest, full_page=True)
        page.pdf(path=dest, …)

    两个代价都在这一句上：

      · **截掉上一份完整导出**：`/api/writer/export` 是请求线程里直接调的
        （服务是 ThreadingHTTPServer），渲染到一半失败 / 整趟被强杀（关窗口 /
        断电 / 活动监视器里强杀），`dest` 上就留着半张图 / 半份 PDF，而它已经
        顶掉了上一次那份完整导出 —— 用户拿到的是一份打不开的文件；
      · **两只手同时写**：连点两次「导出图片」就是两个请求线程往同一个 `dest`
        上落，两边各写各的，顶成正式文件的是一份交织的字节。

    收口与 `book_export.build_epub` / `build_pdf`、`ui_server._atomic_artifact`
    同一把尺子：临时件是 `<目标>.<pid>.<八位随机>.part`，写完整了再改名，失败 /
    中止（`BaseException`）先收残件再往外抛。

这一条钉住（假铬内核，不开真浏览器）
  A. 正常导出：铬被要求写的是同目录随机 `.part`、改名之后才是正式成品、
     旁边不留 `.part`、返回的仍是 `dest`；
  B. 渲染失败 / 中止信号：异常照抛、旧成品逐字节不动、不留 `.part`；
  C. 两条线程同时导同一篇：都成，落下的是一整份、不留 `.part`；
  D. 对照：直写终稿写到一半失败，旧导出确实被截成半份（证明这道闸不是空转）；
  E. 源码口径：png / pdf 两档都走 `_render_atomic`，两个 `path=dest` 的旧写法
     不再出现，临时名从 `os.getpid()` + `uuid4` 拼。

全离线：`sync_playwright` 换成假的，只写系统临时目录里的沙盒导出文件夹，
不 import 浏览器、不联网、不碰真实书库，故归 --fast 静态段。

跑法：.venv/bin/python tests/check_writer_render_atomic.py
"""
import atexit
import contextlib
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import writer as W  # noqa: E402

# 自带沙盒：不碰用户真实书库 / cache。
SB = pathlib.Path(tempfile.mkdtemp(prefix="gz-writer-render-atomic-"))
atexit.register(lambda: shutil.rmtree(SB, ignore_errors=True))

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:220]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def render_dest(name):
    """沙盒导出文件夹里的一份成品路径。"""
    out = SB / "downloads"
    out.mkdir(parents=True, exist_ok=True)
    return str(out / name)


def parts_in(dest):
    folder = os.path.dirname(dest)
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if n.endswith(".part"))


def blob_of(path):
    with open(path, "rb") as f:
        return f.read()


# ─────────────────────────── 假铬内核 ───────────────────────────
class _FakePage:
    def __init__(self, sink):
        self.sink = sink

    def goto(self, *_a, **_k):
        return None

    def evaluate(self, *_a, **_k):
        return None

    def screenshot(self, path=None, full_page=False):
        self.sink(path)

    def pdf(self, path=None, **_k):
        self.sink(path)


class _FakeBrowser:
    def __init__(self, sink):
        self.sink = sink

    def new_page(self, **_k):
        return _FakePage(self.sink)

    def close(self):
        return None


class _FakeChromium:
    def __init__(self, sink):
        self.sink = sink

    def launch(self):
        return _FakeBrowser(self.sink)


class _FakePW:
    def __init__(self, sink):
        self.chromium = _FakeChromium(sink)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@contextlib.contextmanager
def fake_playwright(sink):
    """把 `from playwright.sync_api import sync_playwright` 换成假的。

    只记下铬被要求写到哪个 path（`sink(path)`），不开真浏览器。
    """
    saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _FakePW(sink)
    pkg = types.ModuleType("playwright")
    pkg.sync_api = mod
    sys.modules["playwright"] = pkg
    sys.modules["playwright.sync_api"] = mod
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


HTML = "<!doctype html><html><body><p>正文一段</p></body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes" * 4
PDF = b"%PDF-1.4 fake\n%%EOF\n"

# ─────────────────────────── A：PNG 正常导出 ───────────────────────────
PNG_DEST = render_dest("稿子.png")
png_seen = []


def write_png(path):
    png_seen.append(path)
    with open(path, "wb") as f:
        f.write(PNG)


with fake_playwright(write_png):
    ret = W.export_image(HTML, PNG_DEST, width=760, scale=2)
chk("A1 铬被要求写到同目录的随机 .part，不是终稿",
    len(png_seen) == 1 and png_seen[0] != PNG_DEST
    and png_seen[0].endswith(".part")
    and os.path.dirname(png_seen[0]) == os.path.dirname(PNG_DEST),
    png_seen)
chk("A2 改名之后终稿逐字节是那一张图，旁边不留 .part",
    os.path.isfile(PNG_DEST) and blob_of(PNG_DEST) == PNG and parts_in(PNG_DEST) == [],
    (parts_in(PNG_DEST),))
chk("A3 返回值仍是终稿路径（调用方拿它做「打开所在文件夹」）", ret[0] == PNG_DEST, ret)

# ─────────────────────────── B：PNG 失败 / 中止 ───────────────────────────
PNG_OLD = render_dest("失败.png")
with open(PNG_OLD, "wb") as f:
    f.write(b"OLD-COMPLETE-EXPORT")


def half_png(path):
    with open(path, "wb") as f:
        f.write(b"NEW-HALF")
    raise OSError(5, "chrome died")


thrown = None
try:
    with fake_playwright(half_png):
        W.export_image(HTML, PNG_OLD)
except BaseException as e:                     # noqa: BLE001 —— 门禁要看的就是「抛没抛」
    thrown = e
chk("B1 渲到一半失败：异常照抛、旧导出一字不动、不留 .part",
    isinstance(thrown, OSError) and blob_of(PNG_OLD) == b"OLD-COMPLETE-EXPORT"
    and parts_in(PNG_OLD) == [], (type(thrown).__name__ if thrown else None, parts_in(PNG_OLD)))


def abort_png(path):
    with open(path, "wb") as f:
        f.write(b"NEW-HALF")
    raise KeyboardInterrupt()


thrown = None
try:
    with fake_playwright(abort_png):
        W.export_image(HTML, PNG_OLD)
except BaseException as e:                     # noqa: BLE001
    thrown = e
chk("B2 中止信号（KeyboardInterrupt）：照旧往外抛、旧导出一字不动、不留 .part",
    isinstance(thrown, KeyboardInterrupt) and blob_of(PNG_OLD) == b"OLD-COMPLETE-EXPORT"
    and parts_in(PNG_OLD) == [], (type(thrown).__name__ if thrown else None, parts_in(PNG_OLD)))

# ─────────────────────────── C：两个写者同时导同一张图 ───────────────────────────
PNG_RACE = render_dest("并发.png")
race_res = {}
race_lock = threading.Lock()
race_arrive = threading.Barrier(2)
race_seen = []


def slow_png(path):
    with race_lock:
        race_seen.append(path)
    race_arrive.wait(timeout=30)
    with open(path, "wb") as f:
        f.write(PNG)


def png_worker(i):
    try:
        with fake_playwright(slow_png):
            W.export_image(HTML, PNG_RACE)
        race_res[i] = "ok"
    except BaseException as e:                 # noqa: BLE001
        race_res[i] = "%s: %s" % (type(e).__name__, e)


# 线程在 fake_playwright 之外起，各线程自己装上假的，互不干扰。
ts = [threading.Thread(target=png_worker, args=(i,)) for i in (1, 2)]
for t in ts:
    t.start()
for t in ts:
    t.join(40)
chk("C1 同一张图两个写者同时导：都成、不留 .part",
    race_res.get(1) == race_res.get(2) == "ok" and parts_in(PNG_RACE) == [],
    (race_res, parts_in(PNG_RACE)))
chk("C2 两个写者拿到的临时名一次一个（不是共用固定名）",
    len(race_seen) == 2 and len(set(race_seen)) == 2
    and all(p.endswith(".part") for p in race_seen), race_seen)
chk("C3 落下的是一整张图（某一个写者的整份，不是交织）",
    blob_of(PNG_RACE) == PNG, blob_of(PNG_RACE)[:20])

# ─────────────────────────── D：PDF 正常 / 失败 ───────────────────────────
PDF_DEST = render_dest("稿子.pdf")
pdf_seen = []


def write_pdf(path):
    pdf_seen.append(path)
    with open(path, "wb") as f:
        f.write(PDF)


with fake_playwright(write_pdf):
    W.export_pdf(HTML, PDF_DEST)
chk("D1 PDF 同样先写随机 .part、改名后终稿是一整份、不留 .part",
    len(pdf_seen) == 1 and pdf_seen[0] != PDF_DEST
    and pdf_seen[0].endswith(".part")
    and os.path.dirname(pdf_seen[0]) == os.path.dirname(PDF_DEST)
    and blob_of(PDF_DEST) == PDF and parts_in(PDF_DEST) == [],
    (pdf_seen, parts_in(PDF_DEST)))

PDF_OLD = render_dest("失败.pdf")
with open(PDF_OLD, "wb") as f:
    f.write(b"OLD-PDF-COMPLETE")


def abort_pdf(path):
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 half")
    raise KeyboardInterrupt()


thrown = None
try:
    with fake_playwright(abort_pdf):
        W.export_pdf(HTML, PDF_OLD)
except BaseException as e:                     # noqa: BLE001
    thrown = e
chk("D2 PDF 中止：照旧往外抛、旧成品一字不动、不留 .part",
    isinstance(thrown, KeyboardInterrupt) and blob_of(PDF_OLD) == b"OLD-PDF-COMPLETE"
    and parts_in(PDF_OLD) == [], (type(thrown).__name__ if thrown else None, parts_in(PDF_OLD)))

# ─────────────────────────── E：对照 —— 旧写法确实会截掉旧导出 ───────────────────────────
CTRL = render_dest("对照.png")
with open(CTRL, "wb") as f:
    f.write(b"OLD-COMPLETE-EXPORT")
try:
    with open(CTRL, "wb") as f:                # 老那句 page.screenshot(path=dest)
        f.write(b"NEW-HALF")
        raise OSError(5, "chrome died")
except OSError:
    pass
chk("E1 对照：直写终稿写到一半失败，上一份完整导出确实被截成半份",
    blob_of(CTRL) == b"NEW-HALF", blob_of(CTRL))

# ─────────────────────────── F：源码口径 ───────────────────────────
SRC = (REPO / "writer.py").read_text(encoding="utf-8")


def _func_src(name):
    """从 `def name(` 到下一个顶层 `def` 之间的那段源码。"""
    a = SRC.index("\ndef %s(" % name)
    b = SRC.find("\ndef ", a + 1)
    return SRC[a: b if b != -1 else len(SRC)]


img = _func_src("export_image")
pdf = _func_src("export_pdf")
chk("F1 PNG 档走 _render_atomic，不再有 page.screenshot(path=dest",
    "_render_atomic(dest" in img and "screenshot(path=dest" not in img,
    [l.strip() for l in img.splitlines() if "screenshot" in l])
chk("F2 PDF 档走 _render_atomic，不再有 page.pdf(path=dest",
    "_render_atomic(dest" in pdf and "pdf(path=dest" not in pdf,
    [l.strip() for l in pdf.splitlines() if "pdf(" in l])
chk("F3 临时名从 pid + uuid4 拼、尾巴是 .part",
    'os.getpid()' in SRC and 'uuid.uuid4().hex[:8]' in SRC
    and '"%s.%d.%s.part"' in SRC,
    [l.strip() for l in SRC.splitlines() if "%s.%d.%s.part" in l])

bad = FAIL
print("\n写作导出渲染落盘体检：%d 项通过，失败 %d 项" % (PASSED, len(bad)))
for n in bad:
    print("  ✗ " + n)
sys.exit(1 if bad else 0)
