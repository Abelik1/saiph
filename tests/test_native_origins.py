# SPDX-License-Identifier: AGPL-3.0-or-later
"""A native build must not silently collect DLLs from developer PATH tools."""
import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('native_origins', Path(__file__).parents[1] / 'scripts/packaging/native_origins.py')
origins = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(origins)


def native_fixture(tmp_path):
    interpreter = tmp_path / 'python'
    source = interpreter / 'DLLs/libssl.dll'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'trusted interpreter native bytes')
    bundle = tmp_path / 'bundle'
    target = bundle / '_internal/libssl.dll'
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    analysis = tmp_path / 'Analysis-00.toc'
    analysis.write_text(repr([[], [('libssl.dll', str(source), 'BINARY')]]))
    return interpreter, source, bundle, target, analysis


def test_windows_native_path_discards_ambient_tools_without_mutating_caller(tmp_path):
    environment = {'PATH': 'unrelated/poppler' + os.pathsep + 'unrelated/libheif',
                   'SystemRoot': str(tmp_path / 'Windows'), 'PYTHONPATH': 'ambient/modules',
                   'PYTHONHOME': 'ambient/python', 'OTHER_SETTING': 'preserved'}
    result, roots = origins.windows_native_environment(environment, tmp_path / 'venv', tmp_path / 'python')
    assert result['PATH'].split(os.pathsep) == [str(tmp_path / 'python/DLLs'), str(tmp_path / 'python'),
                                               str(tmp_path / 'venv/Scripts'), str(tmp_path / 'Windows/System32')]
    assert 'PYTHONPATH' not in result and 'PYTHONHOME' not in result
    assert result['OTHER_SETTING'] == 'preserved'
    assert environment['PYTHONPATH'] == 'ambient/modules'
    assert 'poppler' in environment['PATH']
    assert tmp_path / 'Windows/System32' in roots


def test_native_audit_records_actual_trusted_inputs_and_copied_bytes(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    report = origins.audit_analysis(analysis, bundle, [interpreter])
    assert report['files'][0]['sha256'] == origins.digest(target)
    assert report['files'][0]['source'] == str(source.resolve())
    assert report['files'][0]['path'] == '_internal/libssl.dll'


def test_explicit_project_component_does_not_trust_its_entire_build_folder(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    component = tmp_path / 'project/SaiphCamera64.dll'
    component.parent.mkdir()
    component.write_bytes(b'synthetic project camera')
    destination = bundle / '_internal/camera/SaiphCamera64.dll'
    destination.parent.mkdir()
    destination.write_bytes(component.read_bytes())
    analysis.write_text(repr([('libssl.dll', str(source), 'BINARY'),
                             ('camera/SaiphCamera64.dll', str(component), 'BINARY')]))
    with pytest.raises(ValueError, match='outside trusted'):
        origins.audit_analysis(analysis, bundle, [interpreter])
    report = origins.audit_analysis(analysis, bundle, [interpreter], {'camera/SaiphCamera64.dll': component})
    assert len(report['files']) == 2
    destination.write_bytes(b'changed component')
    with pytest.raises(ValueError, match='differs'):
        origins.audit_analysis(analysis, bundle, [interpreter], {'camera/SaiphCamera64.dll': component})


def test_same_named_matching_ambient_dll_is_rejected(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    ambient = tmp_path / 'python-unrelated/poppler/libssl.dll'
    ambient.parent.mkdir(parents=True)
    ambient.write_bytes(source.read_bytes())
    analysis.write_text(repr([('libssl.dll', str(ambient), 'BINARY')]))
    with pytest.raises(ValueError, match='outside trusted build roots: libssl.dll'):
        origins.audit_analysis(analysis, bundle, [interpreter])


def test_collected_binary_tampering_is_rejected(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    target.write_bytes(b'different native bytes')
    with pytest.raises(ValueError, match='differs from its audited input'):
        origins.audit_analysis(analysis, bundle, [interpreter])


def test_unrecorded_collected_dll_is_rejected(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    (target.parent / 'ambient.dll').write_bytes(b'extra native library')
    with pytest.raises(ValueError, match='no audited Analysis input'):
        origins.audit_analysis(analysis, bundle, [interpreter])


def test_extension_inputs_are_audited_and_unsafe_destinations_fail(tmp_path):
    interpreter, source, bundle, target, analysis = native_fixture(tmp_path)
    analysis.write_text(repr([('libssl.dll', str(source), 'EXTENSION')]))
    assert origins.audit_analysis(analysis, bundle, [interpreter])['files'][0]['kind'] == 'EXTENSION'
    analysis.write_text(repr([('../libssl.dll', str(source), 'BINARY')]))
    with pytest.raises(ValueError, match='Unsafe native bundle path'):
        origins.audit_analysis(analysis, bundle, [interpreter])
