#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库根那批运行期模块里，模块级常量不许「写了没人读」。

为什么要单开这一条
    这正是本轮清出来的那一类死码：`anna_browser.CMD_POLL_S`、`mindmap.FORM_NAME`、
    `ui_server.WALL_MIMES` / `NOTES_LOCK` —— 四个全大写常量躺在根目录模块里，全仓
    （含 tests/、mcp/、docs/、壳脚本）一个引用点都没有。它们不报错、不影响运行，
    所以谁都不会去删；而它们又不是没成本：`NOTES_LOCK` 与紧挨着的真锁 `_notes_lock`
    只差一个下划线，改那一段的人得先停下来分辨哪把才是活的。同一类东西在 #219 那批
    里已经删过一轮函数，常量这一档没人管，于是单开这一条把它钉住。

判据（一把保守的尺）
    · 只审**仓库根**的 `*.py`（进 .app 的那批运行期模块，与《架构与模块地图》§2 同一批）；
    · 只看模块级、**单一名字**的赋值（`NAME = …` / `NAME: 类型 = …`），名字形如
      `^_?[A-Z][A-Z0-9_]*$`（全大写才算「常量」；小写模块级变量不在此列）；
    · 一个常量算「有人读」，只要它的名字在**全仓文本**里除了自己的定义行之外还出现过。
      引用面按「任何文件里提过一句」算（tests/、mcp/、docs/、壳脚本、注释全算），
      所以这把尺子只会漏报、不会错报；
    · 只有**定义行**不算引用 —— 否则「同一个名字在另一个模块里也定义了一次」会被
      误当成有人读。

    为什么只收常量、不收函数：本仓有装饰器注册的分发表（`mindmap._register` 把
    `_place_radial` / `_place_fishbone` / `_place_concept` 塞进 `_PLACE`），函数名不出现在
    任何调用点也照样是活的；常量没有这种动态派发，全大写名字没人读就是没人读。

这条门禁带四组对照
    · 一个有人读、一个没人读 → 只点名后者；
    · 同一个名字在另一个模块里也定义了一次 → 两份都点名（定义不算「有人读」）；
    · 只在门禁 / 注释里被读过一次 → 不点名（不误报）；
    · 小写模块级变量 → 不在射程里。

纯文件走查，不起服务、不联网、不开浏览器，归 --fast。

跑法：.venv/bin/python tests/check_dead_consts.py
"""
import ast
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 全大写（可带一个前导下划线）才算「常量」。`__X__` 这类 dunder 不算：
# 它们是模块协议的一部分，不是常量。
CONST_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
# 与 `\bNAME\b` 等价的一把尺：按最长标识符切，`DEAD_CONST2` 不会被当成 `DEAD_CONST`。
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 扫描引用面时跳过的目录：依赖、版本库、构建产物、数据目录（cache/ 与书库不是源码）。
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", "target", "dist",
             "cache", "output", "安装包", ".dsh-task"}
# 二进制 / 归档不进文本引用面（它们的字节里出现一个名字不算「有人读」）。
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".dmg",
            ".zip", ".apkg", ".ttf", ".woff", ".woff2", ".bin", ".pyc", ".so",
            ".dylib", ".dll", ".exe", ".mp3", ".mp4", ".m4a", ".pdf", ".epub"}
MAX_BYTES = 8 * 1024 * 1024

# 真有豁免就写在这儿（键是 `模块名:常量名`），并写清为什么这个常量天生没人读。
# 空表是目标状态：一个常量要么有人读，要么该删。
ALLOW = {}

FAILED = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:300]))
    if cond:
        PASSED += 1
    else:
        FAILED.append(name)


def const_defs(source):
    """模块级、单一名字的全大写常量：[(名字, 定义行号)]。"""
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            continue
        if CONST_RE.match(name):
            out.append((name, node.lineno))
    return out


def dead_consts(sources, corpus_text):
    """sources 是 [(模块名, 源码)]，corpus_text 是全仓引用面（含这些源码）。

    回 [(模块名, 行号, 常量名)]：名字在 corpus 里除了它自己的定义行之外一次都没出现。
    定义行按所有 sources 一起扣（同一个名字在别处又定义一次，不算「有人读」）。
    """
    counts = Counter(IDENT_RE.findall(corpus_text))
    own = Counter()
    defs = []
    for label, source in sources:
        lines = source.split("\n")
        for name, lineno in const_defs(source):
            defs.append((label, lineno, name))
            line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
            own[name] += Counter(IDENT_RE.findall(line))[name]
    return [(label, lineno, name) for label, lineno, name in defs
            if counts[name] - own[name] <= 0]


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def root_modules():
    return sorted(f for f in os.listdir(ROOT)
                  if f.endswith(".py") and os.path.isfile(os.path.join(ROOT, f)))


def walk_corpus():
    """全仓文本拼成一份引用面。读不动的（权限 / 太大 / 二进制）跳过。

    自己这份不算引用面：门禁的说明里点名写清「上一轮删了哪几个死常量」，如果那句
    也被当成「有人读」，这条门禁提一句就把自己写瘸了 —— 见过一次，别再犯。
    """
    me = os.path.abspath(__file__)
    chunks = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and not d.startswith(".build-")]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            p = os.path.join(dirpath, fn)
            if os.path.abspath(p) == me:
                continue
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
                chunks.append(read_text(p))
            except OSError:
                continue
    return "\n".join(chunks)


# ── A. 对照：这把尺子会点名、也会安静 ─────────────────────────────
_SYNTH = "USED_CONST = 1\nDEAD_CONST = 2\n"
_SYNTH_CORPUS = _SYNTH + "print(USED_CONST)\nprint('DEAD_CONST2')\n"
_got = dead_consts([("synth.py", _SYNTH)], _SYNTH_CORPUS)
chk("对照：有人读的不点名、没人读的点名（且 `DEAD_CONST2` 不冒充 `DEAD_CONST`）",
    _got == [("synth.py", 2, "DEAD_CONST")], _got)

_got = dead_consts([("a.py", "SHARED = 1\n"), ("b.py", "SHARED = 1\n")],
                   "SHARED = 1\nSHARED = 1\n")
chk("对照：同一个名字在另一处只被再定义一次，不算「有人读」（两份都点名）",
    _got == [("a.py", 1, "SHARED"), ("b.py", 1, "SHARED")], _got)

_got = dead_consts([("c.py", "ONLY_TESTS = 1\n")],
                   "ONLY_TESTS = 1\nassert ONLY_TESTS == 1\n")
chk("对照：只在门禁 / 注释里被读过一次也算有人读（不误报）", _got == [], _got)

_got = dead_consts([("d.py", "lower_name = 1\nDEAD2 = 2\n")],
                   "lower_name = 1\nDEAD2 = 2\n")
chk("口径：小写模块级变量不在这一刀的射程里", _got == [("d.py", 2, "DEAD2")], _got)

# ── B. 真仓库：根目录那批运行期模块逐个体检 ───────────────────────
mods = root_modules()
corpus = walk_corpus()
chk("扫描面没退化成空（认得出 30+ 个根模块与界面 / 后端的正文）",
    len(mods) >= 25 and "GUIZANG_SELFTEST_DIR" in corpus and "def build_zip" in corpus,
    (len(mods), len(corpus)))

sources = [(fn, read_text(os.path.join(ROOT, fn))) for fn in mods]
bad = [(m, l, n) for m, l, n in dead_consts(sources, corpus)
       if (m + ":" + n) not in ALLOW]
for m, l, n in bad:
    print("       %s:%d 常量 `%s` 全仓没人读 —— 删掉，或写进 ALLOW 并说清为什么" % (m, l, n))
chk("根目录运行期模块里没有「写了没人读」的全大写常量", not bad, bad)

# 同一条判据也要认得出真·活常量，别把「全仓都在用」的也点了（对照落回真数据）。
_live = {n for _m, _l, n in dead_consts(sources, corpus)}
chk("对照：真仓库里在用的常量（如 `CACHE_DIR`）没被点名", "CACHE_DIR" not in _live, sorted(_live)[:8])

print()
if FAILED:
    print("死常量门禁：失败 %d 项" % len(FAILED))
    for n in FAILED:
        print("  ✗ " + n)
    sys.exit(1)
print("死常量门禁：通过 %d 项，失败 0 项" % PASSED)
