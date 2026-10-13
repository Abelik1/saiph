# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicitly gated loopback runner; not the existing Pi Hub entry point."""
from __future__ import annotations

import os
from pathlib import Path

from .hosted import HostedConfig, create_app
from .hosted_auth import AccessTokens, Auth0Config, mfa_claim


def configuration(environ=None):
    env = os.environ if environ is None else environ
    if env.get("ORION_HOSTED_EXPERIMENTAL") != "1":
        raise ValueError("Hosted development service is disabled")
    try:
        auth = Auth0Config(env["ORION_AUTH0_ISSUER"], env["ORION_AUTH0_AUDIENCE"],
                           tuple(env["ORION_AUTH0_NATIVE_CLIENT_IDS"].split(",")), env["ORION_AUTH0_OWNER_SUBJECT"])
        mfa_claim(env)
        database = Path(env["ORION_HOSTED_DATABASE"])
        if not database.is_absolute() or database.name != "orion-hosted.sqlite3":
            raise ValueError()
        return HostedConfig(env["ORION_HOSTED_DEPLOYMENT_ID"], database, auth)
    except (KeyError, ValueError, TypeError):
        raise ValueError("Complete hosted development configuration is required") from None


def main():
    import uvicorn
    config = configuration()
    tokens = AccessTokens(config.auth, mfa_claim=mfa_claim(os.environ))
    uvicorn.run(create_app(config, tokens=tokens), host="127.0.0.1", port=8766,
                access_log=False, proxy_headers=False, server_header=False)


if __name__ == "__main__":
    main()
