#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁：热力图的色阶峰值必须取自**界面上真铺出来的那张图**（activity.py）。

守的是什么
    `levels()` 的三档边界按 `peak()` 算，而 `peak()` 说的是「近一年最忙的那天」。
    「一年」在两处各写了一遍：

      · `calendar()` 铺 53 周 = 371 格，最早一格是 today-370；
      · 旧的 `peak()` 从 `today - YEAR_WEEKS * 7`（today-371）往前数。

    多出来的那一天在图上是**没有格子**的（`prune` 保留 400 天，所以它真躺在账本里）。
    峰值正好落在它身上时，色阶会照一个用户看不见的读数去分档 —— `summary` 里
    `max`（可见格子的最大值）与 `levels` 对不上，整张看得见的图全挤在最低档。
    现在 `peak()` 直接取 `calendar()` 的格子，两个数永远是同一句话；顺带把「比今天
    还晚」的脏日期也挡在外面（旧写法只卡下界）。

怎么验
    纯函数、不碰盘、不碰 HTTP、不起服务：把账本造在边界上（today-371 / today-370 /
    今天 / 未来一天），逐条钉住「算进来的」与「不算进来的」。带一条「旧写法确实会
    读到窗口外那天」的对照，证明这条门禁不是空转。
"""
import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


TODAY = "2026-03-05"
D0 = _dt.date.fromisoformat(TODAY)
SPAN = activity.YEAR_WEEKS * 7                    # 371
FIRST_VISIBLE = (D0 - _dt.timedelta(days=SPAN - 1)).isoformat()   # 2025-02-28
OUT_OF_GRID = (D0 - _dt.timedelta(days=SPAN)).isoformat()         # 2025-02-27（第 372 天）
FUTURE = (D0 + _dt.timedelta(days=3)).isoformat()


def book(days):
    """一份 activity.load 洗过的账本（真实读路径给的就是这个形状）。"""
    d = activity.load({})
    d["study"]["days"] = dict(days)
    d["study"]["total"] = sum(days.values())
    return d


def old_peak(days):
    """旧写法的那把尺子（只卡下界、按 YEAR_WEEKS*7 天往前数），只用来当对照。"""
    hi = 0
    for key, sec in days.items():
        if _dt.date.fromisoformat(key) >= D0 - _dt.timedelta(days=SPAN):
            hi = max(hi, int(sec))
    return hi


# ── 1. 两把尺子的窗口：calendar 铺多少格、最早一格是哪天 ─────────────
cells = activity.calendar(activity.load({}), "study", today=TODAY)
chk("日历：53 周就是 371 格", len(cells) == SPAN, len(cells))
chk("日历：最早一格是 today-370（不是 today-371）",
    cells[0][0] == FIRST_VISIBLE and cells[0][0] != OUT_OF_GRID, (cells[0][0], FIRST_VISIBLE))

# ── 2. 窗口外那天：不许进峰值 ──────────────────────────────────────
dA = book({OUT_OF_GRID: 100000, (D0 - _dt.timedelta(days=10)).isoformat(): 8000})
chk("峰值：窗口外那天（today-371）不算数", activity.peak(dA, "study", today=TODAY) == 8000,
    activity.peak(dA, "study", today=TODAY))
chk("色阶：按可见的 8000 分档，不按看不见的 100000",
    activity.levels(dA, "study", today=TODAY) == [2000, 4000, 6000],
    activity.levels(dA, "study", today=TODAY))

# ── 3. 窗口第一天（today-370）：必须算进来 ────────────────────────
dB = book({OUT_OF_GRID: 100000, FIRST_VISIBLE: 12000,
           (D0 - _dt.timedelta(days=10)).isoformat(): 8000})
chk("峰值：最老的可见格（today-370）里的读数算数",
    activity.peak(dB, "study", today=TODAY) == 12000,
    activity.peak(dB, "study", today=TODAY))

# ── 4. 未来那天（时钟被改过 / 手改账本）：不许进峰值 ───────────────
dC = book({FUTURE: 999999, (D0 - _dt.timedelta(days=10)).isoformat(): 8000})
chk("峰值：比今天还晚的脏日期不算数（旧写法只卡下界）",
    activity.peak(dC, "study", today=TODAY) == 8000,
    activity.peak(dC, "study", today=TODAY))

# ── 5. summary 里那两个数必须是同一句话 ───────────────────────────
sA = activity.summary(dA, today=TODAY)["study"]
chk("summary：max 就是 peak（可见格子的最大值与色阶同源）",
    sA["max"] == activity.peak(dA, "study", today=TODAY) == 8000, sA["max"])
chk("summary：可见的 8000 秒落在最深一档（旧色阶里它是 0 档）",
    activity.level_of(8000, sA["levels"]) == 3 and activity.level_of(8000, [25000, 50000, 75000]) == 0,
    sA["levels"])

# ── 6. 对照：旧那把尺子确实会读到窗口外那天，这条门禁不是空转 ──────
chk("对照：旧写法把 today-371 的 100000 当成峰值（所以上一条才要钉）",
    old_peak(dA["study"]["days"]) == 100000, old_peak(dA["study"]["days"]))
chk("对照：旧峰值算出来的三档与新写法不是同一套",
    activity.levels(dA, "study", today=TODAY) !=
    [max(1, 100000 // 4), 50000, max(1, 100000 * 3 // 4)])

print()
print("热力图峰值窗口门禁：%d 项通过，失败 %d 项" % (PASSED, len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  ✗ " + f)
    sys.exit(1)
