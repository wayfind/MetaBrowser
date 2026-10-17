#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
sdk=${METABROWSER_AGENTCORE_SDK:-$HOME/.local/opt/metacodes/sdk/agentcore-metabrowser-e3a3b932}
zig_bin=${METABROWSER_ZIG:-$HOME/.local/bin/zig}
python3 scripts/check-agentcore-bundle.py "$sdk"
"$zig_bin" build agentcore:plugin "-Dagentcore-sdk=$sdk" -Dtarget=aarch64-macos.13.0 -Doptimize=ReleaseSafe
if pgrep -f 'MetaBrowser.app/Contents/MacOS/Chromium' >/dev/null; then
  printf 'Close the running MetaBrowser before replacing its bundle.\n' >&2
  exit 1
fi
mkdir -p out/macos-arm64
stage=$(mktemp -d out/macos-arm64/package.XXXXXX)
bash scripts/h200.sh 'tar -czf - -C /data/metabrowser/source/unpacked/chromium-154.0.8037.97/out/metabrowser-mac-arm64 Chromium.app' | tar -xzf - -C "$stage"
bash scripts/h200.sh 'python3 /data/metabrowser/project/scripts/app-manifest.py /data/metabrowser/source/unpacked/chromium-154.0.8037.97/out/metabrowser-mac-arm64/Chromium.app' > "$stage/engine-manifest.json"
python3 scripts/app-manifest.py "$stage/Chromium.app" --check "$stage/engine-manifest.json"
cp zig-out/lib/libmetabrowser_metacodes.dylib "$stage/Chromium.app/Contents/Frameworks/"
ditto "$sdk" "$stage/Chromium.app/Contents/Resources/agentcore"
cp "$sdk/bin/rg" "$stage/Chromium.app/Contents/MacOS/rg"
python3 scripts/check-agentcore-bundle.py "$stage/Chromium.app/Contents/Resources/agentcore"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName MetaBrowser' "$stage/Chromium.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName MetaBrowser' "$stage/Chromium.app/Contents/Info.plist"
if [[ -d out/macos-arm64/MetaBrowser.app ]]; then
  mv out/macos-arm64/MetaBrowser.app "$stage/previous.app"
fi
mv "$stage/Chromium.app" out/macos-arm64/MetaBrowser.app
mv "$stage/engine-manifest.json" out/macos-arm64/chromium-app-manifest.json
python3 scripts/app-manifest.py out/macos-arm64/MetaBrowser.app > out/macos-arm64/metabrowser-app-manifest.json
printf 'Packaged: %s/out/macos-arm64/MetaBrowser.app\n' "$PWD"
