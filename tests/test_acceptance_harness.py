# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endpoint comparisons in the attended laptop/phone harness."""
import importlib.util
from pathlib import Path

from PySide6.QtGui import QColor, QColorSpace, QImage

spec = importlib.util.spec_from_file_location(
    'acceptance_laptop_phone', Path(__file__).parents[1] / 'scripts/acceptance-laptop-phone.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def board():
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    for y in range(16):
        for x in range(24):
            image.setPixelColor(x, y, QColor('#26b6cb' if (x // 4 + y // 4) % 2 else '#293541'))
    return image


def test_pasted_srgb_png_with_identical_pixels_matches():
    # Physical acceptance on GNOME: the phone's image arrived pixel-identical but
    # tagged sRGB, and QImage == treated the colour space as a difference.
    pasted = board().convertToFormat(QImage.Format.Format_ARGB32)
    pasted.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    assert pasted.convertToFormat(QImage.Format.Format_RGB32) != board()
    assert harness.same_pixels(pasted, board())


def test_one_different_pixel_or_size_still_fails():
    changed = board()
    changed.setPixelColor(3, 2, QColor('#ffffff'))
    assert not harness.same_pixels(changed, board())
    assert not harness.same_pixels(board().scaled(12, 8), board())


def test_pad_build_picks_newest_sdk_folders_and_windows_tool_names(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('pad_build', Path(__file__).parents[1] / 'scripts/acceptance-phone-pad/build.py')
    build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)
    names = ['android-36', 'android-37.0', 'android-Baklava']
    assert max((tmp_path / n for n in names), key=build.version_key).name == 'android-37.0'
    assert max((tmp_path / n for n in ['36.0.0', '37.0.0-rc1', '35.0.1']), key=build.version_key).name == '37.0.0-rc1'
    tools = tmp_path / 'build-tools'; tools.mkdir()
    (tools / 'd8.bat').write_text('')
    monkeypatch.setattr(build.os, 'name', 'nt')
    assert build.sdk_tool(tools, 'd8') == tools / 'd8.bat'
    monkeypatch.setattr(build.os, 'name', 'posix')
    assert build.sdk_tool(tools, 'd8') == tools / 'd8'
