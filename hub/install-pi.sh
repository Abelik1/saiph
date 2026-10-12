#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash hub/install-pi.sh"; exit 1; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
id -u orion >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash orion
apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates rsync
mkdir -p /opt/orion-mini /var/lib/orion-hub
# Keep the active automation list: it is local configuration, not in the repo.
rsync -a --delete --exclude '.venv' --exclude 'data' --exclude 'config/automations.json' "$ROOT/hub/" /opt/orion-mini/hub/
python3 -m venv /opt/orion-mini/hub/.venv
/opt/orion-mini/hub/.venv/bin/pip install --upgrade pip
/opt/orion-mini/hub/.venv/bin/pip install -r /opt/orion-mini/hub/requirements.txt
[[ -f /opt/orion-mini/hub/config/automations.json ]] || cp /opt/orion-mini/hub/config/automations.example.json /opt/orion-mini/hub/config/automations.json
chown -R orion:orion /opt/orion-mini /var/lib/orion-hub
# Push tokens and session hashes live here.
chmod 700 /var/lib/orion-hub
find /var/lib/orion-hub -type f -exec chmod 600 {} +
install -m 0644 /opt/orion-mini/hub/systemd/orion-hub.service /etc/systemd/system/orion-hub.service
install -m 0644 /opt/orion-mini/hub/systemd/orion-hub-backup.service /opt/orion-mini/hub/systemd/orion-hub-backup.timer /etc/systemd/system/
# Re-running the installer must not erase Firebase settings added later.
[[ -f /etc/orion-hub.env ]] || cat >/etc/orion-hub.env <<'ENV'
ORION_HUB_DATA=/var/lib/orion-hub
ORION_HUB_AUTOMATIONS=/opt/orion-mini/hub/config/automations.json
# ORION_FIREBASE_PROJECT_ID=your-firebase-project
# ORION_FIREBASE_CREDENTIALS=/var/lib/orion-hub/firebase-service-account.json
ENV
chmod 600 /etc/orion-hub.env
# Owner revocation must stop the dedicated backup service synchronously. Only
# that command retains sudo privileges; all other commands use the hub user.
cat >/usr/local/sbin/orion-hub <<'SH'
#!/bin/sh
set -a; . /etc/orion-hub.env; set +a
cd /opt/orion-mini/hub || exit 1
if [ "${1:-}" = "revoke" ]; then
    exec env ORION_HUB_DATA="$ORION_HUB_DATA" /opt/orion-mini/hub/.venv/bin/python -m orion_hub.cli "$@"
fi
exec runuser -u orion -- env ORION_HUB_DATA="$ORION_HUB_DATA" /opt/orion-mini/hub/.venv/bin/python -m orion_hub.cli "$@"
SH
chmod 755 /usr/local/sbin/orion-hub
systemctl daemon-reload
systemctl enable orion-hub
systemctl enable --now orion-hub-backup.timer
systemctl restart orion-hub
printf '\nOrion Hub installed. Health: http://127.0.0.1:8765/v1/health\nCreate a pairing code with:\n  sudo orion-hub pair\n'
