# SPDX-License-Identifier: AGPL-3.0-or-later
"""Original images cross the real native bridge without thumbnail resizing."""
import json
import pathlib
import struct

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from orion_mini.desktop_bridge import DesktopBridge
from orion_mini.link_service import LinkWorkspace


class Window(QObject):
    """The minimal window surface DesktopBridge uses, over an isolated Link workspace."""
    def __init__(self, root):
        super().__init__()
        self.workspace = LinkWorkspace(root)

    def pump_jobs(self):
        pass


@pytest.mark.parametrize("width,height,orientation", [(960, 320, None), (320, 960, None), (320, 960, 6)])
def test_original_view_and_copy_preserve_pixels_and_encoded_file(tmp_path, qtbot, width, height, orientation):
    window = Window(tmp_path)
    bridge = DesktopBridge(window)
    path = tmp_path / "Original photo.jpg"
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF2468AC)
    assert image.save(str(path), "JPEG", 96)
    if orientation:
        # A real EXIF orientation tag, independent of Pillow or a phone fixture.
        tiff = b"II" + struct.pack("<HIH", 42, 8, 1)
        tiff += struct.pack("<HHIHHI", 0x112, 3, 1, orientation, 0, 0)
        exif = b"Exif\0\0" + tiff
        data = path.read_bytes()
        path.write_bytes(data[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + data[2:])
    original = path.read_bytes()
    features = window.workspace.phone_features
    window.workspace.store.save("phone_photo_original", {
        "id": features._photo_key("phone", "17"), "device_id": "phone", "photo_id": "17",
        "path": str(path), "name": path.name, "size": len(original),
    })
    responses = []
    bridge.response.connect(lambda raw: responses.append(json.loads(raw)))
    args = json.dumps({"device_id": "phone", "photo_id": "17"})
    bridge.request("view", "phone.photo.view", args)
    qtbot.waitUntil(lambda: len(responses) == 1, timeout=5000)
    view = responses[-1]
    assert view["ok"], view
    expected = (height, width) if orientation else (width, height)
    assert (view["result"]["width"], view["result"]["height"]) == expected
    assert pathlib.Path(QUrl(view["result"]["url"]).toLocalFile()) == path
    bridge.request("copy", "phone.photo.copy", args)
    qtbot.waitUntil(lambda: len(responses) == 2, timeout=5000)
    assert responses[-1]["ok"], responses[-1]
    clipboard = QApplication.clipboard()
    copied = clipboard.image()
    assert (copied.width(), copied.height()) == expected
    assert copied.pixelColor(20, 20).blue() > copied.pixelColor(20, 20).red()
    assert bytes(clipboard.mimeData().data("image/jpeg")) == original
    assert path.read_bytes() == original
    assert not window.workspace.store.all("phone_photo_save")
    clipboard.clear()


def test_copy_rejects_unreadable_original_without_replacing_clipboard(tmp_path, qtbot):
    window = Window(tmp_path)
    bridge = DesktopBridge(window)
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    features = window.workspace.phone_features
    window.workspace.store.save("phone_photo_original", {"id": features._photo_key("phone", "17"), "path": str(path)})
    QApplication.clipboard().setText("keep this")
    responses = []
    bridge.response.connect(lambda raw: responses.append(json.loads(raw)))
    bridge.request("copy", "phone.photo.copy", json.dumps({"device_id": "phone", "photo_id": "17"}))
    qtbot.waitUntil(lambda: bool(responses), timeout=5000)
    assert not responses[0]["ok"]
    assert "format" in responses[0]["error"]
    assert QApplication.clipboard().text() == "keep this"
    QApplication.clipboard().clear()


def test_original_action_accepts_photo_identifiers_instead_of_arbitrary_paths(tmp_path, qtbot):
    bridge = DesktopBridge(Window(tmp_path))
    responses = []
    bridge.response.connect(lambda raw: responses.append(json.loads(raw)))
    bridge.request("copy", "phone.photo.copy", json.dumps({"path": "/private/photo.jpg"}))
    assert not responses[0]["ok"]
