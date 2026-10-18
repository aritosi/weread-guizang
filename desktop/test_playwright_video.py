#!/usr/bin/env python3
"""Verify real Playwright recording with an installed app's bundled interpreter.

python3 desktop/test_playwright_video.py --backend /path/to/Contents/Resources/backend/guizang-backend --report /tmp/video.json
The driver requires only stdlib; all recording dependencies come from the app.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.backend:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "DYLD_", "GUIZANG_", "PLAYWRIGHT_")) and k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        with tempfile.TemporaryDirectory(prefix="guizang-video-data-") as data:
            env["GUIZANG_DATA"] = data
            return subprocess.run([str(args.backend.resolve()), "-c", Path(__file__).read_text(),
                                   "--report", str(args.report.resolve())], env=env, cwd="/", timeout=120).returncode
    if not getattr(sys, "frozen", False):
        raise SystemExit("Use --backend to test the packaged interpreter, not development Python")
    import ffmpeg_tool
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix="guizang-recording-") as folder:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(record_video_dir=folder, record_video_size={"width": 320, "height": 240})
            page = context.new_page()
            page.set_content('<body style="background:blue;color:white"><h1>Bundled video recording</h1></body>')
            page.wait_for_timeout(1300)
            video = page.video
            context.close()
            path = Path(video.path())
            probe = subprocess.run([ffmpeg_tool.ffprobe_path(), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                                   capture_output=True, text=True, check=True, timeout=30)
            info = json.loads(probe.stdout)
            result = {"ok": path.stat().st_size > 1000 and float(info["format"]["duration"]) > 0,
                      "frozen": True, "backend": sys.executable,
                      "browsers": os.environ["PLAYWRIGHT_BROWSERS_PATH"],
                      "bytes": path.stat().st_size, "format": info["format"]["format_name"],
                      "duration": info["format"]["duration"], "codec": info["streams"][0]["codec_name"],
                      "width": info["streams"][0]["width"], "height": info["streams"][0]["height"]}
            browser.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
