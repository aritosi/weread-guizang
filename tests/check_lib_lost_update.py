#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""书架账「读—改—写」两个请求同时进来时，后写的那份不许把先写的那一笔抹掉。

为什么要单开一条
    `library.json`（夹子 / 归入哪一格 / 状态标签 / 顺序 / 标签）是「读整份 → 改一笔 →
    写整份」的账，而服务是 `ThreadingHTTPServer`：两个窗口 / 两个标签页各点一下
    「新建文件夹」「贴标签」「归入夹子」，两趟请求就会各自 `load_lib()` 拿到同一份旧账、
    各自改一笔、再各自 `save_lib()` 顶回去 —— 后写的那一份把先写的那一笔整份抹掉。
    实测（两线程同时 `folder.new`，在 load 与 save 之间对齐）：两个 id 都回了
    `ok=true`，盘上只剩一个夹子。用户看到的是「建了两个、刷新后少一个」。

    `_WRITE_LOCK` 只保证**单次落盘**不打架（临时名各写各的、`os.replace` 不扑空），
    管不住这两次落盘之间的窗口。阅读时长 / 阅读计划 / 热力图那几本账各有一把这样的
    锁（`_READSTAT_LOCK` / `_PLAN_LOCK` / `_ACTIVITY_LOCK`），书架账这一格一直缺一把；
    现在补的是 `_LIB_LOCK`：`_action` 里会 `save_lib()` 的那九个动作整段罩住，
    `/api/book_state` 与 `/api/delete_many` 这两条只走 `do_POST` 的路各自罩住。

这一条钉三层
  A 源码：`_LIB_LOCK` 确实是一把 RLock；`_action` 在进分派器之前按 `_LIB_ACTIONS`
     把整段罩住；`_dispatch` 里每一处 `save_lib(` 所在的动作都在 `_LIB_ACTIONS` 表里
     （漏登记的 action 会绕过这把锁，当场红）；两条 `do_POST` 路各自 `with _LIB_LOCK:`
     罩在 `load_lib()` 之前。
  B 对照（不是空转）：把**旧写法**（没有锁）在这里重抄一遍，同一把行为级间谍挂在它
     身上，两个线程先各自 load、对齐之后再各自 save —— 间谍量到「同时有 >1 个人在
     读写窗口里」，且盘上只剩后写的那一个夹子。旧写法确实会丢更新，这一条量得到。
  C 新写法：同一把间谍挂在真服务上，两个请求同时打 `/api/action` 的 `folder.new`，
     「同时在读写窗口里」的最大值必须是 1，两个夹子都在盘上、两个回包都是 `ok=true`。

全离线、只碰临时目录，不联网、不开浏览器，归静态段，--fast 也得带上。
"""
import atexit
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

# 自带一个沙盒，绝不碰用户真实的 cache/ 与书库，也不和别的套件共用那份共享沙盒。
SB = pathlib.Path(tempfile.mkdtemp(prefix="gz-lib-race-"))
atexit.register(lambda: shutil.rmtree(SB, ignore_errors=True))
for _d in ("data", "books", "shots"):
    (SB / _d).mkdir(parents=True, exist_ok=True)
os.environ["GUIZANG_DATA"] = str(SB / "data")
os.environ["GUIZANG_BOOKS"] = str(SB / "books")
os.environ["GUIZANG_SHOT_DIR"] = str(SB / "shots")
os.environ["GUIZANG_ANNA_NO_WINDOW"] = "1"

import ui_server  # noqa: E402  —— 必须在环境变量设好之后 import

FAIL = []


def chk(name, ok, extra=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   " + repr(extra)))
    if not ok:
        FAIL.append(name)


SERVER = (REPO / "ui_server.py").read_text(encoding="utf-8")
ACTION = SERVER[SERVER.index("    def _action(self, body):"):
                SERVER.index("    def _dispatch(self, body):")]
DISPATCH = SERVER[SERVER.index("    def _dispatch(self, body):"):
                  SERVER.index("\ndef main():")]

REAL_LOAD = ui_server.load_lib
REAL_SAVE = ui_server.save_lib


def lib_names():
    """盘上那份书架账里，微信读书那一格的夹子名（按落盘顺序）。"""
    lib = REAL_LOAD()
    return [f.get("name") for f in ui_server.lib_scope(lib, None)["folders"]]


def wipe_lib():
    if os.path.exists(ui_server.LIB_PATH):
        os.remove(ui_server.LIB_PATH)


# ── A. 源码体检 ──────────────────────────────────────────────────────────────
chk("源码：_LIB_LOCK 是一把 RLock（可重入，save_lib 里还要再拿 _WRITE_LOCK）",
    re.search(r"^_LIB_LOCK = threading\.RLock\(\)$", SERVER, re.M) is not None)

chk("源码：_action 在进分派器之前按 _LIB_ACTIONS 罩住整段（含 save_lib）",
    "action in _LIB_ACTIONS" in ACTION and "with _LIB_LOCK:" in ACTION
    and ACTION.index("with _LIB_LOCK:") < ACTION.index("self._dispatch(body)"))

# action 表与分派器里的写口对不对得上：每一处 save_lib( 所在的分支都得登记。
_parts = re.split(r'\n        if action == "', DISPATCH)
_savers = set()
for _p in _parts[1:]:
    _name = _p.split('"', 1)[0]
    if "save_lib(" in _p:
        _savers.add(_name)
_m = re.search(r"_LIB_ACTIONS = frozenset\(\{(.*?)\}\)", SERVER, re.S)
_declared = set(re.findall(r'"([a-z.]+)"', _m.group(1))) if _m else set()
chk("源码：分派器里每个 save_lib( 的动作都登记在 _LIB_ACTIONS（漏登记就绕过锁）",
    _savers and _savers == _declared, (_savers, _declared))

for _path in ("/api/book_state", "/api/delete_many"):
    _start = SERVER.index('if u.path == "%s":' % _path)
    _end = SERVER.index("if u.path ==", _start + 10)
    _block = SERVER[_start:_end]
    chk("源码：%s 的 load → save 整段在 with _LIB_LOCK 里" % _path,
        re.search(r"with _LIB_LOCK:\n\s+lib = load_lib\(", _block) is not None)

chk("源码：改账本的动作不止一两条（表没退化成空 / 只罩一处）", len(_declared) >= 8, _declared)


# ── B/C. 行为级间谍 ─────────────────────────────────────────────────────────
class Spy:
    """记「同时有几个人在『读了账本、还没写完』这一段里」，并把这窗口撑开。

    `load` 进来 +1，`save` 写完再 -1；`save` 先停 0.1 秒 —— 没有锁时第二个写者
    必定在这个窗口里挤进来（不是靠运气）。有锁时它连 `load_lib()` 都到不了。
    """

    def __init__(self):
        self.guard = threading.Lock()
        self.open = 0
        self.max_open = 0

    def load(self):
        lib = REAL_LOAD()
        with self.guard:
            self.open += 1
            self.max_open = max(self.max_open, self.open)
        return lib

    def save(self, lib):
        time.sleep(0.1)
        REAL_SAVE(lib)
        with self.guard:
            self.open -= 1


# ── B. 对照：旧写法（没有锁）真的会丢更新 ────────────────────────────────────
spy = Spy()
ui_server.load_lib = spy.load
ui_server.save_lib = spy.save
try:
    wipe_lib()
    barrier = threading.Barrier(2)

    def old_folder_new(name):
        """旧写法的镜子：`folder.new` 改之前逐行同形（load → 改 → save，中间不锁）。"""
        lib = spy.load()
        barrier.wait(5)          # 两个都读到了同一份旧账，再各自往下写
        s = ui_server.lib_scope(lib, None)
        s["folders"].append({"id": "f" + name, "name": name})
        spy.save(lib)

    _ts = [threading.Thread(target=old_folder_new, args=(n,)) for n in ("甲", "乙")]
    for _t in _ts:
        _t.start()
    for _t in _ts:
        _t.join(10)
    old_names = lib_names()
    chk("对照：旧写法两个写者同时在读写窗口里（间谍量得到，不是空转）",
        spy.max_open >= 2, spy.max_open)
    chk("对照：旧写法后写的那一份把先写的抹掉了（盘上只剩一个夹子）",
        len(old_names) == 1, old_names)
finally:
    ui_server.load_lib = REAL_LOAD
    ui_server.save_lib = REAL_SAVE


# ── C. 新写法：真服务上两个请求同时改书架账 ──────────────────────────────────
spy = Spy()
ui_server.load_lib = spy.load
ui_server.save_lib = spy.save
srv = None
try:
    wipe_lib()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(payload):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/action" % port,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    res = {}

    def one(name):
        res[name] = post({"action": "folder.new", "name": name})

    _ts = [threading.Thread(target=one, args=(n,)) for n in ("丙", "丁")]
    for _t in _ts:
        _t.start()
    for _t in _ts:
        _t.join(15)
    new_names = lib_names()
    chk("新写法：两个请求都回了 ok=true 与各自的 id",
        len(res) == 2 and all(v.get("ok") and v.get("id") for v in res.values()), res)
    chk("新写法：读写窗口里同时最多只有一个人（_LIB_LOCK 把 load → save 串起来）",
        spy.max_open == 1, spy.max_open)
    chk("新写法：两个夹子都在盘上（后写的不再抹掉先写的）",
        set(new_names) == {"丙", "丁"}, new_names)
    chk("新写法：坏 action 形状仍回「未知操作」，没被锁那层变成 unhashable 报错",
        post({"action": []}).get("msg") == "未知操作")
finally:
    ui_server.load_lib = REAL_LOAD
    ui_server.save_lib = REAL_SAVE
    if srv is not None:
        srv.shutdown()

# ── D. 好值回归：单条动作照旧走得通，账本内容一个字不差 ──────────────────────
wipe_lib()
srv = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    def post(payload):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/action" % port,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    a = post({"action": "folder.new", "name": "回归甲"})
    b = post({"action": "folder.new", "name": "回归乙"})
    chk("回归：两条顺序请求照旧都落盘", a.get("ok") and b.get("ok")
        and set(lib_names()) == {"回归甲", "回归乙"}, lib_names())
    d = post({"action": "folder.drop", "id": a.get("id")})
    chk("回归：删夹子照旧只删那一个",
        d.get("ok") and lib_names() == ["回归乙"], (d, lib_names()))
finally:
    srv.shutdown()

print()
if FAIL:
    print("书架账丢更新门禁：%d 项未过：%s" % (len(FAIL), FAIL))
    sys.exit(1)
print("书架账丢更新门禁：全部通过")
