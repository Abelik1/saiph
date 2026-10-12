#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Optional distribution-maintained upstream client; no profile or daemon setup.
set -eu
[ "$#" = 0 ] || exit 1
[ "$(id -u)" = 0 ] || exit 1
. /etc/os-release
case "$ID:$VERSION_ID" in
  ubuntu:22.04|ubuntu:24.04|debian:12|debian:13) ;;
  *) echo 'Use the official Seafile instructions for this operating system.' >&2; exit 1 ;;
esac
# Reuse the administrator's configured signed package repositories. Never add a
# PPA, change their trust policy, or import an account/network credential.
if [ ! -x /usr/bin/seaf-cli ]; then
  /usr/bin/apt-get update
  DEBIAN_FRONTEND=noninteractive /usr/bin/apt-get install -y --no-install-recommends seafile-cli
fi
[ -x /usr/bin/seaf-cli ]
