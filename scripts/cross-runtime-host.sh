#!/usr/bin/env bash
set -euo pipefail
root=${METABROWSER_BUILD_ROOT:-/data/metabrowser}
src="$root/source/unpacked/chromium-154.0.8037.97"
sdk="$root/tools/apple-sdk-26.2/MacOSX.sdk"
out="$root/sdk/macos-arm64"
mkdir -p "$out"
"$src/third_party/llvm-build/Release+Asserts/bin/clang++" \
  --target=arm64-apple-macos13.0 -isysroot "$sdk" -fuse-ld=lld \
  -std=c++20 -dynamiclib "$src/metabrowser/runtime_host.cc" \
  -o "$out/libmetabrowser-runtime-host.dylib" \
  -Wl,-install_name,@rpath/libmetabrowser-runtime-host.dylib
sha256sum "$out/libmetabrowser-runtime-host.dylib"
