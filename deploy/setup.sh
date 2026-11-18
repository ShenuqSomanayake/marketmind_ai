#!/usr/bin/env bash
# One-time server setup for MarketMind AI on Ubuntu 24.04.
# Run AFTER Tailscale is connected (step 4 of deploy/README.md):
#   sudo bash setup.sh git@github.com:<you>/marketmind_ai.git
set -euo pipefail

REPO_URL="${1:?Usage: sudo bash setup.sh <git repo SSH url>}"
APP_DIR=/opt/marketmind
DATA_DIR=/var/lib/marketmind
APP_USER=marketmind
KEY="$DATA_DIR/.ssh/deploy_key"

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
tailscale status >/dev/null 2>&1 || { echo "Tailscale isn't connected yet. Do step 4 first."; exit 1; }

echo "==> Installing system packages"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get -y -q upgrade
DEBIAN_FRONTEND=noninteractive apt-get -y -q install python3 python3-venv python3-pip git ufw unattended-upgrades curl
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Creating the '$APP_USER' service account and folders"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR" "$DATA_DIR/backups" "$DATA_DIR/.ssh"
install -d -m 755 -o "$APP_USER" -g "$APP_USER" "$APP_DIR"

echo "==> GitHub deploy key (read-only access to your private repo)"
if [ ! -f "$KEY" ]; then
  sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N "" -C "marketmind-server" -f "$KEY"
fi
sudo -u "$APP_USER" sh -c "ssh-keyscan -t ed25519 github.com >> $DATA_DIR/.ssh/known_hosts 2>/dev/null"
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$DATA_DIR/.ssh/known_hosts"
if ! sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git ls-remote "$REPO_URL" >/dev/null 2>&1; then
  echo
  echo "Add this key to GitHub → your repo → Settings → Deploy keys → Add deploy key (leave 'Allow write access' OFF):"
  echo
  cat "$KEY.pub"
  echo
  read -r -p "Press Enter once you've added it... "
  sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git ls-remote "$REPO_URL" >/dev/null
fi

echo "==> Getting the code"
if [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git clone -q "$REPO_URL" "$APP_DIR"
fi

echo "==> Python environment (this takes a few minutes)"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" HOME="$DATA_DIR" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" HOME="$DATA_DIR" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements-dev.txt"

echo "==> Running the test suite"
(cd "$APP_DIR" && sudo -u "$APP_USER" HOME="$DATA_DIR" .venv/bin/python -m pytest -q -p no:cacheprovider)

echo "==> Settings file"
if [ ! -f /etc/marketmind.env ]; then
  install -m 600 -o root -g root "$APP_DIR/deploy/marketmind.env.example" /etc/marketmind.env
fi

echo "==> Services (app + nightly backup)"
install -m 644 "$APP_DIR"/deploy/marketmind.service "$APP_DIR"/deploy/marketmind-backup.service "$APP_DIR"/deploy/marketmind-backup.timer /etc/systemd/system/
install -m 755 "$APP_DIR/deploy/mm" /usr/local/bin/mm
systemctl daemon-reload
systemctl enable --now marketmind.service marketmind-backup.timer

echo "==> Firewall: only Tailscale traffic gets in"
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
ufw allow OpenSSH   # removed in step 9 once Tailscale SSH is confirmed
ufw --force enable

sleep 3
systemctl --no-pager --lines=0 status marketmind.service || true
echo
echo "Done. Open http://$(hostname):8501 on any device signed in to your Tailscale."
