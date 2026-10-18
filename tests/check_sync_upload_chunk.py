# -*- coding: utf-8 -*-
"""OneDrive 大文件上传会话：分片必须是 320 KiB 的整数倍（sync._ms_put_large）。

为什么单开一条
    `tests/check_sync.py` / `check_sync_json.py` / `check_sync_atomic.py` 分别钉的是
    两条通道的收尾、从网络那头收回来的 JSON 形状、以及落盘那一段。它们都没量过
    **分段本身的大小** —— 而那正好是 Graph 上传会话唯一的硬约束：

      微软官方文档（driveitem-createuploadsession）原话：
        “Use a byte range size that is a multiple of 320 KiB (327,680 bytes).
         Failing to use a fragment size that is a multiple of 320 KiB can result in
         large file transfers failing after the last byte range is uploaded.”

    `_ms_put_large` 原先写 `chunk = 6 * 1024 * 1024`（6,291,456 字节），除
    327,680 得 19.2 —— **除不尽**。于是任何大于 4 MiB 的整份文件（带插图的整本书、
    EPUB、Anki 卡包）每一段都传完了，却在提交最后那一段时失败：用户看到「失败 1」，
    远端一本也没上去；而小文件（走简单上传那一档，不受这条规矩管）一切正常，
    所以这个毛病只在真有大书进云盘时才现形。

这一条钉住
  · **常量**：`sync.UPLOAD_CHUNK` 是 327,680 的整数倍，且落在官方建议的 5–10 MiB；
  · **对照（不是空转）**：拿假的 Graph 上传会话按上面那条规矩判分片，旧值 6 MiB
    当场 416（它确实除不尽），证明这条门禁量得到东西；
  · **真分块**：喂一份比一个分片大的字节，每一段（最后一段除外）的跨距都是
    327,680 的整数倍、区间首尾相接覆盖整份、拼回来逐字节相同；
  · **接线**：> 4 MiB 走上传会话、正好 4 MiB 仍走简单上传（别把门槛挪了）。

不联网、不起服务、不碰真实 cache / 书库，归静态段，--fast 也得带上。
"""
import io
import json
import os
import re
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import sync as S  # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


MIB = 1024 * 1024
CHUNK_RULE = 327680          # 320 KiB，Graph 写死的那条


class FakeResponse:
    def __init__(self, data=b""):
        self._data = data

    def read(self, *_a):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class GraphUpload:
    """假的 upload session：按官方那条 320 KiB 规矩判分片，并记下每次 PUT。

    它只认「顺序完整覆盖」的字节区间，非最后一段跨距除不尽 320 KiB 就回 416 ——
    这正是真 Graph 的做派（`_ms_put_large` 收到 HTTPError 会带异常出去）。
    """

    def __init__(self, total):
        self.total = total
        self.url = "https://upload.example/session"
        self.puts = []
        self.next = 0

    def __call__(self, method, url, data=None, headers=None, timeout=60):
        headers = headers or {}
        if method == "POST":
            return FakeResponse(json.dumps({"uploadUrl": self.url}).encode())
        m = re.match(r"bytes (\d+)-(\d+)/(\d+)\Z", headers.get("Content-Range", ""))
        if not m:
            raise urllib.error.HTTPError(url, 416, "bad range", None, io.BytesIO(b""))
        start, end, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
        span = end - start + 1
        if total != self.total or start != self.next or span <= 0:
            raise urllib.error.HTTPError(url, 416, "bad range", None, io.BytesIO(b""))
        if len(data or b"") != span:
            raise urllib.error.HTTPError(url, 400, "length mismatch", None, io.BytesIO(b""))
        # 官方规矩：最后一片可以不是整数倍，其余必须正好 320 KiB 的整数倍
        if end + 1 < total and span % CHUNK_RULE != 0:
            raise urllib.error.HTTPError(
                url, 416, "fragment not multiple of 320 KiB", None, io.BytesIO(b""))
        self.puts.append((start, end, data))
        self.next = end + 1
        return FakeResponse(b"")


ORIG_HTTP = S._http
ORIG_HEADERS = S._ms_headers
ORIG_LARGE = S._ms_put_large
ORIG_CHUNK = S.UPLOAD_CHUNK

try:
    # ── 1. 常量本身 ───────────────────────────────────────────────
    chk("常量：UPLOAD_CHUNK 是 320 KiB 的整数倍",
        S.UPLOAD_CHUNK % CHUNK_RULE == 0, S.UPLOAD_CHUNK)
    chk("常量：落在官方建议的 5–10 MiB（且大于简单上传 4 MiB 门槛）",
        5 * MIB <= S.UPLOAD_CHUNK <= 10 * MIB and S.UPLOAD_CHUNK > 4 * MIB,
        S.UPLOAD_CHUNK)
    chk("对照：旧值 6 MiB 除不尽 320 KiB（旧写法确实违反那条硬规矩）",
        (6 * MIB) % CHUNK_RULE != 0, (6 * MIB) % CHUNK_RULE)

    # ── 2. 同一份字节，旧值撞 416、新值全过 ────────────────────────
    blob = (b"guizang-sync-payload-0123456789abcdef" * ((3 * 6 * MIB + 1000) // 36 + 1))[
        :3 * 6 * MIB + 1000]
    S._ms_headers = lambda c: {}                    # 不碰令牌与网络

    S.UPLOAD_CHUNK = 6 * MIB                        # 把旧写法搬回来当对照
    old = GraphUpload(len(blob))
    S._http = old
    raised = None
    try:
        S._ms_put_large({}, "books/big.bin", blob)
    except Exception as e:                          # noqa: BLE001
        raised = e
    chk("对照：旧分片 6 MiB 在假 Graph 上确实 416（门禁不空转）",
        isinstance(raised, urllib.error.HTTPError) and raised.code == 416 and not old.puts,
        (type(raised).__name__, getattr(raised, "code", None), len(old.puts)))

    S.UPLOAD_CHUNK = ORIG_CHUNK
    new = GraphUpload(len(blob))
    S._http = new
    err = None
    try:
        S._ms_put_large({}, "books/big.bin", blob)
    except Exception as e:                          # noqa: BLE001
        err = e
    chk("新分片：整份传完不抛（没有在最后一段才失败）", err is None, err)
    spans = [e - s + 1 for s, e, _d in new.puts]
    spans = spans or [0]
    chk("新分片：每一段（末段除外）跨距都是 320 KiB 的整数倍",
        all(sp % CHUNK_RULE == 0 for sp in spans[:-1]), spans)
    chk("新分片：区间首尾相接、覆盖整份字节",
        new.next == len(blob) and new.puts and new.puts[0][0] == 0
        and all(new.puts[i][1] + 1 == new.puts[i + 1][0]
                for i in range(len(new.puts) - 1)), (new.next, len(blob), len(new.puts)))
    chk("新分片：拼回来逐字节等于原件",
        b"".join(d for _s, _e, d in new.puts) == blob, len(new.puts))

    # ── 3. 接线：> 4 MiB 走上传会话，正好 4 MiB 仍走简单上传 ────────
    seen = []
    S._ms_put_large = lambda c, path, b: seen.append(len(b))
    S._http = lambda *a, **k: FakeResponse(b"")
    S._ms_put({}, "books/x.bin", b"x" * (4 * MIB + 1))
    chk("接线：大于 4 MiB 交给上传会话", seen == [4 * MIB + 1], seen)
    S._ms_put({}, "books/x.bin", b"x" * (4 * MIB))
    chk("接线：正好 4 MiB 仍走简单上传（门槛没被顺手挪动）",
        seen == [4 * MIB + 1], seen)
finally:
    S._http = ORIG_HTTP
    S._ms_headers = ORIG_HEADERS
    S._ms_put_large = ORIG_LARGE
    S.UPLOAD_CHUNK = ORIG_CHUNK

print()
print("OneDrive 上传分片体检：" + ("全部通过" if not FAIL else "%d 项未过：%s" % (len(FAIL), FAIL)))
sys.exit(1 if FAIL else 0)
