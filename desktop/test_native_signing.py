#!/usr/bin/env python3
"""Reproduce and repair the Python.framework resource seal failure in isolation."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import tempfile

from audit_native import audit, repair_signatures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1] / "dist/desktop/backend"
    candidates = sorted(backend.rglob("libpython3*.dylib"))
    candidates += [p for p in backend.rglob("Python") if p.is_file() and not p.is_symlink()]
    library = args.library or next(iter(candidates), None)
    if library is None or not library.is_file():
        parser.error("Build the backend first, or pass --library with an arm64 Python library")
    with tempfile.TemporaryDirectory(prefix="guizang-native-signing-") as folder:
        root = Path(folder)
        framework = root / "Python.framework"
        version = framework / "Versions/3.12"
        resources = version / "Resources"
        resources.mkdir(parents=True)
        shutil.copy2(library, version / "Python")
        (resources / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "Python", "CFBundleIdentifier": "org.guizang.signing-fixture",
            "CFBundleName": "Python", "CFBundlePackageType": "FMWK", "CFBundleVersion": "3.12",
        }))
        (framework / "Versions/Current").symlink_to("3.12")
        (framework / "Python").symlink_to("Versions/Current/Python")
        (framework / "Resources").symlink_to("Versions/Current/Resources")
        before = audit(root, strict_signatures=True)
        assert any(not row["signature_valid"] for row in before["files"]), "Fixture did not reproduce the missing resource seal"
        repaired = repair_signatures(root)
        after = audit(root, strict_signatures=True)
        assert repaired == ["Python.framework"], repaired
        assert not after["errors"], after["errors"]
        print(json.dumps({"ok": True, "reproduced_invalid_framework": True,
                          "repaired_bundle": repaired, "strict_native_audit": "passed"}))


if __name__ == "__main__":
    main()
