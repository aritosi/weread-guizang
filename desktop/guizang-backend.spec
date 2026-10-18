# Build with desktop/package_backend.py. No user data enters this allowlist.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(p), ".") for p in root.glob("*.py")]
datas += [(str(root / "ui.html"), "."), (str(root / "requirements.txt"), ".")]
for folder in ("vendor", "mcp", "skills"):
    datas.append((str(root / folder), folder))
datas.append((str(root / "shell" / "onboarding.html"), "shell"))
binaries = []
hiddenimports = [p.stem for p in root.glob("*.py")]
for package in ("playwright", "yt_dlp", "yt_dlp_ejs", "genanki", "pypdf", "feedparser", "psutil", "certifi"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
for distribution in ("playwright", "yt-dlp", "yt-dlp-ejs", "genanki", "pypdf", "feedparser", "psutil", "certifi"):
    datas += copy_metadata(distribution)

a = Analysis([str(root / "desktop" / "backend_entry.py")], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["tkinter", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="guizang-backend",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, target_arch="arm64", codesign_identity=None,
          entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="backend")
