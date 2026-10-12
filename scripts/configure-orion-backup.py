#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Initialize this device's private restic configuration; never prints passwords."""
import argparse
from pathlib import Path
from orion_mini.backups import configure
from orion_mini.companion_tools import tool_path
from orion_mini.storage import read_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--device", choices=["desktop", "laptop"], required=True)
    parser.add_argument("--cloud", type=Path, default=Path.home() / "Cloud")
    parser.add_argument("--restic")
    parser.add_argument("--offsite-config",type=Path,help="Existing private JSON with repository, password_file and environment_file; never paste credentials on the command line")
    args = parser.parse_args()
    executable=tool_path('restic',args.restic)
    if not executable:raise ValueError('Install the standard restic tool first.')
    offsite=None
    if args.offsite_config:
        offsite=read_json(args.offsite_config,{})
        if not isinstance(offsite,dict) or set(offsite)!={'repository','password_file','environment_file'}:
            raise ValueError('Use a private offsite configuration with the documented fields.')
        if not all(isinstance(value,str) and value for value in offsite.values()) or not all(Path(offsite[key]).is_file() for key in ('password_file','environment_file')):
            raise ValueError('Private offsite credential files must already exist.')
    # Retain owner-configured sources (including external Seafile client metadata)
    # when adding offsite storage. Never silently drop them during bootstrap.
    existing=read_json(args.data/'backups/config.json',{})
    sources=list(dict.fromkeys([str(args.data),str(args.cloud),*existing.get('sources',[])]))
    configure(args.data, sources, repository=f"sftp:pi:/srv/orion-backups/{args.device}", executable=executable,offsite=offsite)
    print("Daily encrypted backup configured. Privately preserve the password file; it is required to restore.")

if __name__=='__main__':
    try:main()
    except (OSError,ValueError):
        print('Backup setup did not finish. Check local tool/source paths and private offsite configuration; no credentials were printed.')
        raise SystemExit(1)
