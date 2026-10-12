#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Fixed upstream component setup, invoked only after the desktop's OS consent.
set -eu
[ "$(id -u)" = 0 ] || exit 1
. /etc/os-release
case "$ID:$VERSION_ID" in
  ubuntu:22.04) suite=jammy ;;
  ubuntu:24.04) suite=noble ;;
  debian:12) suite=bookworm ;;
  debian:13) suite=trixie ;;
  *) echo 'This system needs the official Tailscale installation instructions.' >&2; exit 1 ;;
esac
if ! command -v tailscale >/dev/null 2>&1; then
  key=/usr/share/keyrings/tailscale-archive-keyring.gpg
  source=/etc/apt/sources.list.d/tailscale.list
  [ ! -e "$key" ] && [ ! -L "$key" ] && [ ! -e "$source" ] && [ ! -L "$source" ] || exit 1
  apt-get update
  apt-get install -y ca-certificates curl
  stage=$(mktemp -d /tmp/orion-mesh.XXXXXXXX)
  trap 'rm -f -- "$stage/key"; rmdir -- "$stage"' EXIT HUP INT TERM
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --max-time 30 \
    "https://pkgs.tailscale.com/stable/$ID/$suite.noarmor.gpg" -o "$stage/key"
  [ "$(wc -c < "$stage/key")" -le 65536 ] || exit 1
  install -o root -g root -m 0644 "$stage/key" "$key"
  printf 'deb [signed-by=%s] https://pkgs.tailscale.com/stable/%s %s main\n' "$key" "$ID" "$suite" > "$source"
  chmod 0644 "$source"
  apt-get update
  apt-get install -y tailscale
fi
systemctl enable --now tailscaled
