#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安娜账本的「读—改—写」不再互相覆盖（anna_state 那把跨进程锁）。

为什么单开一条
    `tests/check_anna_atomic.py` 钉的是「账本会不会被写坏」——临时件同名时两份内容
    交织、或后一个 `os.replace` 当场 FileNotFoundError。这一条钉的是另一半：账本
    逐字节都很干净，但一次更新的读数被另一次盖掉了（lost update）。

    这条路上确实有两个写手：后端 `/api/anna` 的请求线程（`ThreadingHTTPServer`）与
    窗口子进程 `anna_browser`。两边都是「读整份 → 改一笔 → 写整份」，原子落盘只保证
    **单次落盘**完整，管不住这两次落盘之间的窗口。症状都是用户看得见的数字：

      · 窗口刚落一份下载（`caught +1`）同时界面点了搜索，后写的那次基于旧读数，
        「已接住 N 份」自己往回跳；
      · 窗口的 `drain` 与后端「补收」同时记 `seen` / `books`，先写的那本从「最近入库」
        里消失，`skipped` / `pending` 也会少记。

这一条钉住
  A. **对照（不是空转）**：把旧写法（读 → 栅栏 → 写，没有锁）在这里重抄一遍，
     两个线程各加 200，最终 `caught` 只等于 200 —— 旧写法确实丢更新；
  B. **新写法**：同一把栅栏，两个线程各 200 次 `counted(caught_delta=1)`，最终 400；
  C. **新写法**：`counted` 与 `_pending` 并行，`caught` 与 `skipped` 各自一个不少，
     `pending` 条数对得上（顶到上限为止）；
  D. **跨进程**：两个真进程各 `counted` 100 次，最终 `caught` 必须 200（`fcntl.flock`
     那一半；Windows 上没有 fcntl，那半条按 SKIP 说明白，不装绿）。

全离线、只碰临时目录，不联网、不开浏览器、不起服务，归 --fast 静态段。
"""
import atexit
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import anna_state as anna  # noqa: E402

SB = pathlib.Path(tempfile.mkdtemp(prefix="guizang-anna-lost-"))
atexit.register(lambda: shutil.rmtree(SB, ignore_errors=True))
DD = str(SB)

FAIL = []
PASSED = [0]


def chk(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("  ok  " + name)
    else:
        FAIL.append(name)
        print(" FAIL " + name + (("  <- " + repr(extra)[:220]) if extra else ""))


def reset():
    anna._atomic_write(anna.state_path(DD), anna._blank())


def caught():
    return anna.read_state(DD).get("caught")


def run_pair(worker, n):
    """两个线程同时跑 `worker(n, barrier)`；栅栏钉住每一轮的对齐点。回错误表。"""
    barrier = threading.Barrier(2)
    errs = []

    def one():
        try:
            worker(n, barrier)
        except BaseException as e:                       # 线程里的异常别把套件吞了
            errs.append("%s: %s" % (type(e).__name__, e))

    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    return errs


print("── A. 对照：旧写法（读 → 栅栏 → 写，没有锁）确实丢更新 ──────────")
NA = 200


def old_worker(n, barrier):
    for _ in range(n):
        st = anna.read_state(DD)                 # 两侧都读到同一份旧数
        barrier.wait(10)                         # 对齐：两边读完才允许往下写
        st["caught"] = anna._as_int(st.get("caught")) + 1
        anna._atomic_write(anna.state_path(DD), st)


reset()
errs_old = run_pair(old_worker, NA)
chk("A1 对照两线程都正常收工（栅栏没超时）", errs_old == [], errs_old)
chk("A2 对照：旧写法各加 200 只留下 200 —— 丢了一半增量（这条门禁不是空转）",
    caught() == NA, (caught(), NA * 2))

print("── B. 新写法：同一把栅栏，增量一次都不丢 ────────────────────")
NB = 200


def new_worker(n, barrier):
    for _ in range(n):
        barrier.wait(10)
        anna.counted(DD, {"caught_delta": 1})


reset()
errs_new = run_pair(new_worker, NB)
chk("B1 新写法两线程都正常收工", errs_new == [], errs_new)
chk("B2 新写法：各加 200，账上就是 400（锁把读—改—写串起来了）",
    caught() == NB * 2, (caught(), NB * 2))

print("── C. 新写法：计数与「没进书架」两笔一起记，各归各的 ──────────────")
NC = 40


def counter_worker(n, barrier):
    for _ in range(n):
        barrier.wait(10)
        anna.counted(DD, {"caught_delta": 1})


def pending_worker(n, barrier):
    for i in range(n):
        barrier.wait(10)
        anna._pending(DD, "没进来-%03d.pdf" % i, "格式不认", 2048)


barrier = threading.Barrier(2)
errs_mix = []


def _spawn(fn, n):
    def one():
        try:
            fn(n, barrier)
        except BaseException as e:
            errs_mix.append("%s: %s" % (type(e).__name__, e))
    return threading.Thread(target=one)


reset()
ts = [_spawn(counter_worker, NC), _spawn(pending_worker, NC)]
for t in ts:
    t.start()
for t in ts:
    t.join(120)
st = anna.read_state(DD)
chk("C1 caught 与 skipped 各自一个不少（两种改法并行也不互相盖）",
    st.get("caught") == NC and st.get("skipped") == NC,
    (st.get("caught"), st.get("skipped"), NC))
chk("C2 pending 条数顶到上限为止（新记的在前，一条没被抹）",
    len(st.get("pending") or []) == min(NC, anna.PENDING_KEEP),
    len(st.get("pending") or []))
chk("C3 并行期间没有异常穿出来", errs_mix == [], errs_mix)

print("── D. 跨进程：两个真进程各加 100，最终 200 ──────────────────")
ND = 100
CHILD = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import anna_state as anna\n"
    "n = int(sys.argv[3])\n"
    "for i in range(n):\n"
    "    anna.counted(sys.argv[2], {'caught_delta': 1})\n"
)
reset()
procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(REPO), DD, str(ND)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
         for _ in range(2)]
kids = []
for pr in procs:
    out, _ = pr.communicate(timeout=180)
    kids.append((pr.returncode, out[-200:]))
if anna.fcntl is None:
    # Windows 上没有 fcntl：这一半够不着，明确报 SKIP 而不是假装绿。
    print("  --  D1 SKIP：这套解释器没有 fcntl（Windows），跨进程那一半测不了")
    print("  --  D2 SKIP：同上")
else:
    chk("D1 两个真进程各加 100，最终 200（fcntl 锁那一半）",
        caught() == ND * 2, (caught(), ND * 2, kids))
    chk("D2 两个子进程都正常收工（异常没穿进子进程的输出里）",
        all(rc == 0 for rc, _ in kids), kids)

print()
print("安娜账本「读—改—写」体检：%d 项通过，失败 %d 项" % (PASSED[0], len(FAIL)))
for f in FAIL:
    print("  ✗ " + f)
sys.exit(1 if FAIL else 0)
