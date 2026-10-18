#!/usr/bin/env python3
"""Frozen interpreter adapter for the original Python scripts and desktop server.

The existing backend keeps using [py(), script(...)] / -c / -m. This executable
provides those interpreter operations without requiring an installed Python.
"""
import argparse
import atexit
import importlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import threading
import time


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def configure_runtime():
    root = resource_root()
    sys.path.insert(0, str(root))
    # Set these before importing project modules: their file paths are computed
    # at import time and must never resolve inside the read-only application.
    data = Path(os.environ.get("GUIZANG_DATA") or
                Path.home() / "Library" / "Application Support" / "归藏").expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ["GUIZANG_DATA"] = str(data)
    os.environ.setdefault("GUIZANG_BOOKS", str(data / "output"))
    os.environ.setdefault("GUIZANG_OUTPUT", os.environ["GUIZANG_BOOKS"])
    os.environ["PYTHONUNBUFFERED"] = "1"
    # A fresh child of a frozen interpreter must have independent bootloader
    # lifetime (PyInstaller 6+); this also applies when /api/restart hands over.
    if getattr(sys, "frozen", False):
        import certifi
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        os.environ["GUIZANG_PYTHON"] = sys.executable
        # The standalone interpreter's build-time CA path may not exist on a
        # recipient Mac. All stdlib/requests clients share the bundled CA file.
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    bases = (root, Path(sys.executable).parent.parent,
             Path(sys.executable).parent, root.parent.parent)
    browser = os.environ.get("GUIZANG_BUNDLED_BROWSERS")
    if browser:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(browser).expanduser())
    else:
        for base in bases:
            match = next((base / name for name in ("browsers", "ms-playwright")
                          if (base / name).is_dir()), None)
            if match:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(match)
                break
    tools = os.environ.get("GUIZANG_BUNDLED_TOOLS")
    if not tools:
        tools = next((str(base / name) for base in bases
                      for name in ("media", "bin", "tools")
                      if (base / name / "ffmpeg").is_file()), "")
    if tools:
        os.environ["GUIZANG_FFMPEG"] = str(Path(tools) / "ffmpeg")
        os.environ["GUIZANG_FFPROBE"] = str(Path(tools) / "ffprobe")
        os.environ["PATH"] = tools + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")
    os.chdir(data)
    import platform_compat
    platform_compat.ensure_browser_env()
    return data


class ProcessGuard:
    """Retain descendant identities even after a subprocess starts a new session.

    psutil identifies ancestry by parent PID, independent of process groups.
    Retaining Process instances also protects against killing a reused PID.
    """
    def __init__(self, parent_pid=0):
        import psutil
        self.psutil = psutil
        self.owner = psutil.Process()
        self.parent = psutil.Process(parent_pid) if parent_pid else None
        self.children = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._watch, name="desktop-process-guard", daemon=True)

    def _collect(self):
        try:
            found = self.owner.children(recursive=True)
            with self.lock:
                for proc in found:
                    self.children[(proc.pid, proc.create_time())] = proc
        except self.psutil.Error:
            pass

    def _watch(self):
        while not self.stopped.wait(0.15):
            self._collect()
            if self.parent and not self.parent.is_running():
                os.kill(os.getpid(), signal.SIGTERM)
                return

    def start(self):
        self.thread.start()
        atexit.register(self.stop)

    def stop(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        self._collect()
        with self.lock:
            children = list(self.children.values())
        # Retain the child tree before terminating parents; descendants may then
        # be reparented to launchd and no longer discoverable from this process.
        for proc in reversed(children):
            try:
                proc.terminate()
            except self.psutil.Error:
                pass
        _, alive = self.psutil.wait_procs(children, timeout=3)
        for proc in alive:
            try:
                proc.kill()
            except self.psutil.Error:
                pass
        self.psutil.wait_procs(alive, timeout=2)


def dispatch(argv):
    if not argv:
        raise SystemExit("A script, -c command, or -m module is required")
    if argv[0] == "-c":
        if len(argv) < 2:
            raise SystemExit("-c requires a command")
        sys.argv = ["-c"] + argv[2:]
        exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__", "__package__": None})
    elif argv[0] == "-m":
        if len(argv) < 2:
            raise SystemExit("-m requires a module")
        sys.argv = argv[1:]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
    else:
        script = Path(argv[0])
        if not script.is_file():
            # Paths from an older installation can still name a packaged script.
            script = resource_root() / script.name
        script = script.resolve()
        sys.argv = [str(script)] + argv[1:]
        sys.path.insert(0, str(script.parent))
        # Direct compile works for source files outside the PyInstaller archive
        # and preserves __file__ for all original resource lookups.
        namespace = {"__name__": "__main__", "__file__": str(script),
                     "__package__": None, "__spec__": None, "__cached__": None}
        exec(compile(script.read_bytes(), str(script), "exec"), namespace)
    return 0


def self_test(report_path=""):
    result = {"ok": True, "pid": os.getpid(), "frozen": bool(getattr(sys, "frozen", False)),
              "executable": sys.executable, "data_dir": os.environ["GUIZANG_DATA"], "checks": {}}

    def check(name, operation):
        try:
            value = operation()
            result["checks"][name] = {"ok": True, "detail": value}
        except Exception as exc:
            result["ok"] = False
            result["checks"][name] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    def imports():
        modules = ("playwright.sync_api", "genanki", "pypdf", "feedparser", "yt_dlp", "psutil",
                   "ui_server", "video_note", "book_import", "writer", "login", "anna_browser")
        for module in modules:
            importlib.import_module(module)
        return list(modules)
    check("dependencies", imports)

    def certificates():
        import ssl
        context = ssl.create_default_context()
        stats = context.cert_store_stats()
        if not stats["x509_ca"]:
            raise RuntimeError("no certificate authorities available")
        path = os.environ.get("SSL_CERT_FILE", "")
        if getattr(sys, "frozen", False) and not Path(path).is_file():
            raise RuntimeError("bundled certificate file missing")
        return {"cafile": path or ssl.get_default_verify_paths().cafile, "certificate_count": stats["x509_ca"]}
    check("certificates", certificates)

    def javascript_runtime():
        import yt_dlp
        import video_note
        node = resource_root() / "playwright" / "driver" / "node"
        if not getattr(sys, "frozen", False):
            import playwright
            node = Path(playwright.__file__).parent / "driver" / "node"
        proc = subprocess.run([str(node), "-e", "console.log(JSON.stringify({ok: true}))"],
                              capture_output=True, text=True, timeout=20)
        if proc.returncode or not json.loads(proc.stdout).get("ok"):
            raise RuntimeError(proc.stderr or proc.stdout)
        if getattr(sys, "frozen", False):
            import yt_dlp_ejs.yt.solver
            core, lib = yt_dlp_ejs.yt.solver.core(), yt_dlp_ejs.yt.solver.lib()
            if not core or not lib:
                raise RuntimeError("yt-dlp JavaScript solver resources missing")
            with yt_dlp.YoutubeDL(video_note._ydl_options()) as ydl:
                runtime = ydl._js_runtimes["node"]
                if not runtime.info:
                    raise RuntimeError("yt-dlp could not initialize bundled Node")
            return {"node": str(node), "solver_core_bytes": len(core), "solver_lib_bytes": len(lib)}
        return {"node": str(node)}
    check("javascript_runtime", javascript_runtime)

    def interpreter():
        prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
        code = "import json,sys;print(json.dumps({'ok':True,'arg':sys.argv[1]}))"
        proc = subprocess.run(prefix + ["-c", code, "dispatch"], capture_output=True, text=True, timeout=30)
        if proc.returncode or json.loads(proc.stdout).get("arg") != "dispatch":
            raise RuntimeError(proc.stderr or proc.stdout)
        module = subprocess.run(prefix + ["-m", "yt_dlp", "--version"], capture_output=True, text=True, timeout=30)
        if module.returncode:
            raise RuntimeError(module.stderr)
        script = subprocess.run(prefix + [str(resource_root() / "bootstrap.py")],
                                capture_output=True, text=True, timeout=45) if getattr(sys, "frozen", False) else None
        if script and script.returncode:
            raise RuntimeError(script.stdout + script.stderr)
        return {"command": True, "module": module.stdout.strip(), "script": script is not None}
    check("interpreter", interpreter)

    def browser(headless):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            executable = p.chromium.executable_path
            if not os.access(executable, os.X_OK):
                raise RuntimeError("Chromium lacks executable permission: " + executable)
            with p.chromium.launch(headless=headless) as chrome:
                page = chrome.new_page()
                page.set_content("<html><title>归藏安装测试</title><body>归藏 runtime PDF</body></html>")
                if page.title() != "归藏安装测试":
                    raise RuntimeError("browser DOM check failed")
                pdf = page.pdf() if headless else b""
                if headless and not pdf.startswith(b"%PDF"):
                    raise RuntimeError("PDF export returned invalid data")
                return {"executable": executable, "version": chrome.version, "pdf_bytes": len(pdf)}
    check("browser_headless_pdf", lambda: browser(True))
    check("browser_headed", lambda: browser(False))

    def media():
        import ffmpeg_tool
        paths = {"ffmpeg": ffmpeg_tool.ffmpeg_path(), "ffprobe": ffmpeg_tool.ffprobe_path()}
        versions = {}
        for name, path in paths.items():
            proc = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20)
            if proc.returncode:
                raise RuntimeError(proc.stderr)
            versions[name] = {"path": path, "version": proc.stdout.splitlines()[0]}
        with tempfile.TemporaryDirectory(prefix="desktop-media-") as folder:
            wav = str(Path(folder) / "tone.wav")
            proc = subprocess.run([paths["ffmpeg"], "-v", "error", "-f", "lavfi", "-i",
                                   "sine=frequency=440:duration=0.2", wav], capture_output=True, text=True, timeout=20)
            if proc.returncode:
                raise RuntimeError(proc.stderr)
            probe = subprocess.run([paths["ffprobe"], "-v", "error", "-show_format", "-of", "json", wav],
                                   capture_output=True, text=True, timeout=20)
            if probe.returncode or float(json.loads(probe.stdout)["format"]["duration"]) <= 0:
                raise RuntimeError(probe.stderr or "invalid audio duration")
        return versions
    check("media", media)
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if report_path:
        Path(report_path).write_text(content + "\n", encoding="utf-8")
    print(content, flush=True)
    return 0 if result["ok"] else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    configure_runtime()
    if argv and argv[0] == "--desktop-server":
        parser = argparse.ArgumentParser()
        parser.add_argument("--desktop-server", action="store_true")
        parser.add_argument("--port", type=int, default=0)
        parser.add_argument("--parent-pid", type=int, default=0)
        parser.add_argument("--ready-file", required=True)
        args = parser.parse_args(argv)
        guard = ProcessGuard(args.parent_pid)
        guard.start()

        def quit_signal(signum, frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, quit_signal)
        signal.signal(signal.SIGINT, quit_signal)
        sys.argv = [str(resource_root() / "ui_server.py"), "--port", str(args.port),
                    "--ready-file", args.ready_file]
        try:
            import ui_server
            if getattr(sys, "frozen", False):
                def restart_in_place():
                    guard.stop()
                    restart_args = [sys.executable, "--desktop-server", "--port", str(ui_server.LISTEN_PORT),
                                    "--parent-pid", str(args.parent_pid), "--ready-file", args.ready_file]
                    os.execve(sys.executable, restart_args, dict(os.environ))
                ui_server.DESKTOP_RESTART = restart_in_place
            ui_server.main()
        finally:
            guard.stop()
            Path(args.ready_file).unlink(missing_ok=True)
        return 0
    if argv and argv[0] == "--desktop-self-test":
        parser = argparse.ArgumentParser()
        parser.add_argument("--desktop-self-test", action="store_true")
        parser.add_argument("--report", default="")
        args = parser.parse_args(argv)
        return self_test(args.report)
    return dispatch(argv)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
