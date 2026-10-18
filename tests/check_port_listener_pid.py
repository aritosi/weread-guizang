#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谁在听这个端口：POSIX 上不许只押 `lsof` 一条命令。

`platform_compat.port_listener_pid` 是「旧后端自动接管 / 一键换班」那条链的第一问：
问不出 PID，`port_verdict` 就回不了 takeover / busy，只能判 stranger —— 端口上明明
是自己家的旧后端，界面却继续「后端没启动 / 新功能 404」。而 POSIX 这半段原先只跑
`lsof`：macOS 与多数 Linux 发版自带它，但容器、Alpine、只装了 iproute2 的精简系统
常常没有 —— 这时命令直接 FileNotFoundError，函数静默回 0，整条接管链当场瞎掉。

这一条把三件事钉住：
  1. 解析：lsof / ss / netstat 三种真实输出里各认得出本端口那个 PID，别的端口、
     非 LISTEN 行、v4+v6 重复行都不许认错；
  2. 顺序：先 lsof，问到就停；lsof 不在（或回空）才轮到 ss，再轮到 netstat；
     三条都没有才回 0 —— 认不出照旧回 0，绝不猜；
  3. 真机：真起一个只听本机的子进程，问出来的 PID 必须就是它；没人听的端口回 0。
全程离线、不开浏览器，归静态段。
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import platform_compat as pc  # noqa: E402

FAIL = []
PASSED = 0
SKIPPED = []


def chk(name, cond, extra=""):
    global PASSED
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   " + str(extra)[:300]))
    if cond:
        PASSED += 1
    else:
        FAIL.append(name)


def skip(name, why):
    print("SKIP  %s   %s" % (name, why))
    SKIPPED.append(name)


# ── 1. 三种输出的解析 ────────────────────────────────────────────
SS = """State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
LISTEN 0      5          127.0.0.1:46641      0.0.0.0:*    users:(("python",pid=2,fd=3))
LISTEN 0      128        0.0.0.0:22           0.0.0.0:*    users:(("sshd",pid=777,fd=3))
LISTEN 0      128        [::1]:46641          [::]:*       users:(("python",pid=2,fd=4))
"""
NS = """Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 127.0.0.1:46641         0.0.0.0:*               LISTEN      2/python
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      777/sshd
tcp        0      0 127.0.0.1:9             0.0.0.0:*               ESTABLISHED -
tcp6       0      0 [::1]:46641             :::*                    LISTEN      2/python
"""

chk("lsof 输出取第一个 PID", pc._pids_from_lsof("2\n", 46641) == [2])
chk("lsof 输出里非数字一律不认", pc._pids_from_lsof("2\nnot-a-pid\n", 46641) == [2])
chk("ss 逐行认端口：只捞本端口那条", pc._pids_from_ss(SS, 46641) == [2],
    pc._pids_from_ss(SS, 46641))
chk("ss 认得出另一条（22 端口）", pc._pids_from_ss(SS, 22) == [777])
chk("ss：v4 / v6 两行同一个 pid 去重", pc._pids_from_ss(SS, 46641) == [2])
chk("ss：没有这个端口就回空（表头那一行也不误认）", pc._pids_from_ss(SS, 1) == [])
chk("netstat 认 `PID/程序名` 那一列", pc._pids_from_netstat(NS, 46641) == [2],
    pc._pids_from_netstat(NS, 46641))
chk("netstat：ESTABLISHED 行不算监听（不许认到 `-` 上当 PID）",
    pc._pids_from_netstat(NS, 9) == [])
chk("netstat：v4 / v6 两行同一个 pid 去重", pc._pids_from_netstat(NS, 46641) == [2])
chk("netstat：没有这个端口就回空", pc._pids_from_netstat(NS, 1) == [])


def _stub(by_name, missing=()):
    """把 subprocess.run 换成一条按命令名发牌、并记下调用顺序的假实现。

    by_name：`{"lsof": "…stdout…"}`；missing 里的命令当成「系统里没装」——
    真实现是 FileNotFoundError，这里照同一个异常抛。
    """
    calls = []

    def fake(argv, **kw):
        name = argv[0]
        calls.append(name)
        if name in missing:
            raise FileNotFoundError(2, "No such file or directory", name)

        class R:
            stdout = by_name.get(name, "")
        return R()

    return fake, calls


# ── 2. 顺序：先 lsof，问到就停；缺了才兜底 ──────────────────────
# 这一段是 POSIX 那条链（Windows 走 netstat -ano 的独立分支，不在这条路上）：
# 把 IS_WIN 按成 False，在任何机器上都能把「lsof → ss → netstat」这段逻辑跑一遍。
_pc_win = pc.IS_WIN
pc.IS_WIN = False
fake, calls = _stub({"lsof": "2\n", "ss": SS, "netstat": NS})
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("lsof 答得出就用 lsof 的（顺序第一）", got == 2, got)
chk("lsof 答得出时不再问 ss / netstat", calls == ["lsof"], calls)

fake, calls = _stub({"ss": SS, "netstat": NS}, missing=("lsof",))
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("对照：lsof 不在时由 ss 兜底（旧写法在这里回 0）", got == 2, got)
chk("ss 答得出时不再问 netstat", calls == ["lsof", "ss"], calls)

fake, calls = _stub({"netstat": NS}, missing=("lsof", "ss"))
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("lsof / ss 都不在时由 netstat 兜底", got == 2, got)
chk("三条命令按 lsof → ss → netstat 依次问", calls == ["lsof", "ss", "netstat"], calls)

fake, calls = _stub({"lsof": "", "ss": "", "netstat": ""})
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("三条都问了但谁都没认出 → 回 0（宁可不动，也不猜着杀）", got == 0, got)

fake, calls = _stub({}, missing=("lsof", "ss", "netstat"))
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("三条命令都不在（精简系统）→ 回 0，不抛", got == 0, got)

# lsof 装是装了、却认不出（比如那个端口被别的用户听着）：还得往下问，不许就此判死。
fake, calls = _stub({"lsof": "", "ss": SS, "netstat": NS})
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(46641)
chk("lsof 在但答不出时，继续往 ss 问（不是回 0 就完）", got == 2 and calls == ["lsof", "ss"],
    (got, calls))

# 别的端口：假输出里 22 有、46641 没有，问 22 必须给 777 而不是 2。
fake, _calls = _stub({"lsof": "", "ss": SS})
with mock.patch.object(pc.subprocess, "run", fake):
    got = pc.port_listener_pid(22)
chk("问哪个端口给哪个端口的 PID（不串行）", got == 777, got)
pc.IS_WIN = _pc_win            # 这一段借完就还回去，真机那一段还得按本机来


# ── 3. 真机：子进程真听一个端口，问出来的就是它的 PID ─────────────
CHILD = r"""
import os, socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(5)
print("%d %d" % (s.getsockname()[1], os.getpid()), flush=True)
while True:
    time.sleep(1)
"""

tools = [t for t in ("lsof", "ss", "netstat") if shutil.which(t)]
if pc.IS_WIN:
    # Windows 上走的是 netstat -ano 那一套列序，输出形状与本条里的 ss / Linux
    # netstat 不是一个格式；真机那半留给 Windows 自己的门禁，这里不硬凑。
    skip("真机：起一个只听本机的子进程，问出它的 PID", "Windows 走 netstat -ano 另一条分支")
elif not tools:
    skip("真机：起一个只听本机的子进程，问出它的 PID", "lsof / ss / netstat 一个都没装")
else:
    proc = subprocess.Popen([sys.executable, "-c", CHILD],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        head = (proc.stdout.readline() or "").split()
        port, child_pid = int(head[0]), int(head[1])
        got = 0
        for _ in range(20):
            got = pc.port_listener_pid(port)
            if got:
                break
            time.sleep(0.15)
        chk("真机：起一个只听本机的子进程，问出它的 PID（本机可用工具：%s）"
            % ",".join(tools), got == child_pid, (got, child_pid))
        # 没人听的端口：回 0，不是回上一个答案。
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        free_port = free.getsockname()[1]
        free.close()
        chk("真机：没人听的端口回 0", pc.port_listener_pid(free_port) == 0,
            pc.port_listener_pid(free_port))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


print()
if FAIL:
    print("端口监听者（lsof → ss → netstat）：%d 项通过，失败 %d 项" % (PASSED, len(FAIL)))
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
extra = ("；跳过 %d 项" % len(SKIPPED)) if SKIPPED else ""
print("端口监听者（lsof → ss → netstat）：%d 项通过，失败 0 项%s" % (PASSED, extra))
