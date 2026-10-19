#!/usr/bin/env python3
"""划线笔记那一墙的封面：与书架卡共用同一把尺子（no-referrer + 不收 Referer 的后端代取）。

进「划线笔记」时微信那几本书的封面一直不亮（首字底纹），而同样的书在书架里封面是好的。

根因是这一墙自己拼封面，没走 `extCoverImg()`，于是漏掉了书架那一路的两条收口：

  · `nbCard()` 建的 `<img>` 没设 `referrerPolicy = 'no-referrer'`。微信 / QQ 图床
    对外站来路回 403，而界面是从 `http://127.0.0.1:8770` 打开的，直连那一跳必然带着
    这个 Referer —— 注定失败。全仓另外四处（书架卡 / 详情页大图 / 推荐与搜书卡 /
    阅读器正文图）都收了这道口，只有这一处漏了（见 check_covers.py / check_cover_lazy.py
    里那几条 referrer 断言）。
  · 退路里没有 `/api/cover?url=`。那条由后端带着微信自己的 Referer 去取、落盘缓存，
    **不需要用户配 Key**；这一墙原先只有「官方图 → `/api/cover?book=`（要 Key）」，
    直连失败后只能去问官方接口（多一趟 `/book/info`），本地那一路更是根本没得退。

修法与书架那一路保持同一个顺序：直连（带 no-referrer）→ 后端代取（不要 Key）→
要 Key 的官方接口。协议相对地址也要过 `coverSrc()` 归一，否则浏览器拿本地服务当参照。

这一套不依赖浏览器：只读 `ui.html` 源码静态钉住接线（与 check_cover_lazy.py 同一路子）。
真机上的量法（真浏览器、真图床）留给人手：进这一屏，微信书的封面应当一次就亮，
前端不再先发一条注定 403 的直连请求。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "ui.html").read_text(encoding="utf-8")

checks = []


def chk(name, ok, extra=""):
    checks.append((bool(ok), name, "" if ok else str(extra)[:300]))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else "  <- " + str(extra)[:300]))


def fn_body(name):
    """截出 `function <name>(...) { ... }` 的函数体（到行首的右花括号为止）。"""
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{(.*?)\n\}" % re.escape(name), SRC, re.S)
    return m.group(1) if m else ""


def nbcard_findings(body):
    """把这一墙的封面接线拆成几个可判定的点，给下面「真接线」与「旧写法对照」共用。"""
    ref = "img.referrerPolicy = 'no-referrer'" in body
    normalized = "coverSrc(info.cover)" in body
    proxy = "/api/cover?url=" in body
    # 参照物：`?url=` 必须排在要 Key 的 `?book=` 之前（先走不花 Key 的那条）
    url_at = body.find("/api/cover?url=")
    book_at = body.find("/api/cover?book=")
    ordered = url_at >= 0 and (book_at < 0 or url_at < book_at)
    # referrerPolicy 必须在赋 src 之前设上：设晚了那一跳已经带着 Referer 发出去了
    ref_before_src = ref and body.find("img.referrerPolicy") < body.find("img.src =")
    return {"ref": ref, "normalized": normalized, "proxy": proxy,
            "ordered": ordered, "ref_before_src": ref_before_src}


# ── 对照先立住：旧写法确实会被这几条判红（否则是一组永远为真的断言）────
OLD = """  const alts = [];
  if (info.cover) alts.push(info.cover);
  if (keySet && b.bookId) alts.push('/api/cover?book=' + encodeURIComponent(b.bookId));
  const img = document.createElement('img');
  img.alt = '';
  img.loading = 'lazy';
  img.src = alts[i++];
"""
old_f = nbcard_findings(OLD)
chk("对照：旧写法（裸 info.cover + 没有 no-referrer + 没有 ?url=）四项都判红",
    not old_f["ref"] and not old_f["normalized"] and not old_f["proxy"]
    and not old_f["ref_before_src"], old_f)

# ── 真接线 ──────────────────────────────────────────────────────
card = fn_body("nbCard")
chk("nbCard 还认得出来（函数体截取没退化成空）",
    bool(card) and "const card = document.createElement('div')" in card, card[:200])
f = nbcard_findings(card)
chk("划线笔记卡的封面带 no-referrer（图床拒外站来路，与书架卡同一把尺子）", f["ref"], card[:300])
chk("no-referrer 设在赋 src 之前（设晚了那一跳已经带着 Referer 发出去了）",
    f["ref_before_src"], card[:300])
chk("远端封面过 coverSrc 归一（协议相对地址不当成本地路径）", f["normalized"], card[:300])
chk("退路里有不收 Referer / 不要 Key 的后端代取 /api/cover?url=", f["proxy"], card[:300])
chk("顺序：代取 ?url= 排在要 Key 的 ?book= 之前（与 shelfCard 的 coverAlt / coverLocal 一致）",
    f["ordered"], card[:300])
chk("官方图直连失败后仍能退（onerror 沿 alts 往下走，全挂才露首字底纹）",
    "if (i < alts.length) img.src = alts[i++]" in card and "else ph()" in card, card[-300:])

# ── 两边共用一套尺子，别各写一份 ─────────────────────────────────
chk("书架那一路的同类收口没被顺手拆掉（coverAlt = ?url= 代取仍在）",
    "'/api/cover?url=' + encodeURIComponent(coverSrc(b.cover))" in SRC, SRC[-300:])
chk("coverSrc 这一处归一仍在（协议相对地址补 https 的唯一出口）",
    "function coverSrc(" in SRC and "u.startsWith('//')" in SRC, "coverSrc 被拿掉了")
chk("extCoverImg 的 no-referrer 也还在（书架 / 推荐 / 详情页那几处都靠它）",
    "im.referrerPolicy = 'no-referrer'" in fn_body("extCoverImg"), "extCoverImg 丢了 referrerPolicy")

bad = [c for c in checks if not c[0]]
print("\n划线笔记封面 Referer 与代取退路体检：%d 项通过，失败 %d 项" % (len(checks) - len(bad), len(bad)))
for _, n, x in bad:
    print("  ✗ " + n + ("  | " + x if x else ""))
sys.exit(1 if bad else 0)
