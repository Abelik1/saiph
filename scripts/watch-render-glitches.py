# SPDX-License-Identifier: AGPL-3.0-or-later
"""Watch a running Saiph dashboard's own frames for rendering glitches, passively.

Connects to the DevTools endpoint of an already running instance (a test session
or an installed app started with its debug port), asks Chromium for a screencast
of the frames it produces, and checks each one: the header's left and right ends
and the footer's ends look the same on every page, so a frame where they differ
from their usual look was drawn broken by Chromium itself. It never clicks, types,
focuses, resizes or moves anything, and never saves a picture of the page: only
timestamps and how many strip pixels deviated, so it is safe beside real data.

Compare its log with the moments someone saw blocks, stripes or pixelation:
glitches logged here come from Chromium; glitches seen on screen but not logged
here happen later, while Qt or Windows present the frame.

    python scripts/watch-render-glitches.py --endpoint http://127.0.0.1:9222 --minutes 10
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime
from urllib.request import urlopen


def strips(grey):
    h, w = grey.shape
    return {"header-left": grey[4:58, 8:72], "header-right": grey[4:58, w - 240:w - 8],
            "footer-left": grey[h - 24:h - 4, 8:200], "footer-right": grey[h - 24:h - 4, w - 200:w - 8]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True, help="The instance's DevTools endpoint, e.g. http://127.0.0.1:9222 (loopback only).")
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--settle", type=int, default=3, help="Identical frames needed before a size's look is trusted.")
    options = parser.parse_args(argv)
    if not options.endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
        parser.error("Only a loopback DevTools endpoint on this computer.")
    import numpy as np
    from PySide6.QtGui import QImage
    from websockets.sync.client import connect

    targets = json.loads(urlopen(options.endpoint.rstrip("/") + "/json", timeout=10).read())
    page = next(t for t in targets if t.get("type") == "page" and "index.html" in t.get("url", ""))
    socket = connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=10, legacy=True)
    socket.send(json.dumps({"id": 1, "method": "Page.startScreencast", "params": {"format": "png", "everyNthFrame": 1}}))
    references, candidates, frames, glitches = {}, {}, 0, []
    began, deadline = time.time(), time.time() + options.minutes * 60
    try:
        while time.time() < deadline:
            try:
                message = json.loads(socket.recv(timeout=1))
            except TimeoutError:
                continue
            if message.get("method") != "Page.screencastFrame":
                continue
            params = message["params"]
            socket.send(json.dumps({"id": 2, "method": "Page.screencastFrameAck", "params": {"sessionId": params["sessionId"]}}))
            image = QImage.fromData(base64.b64decode(params["data"])).convertToFormat(QImage.Format.Format_RGB32)
            raw = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), :3]
            grey = raw.astype(np.int16).mean(axis=2)
            frames += 1
            current = strips(grey)
            if grey.shape not in references:
                # A new size (the window was resized): trust its look once it repeats.
                seen = candidates.setdefault(grey.shape, [])
                if seen and all(int((np.abs(current[n] - seen[-1][n]) > 40).sum()) <= 25 for n in current):
                    seen.append(current)
                else:
                    seen[:] = [current]
                if len(seen) >= options.settle:
                    references[grey.shape] = current
                continue
            bad = {n: int((np.abs(s - references[grey.shape][n]) > 40).sum()) for n, s in current.items()}
            bad = {n: c for n, c in bad.items() if c > 25}
            if bad:
                event = {"time": datetime.now().isoformat(timespec="milliseconds"), "strips": bad}
                glitches.append(event)
                print(json.dumps(event), flush=True)
    finally:
        try:
            socket.send(json.dumps({"id": 3, "method": "Page.stopScreencast"}))
            socket.close()
        except Exception:
            pass
    print(json.dumps({"minutes": round((time.time() - began) / 60, 1), "frames": frames, "glitches": len(glitches),
                      "sizes_trusted": len(references)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
