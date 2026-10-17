#!/usr/bin/env bash
# Run ON the Linux builder. Builds the independent contract, not Chromium SDK.
set -euo pipefail
task_root="${1:-/data/metabrowser}"
[[ "$task_root" = /* ]]
[[ "$(uname -m)" == x86_64 ]]
task_proxy="${METABROWSER_BUILD_PROXY:-http://172.16.2.64:3128}"
task_zig_url="${METABROWSER_ZIG_URL:-https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz}"
task_tools="$task_root/tools"
task_source="$task_root/project"
mkdir -p "$task_tools" "$task_root/logs" "$task_root/sdk"
exec 9>"$task_root/prepare-builder.lock"
flock -n 9
task_zig="$task_tools/zig-0.16.0/zig"
if [[ ! -x "$task_zig" ]]; then
  task_archive="$task_tools/zig-x86_64-linux-0.16.0.tar.xz"
  curl --silent --show-error --fail --location --retry 3 --connect-timeout 15 --max-time 600 \
    --proxy "$task_proxy" \
    "$task_zig_url" \
    -o "$task_archive.part"
  printf '%s  %s\n' 70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00 \
    "$task_archive.part" | sha256sum --check --status
  mv "$task_archive.part" "$task_archive"
  task_stage="$(mktemp -d "$task_tools/.zig-stage.XXXXXX")"
  tar -xf "$task_archive" --strip-components=1 -C "$task_stage"
  [[ "$("$task_stage/zig" version)" == 0.16.0 ]]
  mv "$task_stage" "$task_tools/zig-0.16.0"
fi
[[ "$("$task_zig" version)" == 0.16.0 ]]
cd "$task_source"
"$task_zig" fmt --check build.zig src
"$task_zig" build test --summary all
"$task_zig" build -Doptimize=ReleaseSafe --summary all
printf 'CONTRACT_TESTS_PASSED\n'
printf 'Chromium engine SDK is not built by this script.\n'
