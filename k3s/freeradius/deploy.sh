#!/usr/bin/env bash
# Deploy FreeRADIUS to K3s (iron-claw namespace).
#
# Reads .env.prod from the repo root for Supabase connection details,
# generates env ConfigMap + Secret, and applies all resources.
#
# Required vars in .env.prod:
#   RADIUS_SQL_SERVER    — Supabase PostgreSQL host (must be reachable from LKE)
#   RADIUS_SQL_PORT      — PostgreSQL port
#   RADIUS_SQL_LOGIN     — PostgreSQL username
#   RADIUS_SQL_PASSWORD  — PostgreSQL password
#   RADIUS_SQL_DATABASE  — PostgreSQL database name

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.prod"

# --- Load .env.prod ---
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found"
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# --- Validate required vars ---
missing=()
[[ -z "${RADIUS_SQL_SERVER:-}" ]]   && missing+=("RADIUS_SQL_SERVER")
[[ -z "${RADIUS_SQL_PORT:-}" ]]     && missing+=("RADIUS_SQL_PORT")
[[ -z "${RADIUS_SQL_LOGIN:-}" ]]    && missing+=("RADIUS_SQL_LOGIN")
[[ -z "${RADIUS_SQL_PASSWORD:-}" ]] && missing+=("RADIUS_SQL_PASSWORD")
[[ -z "${RADIUS_SQL_DATABASE:-}" ]] && missing+=("RADIUS_SQL_DATABASE")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: missing required vars in $ENV_FILE:"
  printf '  %s\n' "${missing[@]}"
  exit 1
fi

# --- Ensure namespace exists ---
kubectl apply -f "$REPO_ROOT/k3s/iron-claw-proxy/namespace.yaml"

# --- Generate env ConfigMap ---
ENV_CM_FILE="$SCRIPT_DIR/env-configmap.yaml"
cat > "$ENV_CM_FILE" <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: freeradius-env
  namespace: iron-claw
data:
  RADIUS_SQL_SERVER: "$RADIUS_SQL_SERVER"
  RADIUS_SQL_PORT: "$RADIUS_SQL_PORT"
  RADIUS_SQL_LOGIN: "$RADIUS_SQL_LOGIN"
  RADIUS_SQL_DATABASE: "$RADIUS_SQL_DATABASE"
EOF

echo "Generated $ENV_CM_FILE"

# --- Generate Secret ---
SECRET_FILE="$SCRIPT_DIR/secret.yaml"
cat > "$SECRET_FILE" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: freeradius-secrets
  namespace: iron-claw
type: Opaque
stringData:
  RADIUS_SQL_PASSWORD: "$RADIUS_SQL_PASSWORD"
EOF

echo "Generated $SECRET_FILE"

# --- Apply manifests ---
echo "Applying FreeRADIUS manifests..."
kubectl apply -f "$ENV_CM_FILE"
kubectl apply -f "$SECRET_FILE"
kubectl apply -f "$SCRIPT_DIR/raddb-configmap.yaml"
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/service.yaml"

echo ""
echo "Waiting for rollout..."
kubectl rollout status deployment/freeradius -n iron-claw --timeout=90s

echo ""
echo "Done. Verify with:"
echo "  kubectl get pods -n iron-claw"
echo "  kubectl logs -n iron-claw -l app=freeradius"
