#!/usr/bin/env python3
"""Real Chromium UI acceptance using disposable backend data and WeRead fixtures.

Run with .build-desktop-venv/bin/python. --backend may point at a frozen
guizang-backend, so the same UI checks can run against the installed package.
Remote API and image responses are deterministic fixtures; writer data and
pointer interactions use the real application. Timing is observational only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import sys
import tempfile
import time
import traceback
import urllib.request
import zlib

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
def fixture_png():
    def chunk(kind, blob):
        return struct.pack("!I", len(blob)) + kind + blob + struct.pack("!I", zlib.crc32(kind + blob) & 0xffffffff)
    width, height = 180, 270
    rows = b"".join(b"\0" + bytes((35 + y // 5, 95 + y // 3, 140)) * width for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


PNG = fixture_png()


def wait_for(fn, timeout=30):
    until = time.monotonic() + timeout
    last = None
    while time.monotonic() < until:
        try:
            result = fn()
            if result:
                return result
        except Exception as exc:
            last = exc
        time.sleep(.1)
    raise AssertionError("Timed out: %s" % last)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/macos/test-results/ui-optimizations")
    parser.add_argument("--browser-path", type=Path, default=ROOT / "dist/desktop/browsers")
    parser.add_argument("--baseline-ui", type=Path, help="Optional old HTML; run scrolling observations only, allowing baseline blank cards")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(args.browser_path.resolve())
    report = {"ok": False, "checks": {}, "scope": "Real Chromium, fixture WeRead network/images, real isolated writer API; timings are not universal guarantees."}
    process = None
    temp = tempfile.TemporaryDirectory(prefix="guizang-ui-acceptance-")
    log = (args.output / "backend.log").open("w")
    page = browser = None
    try:
        base = args.base_url
        if not base:
            ready = Path(temp.name) / "ready.json"
            env = {k: v for k, v in os.environ.items() if not k.startswith("GUIZANG_")}
            env["GUIZANG_DATA"] = str(Path(temp.name) / "data")
            command = ([str(args.backend.resolve()), "--desktop-server"] if args.backend else [sys.executable, str(ROOT / "ui_server.py")])
            if args.backend:
                env = {k: v for k, v in env.items() if not k.startswith(("PYTHON", "DYLD_", "PLAYWRIGHT_")) and k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            process = subprocess.Popen(command + ["--port", "0", "--ready-file", str(ready)], cwd="/" if args.backend else ROOT, env=env, stdout=log, stderr=log)
            info = wait_for(lambda: json.loads(ready.read_text()), 90)
            base = "http://127.0.0.1:%s" % info["port"]
        base = base.rstrip("/")
        report["base_url"] = base
        report["backend_executable"] = str(args.backend.resolve()) if args.backend else sys.executable
        report["backend_working_directory"] = "/" if args.backend else str(ROOT)
        with urllib.request.urlopen(base + "/", timeout=10) as response:
            report["served_ui_sha256"] = hashlib.sha256(response.read()).hexdigest()

        def api(path="/api/writer", data=None):
            headers = {"Origin": base}
            if data is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(base + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)

        # Real backend writes, exclusively under the temporary data root.
        drafts = [api(data={"do": "create", "title": "Acceptance article %d" % i, "text": "# Article %d\n\nOriginal body %d." % (i, i)})["id"] for i in range(4)]
        books = [api(data={"do": "book.create", "title": "Acceptance book %d" % i})["book"]["id"] for i in range(2)]
        assert api(data={"do": "book.add", "book": books[0], "chapter": drafts[0]})["ok"]
        shelf = [{"bookId": str(100000 + i), "title": "Shelf fixture %03d" % i, "author": "Acceptance", "cover": "https://fixture.invalid/cover/%d.png" % i} for i in range(600)]
        image_hits, requests, errors, moves, fallback_hits = [], [], [], [], []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            report["browser_version"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda req: moves.append(req.post_data_json) if req.url.endswith("/api/writer") and req.method == "POST" and (req.post_data_json or {}).get("do") == "book.move" else None)

            def route_network(route):
                request = route.request
                if args.baseline_ui and request.url.rstrip("/") == base:
                    route.fulfill(status=200, content_type="text/html", body=args.baseline_ui.read_text())
                elif request.url.endswith("/api/state"):
                    response = route.fetch()
                    state = response.json()
                    state.setdefault("weread", {})["key_set"] = True
                    if args.baseline_ui:
                        version = re.search(r"(?:const|let)\s+GUIZANG_PAGE\s*=\s*['\"]([^'\"]+)", args.baseline_ui.read_text())
                        if version:
                            state["version"] = version.group(1)
                        state["code_disk"] = state.get("code", "")
                    route.fulfill(response=response, json=state)
                elif request.url.endswith("/api/weread"):
                    op = request.post_data_json["api_name"]
                    requests.append(op)
                    if op == "/shelf/sync":
                        payload = {"books": shelf, "albums": []}
                    elif op == "/book/recommend":
                        payload = {"books": shelf[:6]}
                    elif op == "/book/similar":
                        payload = {"books": shelf[6:12]}
                    elif op == "/store/search":
                        payload = {"results": [{"books": [{"bookInfo": row} for row in shelf[20:32]]}]}
                    else:
                        payload = {}
                    route.fulfill(json={"ok": True, "data": payload})
                elif "fixture.invalid/cover/" in request.url:
                    image_hits.append(request.url)
                    number = int(re.search(r"/cover/(\d+)\.png", request.url).group(1))
                    if number % 3 == 1:
                        route.fulfill(status=403, body="Fixture CDN requires a trusted origin")
                    else:
                        route.fulfill(status=200, content_type="image/png", body=PNG)
                elif "/api/cover?" in request.url:
                    fallback_hits.append(request.url)
                    route.fulfill(status=200, content_type="image/png", body=PNG)
                elif not request.url.startswith(base):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", route_network)
            page.add_init_script("""window.__uiPerf={frames:[],longTasks:[],blankCards:[],samples:0,inspectedCards:0};
              try{new PerformanceObserver(list=>{for(const e of list.getEntries()) window.__uiPerf.longTasks.push(e.duration)}).observe({type:'longtask',buffered:true})}catch(_){}
              let last=0; function frame(t){const p=window.__uiPerf;
                if(p.record){if(last)p.frames.push(t-last);p.samples++;
                  const pane=document.querySelector('[data-pane="shelf"]:not([hidden])');
                  if(pane){const seen=new Set();for(let y=200;y<innerHeight;y+=180)for(let x=370;x<innerWidth;x+=160){
                    const c=document.elementFromPoint(x,y)?.closest('.wcard');if(!c||seen.has(c))continue;seen.add(c);p.inspectedCards++;
                    const s=getComputedStyle(c);if(Number(s.opacity)<.95||s.visibility==='hidden')p.blankCards.push({id:c.dataset.id,opacity:s.opacity})}}
                }last=p.record?t:0;requestAnimationFrame(frame)}requestAnimationFrame(frame);
            """)
            page.goto(base, wait_until="domcontentloaded")
            page.locator('#nav button[data-v="shelf"]').click()
            page.locator('[data-pane="shelf"] .wcard').first.wait_for()
            page.wait_for_timeout(500)
            first_count = page.locator('[data-pane="shelf"] .wcard').count()
            first_hits = len(image_hits)
            assert first_count < 600, first_count
            assert first_hits < first_count, (first_hits, first_count)
            report["checks"]["shelf_progressive_cards_and_lazy_covers"] = {"initial_cards": first_count, "initial_image_requests": first_hits, "total_fixture_books": 600}
            page.evaluate("window.__uiPerf.longTasks=[];window.__uiPerf.record=true")
            # Actual wheel input in both directions, crossing progressive load boundaries.
            page.mouse.move(1120, 650)
            for _ in range(35):
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(35)
            for _ in range(20):
                page.mouse.wheel(0, -1800)
                page.wait_for_timeout(35)
            page.wait_for_timeout(250)
            page.evaluate("window.__uiPerf.record=false")
            perf = page.evaluate("window.__uiPerf")
            intervals = sorted(perf["frames"])
            report["checks"]["shelf_bidirectional_scroll"] = {"visible_transparent_card_samples": len(perf["blankCards"]), "sampled_frames": perf["samples"], "inspected_cards": perf["inspectedCards"], "loaded_cards": page.locator('[data-pane="shelf"] .wcard').count(), "frame_interval_p95_ms": intervals[int(len(intervals)*.95)] if intervals else None, "frame_interval_max_ms": max(intervals, default=0), "long_tasks_ms": perf["longTasks"]}
            page.screenshot(path=str(args.output / "shelf.png"))
            if args.baseline_ui:
                report["baseline_ui"] = str(args.baseline_ui.resolve())
                report["ok"] = True
                return 0
            assert perf["inspectedCards"] > 0
            assert not perf["blankCards"], perf["blankCards"][:5]
            page.locator('#nav button[data-v="pick"]').click()
            pick = page.locator('[data-pane="pick"] .wcard img')
            pick.first.wait_for()
            page.wait_for_function("Array.from(document.querySelectorAll('[data-pane=pick] .wcard img')).length===6&&Array.from(document.querySelectorAll('[data-pane=pick] .wcard img')).every(im=>im.naturalWidth>0)")
            assert page.locator('[data-pane="pick"] .sgrid > *').count() == 6, "Recommendation skeleton cards remain after loading"
            report["checks"]["recommendation_covers"] = {"loaded": pick.count()}
            page.wait_for_timeout(700)
            page.screenshot(path=str(args.output / "recommendation.png"))
            page.set_viewport_size({"width": 1100, "height": 650})
            page.locator('#nav button[data-v="search"]').click()
            page.locator('#wrq').fill("Acceptance")
            page.locator('#wrgo').click()
            page.locator('#zbodyWr .wcard img').first.wait_for()
            page.wait_for_function("document.querySelector('#zbodyWr .wcard img').naturalWidth>0")
            last_image = page.locator('#zbodyWr .wcard img').last
            last_image.scroll_into_view_if_needed()
            page.wait_for_function("Array.from(document.querySelectorAll('#zbodyWr .wcard img')).every(im=>im.naturalWidth>0)")
            assert page.locator('#zbodyWr .sgrid > *').count() == 12
            assert page.locator('#zbodyWr').evaluate("el=>el.scrollTop") > 0
            report["checks"]["search_nested_scroll_covers"] = {"loaded": page.locator('#zbodyWr .wcard img').count(), "nested_scroll_top": page.locator('#zbodyWr').evaluate("el=>el.scrollTop")}
            assert fallback_hits, "The browser must recover fixture CDN 403 errors through the cover proxy"
            report["checks"]["cdn_403_proxy_fallback"] = {"successful_proxy_responses": len(fallback_hits)}
            page.wait_for_timeout(500)
            page.screenshot(path=str(args.output / "search.png"))
            page.set_viewport_size({"width": 1440, "height": 900})

            def row(did):
                return page.locator('#wrTree .wrdoc[data-id="%s"]' % did)

            def head(bid):
                return page.locator('#wrTree .wrtome[data-b="%s"] .wrtomeh' % bid)

            def drag(source, target, fraction=.5, cancel=False):
                source.scroll_into_view_if_needed()
                a = source.bounding_box()
                target.scroll_into_view_if_needed()
                b = target.bounding_box()
                page.mouse.move(a["x"] + a["width"]*.5, a["y"] + a["height"]*.5)
                page.mouse.down()
                page.mouse.move(a["x"] + a["width"]*.5 + 8, a["y"] + a["height"]*.5, steps=3)
                try:
                    page.wait_for_function("document.body.classList.contains('wrdragging')", timeout=3000)
                except Exception:
                    page.screenshot(path=str(args.output / "drag-start-failure.png"))
                    report["drag_start_failure"] = page.evaluate("""()=>({press:wrPress&&{connected:wrPress.row.isConnected,id:wrPress.row.dataset.id},busy:wrMoveBusy,dirty:WR.dirty,saving:WR.saving,at:document.elementFromPoint(%s,%s)?.outerHTML,body:document.body.className})""" % (a["x"] + a["width"]*.5, a["y"] + a["height"]*.5))
                    raise
                page.mouse.move(b["x"] + b["width"]*.45, b["y"] + b["height"]*fraction, steps=12)
                page.wait_for_timeout(75)
                if cancel:
                    page.dispatch_event("#wrTree", "pointercancel")
                page.mouse.up()
                page.wait_for_function("!document.body.classList.contains('wrdragging')")
                page.wait_for_timeout(200)

            def chapter_ids(bid):
                return [c["id"] for c in api("/api/writer?book=" + bid)["book"]["chapters"]]

            page.locator('#nav button[data-v="write"]').click()
            row(drafts[1]).wait_for()
            drag(row(drafts[1]), head(books[0]))
            wait_for(lambda: chapter_ids(books[0]) == drafts[:2])
            drag(row(drafts[1]), row(drafts[0]), .2)
            wait_for(lambda: chapter_ids(books[0]) == [drafts[1], drafts[0]])
            drag(row(drafts[1]), row(drafts[0]), .8)
            wait_for(lambda: chapter_ids(books[0]) == drafts[:2])
            drag(row(drafts[1]), head(books[1]))
            wait_for(lambda: chapter_ids(books[1]) == [drafts[1]])
            report["checks"]["writer_real_pointer_membership_and_order"] = {"into_book": True, "up": True, "down": True, "between_books": True}
            # Newly moved book is expanded automatically; return a chapter to loose.
            drag(row(drafts[1]), head(""))
            wait_for(lambda: chapter_ids(books[1]) == [])
            loose_before = [x["id"] for x in api()["drafts"] if x["id"] != drafts[0]]
            target_id = next(d for d in loose_before if d != drafts[1])
            drag(row(drafts[1]), row(target_id), .2)
            expected_loose = [d for d in loose_before if d != drafts[1]]
            expected_loose.insert(expected_loose.index(target_id), drafts[1])
            wait_for(lambda: [x["id"] for x in api()["drafts"] if x["id"] != drafts[0]] == expected_loose)
            report["checks"]["writer_loose_drag_sort"] = True
            count_before = len(moves)
            drag(row(drafts[2]), head(books[0]), cancel=True)
            assert len(moves) == count_before, moves[count_before:]
            report["checks"]["writer_pointercancel_does_not_save_move"] = True
            page.wait_for_timeout(450)
            row(drafts[0]).click()
            page.locator('#wrTextIn').click()
            page.keyboard.press("Meta+End")
            page.keyboard.type(" Unsaved acceptance body survives drag.")
            drag(row(drafts[0]), head(books[1]))
            wait_for(lambda: chapter_ids(books[1]) == [drafts[0]])
            assert "Unsaved acceptance body survives drag." in api('/api/writer?id=' + drafts[0])["text"]
            report["checks"]["writer_pending_body_saved_during_drag"] = True
            page.reload(wait_until="domcontentloaded")
            page.locator('#nav button[data-v="write"]').click()
            row(drafts[0]).wait_for()
            assert chapter_ids(books[1]) == [drafts[0]]
            assert [x["id"] for x in api()["drafts"] if x["id"] != drafts[0]] == expected_loose
            report["checks"]["writer_reload_persistence"] = True
            page.wait_for_timeout(700)
            page.screenshot(path=str(args.output / "writer.png"))
            assert not errors, errors
            report["checks"]["javascript_uncaught_errors"] = errors
            report["writer_move_requests"] = moves
            report["fixture_api_requests"] = requests
            report["ok"] = True
            browser.close()
            browser = None
    except Exception as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
        if page:
            try:
                page.screenshot(path=str(args.output / "failure.png"))
                report["failure_page_text"] = page.locator("body").inner_text()[:5000]
            except Exception:
                pass
        raise
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()
        temp.cleanup()
        (args.output / "ui-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
