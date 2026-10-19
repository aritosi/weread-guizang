#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：订阅源发现这一层的两个「合法写法被漏掉」。

守的是同一句话：**别人按规范发出来的订阅源，归藏得认得。** 两个坑都不报错，
只在界面上变成一句「这个地址上没找到订阅源（RSS / Atom / JSON Feed 都没有）」，
用户看着一个能打开的 feed 地址，却永远订不上。

  1. 带 UTF-8 BOM 的 JSON Feed。
     BOM 不是空白：`str.lstrip()` 与 `bytes.lstrip()` 都摘不掉它，于是
     `_looks_like_feed` 判不出「这个地址本来就是订阅源」、`parse_feed` 把它
     当成 RSS 解出 0 条。RSS / Atom 靠子串搜索不受影响，只有 JSON Feed 全军覆没。
     摘 BOM 的出口只有一处（`_decode`，外加 `_looks_like_feed` 开头那三个字节），
     这一条从「字节 → 文本 → 认格式 → 解析 → discover 真跑一遍」逐层钉。

  2. `<link type="application/rss+xml; charset=utf-8">` 这种带 MIME 参数的写法。
     HTML 里 `type` 带参数是合法的，而 HTTP `Link:` 头那条路（`_link_header`）
     早就按 `;` 截断 —— 两条发现路必须是同一把尺子，不然同一份页面在这里被漏掉。

全程离线：不起服务、不联网，`discover` 那一段把 `_fetch_bytes` 换成假的。
跑法：.venv/bin/python tests/check_feed_bom.py
"""
import os
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# GUIZANG_DATA 要在 import feed 之前设好：feed.py 在导入时就把数据目录定下来了，
# 设晚了它算出来的还是用户真实那份 cache/。这一条不落盘，但规矩照旧。
SANDBOX = tempfile.mkdtemp(prefix="gz-feed-bom-")
os.environ["GUIZANG_DATA"] = os.path.join(SANDBOX, "data")

import feed  # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))


BOM = b"\xef\xbb\xbf"
JSON_FEED = (b'{"version":"https://jsonfeed.org/version/1.1","title":"\xe4\xb8\x80\xe4\xb8\xaa\xe6\xba\x90",'
             b'"home_page_url":"https://example.com/","feed_url":"https://example.com/f.json",'
             b'"items":[{"id":"1","url":"https://example.com/a","title":"\xe7\xac\xac\xe4\xb8\x80\xe7\xaf\x87",'
             b'"content_text":"hello"}]}')
RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'

try:
    # ── 1. _decode：开头那一个 U+FEFF 摘掉，正文中间的不动 ──────────────
    chk("_decode：UTF-8 BOM 字节解出来不再带 U+FEFF", feed._decode(BOM + b"{}") == "{}")
    chk("_decode：本来就没有 BOM 的一个字节不改", feed._decode(b"{}") == "{}")
    chk("_decode：已经是 str 的也过同一道口", feed._decode("\ufeff{}") == "{}")
    chk("_decode：正文中间的 U+FEFF 不动（只摘开头那一个）",
        feed._decode("a\ufeffb".encode("utf-8")) == "a\ufeffb",
        repr(feed._decode("a\ufeffb".encode("utf-8"))))

    # ── 2. _looks_like_feed：带 BOM 的 JSON Feed 仍然是 JSON ──────────────
    chk("认格式：带 BOM 的 JSON Feed 判成 json", feed._looks_like_feed(BOM + JSON_FEED) == "json",
        feed._looks_like_feed(BOM + JSON_FEED))
    chk("对照：不带 BOM 的 JSON Feed 也是 json（没把没 BOM 的判坏）",
        feed._looks_like_feed(JSON_FEED) == "json")
    chk("认格式：带 BOM 的 RSS 照旧判成 rss（摘 BOM 没伤到别的格式）",
        feed._looks_like_feed(BOM + RSS) == "rss")
    chk("对照：带 BOM 的普通 HTML 页不会被当成订阅源",
        feed._looks_like_feed(BOM + b"<!doctype html><html><body>x</body></html>") == "")

    # ── 3. parse_feed：带 BOM 的 JSON Feed 要解出条目，不许静默成 0 条 ────
    got = feed.parse_feed(BOM + JSON_FEED, "https://example.com/f.json")
    chk("解析：带 BOM 的 JSON Feed kind=json", got["kind"] == "json", got["kind"])
    chk("解析：书名与站点字段读得到", got["title"] == "一个源" and got["site"] == "https://example.com/",
        (got["title"], got["site"]))
    chk("解析：条目解出来了（不是 0 条）", len(got["entries"]) == 1, len(got["entries"]))
    chk("解析：条目标题与链接对得上",
        got["entries"] and got["entries"][0]["title"] == "第一篇"
        and got["entries"][0]["link"] == "https://example.com/a",
        got["entries"][:1])

    # ── 4. discover 真跑一遍（取回换成假的）：粘一个带 BOM 的地址能订上 ──
    real_fetch = feed._fetch_bytes
    feed._fetch_bytes = lambda u, *a, **k: (BOM + JSON_FEED, u, {})
    try:
        cands = feed.discover("https://example.com/f.json")
    finally:
        feed._fetch_bytes = real_fetch
    chk("发现：带 BOM 的 JSON Feed 地址自己就被认成订阅源",
        len(cands) == 1 and cands[0]["type"] == "json" and cands[0]["url"] == "https://example.com/f.json",
        cands)

    # ── 5. <link alternate> 的 MIME 参数写法：与 Link: 头同一把尺子 ──────
    def link_tag(t):
        return '<link rel="alternate" type="%s" href="/feed.xml">' % t

    chk("发现：<link> 上 application/rss+xml; charset=utf-8 认得出",
        [c["type"] for c in feed._link_rel_alternate(link_tag("application/rss+xml; charset=utf-8"),
                                                     "http://e.com/")] == ["rss"])
    chk("发现：atom / json 带参数也认得出",
        [c["type"] for c in feed._link_rel_alternate(link_tag("application/atom+xml;charset=utf-8"),
                                                     "http://e.com/")] == ["atom"]
        and [c["type"] for c in feed._link_rel_alternate(link_tag("application/feed+json; charset=utf-8"),
                                                         "http://e.com/")] == ["json"])
    chk("对照：不带参数的写法照旧认得出（没把老写法判坏）",
        [c["type"] for c in feed._link_rel_alternate(link_tag("application/rss+xml"),
                                                     "http://e.com/")] == ["rss"])
    chk("对照：type=text/html; charset=… 不算订阅源",
        feed._link_rel_alternate(link_tag("text/html; charset=utf-8"), "http://e.com/") == [])
    chk("两把尺子对齐：Link: 头与 <link> 对同一个带参数的 MIME 给同一个结论",
        [c["type"] for c in feed._link_header({"link": '</feed.xml>; rel="alternate"; type="application/rss+xml; charset=utf-8"'},
                                              "http://e.com/")] == ["rss"])
finally:
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("\n订阅源发现（BOM / MIME 参数）门禁：%d 项通过，失败 %d 项" % (PASSED, len(FAIL)))
for f in FAIL:
    print("  ✗ " + f)
sys.exit(1 if FAIL else 0)
