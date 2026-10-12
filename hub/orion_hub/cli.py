# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import argparse, os, sqlite3, tempfile
from datetime import datetime, timezone
from pathlib import Path
from . import releases, phone_backup, desktop_releases, cloud_provisioning
from .db import Database
from .security import create_pairing_code


def backup_database(data: Path, keep: int) -> Path:
    """Verified private online copies; retain a Cloud companion when configured."""
    from .state_backup import snapshot_pair
    folder = data / 'backups'
    if any(item.is_symlink() for item in (folder, *folder.parents)):
        raise ValueError('Private recovery destination is unavailable')
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != 'nt': folder.chmod(0o700)
    target = folder / f"orion-hub-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.sqlite3"
    # A completed main file is the publication marker. Other simultaneous
    # backups/retention runs must never see a partially written SQLite copy.
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=folder) as staging:
        staged = Path(staging) / target.name
        snapshot_pair(data, staged)
        companion = staged.with_suffix('.cloud')
        if companion.exists(): os.replace(companion, target.with_suffix('.cloud'))
        try:
            os.replace(staged, target)
        except BaseException:
            target.with_suffix('.cloud').unlink(missing_ok=True)
            raise
    for old in sorted(folder.glob('orion-hub-*.sqlite3'))[:-max(1, keep)]:
        # Retain redirected or unrecognized files rather than following them.
        if old.is_symlink(): continue
        companion = old.with_suffix('.cloud')
        if not companion.is_symlink(): companion.unlink(missing_ok=True)
        old.unlink()
    return target


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pair = sub.add_parser("pair")
    pair.add_argument("--minutes", type=int, default=10)
    pair.add_argument("--qr", type=Path, help="write a private one-use pairing QR as SVG; do not print its code")
    pair.add_argument("--hub-url", default="http://100.64.0.1:8765")
    enroll = sub.add_parser("enroll", help="write a private single-use device invitation and QR")
    enroll.add_argument("--output", required=True, type=Path)
    enroll.add_argument("--minutes", type=int, default=10)
    enroll.add_argument("--hub-url")
    enroll.add_argument("--mesh-login-server", default=os.environ.get("ORION_MESH_LOGIN_SERVER"))
    sub.add_parser("devices")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("device_id")
    publish = sub.add_parser("publish-android", help="make an APK the build phones update to")
    publish.add_argument("apk", type=Path)
    publish.add_argument("--version-code", type=int, required=True)
    publish.add_argument("--version-name", required=True)
    sub.add_parser("android")
    desktop = sub.add_parser('publish-desktop', help='stage a private native installer for paired mesh computers')
    desktop.add_argument('installer', type=Path)
    desktop.add_argument('--platform', choices=sorted(desktop_releases.PLATFORMS), required=True)
    desktop.add_argument('--profile', choices=sorted(desktop_releases.PROFILES), required=True)
    desktop.add_argument('--build-number', type=int, required=True)
    desktop.add_argument('--version', required=True)
    backup = sub.add_parser("backup", help="copy the database into data/backups, keeping recent copies")
    backup.add_argument("--keep", type=int, default=14)
    a = p.parse_args()
    data = Path(os.environ.get("ORION_HUB_DATA", "./data"))
    if a.cmd == 'publish-desktop':
        try:
            release = desktop_releases.publish(data, a.installer, a.platform, a.profile, a.build_number, a.version)
        except (OSError, ValueError, KeyError, sqlite3.Error):
            raise SystemExit('Desktop package not published: check native package metadata and use a newer build number') from None
        print(f"Published desktop {release['platform']} {release['profile']} build {release['build']} sha256={release['sha256']}")
        return
    if a.cmd == "backup":
        print("backed up to", backup_database(data, max(1, a.keep)))
        return
    if a.cmd == "publish-android":
        try:
            r = releases.publish(data, a.apk, a.version_code, a.version_name)
        except (OSError, ValueError) as e:
            raise SystemExit(f"not published: {e}")
        print(f"published {r['version_name']} (build {r['version_code']}) sha256={r['sha256']}")
        return
    if a.cmd == "android":
        r = releases.latest(data)
        print(f"{r['version_name']} (build {r['version_code']}) published {r['published_at']} sha256={r['sha256']}" if r else "no Android build published")
        return
    db = Database(data / "orion-hub.sqlite3")
    if a.cmd == "enroll":
        from .enrollment import write_enrollment
        try:
            write_enrollment(db, a.output, a.minutes, a.hub_url, a.mesh_login_server)
        except (OSError, ValueError):
            raise SystemExit("Invitation not written: check mesh configuration and use a new private output path") from None
        print(f"Private invitation and QR written; expires in {a.minutes} minutes.")
    elif a.cmd == "pair":
        minutes = max(1, min(a.minutes, 60))
        if a.qr:
            from .pairing_qr import write_pairing_qr
            try:
                write_pairing_qr(db, a.qr, minutes, a.hub_url)
            except (OSError, ValueError):
                raise SystemExit("QR not written: use a new .svg path in a private directory and the Pi mesh origin")
            print(f"Pairing QR written to {a.qr}; expires in {minutes} minutes. Delete after use.")
        else:
            print(create_pairing_code(db, minutes))
    elif a.cmd == "devices":
        for d in db.rows("SELECT id,name,created_at,last_seen_at FROM devices ORDER BY created_at"):
            print(f"{d['id']}  {d['name']}  last_seen={d['last_seen_at'] or 'never'}")
    elif a.cmd == "revoke":
        cloud_pending = False
        try:
            cloud_provisioning.queue_revoke(db,a.device_id)
        except (OSError,ValueError):
            cloud_pending = True
        try:
            phone_backup.revoke(db,a.device_id)
        except (OSError,ValueError) as error:
            raise SystemExit(str(error)) from None
        print("revoked", a.device_id)
        try:
            cloud_provisioning.revoke(db,a.device_id)
        except (OSError,ValueError):
            cloud_pending = True
        if cloud_pending:
            print("Hub pairing revoked. Cloud access cleanup is pending; the Hub will retry when Seafile is available.")


if __name__ == "__main__":
    main()
