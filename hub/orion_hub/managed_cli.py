# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read managed CLI configuration as data, after dropping service privileges."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import sys


def environment(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
            raise ValueError('Managed configuration needs administrator review')
        # Shell-style quoting is accepted, but no expansion or commands run.
        parts = shlex.split(value, comments=False, posix=True)
        if len(parts) > 1 or '\x00' in value:
            raise ValueError('Quote managed configuration values containing spaces')
        values[name] = parts[0] if parts else ''
    return values


def main():
    try:
        path = Path(sys.argv.pop(1))
        os.environ.update(environment(path))
    except (OSError, ValueError, IndexError):
        raise SystemExit('Managed configuration needs administrator review') from None
    from .cli import main as cli_main
    cli_main()


if __name__ == '__main__':
    main()
