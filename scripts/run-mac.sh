#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
app="$PWD/out/macos-arm64/MetaBrowser.app"
metabrowser_mcp_config="${XDG_CONFIG_HOME:-$HOME/.config}/metabrowser/mcp.json"
if [[ -z "${METABROWSER_MCP_CONFIG+x}" && -f "$metabrowser_mcp_config" ]]; then
  export METABROWSER_MCP_CONFIG="$metabrowser_mcp_config"
fi
# Keep normal browser data in Chromium's persistent Application Support
# directory. Build output is disposable and must never hold the default login
# or session. An explicit fixture/custom profile remains available to callers.
if [[ -n "${METABROWSER_USER_DATA_DIR:-}" ]]; then
  if [[ "$METABROWSER_USER_DATA_DIR" != /* ]]; then
    printf 'METABROWSER_USER_DATA_DIR must be an absolute path.\n' >&2
    exit 1
  fi
  set -- "--user-data-dir=$METABROWSER_USER_DATA_DIR" "$@"
fi
exec "$app/Contents/MacOS/Chromium" \
  --no-first-run --no-default-browser-check "$@"
