# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit legacy/private Workspace Qt entrypoint; Link defaults to Electron."""
if __name__ == '__main__':
    from orion_mini.app import main
    raise SystemExit(main())
