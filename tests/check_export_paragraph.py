#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取书成品里的分段：以 `”` / `.` 收尾的段落不再与下一段粘成一段。

引擎（`export_precise.render_chapter_md`）把 canvas 抠出来的文字行拼回自然段，
判据只有一条：上一行的末字不在 `SENTENCE_END` 里就接续。那份名单原先收了
`」）】》` 这几个右半边括号，却漏了最常出现在段尾的 `”`（对白收尾）与英文书的
`. ! ?` —— 于是「他说：“今天不去了。”」和下一段被拼成一行，导出成品里读着像
作者写漏了换行。这条把三件事钉住：

  A 对照：老那份名单确实把两段粘起来（证明这一条不是空转）。
  B 修好之后：中文对白 `”` / 直角引号 `』` / 英文 `. ! ?` 收尾各自另起一段。
  C 不许过度拆：以 `，` / `、` 收尾的续行仍要接回同一段（换行是排版断的）。
  D 图片仍按位置断开段落，图序号照旧。
  E 与章节标题同名的那一行照旧不进正文。

纯函数，不联网、不起浏览器、不需要 chromium。
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

FAIL = []
PASSED = [0]
NOTES = []


def chk(name, cond, extra=""):
    if cond:
        PASSED[0] += 1
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:300]))
    if not cond:
        FAIL.append(name)


def load_engine():
    """import export_precise；没装 playwright 时用占位模块顶住那一个 import。"""
    try:
        import export_precise as E          # noqa: E402
        return E, "real"
    except Exception as first:
        if "playwright" not in str(first):
            print("import export_precise 失败（不是 playwright 的事）：%r" % (first,))
            return None, "broken"
        pw = types.ModuleType("playwright")
        aa = types.ModuleType("playwright.async_api")
        aa.async_playwright = lambda *a, **k: None
        pw.async_api = aa
        sys.modules.setdefault("playwright", pw)
        sys.modules.setdefault("playwright.async_api", aa)
        try:
            import export_precise as E      # noqa: E402
        except Exception as e:
            print("占位 playwright 之后仍起不来：%r" % (e,))
            return None, "broken"
        return E, "stub"


E, HOW = load_engine()
if HOW == "stub":
    NOTES.append("没装 playwright，纯函数部分用占位模块顶住 import（真装了会用真的）")
elif HOW == "broken":
    print("\n取书成品分段：引擎起不来，这一条不算通过")
    sys.exit(1)

# 修之前的那份收尾名单（与 SENTENCE_END 的差别就是漏掉的那几个字），
# 只用来做「老写法确实会粘」的对照，不参与产品代码。
OLD_END = set("。！？；：」）】》…—")


def old_merge(lines):
    """老判据：末字不在老名单里就接续。"""
    merged = []
    for line in lines:
        if merged and merged[-1] and merged[-1][-1] not in OLD_END:
            merged[-1] += line
        else:
            merged.append(line)
    return merged


def paragraphs(md):
    """成品正文里「一段一行」的部分（去掉章节标题那一行与空段）。"""
    return [p.strip() for p in md.split("\n\n")
            if p.strip() and not p.strip().startswith("#")]


def render(blocks, title="第一章"):
    md, _imgs = E.render_chapter_md(title, blocks, 1)
    return md


def texts(lines):
    return [{"type": "text", "text": t} for t in lines]


# ── A. 对照：老名单确实把对白段与下一段粘起来 ──────────────────────
quote_lines = ["他说：“今天不去了。”", "第二天，天气很好。"]
glued = old_merge(quote_lines)
chk("A1 对照：老名单把 `”` 收尾的对白段与下一段粘成一行",
    glued == ["他说：“今天不去了。”第二天，天气很好。"], glued)
eng_lines = ["Hello world.", "Next sentence here."]
chk("A2 对照：老名单把英文 `.` 收尾的两段粘成一行",
    old_merge(eng_lines) == ["Hello world.Next sentence here."], old_merge(eng_lines))

# ── B. 修好之后：这些收尾各自另起一段 ─────────────────────────────
got = paragraphs(render(texts(quote_lines)))
chk("B1 中文对白以 `”` 收尾：另起一段", got == quote_lines, got)

got = paragraphs(render(texts(["他回过头说：『好。』", "门轻轻关上了。"])))
chk("B2 以 `』` 收尾：另起一段", got == ["他回过头说：『好。』", "门轻轻关上了。"], got)

got = paragraphs(render(texts(eng_lines)))
chk("B3 英文以 `.` 收尾：另起一段", got == eng_lines, got)

got = paragraphs(render(texts(["Are you sure?", "Yes, I am."])))
chk("B4 英文以 `?` 收尾：另起一段", got == ["Are you sure?", "Yes, I am."], got)

got = paragraphs(render(texts(["别动！", "我偏要动。"])))
chk("B5 以 `！` 收尾：另起一段（原有行为不回归）", got == ["别动！", "我偏要动。"], got)

got = paragraphs(render(texts(["他说：“走吧”", "门开了。"])))
chk("B6 行尾没有句号的 `”` 也算说完", got == ["他说：“走吧”", "门开了。"], got)

# ── C. 不许过度拆：排版断开的续行仍要接回同一段 ───────────────────
got = paragraphs(render(texts(["他把书放在桌上，", "然后转身走了。"])))
chk("C1 以 `，` 收尾的续行接回同一段", got == ["他把书放在桌上，然后转身走了。"], got)

got = paragraphs(render(texts(["书、笔、", "本子都摆好了。"])))
chk("C2 以 `、` 收尾的续行接回同一段", got == ["书、笔、本子都摆好了。"], got)

# ── D. 图片仍按位置断开段落，图序号照旧 ───────────────────────────
blocks = [{"type": "text", "text": "第一段。"},
          {"type": "img", "src": "https://example.com/a.png", "w": 10, "h": 10},
          {"type": "text", "text": "第二段。"},
          {"type": "img", "src": "https://example.com/b.png", "w": 10, "h": 10},
          {"type": "text", "text": "第三段。"}]
md, imgs = E.render_chapter_md("第一章", blocks, 3)
chk("D1 图片前后各自成段", paragraphs(md) == [
    "第一段。", "![图](images/ch0003_img01.png)", "第二段。",
    "![图](images/ch0003_img02.png)", "第三段。"], paragraphs(md))
chk("D2 图序号按章节内顺序、扩展名跟着地址",
    [im["file"] for im in imgs] == ["ch0003_img01.png", "ch0003_img02.png"], imgs)

# ── E. 章节标题那一行不会混进正文（原有行为） ─────────────────────
got = paragraphs(render(texts(["第一章", "正文。"]), title="第一章"))
chk("E1 与章节标题同名的那一行被丢掉", got == ["正文。"], got)

for n in NOTES:
    print("NOTE  " + n)
print()
print("取书成品分段：通过 %d 项，失败 %d 项" % (PASSED[0], len(FAIL)))
if FAIL:
    print("未过：" + "、".join(FAIL))
sys.exit(1 if FAIL else 0)
