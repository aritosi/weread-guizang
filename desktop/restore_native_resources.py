#!/usr/bin/env python3
"""Restore native symlink layouts after Tauri's generic resource copying.

Only generated resources in the fixed build output are replaced. Previous trees
are moved to a recoverable build backup; source resources and user data stay put.
"""
from pathlib import Path
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "desktop/src-tauri/target/release/bundle/macos/归藏.app"
RESOURCES = APP / "Contents/Resources"
if not (APP / "Contents/Info.plist").is_file() or APP.is_symlink() or RESOURCES.is_symlink():
    raise SystemExit("Expected generated app bundle is missing or is a symlink")
backup = ROOT / ".build-desktop/resource-backups" / uuid.uuid4().hex
backup.mkdir(parents=True)
for name in ("backend", "browsers", "media"):
    source = ROOT / "dist/desktop" / name
    target = RESOURCES / name
    if not source.is_dir():
        raise SystemExit("Missing prepared resource: " + str(source))
    if target.exists() or target.is_symlink():
        shutil.move(str(target), str(backup / name))
    try:
        subprocess.run(["/usr/bin/ditto", str(source), str(target)], check=True)
    except Exception:
        if target.exists():
            shutil.move(str(target), str(backup / (name + "-incomplete")))
        if (backup / name).exists():
            shutil.move(str(backup / name), str(target))
        raise
print("Native resource layout restored; previous generated resources: " + str(backup))
