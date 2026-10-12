#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo CLOUDFLARED_TUNNEL_TOKEN=... bash hub/install-cloudflared.sh"; exit 1; fi
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
apt-get update
apt-get install -y cloudflared
if [[ -n "${CLOUDFLARED_TUNNEL_TOKEN:-}" ]]; then
  cloudflared service uninstall >/dev/null 2>&1 || true
  cloudflared service install "$CLOUDFLARED_TUNNEL_TOKEN"
  systemctl enable --now cloudflared
  echo "cloudflared service installed. Configure the published route in Cloudflare to http://127.0.0.1:8765."
else
  echo "cloudflared installed. No tunnel token supplied; create the tunnel/route in Cloudflare and run its generated service-install command."
fi
