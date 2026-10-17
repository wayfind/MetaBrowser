#!/usr/bin/env bash
# Official source cache only. Does not call a stock browser an agent SDK.
set -euo pipefail
task_root="${1:-/data/metabrowser}"
[[ "$task_root" = /* ]]
task_proxy="${METABROWSER_BUILD_PROXY:-http://172.16.2.64:3128}"
task_version=154.0.8037.97
task_url="https://storage.googleapis.com/chromium-browser-official/chromium-$task_version.tar.xz"
task_archive="$task_root/source/chromium-$task_version.tar.xz"
mkdir -p "$task_root/source" "$task_root/logs"
exec 9>"$task_root/fetch-chromium-source.lock"
flock -n 9
if [[ ! -f "$task_archive" ]]; then
  curl --silent --show-error --fail --location --retry 2 --connect-timeout 15 \
    --max-time 7200 --speed-time 90 --speed-limit 1048576 --proxy "$task_proxy" \
    "$task_url" -o "$task_archive.part"
  # This MD5 is the official GCS object metadata, retrieved over HTTPS. It
  # checks transfer corruption; it is not a signature. SHA-256 is recorded below.
  printf '%s  %s\n' d7278959edee3efe96403116bdd68a92 "$task_archive.part" | md5sum --check --status
  [[ "$(stat -c %s "$task_archive.part")" == 4174250340 ]]
  mv "$task_archive.part" "$task_archive"
fi
printf '%s  %s\n' d7278959edee3efe96403116bdd68a92 "$task_archive" | md5sum --check --status
sha256sum "$task_archive" > "$task_archive.sha256"
printf '%s  %s\n' 20723618e77b209b90a21f72c403155b44129515a1bc92ce72df4a086f861303 \
  "$task_archive" | sha256sum --check --status
printf 'OFFICIAL_SOURCE_ARCHIVE_VERIFIED\n'
printf 'Next: review/extract source, prepare Chromium tools/dependencies, implement native adapters.\n'
printf 'No Chromium engine or native agent SDK has been compiled by this step.\n'
