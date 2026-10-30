#!/usr/bin/env bash
# Deploy NEO (and jarvis) on the VPS from a git ref. Called by:
#   - the envstore deploy hook  (https://state.<domain>/deploy/<hook>?ref=<sha>)  -> DEPLOY_REF set
#   - you, on the host:        /srv/neo/repo/ops/hetzner/deploy.sh [ref]
# Never touches envstore or caddy (restart those by hand with `docker compose up -d`).
set -euo pipefail
REPO_DIR="${REPO_DIR:-/srv/neo/repo}"
REF="${1:-${DEPLOY_REF:-}}"
cd "$REPO_DIR"

git fetch --quiet origin
if [ -n "$REF" ]; then
  git checkout --quiet --detach "$REF" 2>/dev/null || git checkout --quiet --detach "origin/$REF"
else
  git checkout --quiet --detach origin/main
fi
echo "deploy: $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-80)"

cd "$REPO_DIR/ops/hetzner"
docker compose build --quiet neo jarvis
docker compose up -d --no-deps neo jarvis

# wait for /livez through the internal network (same check Render used)
for i in $(seq 1 30); do
  if docker compose exec -T neo python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:10000/livez',timeout=5)" >/dev/null 2>&1; then
    echo "deploy: neo live after ${i}x5s"
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 5
done
echo "deploy: neo did not answer /livez in 150s" >&2
docker compose logs --tail 50 neo >&2 || true
exit 1
