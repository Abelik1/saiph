# SPDX-License-Identifier: AGPL-3.0-or-later
"""Consent and byte boundaries in the real service adapter; no OS clipboard or network."""
from io import BytesIO
from PIL import Image
import pytest

from orion_mini.clipboard import GuardedClipboardDelivery
from orion_mini.electron_runtime import ElectronRuntime


class Binary:
    def __init__(self):
        self.sent = []
    def publish(self, key, header, data):
        self.sent.append((key, header, data))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('ORION_MINI_TEST', '1')
    monkeypatch.setenv('ORION_MINI_DATA_DIR', str(tmp_path))
    binary = Binary()
    value = ElectronRuntime(tmp_path, lambda *_: None, lambda *_: None, binary=binary)
    try:
        yield value, binary
    finally:
        value.close()


def test_queued_clipboard_rechecks_remote_authority_and_local_consent(runtime):
    value, binary = runtime
    allowed = [True]
    observed = []
    def native(method, args):
        assert method == 'clipboard.write'
        assert value.authorize_clipboard(args['token'])
        allowed[0] = False  # Device revoked while its delivery was queued.
        observed.append(value.authorize_clipboard(args['token']))
    value.native = native
    value.clipboard_received('text/plain', GuardedClipboardDelivery(b'synthetic', lambda: allowed[0]))
    assert observed == [False]
    assert binary.sent[0][2] == b'synthetic'
    assert not value.deliveries
    assert not value.authorize_clipboard(binary.sent[0][0])
    binary.sent.clear()
    value.clipboard_received('text/plain', GuardedClipboardDelivery(b'denied', lambda: False))
    assert not binary.sent
    value.workspace.settings.setdefault('link', {})['clipboard'] = False
    value.clipboard_received('text/plain', b'opted out')
    assert not binary.sent


def test_clipboard_orientation_and_alias_bytes_prevent_image_echo(runtime):
    value, binary = runtime
    source = BytesIO()
    image = Image.new('RGB', (7, 3), 'red')
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, 'JPEG', exif=exif)
    authorized = []
    value.native = lambda method, args: authorized.append(value.authorize_clipboard(args['token']))
    value.clipboard_received('image/jpeg', source.getvalue())
    assert authorized == [True]
    header, prepared = binary.sent[0][1:]
    assert header['mime'] == 'image/png'
    with Image.open(BytesIO(prepared)) as decoded:
        assert decoded.size == (3, 7)
    # Cache knows the normalized image independently of the original JPEG.
    assert value.phone_runtime.clipboard_cache.claim('image/png', prepared) is None


def test_original_photo_decode_is_bounded_before_native_image_allocation(tmp_path):
    picture = tmp_path / 'synthetic.png'
    Image.new('RGB', (4, 5)).save(picture)
    ElectronRuntime.validate_photo(picture)
    picture.write_bytes(b'invalid image')
    with pytest.raises((ValueError, OSError)):
        ElectronRuntime.validate_photo(picture)


def test_original_photo_copy_and_drag_apply_exif_before_native_decode(runtime, tmp_path):
    value, binary = runtime
    file = tmp_path / 'portrait.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (7, 3), 'red').save(file, 'JPEG', exif=exif)
    calls = []
    value.native = lambda method, args: calls.append((method, args))
    for method in ('photo.view', 'photo.copy', 'photo.drag'):
        value.native_photo(method, str(file))
        assert (calls[-1][1]['width'], calls[-1][1]['height']) == (3, 7)
    assert len(binary.sent) == 2
    for _, header, data in binary.sent:
        assert header['kind'] == 'image'
        with Image.open(BytesIO(data)) as image:
            assert image.size == (3, 7)


def test_a_phones_webcam_request_starts_only_after_accept(runtime):
    value, _ = runtime
    started, offered, answers = [], [], [False, True]
    class Camera:
        local = type('Local', (), {'state': 'idle'})
        def stop(self): pass
        def status(self): return {'integrated_available': True}
        def start_local(self, preview): started.append(preview); return {'session': 'a' * 32}
        def offer_to_phone(self, session, device): offered.append((session, device))
    value.workspace.camera = Camera()
    asked = []
    def native(method, args):
        asked.append((method, args))
        return answers.pop(0)
    value.native = native
    # Run the prompt inline; the hosted thread normally hands it to the executor.
    value.announce = lambda: None
    value.executor = type('Inline', (), {'submit': staticmethod(lambda work: work()), 'shutdown': staticmethod(lambda **_: None)})()
    value.workspace.camera_requested('phone-1', 'Synthetic phone')  # Decline.
    assert asked == [('camera.request', {'phone': 'Synthetic phone'})] and started == [] and offered == []
    value.workspace.camera_requested('phone-1', 'Synthetic phone')  # Accept.
    assert started == [False] and offered == [('a' * 32, 'phone-1')]


def test_ringing_never_makes_the_event_loop_wait_for_the_window(runtime):
    import threading
    value, _ = runtime
    released, called = threading.Event(), threading.Event()
    def native(method, args):
        assert (method, args) == ('ring', {'phone': 'Synthetic phone'})
        called.set()
        assert released.wait(5)  # The Stop window is still open.
    value.native = native
    value.workspace.ring_requested('Synthetic phone')  # Returns with the window still open.
    assert called.wait(5)
    released.set()
