# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ask the operating system to confirm the signed-in person before sensitive actions.

Adding a device grants it future clipboard, notification and file content, so
an unlocked computer alone must not be enough. On Windows this uses Windows
Hello (face, fingerprint or PIN) through ``UserConsentVerifier``, parented to
the Saiph window. No credential, biometric or result detail reaches Saiph:
Windows reports only whether the person was verified.

Where no verifier exists (Linux, or Windows Hello not set up), actions keep
their existing on-screen confirmation and the snapshot says protection is
unavailable, so the interface can ask the person to set it up. A refusal,
cancellation or busy verifier always stops the action.
"""
from __future__ import annotations

import hashlib
import sys
import threading
import time
import uuid

VERIFIED = "verified"
UNAVAILABLE = "unavailable"

# Windows.Security.Credentials.UI enumerations.
_AVAILABLE = 0
_RESULT_VERIFIED = 0
_RESULT_UNAVAILABLE = {1, 2, 3}  # DeviceNotPresent, NotConfiguredForUser, DisabledByPolicy
_RESULT_TEXT = {
    4: "Windows Hello is busy. Try again.",
    5: "Windows Hello locked after too many attempts. Try again later.",
    6: "Verification was cancelled. Nothing was changed.",
}

_CLASS = "Windows.Security.Credentials.UI.UserConsentVerifier"
_STATICS = "af4f3f91-564c-4ddc-b8b5-973447627c65"
_INTEROP = "39e050c3-4e74-441a-8dc0-b81104df949c"
_ASYNC_INFO = "00000036-0000-0000-c000-000000000046"
_ASYNC_OPERATION = "9fc2b0bb-e446-44e2-aa61-9cab8f636af2"
_WINRT_NAMESPACE = "11f47ad5-7b73-42c0-abae-878b1e16adee"


class UserVerificationError(ValueError):
    """The person was not verified; the sensitive action must not continue."""


def parameterized_iid(signature: str) -> str:
    """WinRT parameterized interface ID (RFC 4122 version 5 over the type signature)."""
    digest = bytearray(hashlib.sha1(uuid.UUID(_WINRT_NAMESPACE).bytes + signature.encode("utf-8")).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x50
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def async_operation_iid(enum_name: str) -> str:
    return parameterized_iid("pinterface({%s};enum(%s;i4))" % (_ASYNC_OPERATION, enum_name))


class _WindowsHello:
    """Minimal WinRT calls through ctypes; no extra runtime dependency."""

    TIMEOUT_SECONDS = 180

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.combase = ctypes.WinDLL("combase")

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]
        self.GUID = GUID

    def guid(self, value):
        return self.GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    def call(self, pointer, index, *args, argtypes=()):
        ctypes = self.ctypes
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        function = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
        return function(pointer, *args)

    def release(self, pointer):
        if pointer:
            self.call(pointer, 2)

    def check(self, result):
        if result < 0:
            raise OSError("Windows Hello is unavailable.")

    def hstring(self, text):
        ctypes = self.ctypes
        value = ctypes.c_void_p()
        self.check(self.combase.WindowsCreateString(ctypes.c_wchar_p(text), ctypes.c_uint32(len(text)), ctypes.byref(value)))
        return value

    def factory(self, interface):
        ctypes = self.ctypes
        name, result = self.hstring(_CLASS), ctypes.c_void_p()
        try:
            iid = self.guid(interface)
            self.check(self.combase.RoGetActivationFactory(name, ctypes.byref(iid), ctypes.byref(result)))
        finally:
            self.combase.WindowsDeleteString(name)
        return result

    def wait(self, operation):
        """Poll IAsyncInfo, then read the operation's enumeration result."""
        ctypes = self.ctypes
        info = ctypes.c_void_p()
        iid = self.guid(_ASYNC_INFO)
        self.check(self.call(operation, 0, ctypes.byref(iid), ctypes.byref(info),
                             argtypes=(ctypes.POINTER(self.GUID), ctypes.POINTER(ctypes.c_void_p))))
        try:
            status, deadline = ctypes.c_int32(0), time.monotonic() + self.TIMEOUT_SECONDS
            while True:
                self.check(self.call(info, 7, ctypes.byref(status), argtypes=(ctypes.POINTER(ctypes.c_int32),)))
                if status.value != 0:
                    break
                if time.monotonic() >= deadline:
                    self.call(info, 9)  # Cancel
                    raise UserVerificationError("Verification timed out. Nothing was changed.")
                time.sleep(0.05)
            if status.value != 1:  # Completed; Canceled=2, Error=3
                raise UserVerificationError(_RESULT_TEXT[6] if status.value == 2 else "Windows Hello could not verify you.")
            result = ctypes.c_int32(-1)
            self.check(self.call(operation, 8, ctypes.byref(result), argtypes=(ctypes.POINTER(ctypes.c_int32),)))
            return result.value
        finally:
            self.release(info)

    def apartment(self, run):
        """Each call uses its own initialized thread (Saiph calls these off the GUI thread)."""
        initialized = self.combase.RoInitialize(1)  # Multithreaded; RPC_E_CHANGED_MODE is acceptable.
        try:
            return run()
        finally:
            if initialized in (0, 1):
                self.combase.RoUninitialize()

    def available(self) -> bool:
        def run():
            ctypes = self.ctypes
            statics, operation = self.factory(_STATICS), ctypes.c_void_p()
            try:
                self.check(self.call(statics, 6, ctypes.byref(operation), argtypes=(ctypes.POINTER(ctypes.c_void_p),)))
                try:
                    return self.wait(operation) == _AVAILABLE
                finally:
                    self.release(operation)
            finally:
                self.release(statics)
        return self.apartment(run)

    def verify(self, message: str, window: int | None) -> int:
        def run():
            ctypes = self.ctypes
            text, operation = self.hstring(message), ctypes.c_void_p()
            try:
                if window:
                    interop = self.factory(_INTEROP)
                    try:
                        iid = self.guid(async_operation_iid("Windows.Security.Credentials.UI.UserConsentVerificationResult"))
                        self.check(self.call(interop, 6, ctypes.c_void_p(window), text, ctypes.byref(iid), ctypes.byref(operation),
                                             argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(self.GUID),
                                                       ctypes.POINTER(ctypes.c_void_p))))
                    finally:
                        self.release(interop)
                else:
                    statics = self.factory(_STATICS)
                    try:
                        self.check(self.call(statics, 7, text, ctypes.byref(operation),
                                             argtypes=(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))))
                    finally:
                        self.release(statics)
                try:
                    return self.wait(operation)
                finally:
                    self.release(operation)
            finally:
                self.combase.WindowsDeleteString(text)
        return self.apartment(run)


class UserPresence:
    """Serialises verification prompts; ``window`` returns the parent HWND or None."""

    def __init__(self, window=None, *, backend=None, platform=None):
        self.window = window
        self.platform = sys.platform if platform is None else platform
        self._backend = backend
        self._status = None
        self._lock = threading.Lock()

    def backend(self):
        if self._backend is None and self.platform == "win32":
            try:
                self._backend = _WindowsHello()
            except (OSError, AttributeError):
                self._backend = None
        return self._backend

    def status(self) -> str:
        """Cached ``"windows_hello"`` or ``"unavailable"``; cheap after the first call."""
        if self._status is None:
            backend = self.backend()
            try:
                self._status = "windows_hello" if backend is not None and backend.available() else UNAVAILABLE
            except (OSError, UserVerificationError):
                self._status = UNAVAILABLE
        return self._status

    def cached_status(self) -> str:
        return self._status or "checking"

    def confirm(self, reason: str) -> str:
        """Return VERIFIED or UNAVAILABLE; raise UserVerificationError on refusal."""
        if type(reason) is not str or not 0 < len(reason) <= 200:
            raise ValueError("Describe the action to verify.")
        backend = self.backend()
        if backend is None:
            self._status = UNAVAILABLE
            return UNAVAILABLE
        if not self._lock.acquire(timeout=1):
            raise UserVerificationError("Another verification is already open.")
        try:
            window = self.window() if callable(self.window) else self.window
            try:
                result = backend.verify("Saiph: " + reason, window)
            except OSError:
                # The verifier itself could not start; Windows did not refuse the person.
                self._status = UNAVAILABLE
                return UNAVAILABLE
        finally:
            self._lock.release()
        if result == _RESULT_VERIFIED:
            self._status = "windows_hello"
            return VERIFIED
        if result in _RESULT_UNAVAILABLE:
            self._status = UNAVAILABLE
            return UNAVAILABLE
        raise UserVerificationError(_RESULT_TEXT.get(result, "Windows Hello could not verify you. Nothing was changed."))


def confirm(workspace, reason: str) -> str:
    """Verify through the workspace's presence, if the desktop window installed one.

    Headless and test workspaces have none; they never open a system prompt.
    """
    presence = getattr(workspace, "user_presence", None)
    return UNAVAILABLE if presence is None else presence.confirm(reason)


def status(workspace) -> str:
    presence = getattr(workspace, "user_presence", None)
    return UNAVAILABLE if presence is None else presence.cached_status()
