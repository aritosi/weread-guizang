#!/usr/bin/env python3
"""Audit native resources without modifying upstream Chromium signatures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

MAGICS = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
          b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def run(*args):
    try:
        # Verifying large Chromium/Node signatures can take several minutes on
        # the build host. A short timeout would misclassify valid vendor code.
        p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=600 if args[0] == "codesign" else 30)
    except subprocess.TimeoutExpired:
        return 124, "Native inspection timed out: " + " ".join(args)
    return p.returncode, p.stdout + p.stderr


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def repair_signatures(root: Path):
    """Re-sign only invalid native code, preserving working upstream identities.

    Some Playwright archives omit Chromium's resource seals. Signing leaf
    helpers before frameworks and the containing app recreates coherent seals.
    Chromium's V8/Node JIT needs these entitlements under hardened runtime.
    """
    initial = audit(root)
    targets = set()
    for item in initial["files"]:
        if item["signature_valid"]:
            continue
        path = root.resolve() / item["path"]
        target = path
        # Find the closest containing bundle; signing that bundle recreates its
        # resource seal instead of pretending its main executable is standalone.
        for parent in path.parents:
            if parent == root.resolve().parent:
                break
            if parent.suffix in (".app", ".framework"):
                target = parent
                break
        targets.add(target)
    entitlements = {"com.apple.security.cs.allow-jit": True,
                    "com.apple.security.cs.allow-unsigned-executable-memory": True,
                    "com.apple.security.cs.disable-library-validation": True}
    repaired = []
    with tempfile.TemporaryDirectory(prefix="guizang-sign-") as temporary:
        plist = Path(temporary) / "jit.plist"
        plist.write_bytes(plistlib.dumps(entitlements))
        for target in sorted(targets, key=lambda p: len(p.parts), reverse=True):
            command = ["codesign", "--force", "--sign", "-", "--options", "runtime",
                       "--entitlements", str(plist), str(target)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
            if result.returncode:
                raise RuntimeError(f"Signing {target}: {result.stderr}")
            repaired.append(str(target.relative_to(root.resolve())))
    return repaired


def minimum_macos(path):
    """Read only the arm64 slice; an Intel slice may have a different floor."""
    status, commands = run("otool", "-arch", "arm64", "-l", str(path))
    if status:
        return None
    for block in commands.split("Load command "):
        if "cmd LC_BUILD_VERSION\n" in block:
            platform = re.search(r"^\s*platform\s+(\S+)", block, re.M)
            version = re.search(r"^\s*minos\s+(\S+)", block, re.M)
            if platform and version and platform[1] in ("1", "MACOS", "macos"):
                return version[1]
        elif "cmd LC_VERSION_MIN_MACOSX\n" in block:
            version = re.search(r"^\s*version\s+(\S+)", block, re.M)
            if version:
                return version[1]
    return None


def version_tuple(version):
    return tuple((list(map(int, version.split("."))) + [0, 0, 0])[:3])


def audit(root: Path, strict_signatures: bool = False, maximum_macos: str = "13.5"):
    root = root.resolve()
    rows, errors = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in MAGICS:
                continue
        rel = str(path.relative_to(root))
        _, description = run("file", "-b", str(path))
        _, linked = run("otool", "-L", str(path))
        deps = [line.strip().split(" (", 1)[0] for line in linked.splitlines()[1:] if line.startswith("\t")]
        # Absolute non-system dependencies would escape the app on a clean Mac.
        external = [dep for dep in deps if dep.startswith("/") and not dep.startswith(("/System/Library/", "/usr/lib/"))]
        signed, signature = run("codesign", "--verify", "--strict", str(path))
        _, signing_info = run("codesign", "-dv", "--verbose=2", str(path))
        executable = os.access(path, os.X_OK)
        minos = minimum_macos(path) if "arm64" in description else None
        row = {"path": rel, "sha256": digest(path),
               "file": description.strip(), "executable": executable,
               "minimum_macos_arm64": minos,
               "dependencies": deps, "external_dependencies": external,
               "signature_valid": signed == 0, "signature": signing_info.strip()}
        if "arm64" not in description:
            errors.append(f"{rel}: missing arm64 architecture")
        if "executable" in description and not executable:
            errors.append(f"{rel}: missing executable permission")
        if external:
            errors.append(f"{rel}: external dynamic libraries: {external}")
        if minos and version_tuple(minos) > version_tuple(maximum_macos):
            errors.append(f"{rel}: arm64 requires macOS {minos}, exceeds declared {maximum_macos}")
        if strict_signatures and signed:
            errors.append(f"{rel}: invalid signature: {signature.strip()}")
        rows.append(row)
    return {"root": str(root), "maximum_macos": maximum_macos, "native_files": len(rows), "errors": errors, "files": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict-signatures", action="store_true")
    parser.add_argument("--repair-signatures", action="store_true", help="ad-hoc repair invalid signatures with JIT entitlements")
    parser.add_argument("--maximum-macos", default="13.5", help="fail if an arm64 dependency requires a newer macOS")
    args = parser.parse_args()
    repaired = repair_signatures(args.root) if args.repair_signatures else []
    result = audit(args.root, args.strict_signatures, args.maximum_macos)
    result["repaired_signatures"] = repaired
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, ensure_ascii=False))
    return bool(result["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
