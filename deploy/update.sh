#!/usr/bin/env bash
# Deploy the latest code from GitHub. Only restarts the app if every test passes.
#   sudo /opt/marketmind/deploy/update.sh
set -euo pipefail
APP_DIR=/opt/marketmind
DATA_DIR=/var/lib/marketmind
APP_USER=marketmind
KEY="$DATA_DIR/.ssh/deploy_key"
GIT_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$DATA_DIR/.ssh/known_hosts"
as_app() { sudo -u "$APP_USER" env HOME="$DATA_DIR" GIT_SSH_COMMAND="$GIT_SSH" "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
cd "$APP_DIR"
prev=$(as_app git rev-parse HEAD)

echo "==> Pulling latest code"
as_app git pull --ff-only -q
new=$(as_app git rev-parse HEAD)
if [ "$prev" = "$new" ]; then echo "Already up to date ($new)."; exit 0; fi

echo "==> Installing packages"
as_app .venv/bin/pip install -q -r requirements-dev.txt

echo "==> Running tests"
if ! as_app .venv/bin/python -m pytest -q -p no:cacheprovider; then
  echo "!! Tests failed: rolling back to $prev. The running app was not touched."
  as_app git reset -q --hard "$prev"
  as_app .venv/bin/pip install -q -r requirements-dev.txt
  exit 1
fi

echo "==> Backing up the database before restart"
/usr/local/bin/mm backup

install -m 644 deploy/marketmind.service deploy/marketmind-backup.service deploy/marketmind-backup.timer /etc/systemd/system/
install -m 755 deploy/mm /usr/local/bin/mm
systemctl daemon-reload
systemctl restart marketmind.service
echo "==> Updated ${prev:0:7} → ${new:0:7}. App restarted."
