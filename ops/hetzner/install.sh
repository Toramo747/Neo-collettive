#!/usr/bin/env bash
# One-shot bootstrap of a fresh Ubuntu 24.04 Hetzner VPS for NEO.
# Run as root:  bash <(curl -fsSL https://raw.githubusercontent.com/Toramo747/neo-collettive/main/ops/hetzner/install.sh)
# or copy the file over and run `bash install.sh`. Idempotent: safe to re-run.
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/Toramo747/neo-collettive.git}"
BRANCH="${BRANCH:-main}"
BASE=/srv/neo

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl git ufw unattended-upgrades fail2ban

if ! command -v docker >/dev/null 2>&1; then
  echo "== docker"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker

echo "== firewall (ssh, http, https only)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "== directories"
mkdir -p "$BASE"/{state,neo-local,caddy-data,caddy-config,backups}
chmod 700 "$BASE"/state "$BASE"/backups
if [ ! -d "$BASE/repo/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$BASE/repo"
else
  git -C "$BASE/repo" fetch --quiet origin && git -C "$BASE/repo" checkout --quiet --detach "origin/$BRANCH"
fi
chmod +x "$BASE/repo/ops/hetzner/deploy.sh"

if [ ! -f "$BASE/.env" ]; then
  cp "$BASE/repo/ops/hetzner/env.template" "$BASE/.env"
  chmod 600 "$BASE/.env"
  sed -i "s/^ENVSTORE_TOKEN=.*/ENVSTORE_TOKEN=$(openssl rand -hex 24)/; s/^ENVSTORE_DEPLOY_HOOK=.*/ENVSTORE_DEPLOY_HOOK=$(openssl rand -hex 16)/" "$BASE/.env"
  echo "   created $BASE/.env from the template: fill it in (see README)"
fi
if [ ! -f "$BASE/jarvis.env" ]; then
  printf '# env vars of the jarvis service (copied from Render)\n' > "$BASE/jarvis.env"
  chmod 600 "$BASE/jarvis.env"
fi

echo "== nightly backup of the state store (keeps 14 days)"
cat > /etc/cron.daily/neo-state-backup <<'EOF'
#!/bin/sh
set -e
d=/srv/neo/backups
tar -czf "$d/state-$(date -u +%Y%m%d).tgz" -C /srv/neo state neo-local
find "$d" -name 'state-*.tgz' -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/neo-state-backup

cat > /etc/systemd/system/neo.service <<EOF
[Unit]
Description=NEO stack (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$BASE/repo/ops/hetzner
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable neo.service

cat <<EOF

Done. Next steps (README section 4):
  1. edit $BASE/.env      (domain, secrets copied from Render)
  2. edit $BASE/jarvis.env (secrets of the jarvis service, if any)
  3. import the saved state:  bash $BASE/repo/ops/hetzner/import_state.sh /root/render-state.env
  4. start:                   systemctl start neo && docker compose -f $BASE/repo/ops/hetzner/docker-compose.yml logs -f neo
EOF
