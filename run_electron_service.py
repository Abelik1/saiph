# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frozen service executable; background helper modes never start a desktop GUI."""
import sys

if __name__ == '__main__':
    if sys.argv[1:] == ['--profile-path'] or sys.argv[1:] == ['--cloud-rpc-worker'] or '--forward-launch' in sys.argv:
        from orion_mini.electron_launcher import main
    else:
        from orion_mini.electron_service import main
    raise SystemExit(main())
