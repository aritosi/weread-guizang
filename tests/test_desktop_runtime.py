#!/usr/bin/env python3
"""Desktop integration checks: isolated data, interpreter, and process lifetime."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
BUILD_PYTHON = ROOT / ".build-desktop-venv/bin/python"
# Desktop-only dependencies live in the isolated build environment; source
# installations keep their original requirements and can still run this gate.
if importlib.util.find_spec("psutil") is None and BUILD_PYTHON.is_file() and Path(sys.executable) != BUILD_PYTHON:
    os.execv(str(BUILD_PYTHON), [str(BUILD_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
ENTRY = ROOT / "desktop" / "backend_entry.py"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("desktop_backend_entry", ENTRY)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class DesktopRuntime(unittest.TestCase):
    def child(self, *args, **kwargs):
        return subprocess.Popen([sys.executable, str(ENTRY), *args], **kwargs)

    def wait_json(self, path, proc, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if proc.poll() is not None:
                self.fail("runtime exited: " + str(proc.returncode))
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                time.sleep(0.05)
        self.fail("no readiness receipt")

    def test_interpreter_command_module_and_script(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, GUIZANG_DATA=folder)
            code = "import json,sys;print(json.dumps({'arg':sys.argv[1]}))"
            out = subprocess.run([sys.executable, str(ENTRY), "-c", code, "hello"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), {"arg": "hello"})
            script = Path(folder) / "probe.py"
            script.write_text("import os,sys,json;print(json.dumps({'cwd':os.getcwd(),'arg':sys.argv[1],'file':__file__}))")
            out = subprocess.run([sys.executable, str(ENTRY), str(script), "script-argument"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), {"cwd": str(Path(folder).resolve()),
                                                     "arg": "script-argument", "file": str(script.resolve())})
            out = subprocess.run([sys.executable, str(ENTRY), "-m", "json.tool", "--help"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("usage:", out.stdout)

    def test_frozen_interpreter_ignores_old_venv(self):
        import platform_compat
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(sys, "frozen", True, create=True):
            old = Path(folder) / ".venv" / "bin" / "python"
            old.parent.mkdir(parents=True)
            old.touch()
            with mock.patch.dict(os.environ, {"GUIZANG_DATA": folder, "GUIZANG_PYTHON": str(old)}):
                self.assertEqual(platform_compat.venv_python(folder), sys.executable)

    def test_bundled_components_cannot_be_uninstalled(self):
        import cleanup
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(cleanup.component_items(), [])

    def test_frozen_ytdlp_uses_shipped_javascript_runtime(self):
        import playwright
        import video_note
        from yt_dlp import YoutubeDL
        root = str(Path(playwright.__file__).parent.parent)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", root, create=True):
            options = video_note._ydl_options()
            with YoutubeDL(options) as ydl:
                runtime_info = ydl._js_runtimes["node"].info
                self.assertIsNotNone(runtime_info)
                self.assertEqual(runtime_info.path, str(Path(root) / "playwright" / "driver" / "node"))

    @unittest.skipUnless(importlib.util.find_spec("psutil"), "desktop build environment not installed")
    def test_server_random_port_persistent_config_and_signal_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, GUIZANG_DATA=folder, GUIZANG_BOOKS=str(Path(folder) / "output"))
            ready = Path(folder) / "ready.json"
            config = Path(folder) / "cache" / "config.json"
            config.parent.mkdir()
            config.write_text('{"flomo_url":"https://example.invalid/existing"}')
            proc = self.child("--desktop-server", "--port", "0", "--ready-file", str(ready),
                              "--parent-pid", str(os.getpid()), env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                info = self.wait_json(ready, proc)
                self.assertGreater(info["port"], 0)
                self.assertEqual(info["pid"], proc.pid)
                with urllib.request.urlopen("http://127.0.0.1:%d/api/state" % info["port"]) as reply:
                    self.assertEqual(reply.status, 200)
                    self.assertTrue(json.load(reply)["version"])
                self.assertEqual(json.loads(config.read_text())["flomo_url"], "https://example.invalid/existing")
                proc.terminate()
                self.assertEqual(proc.wait(timeout=10), 0, proc.stderr.read().decode())
                self.assertFalse(ready.exists())
                self.assertTrue(config.exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stderr.close()

    @unittest.skipUnless(importlib.util.find_spec("psutil"), "desktop build environment not installed")
    def test_parent_exit_cleans_detached_descendants(self):
        import psutil
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, GUIZANG_DATA=folder)
            receipt = Path(folder) / "tree.json"
            # A real supervisor launches a worker in another process group. The
            # runtime guard must terminate it when its designated parent exits.
            program = ("import sys,time,subprocess,json,signal;"
                       "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
                       "from desktop.backend_entry import ProcessGuard;"
                       "g=ProcessGuard(int(sys.argv[1]));g.start();"
                       "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'],start_new_session=True);"
                       "open(sys.argv[2],'w').write(json.dumps({'worker':p.pid}));time.sleep(90)")
            parent = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(90)"])
            proc = subprocess.Popen([sys.executable, "-c", program, str(parent.pid), str(receipt)],
                                    cwd=ROOT, env=env, stderr=subprocess.PIPE)
            worker = None
            try:
                info = self.wait_json(receipt, proc)
                worker = psutil.Process(info["worker"])
                time.sleep(0.35)
                parent.terminate()
                parent.wait(timeout=5)
                # ProcessGuard signals SIGTERM; install the production handler
                # in this probe to exercise normal atexit cleanup.
                proc.wait(timeout=10)
                end = time.monotonic() + 5
                while worker.is_running() and worker.status() != psutil.STATUS_ZOMBIE and time.monotonic() < end:
                    time.sleep(0.05)
                self.assertTrue(not worker.is_running() or worker.status() == psutil.STATUS_ZOMBIE)
            finally:
                for child in (proc, parent):
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                if worker and worker.is_running():
                    worker.kill()
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
