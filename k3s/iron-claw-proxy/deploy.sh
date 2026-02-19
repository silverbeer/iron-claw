#!/usr/bin/env bash
# Deploy iron-claw-proxy to K3s.
#
# Reads .env.prod from the repo root for secrets, generates the K8s Secret
# manifest, and applies all resources.
#
# Required vars in .env.prod:
#   ANTHROPIC_API_KEY   — Anthropic API key for LLM calls
#   RADIUS_PASSWORD     — RADIUS password for the scraper user
#
# Optional vars in .env.prod:
#   IRON_CLAW_USERNAME  — RADIUS username (default: iron-claw-scraper)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.prod"

# --- Load .env.prod ---
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found"
  echo ""
  echo "Create it with at least:"
  echo "  ANTHROPIC_API_KEY=sk-ant-..."
  echo "  RADIUS_PASSWORD=..."
  exit 1
fi

# Source the env file (skip comments and blank lines)
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# --- Validate required vars ---
missing=()
[[ -z "${ANTHROPIC_API_KEY:-}" ]] && missing+=("ANTHROPIC_API_KEY")
[[ -z "${RADIUS_PASSWORD:-}" ]]   && missing+=("RADIUS_PASSWORD")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: missing required vars in $ENV_FILE:"
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

IRON_CLAW_USERNAME="${IRON_CLAW_USERNAME:-iron-claw-scraper}"

# --- Generate K8s Secret manifest ---
SECRET_FILE="$SCRIPT_DIR/secret.yaml"

cat > "$SECRET_FILE" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: iron-claw-proxy-secrets
  namespace: iron-claw
type: Opaque
stringData:
  PROXY_ANTHROPIC_API_KEY: "$ANTHROPIC_API_KEY"
  IRON_CLAW_USERNAME: "$IRON_CLAW_USERNAME"
  RADIUS_PASSWORD: "$RADIUS_PASSWORD"
EOF

echo "Generated $SECRET_FILE"

# --- Apply manifests ---
echo "Applying iron-claw-proxy manifests..."
kubectl apply -f "$SCRIPT_DIR/namespace.yaml"
kubectl apply -f "$SCRIPT_DIR/configmap.yaml"
kubectl apply -f "$SECRET_FILE"
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/service.yaml"

echo ""
echo "Waiting for rollout..."
kubectl rollout status deployment/iron-claw-proxy -n iron-claw --timeout=60s

echo ""
echo "Done. Verify with:"
echo "  kubectl get pods -n iron-claw"
echo "  kubectl logs -n iron-claw -l app=iron-claw-proxy"
