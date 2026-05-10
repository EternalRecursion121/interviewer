#!/usr/bin/env bash
# Read the current ngrok public URL and write it into the idealists-site .env
# file as PUBLIC_INTERVIEWER_API. Free-tier ngrok URLs change on every restart
# of the tunnel, so run this after `systemctl restart interviewer-ngrok`.
#
# Usage: ./sync-ngrok-url.sh [path/to/.env]

set -euo pipefail

ENV_FILE="${1:-/root/idealists-site/.env}"

URL=$(curl -sS http://127.0.0.1:4040/api/tunnels \
  | python3 -c 'import sys, json; d=json.load(sys.stdin); print(d["tunnels"][0]["public_url"]) if d["tunnels"] else (_ for _ in ()).throw(SystemExit("no tunnels"))')

if [[ -z "$URL" ]]; then
  echo "Could not read ngrok URL — is interviewer-ngrok.service active?" >&2
  exit 1
fi

echo "Current ngrok URL: $URL"

if [[ -f "$ENV_FILE" ]]; then
  if grep -q '^PUBLIC_INTERVIEWER_API=' "$ENV_FILE"; then
    sed -i -E "s|^PUBLIC_INTERVIEWER_API=.*|PUBLIC_INTERVIEWER_API=$URL|" "$ENV_FILE"
  else
    printf '\nPUBLIC_INTERVIEWER_API=%s\n' "$URL" >> "$ENV_FILE"
  fi
  echo "Updated $ENV_FILE"
else
  printf 'PUBLIC_INTERVIEWER_API=%s\n' "$URL" > "$ENV_FILE"
  echo "Created $ENV_FILE"
fi
