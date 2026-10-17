#!/usr/bin/env bash
set -euo pipefail
# Run on the Linux builder. This verifies toolchain transport, not Chromium.
root=${METABROWSER_BUILD_ROOT:-/data/metabrowser}
clang="$root/source/unpacked/chromium-154.0.8037.97/third_party/llvm-build/Release+Asserts/bin/clang"
sdk="$root/tools/apple-sdk-26.2/MacOSX.sdk"
mkdir -p "$root/sdk/macos-arm64"
"$clang" --target=arm64-apple-macos13.0 -isysroot "$sdk" -fuse-ld=lld \
  "$root/project/tests/cross/mac_smoke.c" -framework CoreFoundation \
  -o "$root/sdk/macos-arm64/toolchain-smoke"
sha256sum "$root/sdk/macos-arm64/toolchain-smoke"
