# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local administration. Private provider subjects enter through a file, never logs."""
import argparse
import json
import os
from pathlib import Path
from fastapi import HTTPException
from .hosted_service import AccountRegistry
from .hosted_service_server import configuration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    admit = commands.add_parser('admit')
    admit.add_argument('--identity-file', type=Path, required=True)
    admit.add_argument('--until', type=int, required=True)
    issue = commands.add_parser('issue-code')
    issue.add_argument('--until', type=int, required=True)
    issue.add_argument('--output', type=Path, required=True)
    commands.add_parser('revoke-code').add_argument('--digest', required=True)
    migrate = commands.add_parser('import-owner')
    migrate.add_argument('--snapshot', type=Path, required=True)
    migrate.add_argument('--until', type=int, required=True)
    for action in ('suspend', 'reactivate'):
        commands.add_parser(action).add_argument('--account', required=True)
    args = parser.parse_args()
    try:
        directory, auth = configuration()
        registry = AccountRegistry(directory, auth)
        if args.action == 'import-owner':
            from .hosted_service_migration import import_owner
            result = import_owner(registry, args.snapshot, os.environ.get('ORION_AUTH0_OWNER_SUBJECT'), expires_at=args.until)
            print(json.dumps(result))
            return
        if args.action == 'issue-code':
            # Exclusive creation; never print a live access code or overwrite a file.
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
                code = registry.issue_code(args.until)
                target.write(code + '\n')
            identifier = 'written-to-protected-file'
        elif args.action == 'revoke-code':
            registry.revoke_code(args.digest)
            identifier = 'revoked'
        elif args.action == 'admit':
            value = json.loads(args.identity_file.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or set(value) != {'issuer', 'subject'} or value['issuer'] != auth.issuer:
                raise ValueError()
            identifier = registry.admit(value['subject'], expires_at=args.until)
        else:
            registry.set_active(args.account, args.action == 'reactivate')
            identifier = args.account
    except (ValueError, OSError, TypeError, KeyError, HTTPException, __import__('sqlite3').Error):
        parser.exit(1, 'Account administration rejected; check protected configuration.\n')
    print(json.dumps({'account': identifier, 'action': args.action}))


if __name__ == '__main__':
    main()
