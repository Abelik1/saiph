# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resume and default-route detection for the Linux link reconnect."""
import sys

import pytest

from orion_mini import network_watch, phone


def write_routes(tmp_path, ipv4, ipv6=""):
    v4, v6 = tmp_path / "route", tmp_path / "ipv6_route"
    v4.write_text("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n" + ipv4)
    v6.write_text(ipv6)
    return v4, v6


def test_default_routes_read_ipv4_and_ipv6_defaults_only(tmp_path):
    paths = write_routes(
        tmp_path,
        "wlan-r1\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
        "wlan-r1\t0001A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0\n"
        "down-r1\t00000000\t0201A8C0\t0002\t0\t0\t700\t00000000\t0\t0\t0\n",  # not RTF_UP
        "00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000100 00000001 00000000 00000003 wlan-r1\n"
        "00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200 lo\n"
        "fd000000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001 wlan-r1\n")
    assert network_watch.default_routes(paths) == {("wlan-r1", "0101A8C0"), ("wlan-r1", "fe800000000000000000000000000001")}


def test_unreadable_route_files_are_no_routes(tmp_path):
    assert network_watch.default_routes((tmp_path / "missing", tmp_path / "missing6")) == frozenset()


def test_resume_and_route_changes_report_once():
    clock, routes = [100.0], [frozenset({("wlan-r1", "gw")})]
    watch = network_watch.NetworkWatch(clock=lambda: clock[0], routes=lambda: routes[0])
    assert not watch.changed()
    clock[0] += 0.4  # ordinary scheduling drift
    assert not watch.changed()
    clock[0] += 274.0  # slept 4.5 minutes
    assert watch.changed() and not watch.changed()
    routes[0] = frozenset()  # network went away
    assert watch.changed()
    routes[0] = frozenset({("eth-r1", "gw2")})  # another network
    assert watch.changed() and not watch.changed()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CLOCK_BOOTTIME is Linux-only")
def test_real_clocks_and_routes_work_here(monkeypatch):
    monkeypatch.delenv("ORION_MINI_TEST", raising=False)
    watch = phone.network_watch()
    assert isinstance(watch, network_watch.NetworkWatch)
    assert watch.changed() in (False, True)  # readable without errors


def test_runtime_has_no_watch_under_tests_or_off_linux(monkeypatch):
    monkeypatch.setenv("ORION_MINI_TEST", "1")
    assert phone.network_watch() is None
    monkeypatch.delenv("ORION_MINI_TEST")
    monkeypatch.setattr(phone.sys, "platform", "win32")
    assert phone.network_watch() is None
