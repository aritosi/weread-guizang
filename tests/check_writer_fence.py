#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作 / 便签那一屏的「围栏代码块」判据，必须和后端导出那把尺子（md_fence.py）逐条一致。

为什么要单开这一条：写作平台的正文在界面上由 `ui.html` 的 `wrParse` 就地渲染（编辑要即时
反馈，不能每敲一下问一趟后端），而导出 EPUB / PDF / Markdown 走的是 `book_export.md_to_html`
→ `md_fence`。**同一个状态机有两份实现**，就是《架构与模块地图》里点名的「抄两份就会在
CommonMark 边角上慢慢走散」。走散的后果不是不好看：

  · `~~~` 起的围栏：导出是代码块，编辑时把里面的 `# 注释` 当真标题渲染；
  · ` ``` a`b `（反引号信息串里还有反引号）按 CommonMark 只是正文，旧写法却当开栏，
    把后面真正的标题一路吞进 `<pre>`；
  · 收围栏不比长度 / 不比字符，短一行或另一种字符也能把块收掉；
  · 计数落单一次，后面整篇都成了「代码里」，反斜杠转义不再抽取。

而存盘是拿编辑器里那份 DOM 序列化回 Markdown 的 —— 编辑时判错的结构会**写回磁盘**，所以
这条盯的是「丢稿」那一类最坏的 bug。2026-10-19 实测：修之前 24 个夹具里 3 个与导出逐字
不同（tilde / bt_in_info / shorter_close）。

口径：`wrParse` 与 `md_to_html` 的输出**逐字节相同**（围栏这一段两边本就该一字不差）；
`wrFenceMark` 与 `md_fence.fence_mark` 对同一行给出同一个三元组。要 node（与内联 JS 那两条
同一档），不联网、不起服务、不开浏览器，归 --fast 静态段。
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import selftest  # noqa: E402

ROOT = selftest.REPO
sys.path.insert(0, str(ROOT))

import book_export  # noqa: E402
import md_fence  # noqa: E402

checks = []


def chk(name, ok, extra=""):
    checks.append((bool(ok), name, "" if ok else str(extra)[:400]))
    print(("  ok  " if ok else " FAIL ") + name + ("" if ok else "  <- " + str(extra)[:400]))


# ── 把编辑器那一段 JS 原样抽出来交给 node ────────────────────────────────
# 起止用两句稳定的注释 / 常量当锚：抽不到就当场红，绝不「抽了个空的还一路绿」。
START = "const WRE = {"
END = "/* ── 反向：编辑器里那一片 HTML"


def editor_js():
    src = (ROOT / "ui.html").read_text(encoding="utf-8")
    if src.count(START) != 1 or src.count(END) != 1:
        sys.exit("ui.html 里的两个抽取锚点不再各只有一处（START=%d / END=%d）——"
                 "改了那段结构就顺手改这条门禁的锚点。"
                 % (src.count(START), src.count(END)))
    a, b = src.index(START), src.index(END)
    if a >= b:
        sys.exit("ui.html 里两个锚点的顺序反了，抽不出编辑器那一段")
    return src[a:b]


DOCS = [
    ("标准反引号围栏（带语言串）", "```python\nprint(1)\n```\n\n# 标题\n"),
    ("标准反引号围栏（无语言串）", "```\ncode\n```\n"),
    ("波浪号围栏：导出是代码块，不许把里面的 # 当标题",
     "~~~\n# 不是标题\n**粗**\n~~~\n\n# 真标题\n"),
    ("长波浪号围栏 + 块内短波浪号不算收尾", "~~~~~\na\n~~~\nb\n~~~~~\n"),
    ("反引号信息串里还有反引号：按 CommonMark 只是正文",
     "``` a`b\n# 真标题\n"),
    ("收围栏不短于开头：短一行收不掉", "````\ncode\n```\nstill code\n````\n\nafter\n"),
    ("收围栏不同字符：收不掉", "```\ncode\n~~~\nmore\n```\n"),
    ("一直等不到收围栏：吃到文末", "```\nnever closed\n# 标题在里面\n"),
    ("围栏最多缩进三格", "   ```js\n   a\n   ```\n"),
    ("四格缩进是缩进代码块，不是围栏", "    ```js\na\n"),
    ("收围栏后面只许有空白", "```\nx\n```   \n\nafter\n"),
    ("收围栏后面有别的东西不算收尾", "```\nx\n``` not a close\nmore\n```\n"),
    ("反引号围栏里放波浪号", "```\n~~~\n```\n\nafter\n"),
    ("波浪号围栏里放反引号", "~~~\n```\n# 在里面\n```\n~~~\n"),
    ("正文里的反斜杠转义照旧抽取", "\\# 不是标题\n\\*不是列表\n"),
    ("代码块里的反斜杠是字面量", "```\n\\# 代码里的反斜杠\n```\n"),
    ("块级语法全家桶", "# H1\n\npara **bold** and *ital* and ~~strike~~\n\n- a\n- b\n\n"
                    "1. x\n\n> quote\n\n---\n\n| a | b |\n| --- | :---: |\n| 1 | 2 |\n\n"
                    "- [ ] todo\n- [x] done\n"),
    ("行内码夹着反斜杠", "use `a\\b` here and `x` there\n"),
    ("CRLF 先归一", "# T\r\n\r\n```\r\ncode\r\n```\r\n"),
    ("空文档", ""),
    ("只有一行开栏、没有收栏", "```\n"),
    ("语言串里的尖括号按文本转义", "```a<b\nx\n```\n"),
    ("段落紧接着围栏", "para\ncontinues\n```\nx\n```\n"),
    ("文末没有换行的未收围栏", "```\ncode"),
]

LINES = [
    "```", "```python", "~~~", "~~~~~", "   ```", "    ```", "\t```",
    "``` a`b", "````", "``` ", "```   ", "``` not a close", "~~", "```x`",
    "text", "", "# 标题", "> quote", "---", "`inline`", "``", "~~~ ~~~",
    "  ~~~~ ", "```\t", "``  ``",
]


def main():
    chunk = editor_js()
    if "function wrParse(" not in chunk or "function wrFenceMark(" not in chunk:
        sys.exit("抽出来的那一段里没有 wrParse / wrFenceMark —— 锚点选错了")

    work = pathlib.Path(tempfile.mkdtemp(prefix="gz-wrfence-"))
    try:
        harness = chunk + """
const fs = require("fs");
const fix = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
// 老写法（行首三反引号就翻转的简单开关）：只用来当「这条门禁真的会咬」的对照。
function wrOldMask(lines) {
  const mask = [];
  let fenced = false;
  for (let i = 0; i < lines.length; i++) {
    const s = lines[i];
    if (String(s).trim().slice(0, 3) === "```") { fenced = !fenced; mask.push(true); continue; }
    mask.push(fenced);
  }
  return mask;
}
process.stdout.write(JSON.stringify({
  parse: fix.docs.map(d => wrParse(d)),
  marks: fix.lines.map(l => wrFenceMark(l)),
  old: fix.oldDocs.map(d => wrOldMask(String(d).split("\\n"))),
  now: fix.oldDocs.map(d => wrFenceMask(String(d).split("\\n"))),
}));
"""
        js_path = work / "harness.js"
        js_path.write_text(harness, encoding="utf-8")
        fix_path = work / "fixtures.json"
        old_docs = [d for _n, d in DOCS if "~" in d or "`" in d]
        fix_path.write_text(json.dumps({"docs": [d for _n, d in DOCS],
                                        "lines": LINES,
                                        "oldDocs": old_docs}, ensure_ascii=False),
                            encoding="utf-8")
        node = shutil.which("node")
        if not node:
            sys.exit("这条门禁要 node（与内联 JS 那两条同一档），当前 PATH 里没有")
        proc = subprocess.run([node, str(js_path), str(fix_path)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit("node 跑不起来：%s" % (proc.stderr or proc.stdout)[:600])
        got = json.loads(proc.stdout)

        # ── A. 一边一行：围栏形状判据与 md_fence.fence_mark 同一个三元组 ──
        for line, js in zip(LINES, got["marks"]):
            py = md_fence.fence_mark(line)
            want = None if py is None else {"ch": py[0], "run": py[1], "info": py[2]}
            chk("fence_mark(%r) 两边一致" % line, js == want,
                "js=%r py=%r" % (js, want))

        # ── B. 整篇：编辑器渲染与导出逐字节相同 ──
        for (name, md), js in zip(DOCS, got["parse"]):
            py = book_export.md_to_html(md)
            chk("渲染一致：%s" % name, js == py,
                "js=%r\n     py=%r" % (js[:400], py[:400]))

        # 波浪号围栏这一条单独点名：告的是「把代码里的 # 当成了标题」。
        t = got["parse"][2]
        chk("波浪号围栏渲染成 <pre> 而不是标题", "<pre><code>" in t and "<h1>不是标题</h1>" not in t, t[:300])

        # ── C. 对照：老写法在这几张夹具上确实判得不同（门禁不是摆设） ──
        diff = [i for i, (o, n) in enumerate(zip(got["old"], got["now"])) if o != n]
        chk("对照：老写法与现行判据在这些夹具上确实不同", bool(diff),
            "oldDocs 里没有一份两种判据不同的，说明对照失效")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    bad = [c for c in checks if not c[1]]
    print("\n写作围栏对齐门禁：%d 项通过，失败 %d 项" % (len(checks) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
