#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out/macos-arm64
name=libmetabrowser-runtime-host.dylib
expected=$(bash scripts/h200.sh "sha256sum /data/metabrowser/sdk/macos-arm64/$name" | awk '{print $1}')
[[ "$expected" =~ ^[a-f0-9]{64}$ ]]
bash scripts/h200.sh "cat /data/metabrowser/sdk/macos-arm64/$name" > "out/macos-arm64/$name.partial"
printf '%s  %s\n' "$expected" "out/macos-arm64/$name.partial" | shasum -a 256 -c -
mv "out/macos-arm64/$name.partial" "out/macos-arm64/$name"
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun clang \
  -I chromium/metabrowser tests/cross/runtime_host_test.c \
  -L out/macos-arm64 -lmetabrowser-runtime-host -Wl,-rpath,@executable_path \
  -o out/macos-arm64/runtime-host-test
out/macos-arm64/runtime-host-test
zig_bin=${METABROWSER_ZIG:-$HOME/.local/bin/zig}
"$zig_bin" build-exe src/runtime_smoke.zig -lc -L out/macos-arm64 \
  -lmetabrowser-runtime-host -rpath "$PWD/out/macos-arm64" \
  -femit-bin=out/macos-arm64/zig-runtime-smoke
out/macos-arm64/zig-runtime-smoke
printf 'Returned runtime consumed by C and Zig: PASS\n'
