# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicitly enabled shared-service runner; preserves the owner-only runner."""
import os
from pathlib import Path
from .hosted_auth import ServiceAuth0Config, mfa_claim
from .hosted_service import AccountRegistry, SharedHosted


def configuration(environ=None):
    env = os.environ if environ is None else environ
    if env.get('ORION_HOSTED_SHARED') != '1':
        raise ValueError('Shared hosted service is disabled')
    try:
        auth = ServiceAuth0Config(env['ORION_AUTH0_ISSUER'], env['ORION_AUTH0_AUDIENCE'],
                                 tuple(env['ORION_AUTH0_NATIVE_CLIENT_IDS'].split(',')))
        mfa_claim(env)
        directory = Path(env['ORION_HOSTED_STATE'])
        if not directory.is_absolute():
            raise ValueError()
        return directory, auth
    except (KeyError, TypeError, ValueError):
        raise ValueError('Complete shared hosted configuration is required') from None


def main():
    import uvicorn
    directory, auth = configuration()
    from .hosted_auth import AccessTokens
    web_client = os.environ.get('ORION_AUTH0_WEB_CLIENT_ID')
    if web_client and web_client in auth.client_ids:
        raise ValueError('Website and native clients must be separate')
    claim = mfa_claim(os.environ)
    web_tokens = AccessTokens(ServiceAuth0Config(auth.issuer, auth.audience, (web_client,)), mfa_claim=claim) if web_client else None
    registry = AccountRegistry(directory, auth)
    download_directory = os.environ.get('ORION_HOSTED_DOWNLOADS')
    from .hosted_downloads import Downloads
    downloads = Downloads(registry, download_directory) if download_directory else None
    tokens = AccessTokens(auth, mfa_claim=claim)
    uvicorn.run(SharedHosted(registry, tokens=tokens, web_tokens=web_tokens, downloads=downloads), host='127.0.0.1', port=8767,
                access_log=False, proxy_headers=False, server_header=False, limit_concurrency=128)


if __name__ == '__main__':
    main()
