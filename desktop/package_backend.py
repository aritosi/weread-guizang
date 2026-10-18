#!/usr/bin/env python3
"""Build the offline arm64 sidecar, pinned Chromium and standalone media tools.

Run using .build-desktop-venv/bin/python, after installing requirements-build.txt.
Only allowlisted application resources are collected. Runtime/cache/output/config
files are deliberately excluded; cached native binaries are independently audited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "desktop"
WORK = ROOT / ".build-desktop" / "pyinstaller"


def command(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "GuizangDesktopBuilder/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, output.open("wb") as stream:
        shutil.copyfileobj(response, stream)
        return response.url


def replace_playwright_ffmpeg(destination, registry):
    """Use the audited media FFmpeg for Playwright's standard recording CLI.

    Playwright 1.64's ffmpeg-1013 binary has an arm64 macOS 15 floor, although
    Chromium itself supports 13.0. The bundled standalone FFmpeg supports 12.0
    and passes real WebM recording with Playwright's arguments.
    """
    item = next(item for item in registry if item["name"] == "ffmpeg")
    target_dir = destination / ("ffmpeg-" + item["revision"])
    target_dir.mkdir(parents=True, exist_ok=True)
    source = DIST / "media" / "ffmpeg"
    target = target_dir / "ffmpeg-mac"
    if not source.is_file():
        raise RuntimeError("Prepare media assets before the Playwright recording executable")
    original_hash = sha256(target) if target.is_file() else None
    source_hash = sha256(source)
    if original_hash != source_hash:
        # Native executable carries a valid standalone Developer ID signature;
        # preserve it rather than re-signing the surrounding browser resources.
        command(["ditto", source, target])
    for license_file in ("ffmpeg-LICENSE.txt", "COPYING.GPLv3", "provenance.json"):
        license_source = DIST / "media" / license_file
        if license_source.is_file():
            shutil.copy2(license_source, target_dir / ("MEDIA-" + license_file))
    manifest = {"playwright_revision": item["revision"], "replacement": "media/ffmpeg",
                "sha256": source_hash, "license": "GPL-3.0-or-later",
                "reason": "upstream Playwright ffmpeg requires macOS 15; bundled media ffmpeg supports macOS 12",
                "verification": "real Playwright record_video_dir capture decoded by bundled ffprobe",
                "provenance": "MEDIA-provenance.json"}
    previous = target_dir / "GUIZANG-FFMPEG-REPLACEMENT.json"
    if previous.exists():
        original_hash = json.loads(previous.read_text()).get("original_sha256", original_hash)
    manifest["original_sha256"] = original_hash
    previous.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def browser_assets():
    import playwright
    package = Path(playwright.__file__).parent
    registry = json.loads((package / "driver" / "package" / "browsers.json").read_text())
    wanted = [item for item in registry["browsers"] if item["name"] in ("chromium", "chromium-headless-shell", "ffmpeg")]
    destination = DIST / "browsers"
    destination.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get("GUIZANG_BUILD_BROWSER_CACHE", Path.home() / "Library/Caches/ms-playwright"))
    for item in wanted:
        directory = item["name"].replace("-", "_") + "-" + item["revision"]
        source = cache / directory
        target = destination / directory
        if not target.exists() and (source / "INSTALLATION_COMPLETE").exists():
            print(f"Copy exact Playwright {item['name']} revision {item['revision']}", flush=True)
            # ditto preserves upstream modes, symlinks and Chromium bundle signatures.
            command(["ditto", source, target])
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(destination))
    command([sys.executable, "-m", "playwright", "install", "chromium"], env=env)
    for item in wanted:
        directory = item["name"].replace("-", "_") + "-" + item["revision"]
        if not (destination / directory / "INSTALLATION_COMPLETE").exists():
            raise RuntimeError(f"Incomplete bundled browser: {directory}")
    # Playwright's cache ownership links contain absolute build-machine paths.
    shutil.rmtree(destination / ".links", ignore_errors=True)
    recording_ffmpeg = replace_playwright_ffmpeg(destination, wanted)
    from audit_native import audit, repair_signatures
    repaired = repair_signatures(destination)
    report = audit(destination, strict_signatures=True)
    report["repaired_signatures"] = repaired
    (DIST / "browser-native-audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    if report["errors"]:
        raise RuntimeError("Bundled browser native audit failed: " + "; ".join(report["errors"]))
    return {"playwright_version": importlib.metadata.version("playwright"), "registry": wanted,
            "upstream": "https://playwright.dev/python/docs/browsers", "download_verified_by": "playwright install chromium",
            "recording_ffmpeg": recording_ffmpeg}


def media_assets():
    from audit_native import audit
    media = DIST / "media"
    media.mkdir(parents=True, exist_ok=True)
    previous_manifest = media / "provenance.json"
    previous_rows = json.loads(previous_manifest.read_text()) if previous_manifest.exists() else []
    rows = []
    for name in ("ffmpeg", "ffprobe"):
        target = media / name
        source = Path(os.environ.get("GUIZANG_BUILD_MEDIA_CACHE", str(ROOT / "cache" / "tools"))) / name
        url = f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/{name}.zip"
        resolved = url
        if source.is_file() and not target.exists():
            print(f"Copy existing audited arm64 {name}", flush=True)
            command(["ditto", source, target])
            origin = "existing application native tool cache; original downloader ffmpeg_tool._silicon_url"
            resolved = f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/snapshot/{name}.zip"
        elif not target.exists():
            archive = ROOT / ".build-desktop" / "downloads" / (name + ".zip")
            resolved = download(url, archive)
            with zipfile.ZipFile(archive) as z:
                members = [item for item in z.infolist() if Path(item.filename).name == name and not item.is_dir()]
                if len(members) != 1:
                    raise RuntimeError(f"Unexpected {name} archive contents")
                with z.open(members[0]) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            target.chmod(0o755)
            origin = "downloaded release from upstream builder"
        else:
            origin = "existing bundle asset, hash/version verified again"
            # Preserve the actual source of a cached snapshot instead of
            # relabeling an unchanged binary as today's release download.
            previous = next((row for row in previous_rows if row.get("name") == name and row.get("sha256") == sha256(target)), None)
            if previous:
                resolved = previous["source"]
                origin = previous["origin"]
        result = subprocess.run([str(target), "-version"], check=True, capture_output=True, text=True)
        license_result = subprocess.run([str(target), "-L"], check=True, capture_output=True, text=True)
        (media / (name + "-LICENSE.txt")).write_text(license_result.stdout + license_result.stderr)
        rows.append({"name": name, "sha256": sha256(target), "source": resolved, "origin": origin,
                     "version": result.stdout.splitlines()[0], "build_configuration": result.stdout.splitlines()[2],
                     "license": "GPL-3.0-or-later" if "--enable-gpl" in result.stdout and "--enable-version3" in result.stdout else "see bundled license",
                     "source_code": "https://git.ffmpeg.org/ffmpeg.git",
                     "upstream_build_scripts": "https://git.martin-riedl.de/ffmpeg/build-script"})
    report = audit(media, strict_signatures=True)
    if report["errors"]:
        raise RuntimeError("Media audit failed: " + "; ".join(report["errors"]))
    if not (media / "COPYING.GPLv3").exists():
        download("https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/COPYING.GPLv3", media / "COPYING.GPLv3")
    (media / "provenance.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    return rows


def licenses():
    target = DIST / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    package_rows = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        if name == "pip":
            continue
        package_rows.append({"name": name, "version": distribution.version,
                             "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License"),
                             "project_urls": distribution.metadata.get_all("Project-URL", [])})
        for path in distribution.files or []:
            if any(part.lower().startswith(("license", "copying", "notice")) for part in path.parts):
                source = Path(distribution.locate_file(path))
                if source.is_file():
                    dest = target / name / Path(*[part for part in path.parts if part not in ("..", ".")])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
    (target / "python-packages.json").write_text(json.dumps(package_rows, indent=2, ensure_ascii=False) + "\n")
    python_license = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, target / "Python-LICENSE.txt")
    (target / "THIRD-PARTY-NOTICES.txt").write_text(
        "Guizang desktop includes Python, Playwright (Apache-2.0), Chromium/Chrome for Testing, "
        "Node.js, FFmpeg/FFprobe and the Python packages listed in python-packages.json.\n"
        "Chromium and Node.js retain upstream license files in their respective resource folders.\n"
        "FFmpeg/FFprobe are independent executables from Martin Riedl's build server. The selected "
        "build enables GPL/version3; its full license text and configuration are in media/. "
        "Source and build-script links plus SHA256 hashes are in media/provenance.json. "
        "For public redistribution, supply the complete corresponding source for the exact binary "
        "and included codec libraries, as required by their licenses.\n"
        "FFmpeg: https://ffmpeg.org/ ; licensing: https://ffmpeg.org/legal.html\n"
        "Build server: https://ffmpeg.martin-riedl.de/\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true", help="prepare exact browsers and media; skip PyInstaller")
    parser.add_argument("--backend-only", action="store_true", help="rebuild sidecar; retain prepared assets")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("Build this arm64 bundle on an Apple Silicon Mac.")
    DIST.mkdir(parents=True, exist_ok=True)
    if not args.backend_only:
        media = media_assets()
        browsers = browser_assets()
        licenses()
        (DIST / "dependency-manifest.json").write_text(json.dumps(
            {"python": sys.version, "architecture": platform.machine(), "browsers": browsers, "media": media},
            indent=2, ensure_ascii=False) + "\n")
    if not args.assets_only:
        licenses()
        command([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
                 "--workpath", WORK, ROOT / "desktop" / "guizang-backend.spec"], cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
