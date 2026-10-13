# SPDX-License-Identifier: AGPL-3.0-or-later
"""Notice a Linux resume or default-route change so the link reconnects at once.

CLOCK_BOOTTIME keeps counting while the system sleeps and CLOCK_MONOTONIC does
not, so a jump in their difference is a resume. The default routes in /proc are
the network the link uses; a change means a new or restored network. Reading
both is cheap enough for the phone runtime's half-second loop and needs no
D-Bus session or desktop-specific service."""
from __future__ import annotations

import time
from pathlib import Path

RESUME_GAP = 2.0
ROUTES = (Path("/proc/net/route"), Path("/proc/net/ipv6_route"))


def default_routes(paths=ROUTES):
    """The interfaces and gateways of the current default routes (IPv4 and IPv6)."""
    routes = set()
    for path in paths:
        try:
            lines = path.read_text(encoding="ascii", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if path.name == "route":
                # Iface Destination Gateway Flags ...; RTF_UP is flag 0x1.
                if len(fields) > 3 and fields[1] == "00000000" and fields[3] != "Flags" and int(fields[3], 16) & 1:
                    routes.add((fields[0], fields[2]))
            elif len(fields) == 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[9] != "lo":
                routes.add((fields[9], fields[4]))
    return frozenset(routes)


class NetworkWatch:
    def __init__(self, *, clock=None, routes=default_routes):
        self.clock = clock or self._sleep_offset
        self.routes = routes
        self.offset = self.clock()
        self.current = routes()

    @staticmethod
    def _sleep_offset():
        return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)

    def changed(self) -> bool:
        """True once after a resume or a default-route change since the last call."""
        offset, current = self.clock(), self.routes()
        resumed = offset - self.offset > RESUME_GAP
        moved = current != self.current
        self.offset, self.current = offset, current
        return resumed or moved
