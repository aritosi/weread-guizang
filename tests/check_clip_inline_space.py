# -*- coding: utf-8 -*-
"""剪藏正文里「行内元素之间那一下空白」不许被吃掉。

HTML 里 `<span>beta</span> <span>gamma</span>` 中间那个纯空白文本节点是有意义的
一格 —— 浏览器就渲染成一个空格。`clip_article._TreeBuilder.handle_data` 原先一句
`if not data.strip(): return` 把它整块丢掉，于是：

  · 两个词粘成一个（`alpha betagamma delta`）；
  · 行内加粗 / 斜体连成一串（`**quick***brown*`，星号会当场显示出来）；
  · 标题里被 `<span>` 切开的词也粘住（`# HelloWorld`）。

受影响的不止剪藏：`web_parse`（知乎）与 `feed` 回源补全文都走同一条
`_serialized` → `book_import._md_from_xhtml` 的路。

这一套先钉住「行内该留的留、块级之间不该多出来的不留」，再拿旧写法做一面镜子
（证明不是空转），最后真跑一次 `_extract_once`。纯逻辑、不联网、不开浏览器，归 --fast。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = tempfile.mkdtemp(prefix="guizang-clipspace-")
os.environ["GUIZANG_DATA"] = os.path.join(ROOT, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(ROOT, "books")

import book_import                                                # noqa: E402
import clip_article                                               # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:300]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def md_of(html_text):
    """一段文章 HTML → 归藏最后落进书里的那篇 Markdown（与抓取同一条转换路）。"""
    tree = clip_article.parse_html(html_text)
    frag = clip_article._serialized(clip_article._pick_body(tree), "https://e.com/", [])
    return book_import._md_from_xhtml(frag)


class _OldBuilder(clip_article._TreeBuilder):
    """改这一行之前的那把尺子：纯空白文本节点直接丢。只当对照用。"""

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
            return
        if not data.strip():
            return
        self.cur.add_text(data)


def old_md_of(html_text):
    b = _OldBuilder()
    b.feed(html_text)
    b.close()
    frag = clip_article._serialized(clip_article._pick_body(b), "https://e.com/", [])
    return book_import._md_from_xhtml(frag)


# ── A. 行内之间该有的空格保住 ──────────────────────────────
chk("行内 `<span>a</span> <span>b</span>` 不再粘成一个词",
    "alpha beta gamma delta" in md_of(
        "<article><p>alpha <span>beta</span> <span>gamma</span> delta</p></article>"),
    md_of("<article><p>alpha <span>beta</span> <span>gamma</span> delta</p></article>"))
chk("加粗与斜体之间的空格保住（不再连成 `**quick***brown*`）",
    "the **quick** *brown* fox" in md_of(
        "<article><p>the <b>quick</b> <i>brown</i> fox</p></article>"),
    md_of("<article><p>the <b>quick</b> <i>brown</i> fox</p></article>"))
chk("标题里被 `<span>` 切开的词也分开",
    "# Hello World" in md_of(
        "<article><h1><span>Hello</span> <span>World</span></h1></article>"),
    md_of("<article><h1><span>Hello</span> <span>World</span></h1></article>"))
chk("行内链接之间的空格照旧（原有行为没被这一改带坏）",
    "见 [这里](https://e.com/x) 和 [那里](https://e.com/y)" in md_of(
        '<article><p>见 <a href="https://e.com/x">这里</a> 和 '
        '<a href="https://e.com/y">那里</a></p></article>'))

# ── B. 块级之间不该多出来的不留 ────────────────────────────
out = md_of("<article><div>\n<p>one</p>\n<p>two</p>\n</div></article>")
chk("块级元素之间的空白被吃掉（段落仍是两段、没有多余空行）",
    out == "one\n\ntwo", out)
out = md_of("<article><ul>\n<li>一</li>\n<li>二</li>\n</ul></article>")
chk("列表项之间的空白不影响成列", out == "- 一\n- 二", out)
out = md_of("<article><p>  首尾留白  </p></article>")
chk("段落首尾的留白被 strip 掉", out == "首尾留白", out)

# ── C. 对照：旧写法确实会粘（这一套不是空转）────────────────
old = old_md_of("<article><p>alpha <span>beta</span> <span>gamma</span> delta</p></article>")
chk("对照：旧写法那一刻确实是 `betagamma`",
    "betagamma" in old and "beta gamma" not in old, old)
old = old_md_of("<article><p>the <b>quick</b> <i>brown</i> fox</p></article>")
chk("对照：旧写法确实把加粗斜体连成 `**quick***brown*`",
    "**quick***brown*" in old, old)

# ── D. 端到端：真走一次 _extract_once（假 fetch，不联网）────
PAGE = ("<html><head><title>测试页</title></head><body><div id=\"js_content\">"
        "<p>study the <b>quick</b> <i>brown</i> fox jumps over the lazy dog</p>"
        "<p>alpha <span>beta</span> <span>gamma</span> delta</p>"
        "<p>%s</p></div></body></html>"
        % ("这是一段用来凑够正文长度的测试文字，重复几次让它足够长。" * 6))
_orig_fetch = clip_article.fetch
try:
    clip_article.fetch = lambda u: (PAGE, "https://example.com/p")
    art = clip_article._extract_once("https://example.com/p")
finally:
    clip_article.fetch = _orig_fetch
md = art.get("markdown") or ""
chk("端到端：剪出来的正文里两个词分开", "beta gamma" in md and "betagamma" not in md,
    md[:160])
chk("端到端：加粗斜体不再连成一串",
    "**quick** *brown*" in md and "**quick***brown*" not in md, md[:160])

# ── E. 源码：那一句直接丢的写法确实不在了 ──────────────────
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "clip_article.py"), encoding="utf-8") as f:
    SRC = f.read()
chk("源码：handle_data 不再「纯空白直接 return」",
    re.search(r"if not data\.strip\(\):\s*\n\s*return\b", SRC) is None, "仍能找到旧写法")

print()
if FAIL:
    print("剪藏行内空白：失败 %d 项" % len(FAIL))
    for n in FAIL:
        print("  ✗ " + n)
    sys.exit(1)
print("剪藏行内空白：通过 %d 项，失败 0 项" % PASSED)
