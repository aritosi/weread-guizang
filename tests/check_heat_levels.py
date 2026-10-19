#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁：两张热力图的色阶档位（ui.html 的 heatGridHtml × activity.py 的 level_of）。

它守的是什么
    `activity.levels()` 给三个边界、`level_of()` 回 **0..3 四档**；界面这套色阶却是
    「没有记录 + lv1..lv4」五格。原先那一行 `c[2] ? ' lv' + c[2] : ''` 把 0 档直接
    当成「没有记录」涂成底色、最深一档 lv4 永远涂不到：

      · 秒数 > 0 但不到峰值 1/4 的那一天，和根本没有记录的一天**是同一个灰** ——
        用户明明用了半小时，热力图上却什么都没有；
      · 图例里那五格（少 ▢ ▢ ▢ ▢ ▢ 多）最深那格永远用不上，等于在骗人。

    正确口径：0 秒留底色，有记录的 0/1/2/3 档抬成 lv1/lv2/lv3/lv4。

怎么验
    把 ui.html 里**真那个函数** `heatGridHtml` 抽出来交给 node 跑（不另抄一份），
    喂进 `activity.summary()` 现算的 cells，再解析回来的 HTML 类名。控制组用旧写法
    `c[2] ? 'lv'+c[2] : ''` 跑同一份数据，证明这条门禁不是空转。

纯文件 + `node` 子进程，不联网、不起服务、不开浏览器，归 --fast。
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import selftest  # noqa: E402

sys.path.insert(0, str(selftest.REPO))
import activity  # noqa: E402

FAILED = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))


SRC = (selftest.REPO / "ui.html").read_text(encoding="utf-8")

# ── 1. 从 ui.html 里抽出真的那一个函数（不另抄一份）──────────────────
START = "function heatGridHtml(kind) {"
END = "\nfunction heatHeadHtml("
try:
    i0 = SRC.index(START)
    i1 = SRC.index(END, i0)
    FN = SRC[i0:i1]
except ValueError:
    FN = ""

chk("源码：ui.html 里找得到 heatGridHtml（抽不到函数这条门禁就是空转）", bool(FN), FN[:80])
chk("源码：有记录的那天抬一档（用 c[1] > 0 判有没有记录）", "c[1] > 0" in FN)
chk("源码：档位封顶在 lv4（Math.min(4, c[2] + 1)）", "Math.min(4, c[2] + 1)" in FN)
chk("源码：老那行 `c[2] ? ' lv' + c[2] : ''` 已经不在函数里了",
    "c[2] ? ' lv' + c[2] : ''" not in FN)

# 图例与样式表说的也是这五格：底色 + lv1..lv4。少一格，网格上涂得出来也没人认得。
chk("界面：图例铺的是「没有记录 + lv1..lv4」五格",
    'heatlegend">少<i class="heatcell"></i>' in SRC
    and '<i class="heatcell lv1"></i>' in SRC and '<i class="heatcell lv4"></i>' in SRC)
for _lv in (1, 2, 3, 4):
    chk("样式：.heatcell.lv%d 有定义" % _lv, (".heatcell.lv%d{" % _lv) in SRC)

# ── 2. 用 activity.summary() 现算一份真 cells ──────────────────────
TODAY = "2026-03-05"
PEAK = 8000                       # 峰值 → cuts = [2000, 4000, 6000]
DAYS = {
    "2026-03-02": 600,            # 最低档（0 < 秒 ≤ 2000）：旧写法就是「什么都没有」
    "2026-03-03": 3000,           # 档 1
    "2026-03-04": 5000,           # 档 2
    "2026-03-05": PEAK,           # 档 3（峰值）
}
book = activity.load({})
book["study"]["days"] = dict(DAYS)
book["study"]["total"] = sum(DAYS.values())
summ = activity.summary(book, today=TODAY)
cells = summ["study"]["cells"]

chk("数据：色阶按峰值分四档（3 个边界）", summ["study"]["levels"] == [2000, 4000, 6000],
    summ["study"]["levels"])
chk("数据：level_of 给的档位就是 0..3",
    set(c[2] for c in cells) <= {0, 1, 2, 3}, sorted(set(c[2] for c in cells)))
chk("数据：600 秒那天落在最低档（0），和没记录撞在一起的是它",
    dict((c[0], c[2]) for c in cells)["2026-03-02"] == 0)

# ── 3. 把真函数交给 node 跑，拿回它画的 HTML ───────────────────────
NODE_SRC = (
    "const GZACT = " + json.dumps({"study": {"cells": cells}}, ensure_ascii=False) + ";\n"
    "const HEAT_COL = 14;\n"
    + FN + "\n"
    "process.stdout.write(heatGridHtml('study'));\n"
)
with tempfile.TemporaryDirectory(prefix="guizang-heat-") as tmp:
    js = pathlib.Path(tmp) / "heat.js"
    js.write_text(NODE_SRC, encoding="utf-8")
    proc = subprocess.run(["node", str(js)], capture_output=True, text=True)

chk("node：heatGridHtml 跑得起来（能起、不回退）",
    proc.returncode == 0 and "<div class=\"heatgrid\">" in proc.stdout,
    (proc.stderr or proc.stdout)[-300:])

CELL_RE = re.compile(r'<i class="([^"]*)" data-d="([^"]+)" data-s="(\d+)"')
painted = {}
for cls, date, sec in CELL_RE.findall(proc.stdout):
    painted[date] = (cls, int(sec))

chk("网格：371 格一格不少（跳一格整张图就错位）", len(painted) == len(cells) == 371,
    (len(painted), len(cells)))


def shade(cls):
    """从 class 串里摘出 lvN（没有就是 0 = 只留底色）。"""
    m = re.search(r"\blv(\d)\b", cls or "")
    return int(m.group(1)) if m else 0


# 最强的一条：有记录 ⟺ 带色阶。灰的那天必须真的没有记录。
mismatch = [(c[0], c[1], c[2], painted.get(c[0])) for c in cells
            if (shade(painted.get(c[0], ("", 0))[0]) > 0) != (c[1] > 0)]
chk("口径：有记录的那天必定带色阶、0 秒的那天必定只留底色（两边一一对上）",
    not mismatch, mismatch[:3])

chk("涂色：600 秒（最低档）不是空白，涂成 lv1",
    shade(painted["2026-03-02"][0]) == 1, painted.get("2026-03-02"))
chk("涂色：档 1 / 2 / 3 依次抬成 lv2 / lv3 / lv4",
    [shade(painted[d][0]) for d in ("2026-03-03", "2026-03-04", "2026-03-05")] == [2, 3, 4],
    [painted.get(d) for d in ("2026-03-03", "2026-03-04", "2026-03-05")])
chk("涂色：没提到的那天（没有记录）确实不带 lv 类",
    shade(painted["2026-03-01"][0]) == 0 and painted["2026-03-01"][1] == 0,
    painted.get("2026-03-01"))
chk("涂色：图例那五格现在都能涂出来（底色 + lv1..lv4 全出现）",
    {shade(v[0]) for v in painted.values()} == {0, 1, 2, 3, 4},
    sorted({shade(v[0]) for v in painted.values()}))
chk("涂色：封顶在 lv4，不会冒出 lv5 这种没人认得的类",
    all(shade(v[0]) <= 4 for v in painted.values()))


# ── 4. 对照：旧写法确实错（这条门禁不是空转）──────────────────────
def old_shade(c):
    """老那行：`c[2] ? 'lv' + c[2] : ''`。"""
    return c[2] if c[2] else 0


old_by_day = dict((c[0], old_shade(c)) for c in cells)
chk("对照：旧写法把「有记录的最低档」和「没有记录」涂成一个样（600 秒那天 no lv）",
    old_by_day["2026-03-02"] == 0 and old_by_day["2026-03-01"] == 0)
chk("对照：旧写法下最深那一档 lv4 永远涂不到（峰值那天只到 lv3）",
    old_by_day["2026-03-05"] == 3 and 4 not in set(old_by_day.values()),
    sorted(set(old_by_day.values())))

print("\n热力图色阶门禁：%d 项通过，失败 %d 项" % (PASSED, len(FAILED)))
for f in FAILED:
    print("  ✗ " + f)
sys.exit(1 if FAILED else 0)
