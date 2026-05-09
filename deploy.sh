#!/usr/bin/env bash
# Deploy GrantIQ MCP to Railway from Brett's Mac.
#
# Cowork's sandbox can't reach the Railway API, so this script handles
# the live deploy locally. Pulls secrets from the shared
# ../.deploy-secrets.env file and pushes the project up.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS="$HERE/../.deploy-secrets.env"

if [[ ! -f "$SECRETS" ]]; then
  echo "ERROR: $SECRETS not found." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$SECRETS"; set +a

# Railway CLI rejects when both vars are set — see Brett's memory note.
unset RAILWAY_TOKEN
export RAILWAY_API_TOKEN="${RAILWAY_API_TOKEN:-${RAILWAY_TOKEN:-fb2dc2af-ba63-4a43-81da-2d75e9477060}}"

if ! command -v railway >/dev/null; then
  echo "Installing Railway CLI..."
  brew install railway || npm i -g @railway/cli
fi

cd "$HERE"

PROJECT_NAME="mcp-grantiq"
ADMIN_TOKEN="${GRANTIQ_ADMIN_TOKEN:-$(openssl rand -hex 32)}"

echo "==> Initializing Railway project ($PROJECT_NAME)"
if [[ ! -f .railway/project.json ]]; then
  railway init --name "$PROJECT_NAME" || true
fi

echo "==> Setting service env vars"
railway variables \
  --set "SAM_API_KEY=${SAM_API_KEY:-SAM-4b2f823c-bfd2-4555-bafb-b527e9e48058}" \
  --set "GRANTIQ_ADMIN_TOKEN=$ADMIN_TOKEN" \
  --set "GRANTIQ_DB_PATH=/data/grantiq.db" \
  --set "LOG_LEVEL=INFO"

echo "==> Provisioning Volume at /data (idempotent)"
railway volume add --mount-path /data 2>/dev/null || echo "    (volume already exists or attached)"

echo "==> Deploying"
railway up --detach

echo
echo "==> Done. Get the public URL with:  railway domain"
echo "==> Admin token (save this):        $ADMIN_TOKEN"
