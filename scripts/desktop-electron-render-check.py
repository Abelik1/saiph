# SPDX-License-Identifier: AGPL-3.0-or-later
"""Capture only the exact isolated Electron test window through Windows Graphics Capture.

Optional test dependencies: windows-capture, numpy, Pillow. Run during the standard
visible UI flow. Stable corner strips catch missing tiles; saved candidates need
review and are not a universal GPU stability claim. No desktop-wide capture.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import re
from pathlib import Path
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--label', default='os-frames')
    args = parser.parse_args()
    descriptor = args.session.resolve(strict=True)
    session = json.loads(descriptor.read_text())
    if (session.get('shell') != 'electron' or session.get('mode') != 'isolated'
            or session.get('status') != 'ready' or session.get('existing_profile') is not False
            or Path(session['profile']).resolve() != descriptor.parent / 'profile'
            or not session.get('show') or not 5 <= args.seconds <= 3600
            or not re.fullmatch(r'[a-z0-9-]{1,40}', args.label)):
        raise ValueError('Choose a ready visible isolated Electron test session.')
    from windows_capture import WindowsCapture
    import numpy as np
    from PIL import Image
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == session['pid'] and user.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True
    user.EnumWindows(visit, 0)
    if len(windows) != 1:
        raise ValueError('Expected exactly one visible window owned by this isolated session PID.')
    dwm = ctypes.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    output = descriptor.parent / 'evidence' / args.label
    output.mkdir(parents=True, exist_ok=False)
    statistics = {'frames': 0, 'sizes': [], 'candidates': [], 'self_test': False, 'resize_extent_mismatches': 0,
                  'scope': 'Exact isolated Electron PID/window only, Windows Graphics Capture',
                  'limit': 'Corner-strip comparison; inspect candidates. Does not prove multi-day or other-hardware stability.'}
    references, counts, lock = {}, {}, threading.Lock()
    stop = threading.Event()
    begun = time.monotonic()
    def strips(image):
        h, w = image.shape[:2]
        # Caption/borders are excluded. The logo, computer name and footer text
        # remain fixed across tabs. Reference separately for each native extent.
        return [image[40:85, 18:135, :3].astype(np.int16), image[40:85, w-180:w-18, :3].astype(np.int16),
                image[h-25:h-6, 20:180, :3].astype(np.int16), image[h-25:h-6, w-175:w-20, :3].astype(np.int16)]
    capture = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=windows[0])
    @capture.event
    def on_frame_arrived(frame, control):
        if stop.is_set():
            control.stop()
            return
        image = np.array(frame.frame_buffer, copy=True)
        key = image.shape[:2]
        with lock:
            statistics['frames'] += 1
            bounds = wintypes.RECT()
            if dwm.DwmGetWindowAttribute(windows[0], 9, ctypes.byref(bounds), ctypes.sizeof(bounds)) != 0:
                raise OSError('The isolated window extent is unavailable.')
            extent = (bounds.bottom - bounds.top, bounds.right - bounds.left)
            if key != extent:
                # WGC can deliver the previous frame-pool texture during resize,
                # including stale pixels outside the window's current bounds.
                # Keep that evidence separately; it is not a current-window frame.
                statistics['resize_extent_mismatches'] += 1
                if statistics['resize_extent_mismatches'] <= 3:
                    Image.fromarray(image[:, :, [2,1,0]]).save(output / ('resize-extent-%d.png' % statistics['resize_extent_mismatches']))
                return
            counts[key] = counts.get(key, 0) + 1
            if counts[key] < 12:
                return  # Let resize/compositor transitions settle.
            value = strips(image)
            if key not in references:
                references[key] = value
                broken = image.copy()
                broken[:, 64:128, :3] = 12
                statistics['self_test'] = statistics['self_test'] or any((np.abs(a-b) > 45).sum() > 300 for a,b in zip(value,strips(broken)))
                Image.fromarray(image[:, :, [2,1,0]]).save(output / ('reference-%dx%d.png' % key))
                return
            delta = [int((np.abs(a-b) > 45).sum()) for a,b in zip(value,references[key])]
            if any(count > 300 for count in delta):
                number = len(statistics['candidates']) + 1
                statistics['candidates'].append({'frame': statistics['frames'], 'seconds': round(time.monotonic()-begun, 3), 'changed_components': delta})
                if number <= 12:
                    Image.fromarray(image[:, :, [2,1,0]]).save(output / f'candidate-{number}.png')
    @capture.event
    def on_closed():
        stop.set()
    controller = capture.start_free_threaded()
    try:
        stop.wait(args.seconds)
    finally:
        stop.set()
        controller.stop()
        statistics['sizes'] = [list(size) for size in references]
        statistics['seconds'] = round(time.monotonic()-begun, 2)
        (output / 'results.json').write_text(json.dumps(statistics, indent=2))
    print(json.dumps(statistics))
    return 0 if statistics['frames'] and statistics['self_test'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
