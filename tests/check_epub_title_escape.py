#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""EPUB 目录 / 章节标题栏里的 `&` `<` `>` 不许被转义两次。

为什么单开一份
    `book_export._first_heading` 从 `md_to_html` 的产物里抠 h1：那时文本已经转义过
    一遍（`Tom & Jerry` 在 h1 里是 `Tom &amp; Jerry`），而 nav 与每一节的 `<title>`
    落笔时还会再 `_esc()` 一次。抠出来不还原实体，成品里就是 `&amp;amp;` —— 阅读器
    按 XML 解出来是字面量 `Tom &amp; Jerry`，目录与章节标题栏上就多出一个 `amp;`，
    而同一章的正文 `<h1>` 是好的。`Book.md_to_html` 这条路上早就对，只有标题这一格漏了。

钉住四件事（都在临时目录里真打一个 EPUB，不联网、不起浏览器）：
  A 目录与章节 `<title>`：`&` `<` `>` 各自只转义一次，成品里搜不到 `&amp;amp;` /
    `&amp;lt;` / `&amp;gt;`，且用 ElementTree 解出来的文本逐字等于原始标题（端到端，
    不是只比字符串）
  B `_first_heading` 的口径：回纯文本、剥掉行内标签、没有 h1 时回兜底那句
  C 正文不受影响：同一章正文 `<h1>` 仍是正确的一份，没有被这处改动带着少转或多转
  D 对照：把旧的 `_first_heading`（不还原实体）原样跑一遍，它确实产出 `&amp;amp;` ——
    这条门禁量的不是空气
"""
import html
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import book_export          # noqa: E402

FAIL = []
TMP = tempfile.mkdtemp(prefix="gz-epub-title-")


def chk(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:220]))
    if not cond:
        FAIL.append(name)


def make_book(root, chapters, title="测试书", author="某人", meta=None):
    """造一本最小的书：chapters/NNNN.md 按给定正文写，返回书目录。"""
    d = os.path.join(root, "bk")
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    for i, md in enumerate(chapters):
        with open(os.path.join(d, "chapters", "%04d.md" % i), "w", encoding="utf-8") as f:
            f.write(md)
    if meta is not None:
        import json
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    return d


def build(d, root, title="测试书", author="某人"):
    dest = os.path.join(root, "out.epub")
    if os.path.exists(dest):
        os.remove(dest)
    book_export.build_epub(d, dest, title=title, author=author)
    with zipfile.ZipFile(dest) as z:
        return dest, {n: z.read(n).decode("utf-8")
                      for n in z.namelist() if n.endswith((".opf", ".xhtml"))}


def nav_links(nav_text):
    """nav.xhtml 里每个 <a> 的 href → 显示文本（按 XML 真解一遍，不是抓字符串）。"""
    root = ET.fromstring(nav_text)
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "a":
            out.append((el.get("href") or "", "".join(el.itertext())))
    return out


def title_of(xhtml):
    root = ET.fromstring(xhtml)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "title":
            return "".join(el.itertext())
    return None


def h1_of(xhtml):
    root = ET.fromstring(xhtml)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "h1":
            return "".join(el.itertext())
    return None


# 旧写法：h1 抠出来只剥标签，不还原实体（本处改动前的那一行）。
def old_first_heading(body, fallback):
    m = re.search(r"<h1>(.*?)</h1>", body)
    if m:
        t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if t:
            return t
    return fallback


try:
    # ── A. 真打一个 EPUB，目录与章节标题只转义一次 ─────────────────────
    cases = [
        ("A1 & 不再写成 &amp;amp;", "# Tom & Jerry\n\n正文一句。\n", "Tom & Jerry"),
        ("A2 < 与 > 不再写成 &amp;lt; / &amp;gt;",
         "# A < B > C\n\n正文。\n", "A < B > C"),
        ("A3 引号与撇号原样保留", '# He said "hi" & it\'s ok\n\n正文。\n',
         'He said "hi" & it\'s ok'),
        ("A4 行内标签剥掉之后才是标题文本", "# **粗** 与 *斜* & 尾\n\n正文。\n",
         "粗 与 斜 & 尾"),
    ]
    for label, md, want in cases:
        root = tempfile.mkdtemp(dir=TMP)
        d = make_book(root, [md])
        _dest, files = build(d, root)
        nav = files["OEBPS/nav.xhtml"]
        sec = files["OEBPS/sec0000.xhtml"]
        chk(label + "（目录文本逐字等于标题）",
            nav_links(nav) == [("sec0000.xhtml", want)], nav_links(nav))
        chk(label + "（章节 <title> 逐字等于标题）",
            title_of(sec) == want, title_of(sec))
        # 成品里不许出现「转义了两次」的那几种形状
        bad = [s for s in ("&amp;amp;", "&amp;lt;", "&amp;gt;") if s in nav or s in sec]
        chk(label + "（成品里搜不到二次转义的形状）", not bad, bad)

    # ── B. _first_heading 的口径 ──────────────────────────────────────
    chk("B1 回纯文本（& 还原成一个字符）",
        book_export._first_heading(book_export.md_to_html("# Tom & Jerry\n"), "x")
        == "Tom & Jerry")
    chk("B2 < > 也还原", book_export._first_heading(book_export.md_to_html("# A < B > C\n"), "x")
        == "A < B > C")
    chk("B3 行内标签剥掉、只留文本",
        book_export._first_heading(book_export.md_to_html("# **粗** 尾\n"), "x") == "粗 尾")
    chk("B4 没有 h1 时回兜底那句",
        book_export._first_heading(book_export.md_to_html("只有正文，没有标题。\n"), "第 3 章")
        == "第 3 章")
    chk("B5 空 h1 也回兜底", book_export._first_heading("<h1>   </h1>", "第 4 章") == "第 4 章")

    # ── C. 正文那一份没被带着改坏 ─────────────────────────────────────
    root = tempfile.mkdtemp(dir=TMP)
    d = make_book(root, ["# Tom & Jerry\n\na & b\n"])
    _dest, files = build(d, root)
    chk("C1 正文 <h1> 仍是正确的一份（解出来是 Tom & Jerry）",
        h1_of(files["OEBPS/sec0000.xhtml"]) == "Tom & Jerry",
        h1_of(files["OEBPS/sec0000.xhtml"]))
    chk("C2 正文里出现 `&` 的段落照旧只转义一次",
        "<p>a &amp; b</p>" in files["OEBPS/sec0000.xhtml"],
        [l for l in files["OEBPS/sec0000.xhtml"].splitlines() if "a &" in l][:1])
    # 元数据里的 & 也不能被顺手改成别的：opf 解出来正是书名
    root = tempfile.mkdtemp(dir=TMP)
    d = make_book(root, ["# 第一章\n\n正文。\n"])
    _dest, files = build(d, root, title="A & B")
    opf = files["OEBPS/content.opf"]
    meta_titles = ["".join(el.itertext()) for el in ET.fromstring(opf).iter()
                   if el.tag.rsplit("}", 1)[-1] == "title"]
    chk("C3 书名里的 & 照旧一份（没被这处改动牵连）", "A & B" in meta_titles, meta_titles)

    # ── D. 对照：旧写法确实产出二次转义 ───────────────────────────────
    old = old_first_heading(book_export.md_to_html("# Tom & Jerry\n"), "x")
    chk("D1 对照：旧写法抠出来的是 `Tom &amp; Jerry`（再 _esc 一次就是 &amp;amp;）",
        old == "Tom &amp; Jerry", old)
    chk("D2 对照：旧的中间值过一遍 _esc() 就是成品里那串二次转义",
        book_export._esc(old) == "Tom &amp;amp; Jerry", book_export._esc(old))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
print("EPUB 标题转义门禁：" + ("全部通过" if not FAIL else "%d 项未过：%s" % (len(FAIL), FAIL)))
sys.exit(1 if FAIL else 0)
