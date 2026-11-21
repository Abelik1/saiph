# SPDX-License-Identifier: AGPL-3.0-or-later
"""Source launcher and read-only compatibility helpers for the Electron desktop."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

from . import child_process


def profile_path():
    from .paths import APP_DATA
    return Path(os.environ.get('ORION_MINI_DATA_DIR', str(APP_DATA))).resolve()


def forward_arguments(root, arguments):
    from .enrollment import forward_invitation, forward_local
    from .send_files import arguments as split_files, forward
    rest, files = split_files(['saiph', *arguments])
    if files:
        return forward(root, files)
    if '--enrollment' in rest:
        index = rest.index('--enrollment')
        return index + 1 < len(rest) and forward_invitation(root, rest[index + 1])
    if '--open-phone-app' in rest:
        index = rest.index('--open-phone-app')
        return index + 1 < len(rest) and forward_local(root, '/v1/phone/app', {'package': rest[index + 1]})
    return forward_local(root, '/v1/window/show', {})


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ['--profile-path']:
        print(profile_path())
        return 0
    if arguments == ['--cloud-rpc-worker']:
        from .cloud_client import rpc_worker_main
        return rpc_worker_main()
    if arguments and arguments[0] == '--forward-launch':
        result = forward_arguments(profile_path(), json.loads(arguments[1]))
        print(json.dumps({'forwarded': bool(result)}))
        return 0 if result else 3
    from .modules import edition
    addon = edition()
    if addon is not None:
        # Private Workspace remains an external, explicitly selected Qt build.
        from .app import main as legacy_main
        return legacy_main()
    if forward_arguments(profile_path(), arguments):
        return 0
    root = Path(__file__).resolve().parents[2]
    runtime = root / 'desktop/node_modules/electron'
    try:
        executable = runtime / 'dist' / (runtime / 'path.txt').read_text(encoding='utf-8').strip()
        if not executable.is_file() or not (root / 'desktop/dist/main.cjs').is_file():
            raise ValueError()
    except (OSError, ValueError):
        raise SystemExit('Build desktop/ and frontend/ first; see desktop/README.md.') from None
    environment = dict(os.environ)
    environment['SAIPH_PYTHON'] = sys.executable
    environment.pop('ELECTRON_RUN_AS_NODE', None)
    environment.pop('NODE_OPTIONS', None)
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    return child_process.run([str(executable), str(root / 'desktop'), *arguments], cwd=root, env=environment, **options).returncode


if __name__ == '__main__':
    raise SystemExit(main())
