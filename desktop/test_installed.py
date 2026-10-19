#!/usr/bin/env python3
"""Acceptance tests against an app copied out of a mounted DMG.

Uses only the standard library in the test driver. The installed app receives a
system-only PATH, no virtualenv/Python injection, and a disposable user data root.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile


def wait_for(operation, timeout=90):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            result = operation()
            if result:
                return result
        except Exception as exc:
            error = exc
        time.sleep(0.2)
    raise RuntimeError("Timed out: %s" % error)


def exists(pid):
    try:
        os.kill(pid, 0)
        status = subprocess.check_output(["/bin/ps", "-o", "stat=", "-p", str(pid)], text=True).strip()
        return status and not status.startswith("Z")
    except (ProcessLookupError, subprocess.CalledProcessError):
        return False


def descendants(pid):
    rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid="], text=True)
    parents = {}
    for line in rows.splitlines():
        child, parent = map(int, line.split())
        parents.setdefault(parent, []).append(child)
    result = []
    pending = [pid]
    while pending:
        current = pending.pop()
        children = parents.get(current, [])
        result.extend(children)
        pending.extend(children)
    return result


def browser_descendants(pid):
    children = descendants(pid)
    rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,command="], text=True)
    commands = {}
    for row in rows.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) == 2:
            commands[int(parts[0])] = parts[1]
    if any("Chrome for Testing" in commands.get(child, "") for child in children):
        return children
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dmg", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.dmg = args.dmg.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "dmg": str(args.dmg.resolve()), "sha256": hashlib.sha256(args.dmg.read_bytes()).hexdigest(), "checks": {}}
    mount = Path(tempfile.mkdtemp(prefix="guizang-dmg-mount-"))
    installation = args.output / "Applications"
    installation.mkdir(exist_ok=True)
    app = installation / "归藏.app"
    data = args.output / "Application Support" / "归藏"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "DYLD_", "GUIZANG_", "PLAYWRIGHT_")) and k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
    env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", GUIZANG_DATA=str(data.resolve()), PYTHONDONTWRITEBYTECODE="1")
    process = None
    attached = False
    log = (args.output / "host.log").open("ab")
    try:
        subprocess.run(["/usr/bin/hdiutil", "verify", str(args.dmg)], check=True, capture_output=True)
        subprocess.run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(args.dmg)], check=True, capture_output=True)
        attached = True
        subprocess.run(["/usr/bin/ditto", str(mount / "归藏.app"), str(app)], check=True)
        subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True, capture_output=True)
        attached = False
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True)
        report["checks"]["dmg_install_signature"] = True
        resources = app / "Contents/Resources"
        backend = resources / "backend/guizang-backend"
        # Simulate the old install's broken virtualenv and cached media tool.
        # A complete desktop build must never fall back to either of these.
        for relative in (".venv/bin/python", "cache/tools/ffmpeg", "cache/tools/ffprobe"):
            stale = data / relative
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("#!/bin/sh\nexit 98\n")
            stale.chmod(0o755)
        runtime = args.output / "runtime-self-test.json"
        subprocess.run([str(backend), "--desktop-self-test", "--report", str(runtime.resolve())], env=env, cwd="/", stdout=log, stderr=log, check=True, timeout=600)
        runtime_report = json.loads(runtime.read_text())
        assert runtime_report["ok"] and runtime_report["frozen"]
        prefix = str(resources.resolve()) + "/"
        assert runtime_report["executable"].startswith(prefix)
        for name in ("ffmpeg", "ffprobe"):
            assert runtime_report["checks"]["media"]["detail"][name]["path"].startswith(prefix)
        assert runtime_report["checks"]["browser_headed"]["detail"]["executable"].startswith(prefix)
        report["checks"]["obsolete_venv_media_cache_ignored"] = True
        report["checks"]["frozen_runtime"] = runtime_report["checks"]
        notes_fixture = '''import json,tempfile
from pathlib import Path
import book_notes
with tempfile.TemporaryDirectory() as folder:
    raw = {"marks": [{"id":"m1","text":"kept","tag":[]},
                     {"id":"m2","text":"valid","tag":"point"}],
           "entries": [{"id":"e1","title":"kept","body":"body","tag":{}}]}
    (Path(folder)/book_notes.NOTES_FILE).write_text(json.dumps(raw), encoding="utf-8")
    doc = book_notes.load_notes(folder)
    assert len(doc["marks"]) == 2 and len(doc["entries"]) == 1
    assert doc["marks"][0]["tag"] == "" and doc["marks"][1]["tag"] == "point"
    assert doc["entries"][0]["tag"] == ""
    print(json.dumps({"ok":True,"module":book_notes.__file__,"marks":2,"entries":1}))
'''
        notes = subprocess.run([str(backend), "-c", notes_fixture], env=env, cwd="/",
                               capture_output=True, text=True, check=True, timeout=60)
        notes_report = json.loads(notes.stdout)
        assert notes_report["ok"] and notes_report["module"].startswith(prefix)
        report["checks"]["installed_notes_dirty_tags"] = notes_report
        recorder = '''import json,subprocess,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
import ffmpeg_tool
with tempfile.TemporaryDirectory() as folder:
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(record_video_dir=folder,record_video_size={"width":320,"height":240})
        page=context.new_page()
        page.set_content("<h1>Installed recording test</h1>")
        page.wait_for_timeout(400)
        context.close()
        browser.close()
    video=next(Path(folder).glob("*.webm"))
    info=json.loads(subprocess.check_output([ffmpeg_tool.ffprobe_path(),"-v","error","-show_format","-show_streams","-of","json",str(video)]))
    assert float(info["format"]["duration"])>0
    print(json.dumps({"bytes":video.stat().st_size,"codec":info["streams"][0]["codec_name"],"duration":info["format"]["duration"]}))
'''
        recording = subprocess.run([str(backend), "-c", recorder], env=env, cwd="/", capture_output=True, text=True, check=True, timeout=180)
        report["checks"]["installed_playwright_video_recording"] = json.loads(recording.stdout)
        executable = app / "Contents/MacOS/guizang-desktop"
        assert executable.is_file(), executable

        def launch():
            p = subprocess.Popen([str(executable.resolve())], env=env, cwd="/", stdout=log, stderr=log)
            ready = wait_for(lambda: json.loads((data / "desktop-ready.json").read_text()))
            base = "http://127.0.0.1:%d" % ready["port"]
            wait_for(lambda: urllib.request.urlopen(base + "/api/state", timeout=2).status == 200)
            return p, ready, base

        process, ready, base = launch()

        def request(path, payload=None):
            headers = {"Origin": base}
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode()
            with urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers), timeout=90) as response:
                blob = response.read()
                return json.loads(blob) if "application/json" in response.headers.get("Content-Type", "") else blob

        state = request("/api/state")
        assert state["chromium"]
        assert Path(state["out"]).resolve() == (data / "output").resolve()
        assert "归藏".encode() in request("/")
        assert b"markdown" in request("/vendor/markdown-it.min.js").lower()
        book = request("/api/import", {"name": "安装验收.md", "title": "安装验收", "data": base64.b64encode("# 第一章\n\n安装环境中的正文与笔记。\n".encode()).decode()})
        assert book["ok"], book
        bid = book["book"]["id"]
        query = urllib.parse.urlencode({"book": bid})
        assert "安装环境中的正文" in request("/api/md?" + query).decode()
        epub = request("/api/epub?" + query)
        assert zipfile.ZipFile(io.BytesIO(epub)).read("mimetype") == b"application/epub+zip"
        assert request("/api/pdf?" + query).startswith(b"%PDF")
        assert zipfile.ZipFile(io.BytesIO(request("/api/zip?" + query))).namelist()
        destination = data / "exports"
        destination.mkdir(exist_ok=True)
        assert request("/api/action", {"action": "export_dir", "dir": str(destination.resolve())})["ok"]
        report["checks"]["ui_import_markdown_epub_pdf_zip_config"] = True
        before = ready["pid"]
        reply = request("/api/restart", {})
        assert reply["ok"], reply
        time.sleep(1.5)
        wait_for(lambda: request("/api/state"))
        assert json.loads((data / "desktop-ready.json").read_text())["pid"] == before
        report["checks"]["in_app_restart_preserves_supervision"] = True
        process.terminate()
        process.wait(timeout=20)
        wait_for(lambda: not exists(before), timeout=15)
        report["checks"]["host_sigterm_backend_cleanup"] = True
        process, ready, base = launch()
        assert any(row["id"] == bid for row in request("/api/state")["books"])
        assert json.loads((data / "cache/config.json").read_text())["export_dir"] == str(destination.resolve())
        report["checks"]["relaunch_data_config_persistence"] = True
        backend_pid = ready["pid"]
        login = request("/api/action", {"action": "login"})
        assert login["ok"], login
        # Wait for the actual browser tree, rather than only its Python launcher.
        task_children = wait_for(lambda: browser_descendants(backend_pid), timeout=90)
        time.sleep(0.5)
        task_children = list(set(task_children + descendants(backend_pid)))
        assert task_children
        process.kill()
        process.wait(timeout=10)
        wait_for(lambda: not exists(backend_pid), timeout=20)
        wait_for(lambda: not any(exists(pid) for pid in task_children), timeout=20)
        report["checks"]["forced_host_exit_backend_cleanup"] = True
        report["checks"]["forced_host_exit_automation_descendants"] = {"chromium_observed": True, "pids_reaped": task_children}
        process = None
        report["ok"] = True
        report["installed_app"] = str(app.resolve())
        report["data_root"] = str(data.resolve())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        log.close()
        if attached:
            subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], capture_output=True)
        (args.output / "installation-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
