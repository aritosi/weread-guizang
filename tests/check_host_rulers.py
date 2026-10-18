#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内网地址闸门·两把尺子同一份归一，以及 `evil.localhost` 不再算公网。

为什么要单开一条
    `clip_article.py` 里有两把主机名尺子，判的都是「这一趟要不要替用户把请求发出去」：

      · `host_blocked`        —— 本机 / 内网一律拒（剪藏、内置浏览器、平台解析、封面兜底）；
      · `_loopback_host`      —— 只认「回环自己」，给插图下载与订阅取回留一条回环的口子
                                 （那两条路的离线夹具、用户本机的图床 / RSS 桥就在 127.0.0.1 上）。

    两把尺子的差别只该在**最后的判据**（`_ip_blocked` vs `.is_loopback`），
    「怎么把一个主机名归一成要判的那几个写法」必须逐字同一份：百分号解码、
    剥 IPv6 方括号、去结尾的点、IDNA 本名、老式 IPv4（`2130706433` / `127.1`）、
    IPv4 映射的 IPv6（`::ffff:127.0.0.1`）。原先这一段在两处各抄了一遍，docstring
    自己写着「逐句与 host_blocked 对齐」—— 改一边忘了另一边，就是同一个名字
    两种答案。现在归一到 `_host_candidates` / `_host_ip` 两个助手，两处共用。

    顺着这个不变式当场量出一处真漏（本条门禁的由来）：`*.localhost` 底下任何名字
    按 RFC 6761 §6.3 都是特殊名字、`getaddrinfo` 与浏览器一律回环，`_loopback_host`
    也早就认（`.endswith(".localhost")`），可 `host_blocked` 只靠一条按 `^localhost`
    加锚的正则 —— `localhost.localdomain` 挡住了，`evil.localhost` 却一路放行：
    `url_block_reason("http://evil.localhost:8770/api/state")` 回空串，剪藏 / 内置
    浏览器 / 平台解析 / 封面兜底四条路都会去敲本机自己那扇门。修法是把 localhost
    名字也收进共用助手 `_localhost_name`，两把尺子一起用。

这一条钉五面，全离线（只碰纯函数与 `ipaddress` / `socket`，不联网、不开浏览器、
不碰真实 cache/ 与书库），归 --fast 静态段：
    ① 接线：两个归一助手各只有一处定义，`host_blocked` 与 `_loopback_host` 都真的调它们；
    ② 真漏：`evil.localhost` / `.localhost` / 换身写法都拒，且给的是人话不是英文报错；
    ③ 不变式：回环 ⊂ 拒绝（`_loopback_host(h)` ⇒ `host_blocked(h)`），且
       `host_lan_blocked(h) == host_blocked(h) and not _loopback_host(h)`，逐条对着
       一族换身写法与一棵确定性枚举的语料验；
    ④ 对照：拿一把「只认字面量」的朴素回环尺子与旧那条 `BLOCKED_HOSTS` 正则做对照，
       语料里真的存在它们答错的名字（证明②③不是空转 —— 归一与这一档都是必要的）；
    ⑤ 认不出的输入只回布尔、绝不抛。
"""
import ipaddress
import pathlib
import random
import string
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import clip_article                                            # noqa: E402

FAIL = []
PASSED = 0


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + repr(extra)[:220]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


# 一族「字面不是回环、连的却是回环 / 内网」的换身写法：两把尺子必须都认得出。
# 每条的注释是 socket / getaddrinfo 真正会连到的地址（由各自归一那一步得出）。
TRICKY = [
    "127.0.0.1",
    "127.0.0.1.",                 # 结尾的点
    "LOCALHOST",                  # 大小写
    "localhost.",                 # 结尾的点
    "localhost",                  # localhost 本身
    ".localhost",                 # `.localhost` 底下（前导点也算同一个名字）
    "evil.localhost",             # *.localhost → 回环（RFC 6761 §6.3）
    "x.localhost",
    "sub.LOCALHOST",
    "%31%32%37.0.0.1",            # 百分号编码 → 127.0.0.1
    "%6c%6f%63%61%6c%68%6f%73%74",  # 百分号编码 → localhost
    "1²7.0.0.1",                  # IDNA 归一 → 127.0.0.1
    "lºcalhost",                  # IDNA 归一 → localhost
    "2130706433",                 # 老式 IPv4 → 127.0.0.1
    "0x7f000001",                 # 十六进制老式 IPv4
    "0177.0.0.1",                 # 八进制老式 IPv4
    "127.1",                      # 少写几段
    "::1",                        # IPv6 回环
    "[::1]",                      # 方括号包着
    "::ffff:127.0.0.1",           # IPv4 映射的 IPv6
    "[::ffff:127.0.0.1]",
    "0.0.0.0",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "169.254.169.254",            # 云元数据
    "100.64.0.1",                 # 运营商级 NAT
    "fe80::1",                    # 链路本地
    "fe80::1%eth0",               # 带 zone id
    "example.com",
    "1.1.1.1",
    "8.8.8.8",
    "172.32.0.1",                 # 172.16/12 之外，公网
    "11.0.0.1",                   # 10/8 之外，公网
]

# ── ① 接线：归一只有一处 ────────────────────────────────────────────────
SRC = (REPO / "clip_article.py").read_text(encoding="utf-8")
chk("_host_candidates / _host_ip / _localhost_name 各只有一处定义（归一只此一份）",
    all(SRC.count("def %s(" % n) == 1
        for n in ("_host_candidates", "_host_ip", "_localhost_name")),
    {n: SRC.count("def %s(" % n)
     for n in ("_host_candidates", "_host_ip", "_localhost_name")})
for fn in ("host_blocked", "_loopback_host"):
    body = SRC.split("def %s(" % fn, 1)[1].split("\ndef ", 1)[0]
    chk("%s 真的调了共用的归一 + localhost 名字（不是又抄了一份）" % fn,
        "_host_candidates(host)" in body and "_host_ip(" in body
        and "_localhost_name(" in body, body[:160])


# ── ② 真漏：`*.localhost` 与一族换身写法都必须拒，且给人话 ───────────────
for h in ("evil.localhost", "x.localhost", "sub.LOCALHOST", ".localhost"):
    chk("`*.localhost` 是本机自己，必须拒：%s" % h,
        clip_article.host_blocked(h) is True, clip_article.host_blocked(h))
    chk("`*.localhost` 的地址给你一句人话（不是英文报错）：%s" % h,
        "本机或内网" in clip_article.url_block_reason("http://%s:8770/api/state" % h),
        clip_article.url_block_reason("http://%s:8770/api/state" % h))

# 对照：旧那条只有 `^localhost` 加锚的正则确实认不出 `evil.localhost`
# （它就是这一档漏出去的原因；`localhost.localdomain` 被挡住纯属那条正则的前缀恰好命中）。
chk("对照：旧正则认不出 `evil.localhost`（这一档原先就漏在这）",
    clip_article.BLOCKED_HOSTS.match("evil.localhost") is None,
    clip_article.BLOCKED_HOSTS.match("evil.localhost"))
chk("对照：`localhost.localdomain` 旧正则挡得住（所以「漏」不是全漏）",
    clip_article.BLOCKED_HOSTS.match("localhost.localdomain") is not None)
chk("修法：_localhost_name 认 `localhost` / `.localhost` / `evil.localhost`，不误伤 `evil-localhost.com`",
    all(clip_article._localhost_name(x)
        for x in ("localhost", ".localhost", "evil.localhost", "sub.localhost"))
    and not any(clip_article._localhost_name(x)
                for x in ("evil-localhost.com", "notlocalhost", "localhost.evil.com", "example.com")))


# ── ③ 不变式：回环 ⊂ 拒绝，且内网那把尺子的定义就是这个差集 ──────────────
def pair_ok(h):
    blocked = clip_article.host_blocked(h)
    loop = clip_article._loopback_host(h)
    lan = clip_article.host_lan_blocked(h)
    return (isinstance(blocked, bool) and isinstance(loop, bool) and isinstance(lan, bool)
            and (not loop or blocked)                 # 回环必然是「拒绝」的子集
            and lan == (blocked and not loop)), (blocked, loop, lan)  # 差集的定义本身


tricky_bad = [h for h in TRICKY if not pair_ok(h)[0]]
chk("不变式：%d 条换身写法逐条成立（回环 ⊂ 拒绝，内网那把尺子 = 差集）" % len(TRICKY),
    not tricky_bad, {h: pair_ok(h)[1] for h in tricky_bad[:5]})

# 确定性枚举的语料：短串（长度 0..16）按固定种子铺一批，覆盖点 / 冒号 / 方括号 /
# 百分号 / 连字符这些形状，再叠一批「编码 + 内网名」的拼接。不求「每条都好」，
# 只求两把尺子对任何一条都同归一。
rnd = random.Random(20261019)
ALPHA = string.ascii_lowercase + string.digits + ".:%[]-_"
CORPUS = set()
for _ in range(4000):
    CORPUS.add("".join(rnd.choice(ALPHA) for _ in range(rnd.randint(0, 16))))
for _ in range(400):
    CORPUS.add("%%%02X" % rnd.randrange(256) + rnd.choice(["127.0.0.1", "localhost", "192.168.1.1"]))
CORPUS |= {"", " ", "::", "%", "%%", "%2e", "..", "a" * 300, "1" * 40}

corpus_bad = [h for h in CORPUS if not pair_ok(h)[0]]
chk("不变式：%d 条确定性语料上两把尺子不分叉（失败 %d 条）" % (len(CORPUS), len(corpus_bad)),
    not corpus_bad, {h: pair_ok(h)[1] for h in corpus_bad[:5]})


# ── ④ 对照：两把旧尺子在语料里确实答错（②③不是空转）───────────────────
def _naive_loopback(h):
    """旧想像里的那种写法：不解编码、不归一、不认老式 IP、不认 `.localhost` 子域。"""
    s = str(h or "").strip().lower()
    return s in ("localhost", "::1", "[::1]") or s.startswith("127.")


disagree = [h for h in TRICKY if _naive_loopback(h) != clip_article._loopback_host(h)]
chk("对照：只认字面量的朴素回环尺子在语料里确实答错（归一不是可有可无）",
    len(disagree) >= 3, disagree[:6])


def _old_host_blocked(host):
    """旧判据：`BLOCKED_HOSTS` 正则 + IP 解析，没有 `_localhost_name` 那一档。"""
    cands = clip_article._host_candidates(host)
    if not cands:
        return True
    for cand in cands:
        if clip_article.BLOCKED_HOSTS.match(cand):
            return True
        ip = clip_article._host_ip(cand)
        if ip is None:
            continue
        m = ip.ipv4_mapped if ip.version == 6 else None
        if clip_article._ip_blocked(m if m is not None else ip):
            return True
    return False


newly = [h for h in TRICKY if clip_article.host_blocked(h) and not _old_host_blocked(h)]
chk("对照：新增的 localhost 名字那一档确实拦下了旧判据放行的名字",
    {"evil.localhost", "x.localhost", ".localhost"} <= set(newly), newly)


# ── ⑤ 认不出的输入只回布尔、绝不抛 ──────────────────────────────────────
WEIRD = [None, "", "   ", "-", "--1", "1_0.0.1", "9" * 5000, "127..0.1",
         "lº" * 200, "%", "%zz", "。[::1]", "\x00localhost", "１２７", "a" * 300]
thrown = []
for h in WEIRD:
    try:
        got = (clip_article.host_blocked(h), clip_article._loopback_host(h),
               clip_article.host_lan_blocked(h))
    except Exception as e:                        # noqa: BLE001 —— 就是来找它抛不抛
        thrown.append((h, "%s: %s" % (type(e).__name__, e)))
    else:
        if not all(isinstance(x, bool) for x in got):
            thrown.append((h, got))
chk("认不出的输入只回布尔、绝不抛（%d 条）" % len(WEIRD), not thrown, thrown[:5])

cand_bad = [h for h in WEIRD + TRICKY
            if not (isinstance(clip_article._host_candidates(h), tuple)
                    and all(isinstance(c, str) for c in clip_article._host_candidates(h)))]
chk("_host_candidates 只回字符串元组（认不出回空元组）", not cand_bad, cand_bad[:5])

ip_bad = []
for c in ("127.0.0.1", "::1", "fe80::1%eth0", "2130706433", "example.com",
          "1²7.0.0.1", "", "a" * 300, "%", "1.2.3.4.5"):
    got = clip_article._host_ip(c)
    if not (got is None or isinstance(got, (ipaddress.IPv4Address, ipaddress.IPv6Address))):
        ip_bad.append((c, got))
chk("_host_ip 只回 IP 或 None", not ip_bad, ip_bad)

print()
print("内网地址闸门·两把尺子同归一（含 `*.localhost`）：%d 项通过，失败 %d 项"
      % (PASSED, len(FAIL)))
for n in FAIL:
    print("  ✗ " + n)
sys.exit(1 if FAIL else 0)
