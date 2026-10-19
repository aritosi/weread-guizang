# -*- coding: utf-8 -*-
"""导入 / 剪藏正文里的围栏代码块：缩进、制表符、空行一个字符都不许动。

`_ToMarkdown` 对 `<pre>` 是明确「原样保留」的（`handle_data` 里 `self.pre` 那一支），
可收尾的 `text()` 又把整篇过了一遍 `[ \\t]{2,}` → 空格 —— 于是导一本带代码示例的
EPUB、剪藏一篇技术文章，代码里每一级缩进都被压成一个空格：Python 的 `def` 体、YAML
的层级、缩进式树形输出从此都是错的，而且不报任何错，用户只有翻到那一章才发现。

这里钉三件事：
  A 纯函数：`_md_from_xhtml` 围栏里的多级缩进 / 制表符 / 连续空行原样保留；
  B 正文照旧：围栏外的连续空格与连续空行仍收干净（这次改动不碰正文口径）；
  C 两条真路：EPUB 导入落盘的章节、剪藏抽取出来的 Markdown，缩进都在；
  D 对照：老那把「全文一把 `[ \\t]{2,}`」确实把缩进压没了 —— 证明这扇门不是空转。

全程内存 / 临时沙盒，不联网、不开浏览器、不碰真实书库。

跑法：.venv/bin/python tests/check_import_code_indent.py
"""
import atexit
import io
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SANDBOX = tempfile.mkdtemp(prefix="gz-codeindent-")
atexit.register(lambda: shutil.rmtree(SANDBOX, ignore_errors=True))
os.environ["GUIZANG_DATA"] = os.path.join(SANDBOX, "data")
os.environ["GUIZANG_BOOKS"] = os.path.join(SANDBOX, "books")

import book_import as B            # noqa: E402
import clip_article                # noqa: E402

PASSED = 0
FAIL = []


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
        print("  ok  " + name)
    else:
        FAIL.append(name)
        print("  ✗  " + name + "   " + repr(extra))


def code_of(md):
    """取围栏里那一段（不带围栏行）；没有围栏给空串。"""
    m = re.search(r"```[^\n]*\n(.*?)\n?```", md or "", re.S)
    return m.group(1) if m else ""


class _Legacy(B._ToMarkdown):
    """改之前那版收尾：整篇（含围栏）一起归一。只用来做对照，产品代码里已经没有它。"""

    def text(self):
        s = "".join(self.out)
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"[ \t]{2,}", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


def legacy_md(html):
    p = _Legacy()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.text()


CODE = "def f():\n    if x:\n        return 1\n    return 0"

# ── A. 纯函数：围栏里的缩进 / 制表符 / 空行原样 ─────────────────────
a_md = B._md_from_xhtml("<pre>%s</pre>" % CODE)
chk("A1 `<pre>` 里的四级缩进原样落进围栏", code_of(a_md) == CODE, code_of(a_md))
chk("A2 围栏里没有出现「被压成一个空格」的那一行",
    "        return 1" in a_md and not re.search(r"(?m)^ return 1$", a_md), a_md)

tab_md = B._md_from_xhtml("<pre>a\n\tb\n\t\tc</pre>")
chk("A3 制表符缩进也一个字不动", code_of(tab_md) == "a\n\tb\n\t\tc", code_of(tab_md))

blank_md = B._md_from_xhtml("<pre>x\n\n\n\ny</pre>")
chk("A4 围栏里的连续空行是内容，不跟着正文一起收",
    code_of(blank_md) == "x\n\n\n\ny", code_of(blank_md))

mix_md = B._md_from_xhtml("<p>说明文字</p><pre>%s</pre><p>后面    还有话</p>" % CODE)
chk("A5 围栏外的正文仍照旧归一，围栏内不动",
    code_of(mix_md) == CODE and "后面 还有话" in mix_md, mix_md)

# ── B. 正文口径一个字不改 ────────────────────────────────────────
chk("B1 正文里连续空格仍压成一个",
    "a     b" not in B._md_from_xhtml("<p>a     b</p>")
    and "a b" in B._md_from_xhtml("<p>a     b</p>"),
    B._md_from_xhtml("<p>a     b</p>"))
chk("B2 正文里连续空行仍最多留一行",
    B._md_from_xhtml("<p>a</p><p></p><p></p><p></p><p>b</p>") == "a\n\nb",
    B._md_from_xhtml("<p>a</p><p></p><p></p><p></p><p>b</p>"))


# ── C. 真路一：EPUB 导入落盘的章节 ──────────────────────────────
def build_epub(docs, title="代码示例"):
    buf = io.BytesIO()
    manifest, spine = [], []
    for i, (href, _html) in enumerate(docs):
        manifest.append('<item id="c%d" href="%s" media-type="application/xhtml+xml"/>'
                        % (i, href))
        spine.append('<itemref idref="c%d"/>' % i)
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>%s</dc:title><dc:creator>某人</dc:creator></metadata>'
           '<manifest>%s</manifest><spine>%s</spine></package>'
           % (title, "".join(manifest), "".join(spine)))
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        for href, html in docs:
            z.writestr("OEBPS/" + href, html)
    return buf.getvalue()


page = ('<html><body><h1>第一章 代码</h1><p>%s</p><pre>%s</pre></body></html>'
        % ("正文" * 40, CODE))
dest = os.path.join(SANDBOX, "books")
info = B.import_book(dest, "代码书.epub", build_epub([("ch1.xhtml", page)]))
ch_dir = os.path.join(info["dir"], "chapters")
saved = "".join(open(os.path.join(ch_dir, f), encoding="utf-8").read()
                for f in sorted(os.listdir(ch_dir)))
chk("C1 EPUB 导入：章节里就是那一段带缩进的代码",
    code_of(saved) == CODE, saved)
chk("C2 EPUB 导入：`def` 体里的八个空格还在",
    "        return 1" in saved, saved)


# ── C. 真路二：剪藏抽取出来的 Markdown ──────────────────────────
PAGE = ('<html><head><title>技术文 - 某号</title>'
        '<meta property="og:title" content="技术文"></head><body>'
        '<article><h1>标题</h1><p>%s</p><pre>%s</pre><p>结尾</p></article></body></html>'
        % ("正文" * 120, CODE))
clip_article._PREVIEW_CACHE.clear()
_old_fetch = clip_article.fetch
clip_article.fetch = lambda url: (PAGE, "https://blog.example.com/post/9")
try:
    art = clip_article._extract_once("https://blog.example.com/post/9")
finally:
    clip_article.fetch = _old_fetch
chk("C3 剪藏：抽取出来的 Markdown 里代码缩进还在",
    code_of(art["markdown"]) == CODE, code_of(art["markdown"]))

# ── D. 对照：老写法确实把缩进压成一个空格 ───────────────────────
legacy = legacy_md("<pre>%s</pre>" % CODE)
chk("D1 对照：老写法把四级缩进压成一个空格",
    code_of(legacy) == "def f():\n if x:\n return 1\n return 0", code_of(legacy))
chk("D2 对照与现在这版在同一个输入上结果不同（这一刀不是空转）",
    legacy != a_md and code_of(legacy) != code_of(a_md))

print()
print("导入 / 剪藏代码块缩进体检：%d 项通过，失败 %d 项" % (PASSED, len(FAIL)))
for n in FAIL:
    print("  ✗ " + n)
sys.exit(1 if FAIL else 0)
