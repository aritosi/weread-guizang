#!/usr/bin/env python3
"""Copy a source checkout's cache/output into Application Support, preserving conflicts.

Original data is never moved or deleted. Existing app files win; differing source
files remain recoverable in source-imports/<timestamp>/conflicts/ with a manifest.
Run while the old app is closed to obtain a consistent browser profile snapshot.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.digest()


def migrate(source, target):
    source, target = source.resolve(), target.expanduser().resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source and destination must be separate directories")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive = target / "source-imports" / stamp
    archive.mkdir(parents=True)
    result = {"source": str(source), "target": str(target), "copied": [], "conflicts": [], "identical": 0, "skipped_links": []}
    for area in ("cache", "output"):
        folder = source / area
        if not folder.is_dir():
            continue
        for src in sorted(folder.rglob("*")):
            if src.is_symlink():
                result["skipped_links"].append(str(src.relative_to(source)))
                continue
            if not src.is_file():
                continue
            rel = src.relative_to(source)
            dest = target / rel
            if dest.is_file():
                if dest.stat().st_size == src.stat().st_size and digest(dest) == digest(src):
                    result["identical"] += 1
                    continue
                dest = archive / "conflicts" / rel
                result["conflicts"].append(str(rel))
            elif dest.exists():
                dest = archive / "conflicts" / rel
                result["conflicts"].append(str(rel))
            else:
                result["copied"].append(str(rel))
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if digest(dest) != digest(src):
                raise IOError("Copy verification failed: %s" % rel)
    manifest = archive / "manifest.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {"copied": len(result["copied"]), "conflicts_preserved": len(result["conflicts"]), "identical": result["identical"], "skipped_links": len(result["skipped_links"]), "manifest": str(manifest)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path.home() / "Library/Application Support/归藏")
    options = parser.parse_args()
    print(json.dumps(migrate(options.source, options.target), ensure_ascii=False, indent=2))
