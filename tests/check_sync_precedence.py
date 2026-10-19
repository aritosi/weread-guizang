#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云同步「两边都有同一份」时的先后：小账本比修改时间、取新的那份。

为什么单开一条
    `sync.py` 的模块说明一直写着「同一个文件都有的，比大小与修改时间，取新的那份」，
    而实现只做了「本地有就传上去」—— 于是换机场景里最想要的那三本小账本
    （`cache/readstat.json` 阅读时长 / `cache/library.json` 书架 / `cache/notes_index.json`
    划线索引）**永远不会从云上回来**：B 机那份一直都在，同步就永远只上传，
    A 机上读的进度、存的书架 B 机永远看不到。这一条钉住：

      · 远端确实更新（> 本机 + 1 秒）→ 取回来，且把本机那份的修改时间对齐成远端的
        （不对齐就两边轮流「我更新」，每次同步都来回搬一遍）；
      · 本机更新 / 时间一样 / 问不到远端时间 → 照旧把本机这份传上去（与改之前同）；
      · 本地没有、远端有 → 照旧取回来，且**不为它多发一次属性查询**；
      · 书库文件不做这一比（几千个文件每个多一次 PROPFIND，代价不值）→ 仍以本机为准。

网络全程是假的（记账 Transport），不起服务、不联网、不碰真实 cache/ 与书库。
Google 上那两个属性查询 WebDAV 用 PROPFIND、OneDrive 用 Graph item 元数据，
两家的解析都在这里喂正常值与三种坏值。
"""
import atexit
import email.utils
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import sync as S  # noqa: E402

FAIL = []


def chk(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if not cond:
        FAIL.append(name)


ORIG_HTTP = S._http
BASE = "https://dav.example.com/remote.php/dav/files/u"


class FakeResponse:
    def __init__(self, data=b""):
        self._data = data

    def read(self, *_a):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class Transport:
    """记账的假 HTTP：可预置远端文件、属性（PROPFIND / Graph item）、错误。"""

    def __init__(self):
        self.calls = []            # [(method, url)]
        self.remote = {}           # url -> bytes（GET / PUT 命中）
        self.propfind = {}         # url -> xml（没预置就按 405 处理）
        self.reply = {}            # url -> bytes（Graph item 元数据这类 JSON）
        self.raise_on = {}         # url -> (code, body)
        self.raise_method = {}     # (method, url) -> (code, body)，只砸某一个方法

    def __call__(self, method, url, data=None, headers=None, timeout=60):
        self.calls.append((method, url))
        if (method, url) in self.raise_method:
            code, body = self.raise_method[(method, url)]
            raise urllib.error.HTTPError(url, code, "err", None, io.BytesIO(body or b""))
        if url in self.raise_on:
            code, body = self.raise_on[url]
            raise urllib.error.HTTPError(url, code, "err", None, io.BytesIO(body or b""))
        if method == "MKCOL":
            return FakeResponse()
        if method == "PROPFIND":
            if url in self.propfind:
                return FakeResponse(self.propfind[url].encode("utf-8"))
            raise urllib.error.HTTPError(url, 405, "no propfind", None, io.BytesIO(b""))
        if method == "PUT":
            self.remote[url] = data
            return FakeResponse()
        if method == "GET":
            if url in self.reply:
                return FakeResponse(self.reply[url])
            if url in self.remote:
                return FakeResponse(self.remote[url])
            raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))
        return FakeResponse()

    def urls(self, method=None):
        return [u for m, u in self.calls if method is None or m == method]


def dav_url(path):
    import urllib.parse
    return BASE + "/" + urllib.parse.quote(path)


def propfind_xml(mtime=0, size=0):
    """一段最小可用的 multistatus 回包。mtime 传 0 就整段不带 getlastmodified。"""
    prop = ["<d:getcontentlength>%d</d:getcontentlength>" % size]
    if mtime:
        prop.insert(0, "<d:getlastmodified>%s</d:getlastmodified>"
                    % email.utils.formatdate(mtime, usegmt=True))
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?><d:multistatus xmlns:d=\"DAV:\">"
            "<d:response><d:propstat><d:prop>%s</d:prop></d:propstat>"
            "</d:response></d:multistatus>" % "".join(prop))


def dav_cfg(**what):
    w = {"time": True, "records": False, "books": False}
    w.update(what)
    return S._norm({"enabled": True, "provider": "webdav", "what": w,
                    "webdav": {"url": BASE, "user": "u", "pass": "p"}})


def od_cfg(**what):
    w = {"time": True, "records": False, "books": False}
    w.update(what)
    return S._norm({"enabled": True, "provider": "onedrive", "what": w,
                    "onedrive": {"client_id": "cid", "access_token": "tok",
                                 "access_exp": S._now() + 3600}})


TMP = tempfile.mkdtemp(prefix="guizang-sync-order-")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))
CACHE = os.path.join(TMP, "cache")
BOOKS = os.path.join(TMP, "books")
os.makedirs(CACHE)
os.makedirs(os.path.join(BOOKS, "微信读书", "bk1", "chapters"))
READSTAT = os.path.join(CACHE, "readstat.json")
LEDGER_PATH = "guizang/cache/readstat.json"
LEDGER_URL = dav_url(LEDGER_PATH)
T0 = 1700000000


def put(path, text, mtime=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))


# ─────────────────────────── 属性解析（纯函数） ───────────────────────────
chk("_http_date：RFC1123 GMT 解得成秒",
    S._http_date("Wed, 15 Nov 2023 06:13:20 GMT") == 1700028800,
    S._http_date("Wed, 15 Nov 2023 06:13:20 GMT"))
chk("_http_date：坏串 / 空 / 整段 HTML 都回 0（不抛）",
    S._http_date("not a date") == 0 and S._http_date(None) == 0
    and S._http_date("<html>nope</html>") == 0)
chk("_iso_epoch：Graph 的 ISO8601（带 Z）解得成秒",
    S._iso_epoch("2023-11-15T06:13:20Z") == 1700028800,
    S._iso_epoch("2023-11-15T06:13:20Z"))
chk("_iso_epoch：坏串 / 空回 0",
    S._iso_epoch("") == 0 and S._iso_epoch("xx") == 0)
chk("LEDGER_REMOTE：就是那三本小账本",
    S.LEDGER_REMOTE == {"guizang/cache/readstat.json",
                        "guizang/cache/library.json",
                        "guizang/cache/notes_index.json"}, S.LEDGER_REMOTE)

# ─────────────────────────── WebDAV：远端更新 → 取回来 ───────────────────────────
tr = Transport()
S._http = tr
put(READSTAT, '{"v":"local"}', T0)
tr.remote[LEDGER_URL] = b'{"v":"cloud"}'
tr.propfind[LEDGER_URL] = propfind_xml(mtime=T0 + 1000, size=15)
ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
chk("WebDAV：远端更新 → 取回来（不再把本机旧读数盖上去）",
    ok and "取回 1" in msg and open(READSTAT, "rb").read() == b'{"v":"cloud"}',
    (ok, msg, open(READSTAT, "rb").read()))
chk("WebDAV：远端更新时一个 PUT 都不发",
    not any(u == LEDGER_URL for u in tr.urls("PUT")), tr.urls("PUT"))
chk("WebDAV：取回后本机修改时间对齐成远端的（不再两边轮流「我更新」）",
    int(os.path.getmtime(READSTAT)) == T0 + 1000, os.path.getmtime(READSTAT))
chk("WebDAV：属性查询走的是同一条路径，Depth: 0",
    LEDGER_URL in tr.urls("PROPFIND"), tr.calls[:6])

# ─────────────────────────── 本机更新 / 一样新 → 照旧上传 ───────────────────────────
tr = Transport()
S._http = tr
put(READSTAT, '{"v":"mine"}', T0 + 5000)
tr.remote[LEDGER_URL] = b'{"v":"cloud"}'
tr.propfind[LEDGER_URL] = propfind_xml(mtime=T0 + 1000, size=15)
ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
chk("WebDAV：本机更新 → 传上去，本机这份不被远端旧数据顶掉",
    ok and "上传 1" in msg and open(READSTAT, "rb").read() == b'{"v":"mine"}',
    (ok, msg, open(READSTAT, "rb").read()))

tr = Transport()
S._http = tr
put(READSTAT, '{"v":"same"}', T0 + 1000)
tr.remote[LEDGER_URL] = b'{"v":"cloud"}'
tr.propfind[LEDGER_URL] = propfind_xml(mtime=T0 + 1000, size=15)   # 只差 0 秒
ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
chk("WebDAV：时间一样（1 秒容差内）→ 本机为准，不把本机改动吞掉",
    ok and "上传 1" in msg and open(READSTAT, "rb").read() == b'{"v":"same"}',
    (ok, msg, open(READSTAT, "rb").read()))

# ─────────────────────────── 问不到远端时间 → 退回老口径 ───────────────────────────
for label, setup in (
        ("服务器不认 PROPFIND（405）", lambda tr: None),
        ("回的不是 XML（反代插了一页 HTML）", lambda tr: tr.propfind.__setitem__(
            LEDGER_URL, "<html><body>login</body></html>")),
        ("XML 里没有 getlastmodified", lambda tr: tr.propfind.__setitem__(
            LEDGER_URL, propfind_xml(mtime=0, size=15)))):
    tr = Transport()
    S._http = tr
    put(READSTAT, '{"v":"local2"}', T0)
    tr.remote[LEDGER_URL] = b'{"v":"cloud"}'
    setup(tr)
    ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
    chk("WebDAV：%s → 退回「本机为准传上去」，不报错" % label,
        ok and "上传 1" in msg and open(READSTAT, "rb").read() == b'{"v":"local2"}',
        (ok, msg))

# 属性查询整条路抛别的异常（超时 / DNS）也只能退回去，不能把这一趟算失败
tr = Transport()
S._http = tr
put(READSTAT, '{"v":"local3"}', T0)
tr.remote[LEDGER_URL] = b'{"v":"cloud"}'
tr.raise_method[("PROPFIND", LEDGER_URL)] = (500, b"boom")
ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
chk("WebDAV：属性查询回 500 → 照旧上传（一次查询失败不挡本地改动）",
    ok and "上传 1" in msg and open(READSTAT, "rb").read() == b'{"v":"local3"}',
    (ok, msg))

# ─────────────────────────── 本地没有 → 照旧取回，且不多发查询 ───────────────────────────
tr = Transport()
S._http = tr
if os.path.exists(READSTAT):
    os.remove(READSTAT)
tr.remote[LEDGER_URL] = b'{"from":"cloud"}'
ok, msg = S.run(dav_cfg(), CACHE, BOOKS)
chk("WebDAV：本地没有、远端有 → 取回来（老规矩没变）",
    ok and "取回 1" in msg and open(READSTAT, "rb").read() == b'{"from":"cloud"}',
    (ok, msg))
chk("WebDAV：本地没有时不为它多发一次 PROPFIND",
    tr.urls("PROPFIND") == [], tr.urls("PROPFIND"))

# ─────────────────────────── 书库文件不做这一比 ───────────────────────────
BOOKFILE = os.path.join(BOOKS, "微信读书", "bk1", "chapters", "0001.md")
BOOKREL = "guizang/books/微信读书/bk1/chapters/0001.md"
tr = Transport()
S._http = tr
put(BOOKFILE, "# 第一章\n", T0)
if os.path.exists(READSTAT):
    os.remove(READSTAT)
tr.remote[dav_url(BOOKREL)] = b"# cloud\n"
tr.propfind[dav_url(BOOKREL)] = propfind_xml(mtime=T0 + 10000, size=8)
ok, msg = S.run(dav_cfg(books=True, time=False), CACHE, BOOKS)
chk("书库文件：就算远端更新也照旧以本机为准（不为每个文件多一次属性查询）",
    ok and "上传 1" in msg
    and open(BOOKFILE, "rb").read() == "# 第一章\n".encode("utf-8"),
    (ok, msg, open(BOOKFILE, "rb").read()))
chk("书库文件：没有对书库里的文件发 PROPFIND",
    tr.urls("PROPFIND") == [], tr.urls("PROPFIND"))

# ─────────────────────────── OneDrive：同一条路 ───────────────────────────
ITEM_URL = "%s/me/drive/special/approot:/%s" % (S.GRAPH, "guizang/cache/readstat.json")
CONTENT_URL = ITEM_URL + ":/content"
tr = Transport()
S._http = tr
put(READSTAT, '{"v":"local"}', T0)
tr.remote[CONTENT_URL] = b'{"v":"cloud"}'
tr.reply[ITEM_URL] = json.dumps(
    {"size": 15, "lastModifiedDateTime": "2023-11-15T06:13:20Z"}).encode()
ok, msg = S.run(od_cfg(), CACHE, BOOKS)
chk("OneDrive：远端更新 → 走 item 元数据判先后，取回来",
    ok and "取回 1" in msg and open(READSTAT, "rb").read() == b'{"v":"cloud"}',
    (ok, msg, open(READSTAT, "rb").read()))
chk("OneDrive：没有往 Graph 发 PUT",
    not any("/content" in u for u in tr.urls("PUT")), tr.urls("PUT"))
chk("OneDrive：元数据地址是不带 /content 的那条",
    tr.urls("GET")[:1] == [ITEM_URL] or ITEM_URL in tr.urls("GET"), tr.urls("GET"))

tr = Transport()
S._http = tr
put(READSTAT, '{"v":"mine"}', T0 + 99999)
tr.remote[CONTENT_URL] = b'{"v":"cloud"}'
tr.reply[ITEM_URL] = json.dumps(
    {"size": 15, "lastModifiedDateTime": "2023-11-15T06:13:20Z"}).encode()
ok, msg = S.run(od_cfg(), CACHE, BOOKS)
chk("OneDrive：本机更新 → 照旧上传（老规矩没变）",
    ok and "上传 1" in msg and open(READSTAT, "rb").read() == b'{"v":"mine"}',
    (ok, msg))

tr = Transport()
S._http = tr
put(READSTAT, '{"v":"local"}', T0)
tr.remote[CONTENT_URL] = b'{"v":"cloud"}'
tr.raise_on[ITEM_URL] = (404, b"")
ok, msg = S.run(od_cfg(), CACHE, BOOKS)
chk("OneDrive：item 元数据 404 / 认不出 → 退回上传",
    ok and "上传 1" in msg, (ok, msg))

# ─────────────────────────── 离线接线 ───────────────────────────
SRC = open(os.path.join(ROOT, "sync.py"), encoding="utf-8").read()
chk("接线：run 里确实走了 _dav_meta / _ms_meta 这条判据",
    "_dav_meta if webdav else _ms_meta" in SRC and "meta[\"mtime\"] > local_mtime + 1" in SRC)
chk("接线：取回远端那份之后会 settle 修改时间",
    "_settle_mtime(local, meta.get(\"mtime\"))" in SRC)

S._http = ORIG_HTTP
print()
print("云同步取新体检：" + ("全部通过" if not FAIL else "%d 项未过：%s" % (len(FAIL), FAIL)))
sys.exit(1 if FAIL else 0)
