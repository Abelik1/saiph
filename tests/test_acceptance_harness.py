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
