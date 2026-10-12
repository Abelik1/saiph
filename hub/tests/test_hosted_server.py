# SPDX-License-Identifier: AGPL-3.0-or-later
from uuid import uuid4

import pytest
pytest.importorskip("jwt")

from orion_hub.hosted_server import configuration


def valid(tmp_path):
    return {"ORION_HOSTED_EXPERIMENTAL": "1", "ORION_AUTH0_ISSUER": "https://synthetic.eu.auth0.com/",
            "ORION_AUTH0_AUDIENCE": "https://api.example", "ORION_AUTH0_NATIVE_CLIENT_IDS": "desktop,android",
            "ORION_AUTH0_OWNER_SUBJECT": "auth0|synthetic", "ORION_HOSTED_DEPLOYMENT_ID": str(uuid4()),
            "ORION_HOSTED_DATABASE": str(tmp_path / "orion-hosted.sqlite3")}


def test_complete_explicit_configuration(tmp_path):
    value = valid(tmp_path)
    config = configuration(value)
    assert config.auth.client_ids == ("desktop", "android")
    assert config.database.name == "orion-hosted.sqlite3"


@pytest.mark.parametrize("name", list(valid(__import__('pathlib').Path.cwd())))
def test_every_setting_required(tmp_path, name):
    value = valid(tmp_path)
    del value[name]
    with pytest.raises(ValueError):
        configuration(value)


@pytest.mark.parametrize("setting,value", [("ORION_HOSTED_EXPERIMENTAL", "true"),
    ("ORION_HOSTED_DATABASE", "orion-hosted.sqlite3"), ("ORION_HOSTED_DATABASE", "/var/lib/orion-hub/orion-hub.sqlite3"),
    ("ORION_AUTH0_ISSUER", "http://tenant.example/"), ("ORION_AUTH0_NATIVE_CLIENT_IDS", ""),
    ("ORION_HOSTED_DEPLOYMENT_ID", "not-an-id")])
def test_bad_configuration_fails_closed(tmp_path, setting, value):
    env = valid(tmp_path)
    env[setting] = value
    with pytest.raises(ValueError):
        configuration(env)
