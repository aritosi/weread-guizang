#!/bin/bash
# Build a self-contained arm64 app and a compressed drag-to-install DMG.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
if [ "$(uname -m)" != arm64 ]; then
  echo 'This build targets Apple Silicon; run it on an arm64 Mac.' >&2
  exit 1
fi
xcode-select -p >/dev/null
command -v cargo >/dev/null
command -v npm >/dev/null

# Probe each SDK rather than using a newer SDK that an older CLT linker cannot parse.
if [ -z "${SDKROOT:-}" ]; then
  PROBE="$(mktemp -d -t guizang-sdk)"
  for SDK in "$(xcrun --show-sdk-path)" /Library/Developer/CommandLineTools/SDKs/MacOSX*.sdk; do
    if echo 'int main(void) { return 0; }' | xcrun clang -isysroot "$SDK" -x c - -o "$PROBE/probe" 2>/dev/null; then
      export SDKROOT="$SDK"
      break
    fi
  done
  rm -rf "$PROBE"
  test -n "${SDKROOT:-}" || { echo 'No working macOS SDK found.' >&2; exit 1; }
fi
export MACOSX_DEPLOYMENT_TARGET=13.5
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"

if [ "${GUIZANG_SKIP_BACKEND_BUILD:-0}" != 1 ]; then
  BUILD_PY="${GUIZANG_BUILD_PYTHON:-}"
  if [ -z "$BUILD_PY" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then BUILD_PY="$ROOT/.venv/bin/python";
    else BUILD_PY="$(command -v python3.12 || command -v python3)"; fi
  fi
  "$BUILD_PY" -c 'import sys; assert sys.version_info >= (3, 11), "Build requires Python 3.11+"'
  if [ ! -x .build-desktop-venv/bin/python ]; then
    "$BUILD_PY" -m venv .build-desktop-venv
  fi
  .build-desktop-venv/bin/python -m pip install -r desktop/requirements-build.txt
  .build-desktop-venv/bin/python desktop/package_backend.py
fi
test -x dist/desktop/backend/guizang-backend
test -x dist/desktop/media/ffmpeg
test -x dist/desktop/media/ffprobe
# PyInstaller can collect a Python.framework whose executable carries a bare
# Mach-O signature. Re-sign the containing framework to seal its Resources before
# Tauri copies it; changing Python versions alone does not repair that layout.
.build-desktop-venv/bin/python desktop/audit_native.py dist/desktop/backend \
  --repair-signatures --strict-signatures \
  --output "$ROOT/dist/desktop/backend-native-audit.json"
/usr/bin/python3 - <<'PY'
import json, pathlib, re
root = pathlib.Path.cwd()
version = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root/'ui_server.py').read_text(), re.M)[1]
path = root/'desktop/src-tauri/tauri.conf.json'
conf = json.loads(path.read_text())
conf['version'] = version
path.write_text(json.dumps(conf, ensure_ascii=False, indent=2)+'\n')
path = root/'desktop/src-tauri/Cargo.toml'
path.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version}"', path.read_text(), count=1, flags=re.M))
PY
(
  cd desktop
  npm ci --no-audit --no-fund
  if [ "${GUIZANG_SKIP_TAURI_COMPILE:-0}" = 1 ]; then
    npm run tauri -- bundle --bundles app
  else
    npm run build
  fi
)
APP="$ROOT/desktop/src-tauri/target/release/bundle/macos/归藏.app"
test -d "$APP"
# Tauri's generic resource copier expands framework symlinks. Restore native
# onedir trees with ditto so Chromium/Python retain their signed bundle layout.
/usr/bin/python3 "$ROOT/desktop/restore_native_resources.py"
codesign --force --sign "${APPLE_SIGNING_IDENTITY:--}" --options runtime \
  --entitlements "$ROOT/desktop/src-tauri/Entitlements.plist" "$APP"
codesign --verify --deep --strict "$APP"
.build-desktop-venv/bin/python desktop/audit_native.py "$APP" --strict-signatures \
  --output "$ROOT/dist/desktop/app-native-audit.json"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
OUT="$ROOT/dist/macos"
mkdir -p "$OUT"
DMG="$OUT/归藏-${VERSION}-arm64.dmg"
STAGE="$(mktemp -d -t guizang-dmg)"
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/归藏.app"
ln -s /Applications "$STAGE/Applications"
cp desktop/INSTALL.txt "$STAGE/安装说明.txt"
hdiutil create -quiet -volname "归藏 ${VERSION} arm64" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
hdiutil verify "$DMG"
shasum -a 256 "$DMG" > "$DMG.sha256"
echo "DMG: $DMG"
