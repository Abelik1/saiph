# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session startup operates on owned entries and the installed stable launcher."""
import os
from pathlib import Path

import pytest

from orion_mini import platform


@pytest.fixture
def session(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    config = tmp_path / 'xdg-config'
    monkeypatch.setattr(platform.sys, 'platform', 'linux')
    monkeypatch.setattr(platform.Path, 'home', lambda: home)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setattr(platform.sys, 'frozen', True, raising=False)
    launcher = home / '.local/bin/orion'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\n# ORION_OWNED=1\nexec installed-current\n', encoding='utf-8')
    return home, config, launcher


def test_installed_startup_uses_installer_filename_xdg_and_stable_launcher(session, monkeypatch):
    home, config, launcher = session
    monkeypatch.setattr(platform.sys, 'executable', str(home / '.local/lib/orion/releases/1.0.0/app/OrionMini'))
    platform.set_startup(True)
    entry = config / 'autostart/orion.desktop'
    initial = entry.read_text()
    assert '# ORION_OWNED=1' in initial
    assert 'Exec=' + platform._desktop_quote(launcher) + '\n' in initial
    assert 'releases/' not in initial and 'orion-mini.desktop' not in initial
    # A new release keeps the same startup target and remains removable.
    monkeypatch.setattr(platform.sys, 'executable', str(home / '.local/lib/orion/releases/2.0.0/app/OrionMini'))
    platform.set_startup(True)
    assert entry.read_text() == initial
    platform.set_startup(False)
    assert not entry.exists()
    assert not (home / '.config/autostart/orion.desktop').exists()


@pytest.mark.parametrize('enabled', [True, False])
def test_unrelated_startup_entry_preserved(session, enabled):
    _, config, _ = session
    entry = config / 'autostart/orion.desktop'
    entry.parent.mkdir(parents=True)
    original = '[Desktop Entry]\nName=Someone else\nExec=other-app\n'
    entry.write_text(original)
    with pytest.raises(ValueError, match='unrelated startup entry was preserved'):
        platform.set_startup(enabled)
    assert entry.read_text() == original


def test_installed_startup_accepts_owned_disabled_entry(session):
    _, config, _ = session
    platform.set_startup(True)
    entry = config / 'autostart/orion.desktop'
    entry.write_text(entry.read_text().replace('enabled=true', 'enabled=false'))
    platform.set_startup(False)
    assert not entry.exists()


def test_portable_copy_does_not_write_broken_startup(session):
    _, config, launcher = session
    launcher.unlink()
    with pytest.raises(ValueError, match='Install Saiph'):
        platform.set_startup(True)
    assert not (config / 'autostart/orion.desktop').exists()


def test_source_startup_keeps_legacy_filename_and_exact_legacy_entry(session, monkeypatch):
    _, config, _ = session
    monkeypatch.setattr(platform.sys, 'frozen', False)
    platform.set_startup(True)
    entry = config / 'autostart/orion-mini.desktop'
    assert ' -m orion_mini\n' in entry.read_text()
    # Existing source entries predate the ownership marker.
    entry.write_text(entry.read_text().replace('# ORION_OWNED=1\n', '').replace('Name=Saiph\n', 'Name=Orion Mini\n'))
    platform.set_startup(False)
    assert not entry.exists()


def test_relative_xdg_root_refused_without_writing(session, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', 'relative-config')
    with pytest.raises(ValueError, match='absolute local folder'):
        platform.set_startup(True)


def test_exec_field_escapes_percent_and_reserved_characters():
    assert platform._desktop_quote('a%file$`"\\') == '"a%%file\\$\\`\\"\\\\"'


@pytest.mark.skipif(os.name == 'nt', reason='Unix symlink fixture')
@pytest.mark.parametrize('enabled', [True, False])
def test_symlink_startup_entry_is_preserved(session, tmp_path, enabled):
    _, config, _ = session
    entry = config / 'autostart/orion.desktop'
    entry.parent.mkdir(parents=True)
    target = tmp_path / 'unrelated.desktop'
    target.write_text('preserve me')
    entry.symlink_to(target)
    with pytest.raises(ValueError, match='redirected or unrelated'):
        platform.set_startup(enabled)
    assert entry.is_symlink() and target.read_text() == 'preserve me'


@pytest.mark.parametrize("enabled", [True, False])
def test_existing_orion_startup_can_be_controlled_after_brand_upgrade(session, enabled):
    _, config, launcher = session
    entry = config / "autostart/orion.desktop"
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]\n# ORION_OWNED=1\nType=Application\nName=Orion\nExec="
                     + platform._desktop_quote(launcher)
                     + "\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
    platform.set_startup(enabled)
    if enabled:
        assert "Name=Saiph\n" in entry.read_text()
        assert "Exec=" + platform._desktop_quote(launcher) + "\n" in entry.read_text()
    else:
        assert not entry.exists()
