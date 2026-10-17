#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Issue #212：油管「要登录 / 年龄确认」与「点视频就该一键转笔记」的离线体检。

用户报的两件事，这一条把边界一起钉住：

  ① 「点击油管视频读取的时候会显示无法读取视频需要登录或者年龄确认」。
     归藏只借**用户自己**在内置浏览器档案里的登录态：`video_note` 从
     `cache/browser_profile`（可用 GUIZANG_BROWSER_PROFILE 指到别处）读 Chromium
     的 cookie，只取 youtube / google 这一族，导成 Netscape 文件交给 yt-dlp 的
     `cookiefile`。读不到就当未登录。**不代填账号、不解验证码、不绕年龄门**，
     报错话术也只说「先登录 / 自己下好再导进来」。
     另外油管的机器人校验（Sign in to confirm you're not a bot）与年龄门分开报，
     别把「被当成机器人」也说成「要登录 / 年龄确认」——那是两条不同的正路。

  ② 「点击视频即可一键 ASR 转录为笔记，无需在页面点击打开」+「修复无效按钮」。
     静态目录里整张卡的封面与标题现在都挂 `data-gz-use`，点一下就是
     `gzUseLink` → 视频那一屏当场开跑；「在油管打开」那颗仍走原来的 `/api/browse`，
     不再要求用户先进播放页再点一次。

  ③ 「优化减少每次取回的时间」：`plan()` 认过的元信息在进程内留一份，
     `download_audio()` 用它走 `process_ie_result`，省掉同一条链接的第二次解析；
     复用失败时退回整体再取一次（正确性优先）。

全程离线：cookie 用假对象、下载用假 YoutubeDL，不联网、不起服务、不开浏览器，归 --fast。
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile
from types import SimpleNamespace

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# GUIZANG_DATA 要在 import 之前设好：模块导入时就把 TMP_ROOT 定下来了。
SANDBOX = tempfile.mkdtemp(prefix="gz-yt-login-")
atexit.register(lambda: shutil.rmtree(SANDBOX, ignore_errors=True))
os.environ["GUIZANG_DATA"] = os.path.join(SANDBOX, "data")
os.makedirs(os.environ["GUIZANG_DATA"], exist_ok=True)
# 档案指进沙盒：这一条绝不去碰用户真实的浏览器档案。
os.environ["GUIZANG_BROWSER_PROFILE"] = os.path.join(SANDBOX, "profile")

import video_note as vn  # noqa: E402
import web_browse as wb  # noqa: E402

CHECKS = []
FAIL = []


def chk(name, cond, extra=""):
    CHECKS.append(name)
    print(("  ok  " if cond else " FAIL ") + name + ("" if cond else "  <- " + repr(extra)[:300]))
    if not cond:
        FAIL.append(name)


def cookie(domain, name, value, secure=True, path="/", expires=4102444800):
    return SimpleNamespace(domain=domain, name=name, value=value,
                           secure=secure, path=path, expires=expires)


# ══════════════════════════════════════════════════════════════════
# A YouTube 与别的站走不同的口吻（别再带 B 站的 Referer）
# ══════════════════════════════════════════════════════════════════
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
SHORT = "https://youtu.be/dQw4w9WgXcQ"
BILI = "https://www.bilibili.com/video/BV1xx411c7mD"

chk("认得 YouTube 的两种地址", vn._is_youtube(YT) and vn._is_youtube(SHORT), (YT, SHORT))
chk("不把 B 站 / 空 / 仿冒认成 YouTube",
    not vn._is_youtube(BILI) and not vn._is_youtube("")
    and not vn._is_youtube("https://youtube.com.evil.cn/x"), BILI)

yt_h = vn._headers_for(YT)
bili_h = vn._headers_for(BILI)
chk("YouTube 用浏览器口吻：带 Accept-Language", "Accept-Language" in yt_h, yt_h)
chk("YouTube 不带 B 站的 Referer（那种破绽别再漏出去）",
    "Referer" not in yt_h, yt_h)
chk("B 站照旧带自己的 Referer、不带那个 Accept-Language",
    bili_h.get("Referer") == "https://www.bilibili.com/" and "Accept-Language" not in bili_h,
    bili_h)

# ══════════════════════════════════════════════════════════════════
# B 只导 youtube / google 这一族，写成 Netscape 文件
# ══════════════════════════════════════════════════════════════════
COOKIES = [
    cookie(".youtube.com", "SID", "yt-secret"),
    cookie(".google.com", "SAPISID", "g-secret"),
    cookie("www.bilibili.com", "bili_jct", "bili-secret"),        # 不该跟着走
    cookie("evil.cn", "tracker", "nope"),
    cookie(".youtube.com", "BAD\tNAME", "x"),                     # 制表符注入，跳过
    cookie(".youtube.com", "OK", "line\nbreak"),                  # 换行注入，跳过
]
_orig_browser_cookies = vn._browser_cookies
vn._browser_cookies = lambda profile: list(COOKIES)
try:
    out = os.path.join(SANDBOX, "cookies.txt")
    kept = vn.export_browser_cookies(os.path.join(SANDBOX, "profile", "Default"), out)
    body = open(out, encoding="utf-8").read() if os.path.isfile(out) else ""
finally:
    vn._browser_cookies = _orig_browser_cookies

chk("只留下 youtube / google 那两条", kept == 2, kept)
chk("B 站与别家的 cookie 没跟着走",
    "bili_jct" not in body and "tracker" not in body, body)
chk("写的是 Netscape 那副样子（域名 / 子域 / 路径 / 安全 / 过期 / 名 / 值）",
    body.startswith("# Netscape HTTP Cookie File")
    and ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tyt-secret" in body, body)
chk("名字或值里带制表符 / 换行的整条丢掉（不给文件注入留口子）",
    "BAD\tNAME" not in body and "line\nbreak" not in body, body)

# 一条都不匹配时不写文件、回 0
_orig_browser_cookies = vn._browser_cookies
vn._browser_cookies = lambda profile: [cookie("evil.cn", "x", "y")]
try:
    only_out = os.path.join(SANDBOX, "none.txt")
    if os.path.exists(only_out):
        os.remove(only_out)
    n_none = vn.export_browser_cookies("whatever", only_out)
finally:
    vn._browser_cookies = _orig_browser_cookies
chk("没有这一族的 cookie 时不写文件、回 0",
    n_none == 0 and not os.path.exists(only_out), (n_none, os.path.exists(only_out)))

# ══════════════════════════════════════════════════════════════════
# C _ydl_options：YouTube 有登录态就带 cookiefile，别的站不读也不带
# ══════════════════════════════════════════════════════════════════
_orig_cookie_file = vn.cookie_file
vn.cookie_file = lambda: "/tmp/does-not-matter.txt"
try:
    yt_opts = vn._ydl_options({}, YT)
    bili_opts = vn._ydl_options({}, BILI)
finally:
    vn.cookie_file = _orig_cookie_file

chk("YouTube 带上 cookiefile（借的是用户自己那份档案）",
    yt_opts.get("cookiefile") == "/tmp/does-not-matter.txt", yt_opts)
chk("B 站那一路不碰 cookie 文件", "cookiefile" not in bili_opts, bili_opts)

_orig_cookie_file = vn.cookie_file
vn.cookie_file = lambda: ""
try:
    no_cookie = vn._ydl_options({}, YT)
finally:
    vn.cookie_file = _orig_cookie_file
chk("没有登录态就不带 cookiefile（当未登录，不硬编一份）",
    "cookiefile" not in no_cookie, no_cookie)

# ══════════════════════════════════════════════════════════════════
# D 报错话术：机器人校验与年龄门分开，都得指向「用你自己的登录态」
# ══════════════════════════════════════════════════════════════════
bot = vn._ydl_error(Exception("Sign in to confirm you're not a bot. Use --cookies"))
age = vn._ydl_error(Exception("Sign in to confirm your age. This video may be inappropriate"))
priv = vn._ydl_error(Exception("Private video. Sign in if you've been granted access"))
chk("都是 ValueError（界面认这个异常）",
    all(isinstance(e, ValueError) for e in (bot, age, priv)))
chk("机器人校验单独报：话里点出「机器人」与「登录」",
    "机器人" in str(bot) and "登录" in str(bot), str(bot))
chk("年龄确认那条点出「年龄」与「登录」",
    "年龄" in str(age) and "登录" in str(age), str(age))
chk("私享视频也归到登录那条正路，不再是一句「取不到」",
    "登录" in str(priv), str(priv))
chk("三条都讲清「只用你自己的登录态 / 不绕过」（边界写进用户看得到的话里）",
    all("登录态" in str(e) or "不绕过" in str(e) for e in (bot, age, priv)),
    (str(bot), str(age), str(priv)))

# 源码：不许出现代填账号 / 输密码这类「绕过」的写法
src = (REPO / "video_note.py").read_text(encoding="utf-8")
chk("没有把账号密码写进请求的写法（不代填、不绕过）",
    "password" not in src and "账号密码" not in src, None)
chk("cookie 只从档案这一处读（不是从别的地方捡）",
    src.count("extract_cookies_from_browser(") == 1, src.count("extract_cookies_from_browser("))

# ══════════════════════════════════════════════════════════════════
# E 省掉第二次解析：plan 认过的元信息直接拿去下
# ══════════════════════════════════════════════════════════════════
CALLS = []


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _write(self):
        d = self.opts.get("outtmpl", "").rsplit("/", 1)[0]
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "audio.m4a"), "wb") as f:
            f.write(b"\x00\x00ftypM4A ")

    def process_ie_result(self, info, download=False):
        CALLS.append(("process", info))
        self._write()
        return info

    def download(self, urls):
        CALLS.append(("download", list(urls)))
        self._write()


def reset_meta():
    vn._META_CACHE.clear()
    del vn._META_CACHE_ORDER[:]


_orig_ydl_class = vn._ydl_class
vn._ydl_class = lambda: FakeYDL
try:
    reset_meta()
    vn._remember_meta(YT, {"id": "dQw4w9WgXcQ", "title": "假元信息"})
    task = os.path.join(SANDBOX, "task-cached")
    path = vn.download_audio(YT, task)
    chk("有刚认过的元信息时走 process_ie_result（不再整体重取一遍）",
        CALLS and CALLS[0][0] == "process" and CALLS[0][1].get("id") == "dQw4w9WgXcQ",
        CALLS)
    chk("这条路上没有第二次 download（省下的就是那一次网络解析）",
        all(c[0] != "download" for c in CALLS), CALLS)
    chk("照样回音频文件路径", os.path.isfile(path), path)

    CALLS.clear()
    reset_meta()
    task2 = os.path.join(SANDBOX, "task-plain")
    vn.download_audio(BILI, task2)
    chk("没有缓存时照旧走 download([url])（B 站那条路没变）",
        CALLS and CALLS[0][0] == "download" and CALLS[0][1] == [BILI], CALLS)

    # 复用那份失败时退回整体再取一次：正确性优先，别省出个空文件。
    CALLS.clear()
    reset_meta()
    vn._remember_meta(YT, {"id": "stale"})

    class FlakyYDL(FakeYDL):
        def process_ie_result(self, info, download=False):
            CALLS.append(("process-fail", info))
            raise RuntimeError("格式过期了")

    vn._ydl_class = lambda: FlakyYDL
    task3 = os.path.join(SANDBOX, "task-fallback")
    path3 = vn.download_audio(YT, task3)
    chk("复用失败时退回整体再取一次（不把错误当结果）",
        [c[0] for c in CALLS] == ["process-fail", "download"], CALLS)
    chk("退回后照样下到音频文件", os.path.isfile(path3), path3)
finally:
    vn._ydl_class = _orig_ydl_class
    reset_meta()

# ══════════════════════════════════════════════════════════════════
# F 点视频 = 一键转笔记（封面 / 标题都挂 data-gz-use），无效按钮收口
# ══════════════════════════════════════════════════════════════════
import json  # noqa: E402

CARD = {"id": "AAAA111122", "title": "一支示例", "channel": "某频道",
        "length": "3:03", "when": "今天", "thumb": "https://i.ytimg.com/vi/AAAA111122/mq.jpg"}
PAGE = ("<html><body><script>var ytInitialData = %s;</script></body></html>"
        % json.dumps({"z": [{"videoRenderer": {
            "videoId": CARD["id"],
            "title": {"runs": [{"text": CARD["title"]}]},
            "ownerText": {"runs": [{"text": CARD["channel"]}]},
            "lengthText": {"simpleText": CARD["length"]},
            "publishedTimeText": {"simpleText": CARD["when"]},
            "thumbnail": {"thumbnails": [{"url": CARD["thumb"], "width": 336}]}}}]},
            ensure_ascii=False))
HTML = wb.yt_static(PAGE, "https://www.youtube.com/results?search_query=x")
WATCH = "https://www.youtube.com/watch?v=AAAA111122"

chk("封面那颗挂 data-gz-use（点封面就是「转成笔记」）",
    'class="th" href="%s" data-gz-use' % WATCH in HTML, HTML[:400])
chk("标题那颗也挂 data-gz-use（整张卡点哪儿都开跑）",
    'class="ti" href="%s" data-gz-use' % WATCH in HTML, HTML[:500])
chk("「在油管打开」仍走原来的内置浏览器（不带 data-gz-use）",
    '<a href="%s">在油管打开</a>' % WATCH in HTML, HTML[:600])
chk("那颗明确写着「一键转成笔记」，不让人猜",
    "一键转成笔记" in HTML and "转成笔记" in HTML, HTML[:600])
chk("搜索框与搜索按钮照旧在（另一颗按钮没被弄坏）",
    'name="search_query"' in HTML and "<button type=\"submit\">搜索</button>" in HTML,
    HTML[:600])
chk("副标题告诉用户「点封面或标题就转」",
    "点任意一支的封面或标题" in HTML, HTML[:300])

# 注入的那段脚本：data-gz-use → gzUseLink；普通链接与表单 → gzBrowse
script = wb._LINK_SCRIPT
chk("脚本认 data-gz-use，回传 gzUseLink",
    "data-gz-use" in script and "gzUseLink" in script, script[:400])
chk("封面 / 标题的点击不会掉进 gzBrowse（不是「再取一页」）",
    script.index("data-gz-use") < script.index("tell(h)"), script[:600])

print()
if FAIL:
    print("油管登录态 / 一键转笔记体检：失败 %d 项（共 %d 项）" % (len(FAIL), len(CHECKS)))
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
print("油管登录态 / 一键转笔记体检：%d 项通过，失败 0 项" % len(CHECKS))
