# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time the dashboard's native state snapshot on a synthetic, disposable profile.

The desktop page asks for this snapshot whenever the bridge says something
changed. This builds a fresh profile in a temporary folder, fills it with
synthetic phone rows of a realistic size, and times what one refresh costs on
the Qt GUI thread: the snapshot, its JSON and its revision hash.

    python scripts/measure-desktop-state.py
    python scripts/measure-desktop-state.py --notifications 400 --messages 3000 --photos 300
    python scripts/measure-desktop-state.py --seed-only build/desktop-ui/my-test/profile

`--seed-only` adds the same synthetic rows to an existing disposable test
profile (for example one made by scripts/desktop-ui.py) and exits. Never point
it at a real profile. No account, phone, network or installed app is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import sys
import tempfile
from contextlib import nullcontext
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# A small synthetic JPEG-sized preview, as the photo grid keeps one per photo.
PREVIEW = "data:image/jpeg;base64," + "A" * 6000


def seed(profile: Path, notifications: int, messages: int, photos: int) -> None:
    """Synthetic rows only: obviously fake names, numbers and text."""
    device = "synthetic-phone"
    rows = []
    # Shapes follow frontend/src/workspace/types.ts and the phone feature tests.
    for n in range(notifications):
        rows.append(("phone_notification", f"n{n}", {"id": f"n{n}", "device_id": device, "key": f"synthetic|{n}", "app": "Synthetic chat",
                     "package": "org.example.chat", "title": f"Test contact {n % 40}", "text": f"Synthetic message body {n} " * 3,
                     "timestamp": 1_760_000_000_000 + n, "actions": [], "updated_at": "2026-10-18T00:00:00Z"}))
    threads = max(1, messages // 25)
    for t in range(threads):
        rows.append(("phone_thread", f"t{t}", {"id": f"t{t}", "device_id": device, "thread": t, "recipients": [f"+1555000{t:04d}"],
                     "message": {"body": "Synthetic snippet", "timestamp": 1_760_000_000_000 + t}}))
    for m in range(messages):
        rows.append(("phone_message", f"m{m}", {"id": f"m{m}", "device_id": device, "thread": m % threads, "message_id": m,
                     "body": f"Synthetic text message number {m}", "timestamp": 1_760_000_000_000 + m,
                     "direction": "incoming" if m % 2 else "outgoing"}))
    for p in range(photos):
        rows.append(("phone_photo", f"p{p}", {"id": f"p{p}", "device_id": device, "photo_id": str(p), "name": f"IMG_{p:05d}.jpg",
                     "timestamp": 1_760_000_000_000 + p, "width": 4000, "height": 3000, "size": 3_000_000,
                     "thumbnail": {"sha256": f"{p:064x}"}, "preview": PREVIEW}))
    with sqlite3.connect(profile / "workspace.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")
        db.executemany("INSERT OR REPLACE INTO records VALUES (?,?,?)", [(k, i, json.dumps(v)) for k, i, v in rows])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notifications", type=int, default=300)
    parser.add_argument("--messages", type=int, default=2000)
    parser.add_argument("--photos", type=int, default=150)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--seed-only", type=Path, metavar="PROFILE")
    parser.add_argument("--separate-connections", action="store_true", help="Open the database per read, as before Store.reading().")
    options = parser.parse_args(argv)
    if options.seed_only:
        profile = options.seed_only.resolve(strict=True)
        if not (profile / "settings.json").is_file():
            parser.error("Choose a disposable test profile that contains settings.json.")
        seed(profile, options.notifications, options.messages, options.photos)
        print(json.dumps({"seeded": str(profile)}))
        return 0
    os.environ["ORION_MINI_TEST"] = "1"
    sys.path.insert(0, str(REPO / "src"))
    with tempfile.TemporaryDirectory(prefix="saiph-state-", ignore_cleanup_errors=True) as directory:
        profile = Path(directory)
        (profile / "settings.json").write_text(json.dumps({"machine": {"name": "Test desktop"},
                                                          "start_with_windows": False, "close_to_tray": False}), encoding="utf-8")
        from orion_mini.link_service import LinkWorkspace
        workspace = LinkWorkspace(profile)
        seed(profile, options.notifications, options.messages, options.photos)
        workspace.dispatch("state", {})  # Warm imports and caches.
        timings, size = [], 0
        for _ in range(options.runs):
            began = time.perf_counter()
            # As the bridge builds it: one shared connection when the store offers one.
            reading = workspace.store.reading() if hasattr(workspace.store, "reading") and not options.separate_connections else nullcontext()
            with reading:
                snapshot = workspace.dispatch("state", {})
            body = json.dumps(snapshot)
            hashlib.sha256(body.encode()).hexdigest()
            timings.append((time.perf_counter() - began) * 1000)
            size = len(body)
        print(json.dumps({"synthetic": True, "bytes": size, "runs": options.runs,
                          "median_ms": round(statistics.median(timings), 1), "max_ms": round(max(timings), 1),
                          "rows": {"notifications": options.notifications, "messages": options.messages, "photos": options.photos}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
