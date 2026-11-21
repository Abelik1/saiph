# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded image decoding for services, independent of a GUI event loop."""
from __future__ import annotations
from io import BytesIO


def decoded(data, *, expected=None, max_pixels=40_000_000, orient=False):
    from PIL import Image, ImageOps
    image = Image.open(BytesIO(data))
    if (expected is not None and image.format != expected) or min(image.size) < 1 or image.width * image.height > max_pixels:
        image.close()
        raise ValueError('Invalid image format or dimensions.')
    image.load()
    return ImageOps.exif_transpose(image) if orient else image


def png_bytes(data, *, max_pixels=40_000_000):
    with decoded(data, max_pixels=max_pixels, orient=True) as image:
        output = BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()


def camera_pixels(data, width, height, rotation, sink):
    from PIL import Image, ImageOps
    with decoded(data, expected='JPEG') as source:
        dimensions = source.size
        if not sink:
            return dimensions, None
        upright = source.rotate(-rotation, expand=True) if rotation else source
        fitted = ImageOps.contain(upright, (width, height), Image.Resampling.BILINEAR)
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 255))
        canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
        return dimensions, canvas.tobytes()
