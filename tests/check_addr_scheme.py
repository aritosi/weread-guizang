#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归藏门禁：两个「地址里先看有没有协议」的判据（web_browse / anna_state）。

同一个错法在两处各写了一遍：**把「以某几个字符开头」当成「已经有了协议」**。
两处都不抛异常、也不丢数据，就是把一个正常地址判成了别的形状 —— 界面上要么
「这一页打不开」，要么窗口根本开不出来。所以这条门禁只盯这两个判据。

① `web_browse.normalize`（内置浏览器的地址栏）
   地址栏里不带协议地打「主机:端口」—— `example.com:8080/x`、`myserver:9000` ——
   `_SCHEME`（`^[a-zA-Z][a-zA-Z0-9+.\\-]*:`）会把 `example.com:` 整个当成协议名，
   紧接着被「只认 http/https 链接（现在这个是 example.com）」拒掉。用户照着浏览器
   的习惯敲一个正常地址，看到的是一句莫名其妙的话。
   修法：冒号前那一段不是 http(s) 时，再看它像不像主机 —— 「带点」或「冒号后直接
   跟数字」就按 主机:端口 补上 https；`javascript:` / `data:` / `mailto:` /
   `ftp://` 一个字不动，仍归原来那道闸去拒。

② `anna_state.with_scheme`（安娜的档案搜索窗口）
   判据写的是 `d.startswith("http")` —— 那是「以 h-t-t-p 开头」。用户填的镜像主机名
   本身以 http 开头（`httpbin.org`）时，函数当成「已经带了协议」原样返回，窗口地址
   少一个协议头，`page.goto` 报 `Cannot navigate to invalid URL`。
   修法：判完整的 `http://` / `https://` 前缀。

这条门禁带**对照**：把旧判据在这里重抄一遍，确认它对同一个输入会给出错的结果
（否则这组断言可能只是空转）；并确认收紧的那一面没被改松 —— `javascript:` 在
新旧两把尺子下都必须被拒。

纯函数、离线、不起服务、不开浏览器，归 --fast 静态段。
"""
import pathlib
import re
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import anna_state as anna  # noqa: E402
import web_browse as wb  # noqa: E402

FAILED = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(name)
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))


def blocked(u):
    """跑一遍 normalize，回 (是否 Blocked, 回话 / 结果)。"""
    try:
        return False, wb.normalize(u)
    except wb.Blocked as e:
        return True, str(e)


# ── 0. 对照：旧判据（只看 `_SCHEME`）确实把 主机:端口 当成协议 ──────────
# 与 web_browse.normalize 改之前逐行同形。没有这一条，下面的断言可能只是空转。
_OLD_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def old_normalize(raw):
    u = (raw or "").strip()
    if not u:
        raise wb.Blocked("地址是空的")
    if not _OLD_SCHEME.match(u):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    if p.scheme.lower() not in wb.ALLOWED_SCHEMES:
        raise wb.Blocked("只认 http/https 链接（现在这个是 %s）" % (p.scheme or "空"))
    return urllib.parse.urlunparse(p)


try:
    old_normalize("example.com:8080/x")
    chk("对照：旧判据对 example.com:8080/x 确实拒（这门禁不是空转）", False, "居然放行了")
except wb.Blocked as e:
    chk("对照：旧判据对 example.com:8080/x 确实拒（这门禁不是空转）",
        "example.com" in str(e), str(e))

# 旧对照的另一面：收紧的判据在旧写法下也必须拒（说明它本来就在拒）。
try:
    old_normalize("javascript:alert(1)")
    chk("对照：旧判据也拒 javascript:", False, "居然放行了")
except wb.Blocked as e:
    chk("对照：旧判据也拒 javascript:", "javascript" in str(e), str(e))

# ── 1. 主机:端口（不带协议）现在应当补上 https 放行 ─────────────────────
for raw, want in (
    ("example.com:8080", "https://example.com:8080"),
    ("example.com:8080/x", "https://example.com:8080/x"),
    ("myserver:9000", "https://myserver:9000"),            # 主机不带点、端口是数字
    ("nas.local:5000/dav", "https://nas.local:5000/dav"),
    ("www.example.com:443/", "https://www.example.com:443/"),
):
    hit, got = blocked(raw)
    chk("主机:端口 补 https 且放行 %s" % raw, not hit and got == want, got)

# 不带冒号的写法一个字不改：还是补 https。
for raw, want in (
    ("ai-bot.cn", "https://ai-bot.cn"),
    ("example.com/x?q=1", "https://example.com/x?q=1"),
):
    hit, got = blocked(raw)
    chk("不带冒号的正常地址照旧补 https %s" % raw, not hit and got == want, got)

# 已经写了协议的照旧原样留着。
for raw in ("http://example.com/x", "https://example.com/x"):
    hit, got = blocked(raw)
    chk("已带协议的地址原样留着 %s" % raw, not hit and got == raw, got)

# ── 2. 收紧的那一面一个字没松：非 http(s) 的 scheme 仍拒 ────────────────
for raw, scheme in (
    ("javascript:alert(1)", "javascript"),
    ("JavaScript:alert(1)", "javascript"),
    ("data:text/html,<b>x</b>", "data"),
    ("mailto:someone@example.com", "mailto"),
    ("ftp://example.com/x", "ftp"),
    ("file:///etc/hosts", "file"),
    ("javascript:123", "javascript"),
    ("data:123", "data"),
    ("ftp:21", "ftp"),
    ("file:123", "file"),
    ("mailto:123", "mailto"),
):
    hit, got = blocked(raw)
    chk("非 http(s) 的 scheme 仍拒 %s" % raw,
        hit and scheme in got, (hit, got))

# 本机 / 内网那一道闸也照旧：`localhost:8770` 现在是「主机:端口」，
# 放行到内网闸门后必须被拒，且拒话是「本机或内网」，不是「只认 http/https」。
hit, got = blocked("localhost:8770")
chk("localhost:8770 走内网那道闸（不是 scheme 那道）",
    hit and "本机或内网" in got and "只认 http" not in got, got)
for raw in ("http://127.0.0.1:8770/api/state", "http://192.168.1.1/admin",
            "127.0.0.1:8080/x"):
    hit, got = blocked(raw)
    chk("内网地址照旧拒 %s" % raw, hit and "本机或内网" in got, got)

# 半个方括号那几条仍收成 Blocked 带人话（不是裸 ValueError）。
for raw in ("http://[::1", "https://["):
    hit, got = blocked(raw)
    chk("半个方括号仍收成 Blocked %s" % raw, hit and "解不出来" in got, got)

# ── 3. anna.with_scheme：以 http 开头的主机名不再被当成协议头 ────────────
# 对照：旧判据（`startswith("http")`）对同一个域名给出的是没有协议的一串字。
def old_with_scheme(domain):
    d = anna.clean_domain(domain)
    return d if d.startswith("http") else "https://" + d


chk("对照：旧判据把 httpbin.org 当成已有协议（这门禁不是空转）",
    old_with_scheme("httpbin.org") == "httpbin.org", old_with_scheme("httpbin.org"))

for raw, want in (
    ("httpbin.org", "https://httpbin.org"),
    ("http://httpbin.org", "https://httpbin.org"),
    ("https://httpbin.org", "https://httpbin.org"),
    ("httparchive.org", "https://httparchive.org"),
    ("annas-archive.is", "https://annas-archive.is"),
    ("http://annas-archive.is", "https://annas-archive.is"),
    ("http://annas-archive.gd:8443/search", "https://annas-archive.gd:8443"),
):
    got = anna.with_scheme(raw)
    chk("with_scheme(%s) 补完整协议头" % raw,
        got == want and got.startswith("https://"), got)

# 空 / 洗不出东西时仍回默认域名，且一定带协议头。
for raw in ("", None, "   "):
    got = anna.with_scheme(raw)
    chk("with_scheme(%r) 回默认域名且带协议头" % (raw,),
        got == "https://" + anna.DEFAULT_DOMAIN, got)

# 搜索地址：用户填的自定义域名（以 http 开头）也拼得出可用的整条 URL。
u = anna.search_url("归藏", "httpbin.org")
chk("search_url 用自定义域名时带完整协议头",
    u.startswith("https://httpbin.org/search?q="), u)
chk("search_url 默认域名照旧",
    anna.search_url("x").startswith("https://" + anna.DEFAULT_DOMAIN + "/search?q=x"),
    anna.search_url("x"))

print("\n地址协议判据门禁：%d 项通过，失败 %d 项" % (PASSED, len(FAILED)))
for f in FAILED:
    print("  ✗ " + f)
sys.exit(1 if FAILED else 0)
