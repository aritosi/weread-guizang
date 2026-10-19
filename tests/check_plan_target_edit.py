# -*- coding: utf-8 -*-
"""阅读计划「调整目标」门禁：改了节奏，终点日必须跟着新节奏重推。

为什么单开这一条：`put_plan` 的终点日旧写法是「调用方给了日期就照用，否则一律沿用
`base["target"]`」。而界面的「调整目标」只发 `period` + `pages`、从不发 `target`
（`ui.html` 的 `plSave` 那一段），于是把每天 20 页改成 100 页之后：

  · 读数里的 `target` 还是建计划那天的（15 天后），不是新节奏的 3 天后；
  · `_fill_pace` 的 `days_left` / `need_pace` / `on_pace` 全拿旧终点日算，
    界面上「预计读完 … 截止」「想按目标收尾，往后每天要读到约 N 页」跟着一起错。

这一条只钉纯逻辑（`readplan.put_plan` / `view`），不起服务、不开浏览器，归静态段：

  1. 改了每天 / 每周的页数 → 终点日按新节奏重推（快、慢、切周期三种都走一遍）；
  2. 节奏**没变**的重存 → 终点日不动（书补了新章、总页数变大也不挪）；
  3. 调用方明确给的终点日永远优先；改节奏而没重申终点日时按新节奏重推；
  4. 改节奏不清已读高水位与每日账（与 check_plan.py 那条「改目标不清零」同一承诺）；
  5. 对照：把旧写法（一律沿用 base target）演一遍，证明它真会在第 1 条上判错。
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import readplan as rp  # noqa: E402

FAIL = []
PASSED = [0]


def chk(name, cond, extra=""):
    if cond:
        PASSED[0] += 1
    else:
        FAIL.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:240]))


DAY = "2026-03-05"
NOW = int(rp.datetime.strptime(DAY + " 12:00", "%Y-%m-%d %H:%M").timestamp())


def day(n):
    return (rp.datetime.strptime(DAY, "%Y-%m-%d") + rp.timedelta(days=n)).strftime("%Y-%m-%d")


# ── A 改了节奏，终点日跟着新节奏走 ─────────────────────────────
store = rp.blank()
p = rp.put_plan(store, "B", "书", 300, "daily", 20, now=NOW)
chk("建计划：每天 20 页读 300 页 → 15 天后", p["target"] == day(15), p["target"])

p = rp.put_plan(store, "B", "书", 300, "daily", 100, now=NOW)
chk("改快（20→100/天）：终点日重推成 3 天后",
    p["target"] == day(3), p["target"])

p = rp.put_plan(store, "B", "书", 300, "weekly", 100, now=NOW)
chk("换周期（100/天→100/周）：终点日重推成 3 周后",
    p["target"] == day(21), p["target"])

p = rp.put_plan(store, "B", "书", 300, "weekly", 25, now=NOW)
chk("改慢（100/周→25/周）：终点日重推成 12 周后",
    p["target"] == day(84), p["target"])

v = rp.view(store, "B", total=300, now=NOW, today=DAY)
chk("读数里的终点日与新节奏一致", v.get("target") == day(84), v.get("target"))

# ── B 节奏没变的重存，终点日不动 ───────────────────────────────
before = rp.get(store, "B")["target"]
p = rp.put_plan(store, "B", "书", 300, "weekly", 25, now=NOW)
chk("同节奏重存：终点日不动", p["target"] == before, (before, p["target"]))
p = rp.put_plan(store, "B", "书", 400, "weekly", 25, now=NOW)
chk("同节奏重存 + 总页数变大：终点日仍不动（不无端后移）",
    p["target"] == before, (before, p["target"]))

# ── C 明确给的终点日优先 ───────────────────────────────────────
p = rp.put_plan(store, "C", "书", 300, "daily", 20, now=NOW, target="2026-04-01")
chk("明确给终点日：照用", p["target"] == "2026-04-01", p["target"])
p = rp.put_plan(store, "C", "书", 300, "daily", 50, now=NOW, target="2026-04-01")
chk("改节奏 + 再明确给终点日：仍照用", p["target"] == "2026-04-01", p["target"])
p = rp.put_plan(store, "C", "书", 300, "daily", 100, now=NOW)
chk("改节奏但没重申终点日：按新节奏重推",
    p["target"] == day(3), p["target"])

# ── D 改节奏不清已读高水位与每日账 ─────────────────────────────
ch = [{"chars": 1000}] * 5
store2 = rp.blank()
rp.put_plan(store2, "D", "书", 5, "daily", 1, now=NOW)
rp.record_pos(store2, "D", ch, 1, 0, now=NOW)
rp.put_plan(store2, "D", "书", 5, "daily", 3, now=NOW)
q = rp.get(store2, "D")
chk("改节奏后高水位还在（1 页）", q["high"] == 1, q["high"])
chk("改节奏后今日的账还在（1 页）", q["days"].get(DAY) == 1, q["days"])
chk("改节奏后终点日按新节奏（5 页 / 每天 3 页 = 2 天后）",
    q["target"] == day(2), q["target"])

# ── E 对照：旧写法在这一格上是错的 ─────────────────────────────
old_store = rp.blank()
rp.put_plan(old_store, "E", "书", 300, "daily", 20, now=NOW)
base = old_store["plans"]["E"]
old_target = base["target"]  # 旧写法：base["target"]，不看新节奏
chk("对照：旧写法在「20/天 → 100/天」后仍是 15 天后的旧日期",
    old_target == day(15), old_target)
chk("对照：旧日期与新节奏该给的日期不同（门禁能抓住这一格）",
    old_target != day(3), (old_target, day(3)))

print("\n阅读计划调整目标门禁：%d 项通过，失败 %d 项" % (PASSED[0], len(FAIL)))
for n in FAIL:
    print("  ✗ " + n)
sys.exit(1 if FAIL else 0)
