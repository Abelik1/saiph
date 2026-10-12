# SPDX-License-Identifier: AGPL-3.0-or-later
from orion_hub.managed_cli import environment
import pytest


def test_config_is_literal_data_and_never_shell_evaluated(tmp_path):
    path = tmp_path / 'server.env'
    marker = tmp_path / 'must-not-exist'
    path.write_text(f"# optional config\nORION_HUB_PORT=9876\nORION_OPTIONAL='$(touch {marker})'\nORION_EMPTY=\n")
    result = environment(path)
    assert result['ORION_HUB_PORT'] == '9876'
    assert result['ORION_OPTIONAL'] == f'$(touch {marker})'
    assert result['ORION_EMPTY'] == '' and not marker.exists()


@pytest.mark.parametrize('value', ['not an assignment', 'BAD-NAME=value', 'ORION_PATH=two words', 'ORION_PATH="unterminated'])
def test_invalid_configuration_never_echoes_values(tmp_path, value):
    path = tmp_path / 'server.env'
    path.write_text(value)
    with pytest.raises(ValueError) as error:
        environment(path)
    assert value not in str(error.value)
