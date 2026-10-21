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
# Accept either name from the secrets file, then keep only RAILWAY_API_TOKEN.
if [[ -z "${RAILWAY_API_TOKEN:-}" && -z "${RAILWAY_TOKEN:-}" ]]; then
  echo "ERROR: RAILWAY_API_TOKEN is not set. Refusing to deploy." >&2
  exit 1
fi
export RAILWAY_API_TOKEN="${RAILWAY_API_TOKEN:-$RAILWAY_TOKEN}"
unset RAILWAY_TOKEN

if ! command -v railway >/dev/null; then
  echo "Installing Railway CLI..."
  brew install railway || npm i -g @railway/cli
fi

cd "$HERE"

PROJECT_NAME="mcp-grantiq"
# Never deploy the published placeholder. Generate a token when one is not set.
if [[ -z "${GRANTIQ_ADMIN_TOKEN:-}" || "$GRANTIQ_ADMIN_TOKEN" == "your-admin-token" || "$GRANTIQ_ADMIN_TOKEN" == "replace-with-strong-random" ]]; then
  ADMIN_TOKEN="$(openssl rand -hex 32)"
else
  ADMIN_TOKEN="$GRANTIQ_ADMIN_TOKEN"
fi

echo "==> Initializing Railway project ($PROJECT_NAME)"
if [[ ! -f .railway/project.json ]]; then
  railway init --name "$PROJECT_NAME" || true
fi

if [[ -z "${SAM_API_KEY:-}" || "$SAM_API_KEY" == "your-key-here" ]]; then
  echo "ERROR: SAM_API_KEY is not set. Refusing to deploy." >&2
  exit 1
fi

echo "==> Setting service env vars"
railway variables \
  --set "SAM_API_KEY=$SAM_API_KEY" \
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
