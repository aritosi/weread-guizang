# -*- coding: utf-8 -*-
"""批量贴标签的回执必须按真实篇数说，不能整批报「全贴上」。

用户路径：书架那一屏 `⋯` → 「给筛出的 N 篇贴同一张标签」→「贴上」。这一批是逐条发
`book.tag` 的，而下面三种情况都会让其中一部分（在有 Remote 的「我的书架」格里是大部分）
一条都没贴上：

  · 「我的书架」是混合源：微信书架里有、还没取回本机的书没有本地目录，`book.tag`
    回的是 `{"ok": false, "msg": "找不到这本书"}`（见 `uiBatchTag` 自己那条注释）；
  · 后端正好在换班 / 没在跑：`post` 是裸 `fetch`，当场 reject；
  · 某一次后端抛了异常：总兜底回 `{"ok": false, "msg": "这个操作没做成：…"}`。

旧写法把这些回包整个丢掉：

    for (const id of ids) await post('book.tag', {book: id, add: [t]}).catch(() => {});
    await afterLib(mod, '已给 ' + ids.length + ' 篇贴上「' + t + '」');

于是 30 篇里成了 5 篇也报「已给 30 篇贴上」—— 正是《开发规范》§4 那句「报错那句不能编」
要挡的形状：回执宣布的事与真实落地的事不是同一件。这一套离线钉住修好之后的形状：

  A 接线：`uiBatchTag` 走 `tagBatchRun` / `tagBatchReply`，旧那句整批报成的话不在。
  B 纯逻辑（node）：把 ui.html 里**真的**那两支抽出来，喂三组回包 ——
    全成说全成、部分成只报部分、一条都不成不许说成。
  C 对照：旧那句表达式拿同一组「3 篇成 2 篇」的回包跑一遍，确实报出「已给 3 篇」，
    免得这道闸被拿掉之后这条还在空转。
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = (ROOT / "ui.html").read_text(encoding="utf-8")

PASSED = 0
FAIL = []


def chk(name, ok, extra=""):
    global PASSED
    if ok:
        PASSED += 1
        print("  ok  " + name)
    else:
        FAIL.append(name)
        print(" FAIL " + name + ("  <- " + str(extra)[:300]))


def body(sig):
    """从 ui.html 里抠出某个函数**产品里那一份**的源码（到行首的 } 为止）。"""
    m = re.search(re.escape(sig) + r"\s*\{.*?\n\}", SRC, re.S)
    return m.group(0) if m else ""


run_src = body("async function tagBatchRun(ids, tag)")
reply_src = body("function tagBatchReply(total, ok, why, tag)")
batch_src = body("function uiBatchTag(mod)")

# ── A 接线：走这两支，旧那句整批报成的话不在 ──────────────────────
chk("A1 ui.html 里抽得到 tagBatchRun / tagBatchReply",
    bool(run_src) and bool(reply_src), (len(run_src), len(reply_src)))
chk("A2 uiBatchTag 走 tagBatchRun 数真实篇数",
    "tagBatchRun(ids, t)" in batch_src and "post('book.tag'" not in batch_src, batch_src[:200])
chk("A3 uiBatchTag 的回执走 tagBatchReply，不是写死的整批成功",
    "tagBatchReply(" in batch_src and "已给 ' + ids.length" not in batch_src, batch_src[:200])

# ── B/C node：真跑产品那两支 ──────────────────────────────────────
print()
print("── B 回执按真实篇数说（node 跑产品里那一份）──")
node = shutil.which("node")
if not node:
    print("SKIP  纯逻辑那一段：本机没有 node（这条不能算过，装了再跑）")
elif not (run_src and reply_src):
    chk("B0 能从 ui.html 里抽到两支函数", False, "抽不到函式体")
else:
    harness = """
let script = [];
function setScript(list) { script = list.slice(); }
async function post(action, extra) {
  const step = script.shift();
  if (step === 'throw') throw new Error('boom');
  return step;
}
""" + run_src + "\n" + reply_src + """
// ① 全成
setScript([{ok: true}, {ok: true}, {ok: true}]);
const all = await tagBatchRun(['a', 'b', 'c'], '待读');
const allMsg = tagBatchReply(all.total, all.ok, all.why, '待读');

// ② 三篇里成了两篇，中间那篇后端回「找不到这本书」
setScript([{ok: true}, {ok: false, msg: '找不到这本书'}, {ok: true}]);
const part = await tagBatchRun(['a', 'b', 'c'], '待读');
const partMsg = tagBatchReply(part.total, part.ok, part.why, '待读');

// ③ 连不上：post 当场 reject（裸 fetch 的形状）
setScript(['throw', 'throw']);
const none = await tagBatchRun(['a', 'b'], '待读');
const noneMsg = tagBatchReply(none.total, none.ok, none.why, '待读');

// ④ 失败回包里没有 msg：也要有个诚实的兜底，不许空着说成
setScript([{ok: false}, {ok: true}]);
const naked = await tagBatchRun(['a', 'b'], '待读');
const nakedMsg = tagBatchReply(naked.total, naked.ok, naked.why, '待读');

// ⑤ 对照：旧写法拿②那组回包跑一遍
setScript([{ok: true}, {ok: false, msg: '找不到这本书'}, {ok: true}]);
const ids = ['a', 'b', 'c'];
for (const id of ids) { try { await post('book.tag', {book: id, add: ['待读']}); } catch (e) {} }
const oldMsg = '已给 ' + ids.length + ' 篇贴上「待读」';

console.log(JSON.stringify({
  all: [all.total, all.ok, all.why, allMsg],
  part: [part.total, part.ok, part.why, partMsg],
  none: [none.total, none.ok, none.why, noneMsg],
  naked: [naked.total, naked.ok, naked.why, nakedMsg],
  oldMsg,
}));
"""
    try:
        out = subprocess.run([node, "-e", harness], capture_output=True, text=True,
                             timeout=30)
        got = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as e:
        got = {"err": "%s: %s | %s" % (type(e).__name__, e,
                                       (locals().get("out") and out.stderr) or "")}

    if "err" in got:
        chk("B0 抽出来的两支能在 node 里跑起来", False, got)
    else:
        all_r = got.get("all", [])
        part_r = got.get("part", [])
        none_r = got.get("none", [])
        naked_r = got.get("naked", [])
        chk("B1 全成：篇数照数、回执说「已给 3 篇贴上「待读」」",
            all_r == [3, 3, "", "已给 3 篇贴上「待读」"], all_r)
        chk("B2 部分成：只说「2/3」，并把后端那句原因带上",
            part_r[:3] == [3, 2, "找不到这本书"]
            and "2/3" in part_r[3] and "找不到这本书" in part_r[3]
            and "已给" not in part_r[3], part_r)
        chk("B3 一条都没成：不许出现「已给」，要有诚实兜底",
            none_r[:3] == [2, 0, "本机服务没答上来"]
            and "已给" not in none_r[3] and none_r[3].startswith("一篇都没贴上"), none_r)
        chk("B4 失败回包没带原因：也不许报成，兜底那句仍要出现",
            naked_r[:3] == [2, 1, "本机服务没答上来"] and "已给" not in naked_r[3], naked_r)
        chk("C1 对照：旧那句表达式真会把 2/3 报成「已给 3 篇」",
            got.get("oldMsg") == "已给 3 篇贴上「待读」", got.get("oldMsg"))

print()
if FAIL:
    print("批量贴标签回执门禁：失败 %d 项" % len(FAIL))
    for n in FAIL:
        print("  ✗ " + n)
    sys.exit(1)
print("批量贴标签回执：通过 %d 项，失败 0 项" % PASSED)
