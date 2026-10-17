#!/usr/bin/env bash
# Explicit verified route; no private key or remote service credentials are stored.
set -euo pipefail
task_key="${METABROWSER_SSH_KEY:-$HOME/.ssh/id_ed25519}"
task_jump="${METABROWSER_SSH_JUMP:-shuzuan@58.211.6.133}"
task_jump_port="${METABROWSER_SSH_JUMP_PORT:-104}"
task_host="${METABROWSER_SSH_HOST:-ubuntu@114.94.190.2}"
task_port="${METABROWSER_SSH_PORT:-2216}"
# These fields are used by OpenSSH's ProxyCommand. Restrict their grammar.
[[ "$task_jump" =~ ^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.:-]+$ ]]
[[ "$task_jump_port" =~ ^[0-9]+$ ]]
exec ssh -o BatchMode=yes -o IdentitiesOnly=yes -i "$task_key" \
  -o StrictHostKeyChecking=yes -o ConnectTimeout=15 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o "ProxyCommand=ssh -o BatchMode=yes -o ConnectTimeout=15 -p $task_jump_port $task_jump -W %h:%p" \
  -p "$task_port" "$task_host" "$@"
