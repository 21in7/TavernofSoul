"""DB import compatibility and the real Python 3 validation boundaries.

Python 3 is always collected. Python 2.7 is a separate measured case only when
shutil.which finds it; Python 3-only collection makes no Python 2 success claim.
No map_image/main/importAll or operational data is used.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

# Reuse the existing temporary parser release, without duplicating its fixture.
from test_release_contract import good_release, release_db


PYTHON27 = shutil.which('python2.7')
IMPORT_INTERPRETERS = [
    pytest.param(sys.executable, tuple(sys.version_info[:2]), id='current-python3'),
]
if PYTHON27 is not None:
    IMPORT_INTERPRETERS.append(pytest.param(PYTHON27, (2, 7), id='installed-python2.7'))
IMPORT_SCOPE = ('python3-and-installed-python2.7' if PYTHON27 is not None else
                'python3-only: python2.7 was not found; no python2 result')


IMPORT_CHILD = r'''
import json
import os
import sys

print(json.dumps({
    'executable': sys.executable,
    'version_info': list(sys.version_info),
    'version': sys.version,
}))
sys.stdout.flush()
expected = tuple(int(value) for value in sys.argv[1:3])
assert tuple(sys.version_info[:2]) == expected, 'wrong interpreter version'
assert sys.dont_write_bytecode, 'bytecode must be disabled'
assert 'ipfparser.contracts' not in sys.modules
import DB
root = os.path.dirname(os.getcwd())
assert os.path.realpath(DB.__file__) == os.path.join(root, 'parser_tidy', 'DB.py')
assert os.path.join(root, 'TavernofSoul') in sys.path
assert os.path.isfile(os.path.join(root, 'TavernofSoul', 'ipfparser', 'contracts.py'))
assert 'ipfparser.contracts' not in sys.modules, 'DB imported Python 3 contracts eagerly'
print('DB import left ipfparser.contracts unloaded')
'''


@pytest.mark.parametrize('executable,expected_version', IMPORT_INTERPRETERS)
def test_db_import_leaves_contracts_unloaded(tmp_path, executable, expected_version,
                                           record_property):
    assert sys.version_info.major == 3, 'the parent test suite requires Python 3'
    source = Path(__file__).resolve().parents[2]
    isolated = tmp_path / 'import-only'
    parser = isolated / 'parser_tidy'
    package = isolated / 'TavernofSoul' / 'ipfparser'
    parser.mkdir(parents=True)
    package.mkdir(parents=True)
    shutil.copyfile(source / 'parser_tidy' / 'DB.py', parser / 'DB.py')
    shutil.copyfile(source / 'TavernofSoul' / 'ipfparser' / 'contracts.py',
                    package / 'contracts.py')
    # Only the approved module sources are needed, with an inert package marker.
    (package / '__init__.py').write_text('', encoding='utf-8')
    before_paths = {path.relative_to(isolated) for path in isolated.rglob('*')}
    before = {path.relative_to(isolated): path.read_bytes()
              for path in isolated.rglob('*') if path.is_file()}
    record_property('interpreter_collection_scope', IMPORT_SCOPE)
    print(IMPORT_SCOPE)
    result = subprocess.run(
        [executable, '-B', '-E', '-S', '-c', IMPORT_CHILD,
         str(expected_version[0]), str(expected_version[1])],
        cwd=str(parser), capture_output=True, text=True, timeout=30)
    print(result.stdout)
    record_property('interpreter_identity', result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    identity = json.loads(result.stdout.splitlines()[0])
    assert tuple(identity['version_info'][:2]) == expected_version
    assert 'DB import left ipfparser.contracts unloaded' in result.stdout
    after = {path.relative_to(isolated): path.read_bytes()
             for path in isolated.rglob('*') if path.is_file()}
    assert {path.relative_to(isolated) for path in isolated.rglob('*')} == before_paths
    assert after == before, 'import must not write files, including bytecode'


@pytest.fixture
def validation_calls(monkeypatch):
    from ipfparser import contracts

    calls = []

    def observe(name, real_validator):
        def delegate(argument, *, require_version):
            call = {'name': name, 'argument': argument,
                    'require_version': require_version}
            calls.append(call)
            try:
                call['result'] = real_validator(argument, require_version=require_version)
            except contracts.ContractError as error:
                call['error'] = error
                raise
            return call['result']
        return delegate

    for name in ('validate_release', 'load_release'):
        monkeypatch.setattr(contracts, name, observe(name, getattr(contracts, name)))
    return calls


@pytest.mark.parametrize('with_version', [False, True], ids=['optional', 'required'])
@pytest.mark.parametrize('stored_version', [False, True], ids=['no-stored-version', 'stored-version'])
def test_validation_methods_preserve_data_path_and_version_policy(
        release_db, validation_calls, with_version, stored_version):
    db = release_db
    directory = Path(db.BASE_PATH_OUTPUT)
    payload = {'version': 'compat-v2'} if with_version else None
    if stored_version:
        db.data['version'] = {'version': 'contract-v1'}
    else:
        db.data.pop('version', None)
    version_file = directory / 'version.json'
    if payload is not None:
        version_file.write_text(json.dumps(payload), encoding='utf-8')
    elif not stored_version:
        version_file.unlink()
    before = copy.deepcopy(db.data)

    assert db._validate_release(payload) is None
    assert db._validate_staged_release(directory, payload) is None

    assert [call['name'] for call in validation_calls] == ['validate_release', 'load_release']
    assert all(call['require_version'] is with_version for call in validation_calls)
    memory, staged = validation_calls
    expected = dict(db.data)
    if payload is not None:
        expected['version'] = payload
    assert memory['argument'] == expected
    assert memory['argument'] is not db.data
    for key, value in db.data.items():
        if key != 'version' or payload is None:
            assert memory['argument'][key] is value
    if payload is not None:
        assert memory['argument']['version'] is payload
    assert memory['result'] is None
    assert staged['argument'] is directory
    assert staged['result'] == (payload if with_version else db.data.get('version'))
    assert db.data == before


@pytest.mark.parametrize('with_version', [False, True], ids=['optional', 'required'])
def test_export_calls_real_memory_validation_before_real_staged_validation(
        release_db, validation_calls, with_version):
    payload = {'version': 'compat-v2'} if with_version else None
    release_db.export(version_payload=payload)

    assert [call['name'] for call in validation_calls] == ['validate_release', 'load_release']
    assert all(call['require_version'] is with_version for call in validation_calls)
    assert validation_calls[1]['argument'] == release_db.BASE_PATH_OUTPUT + '.staging'
    assert validation_calls[1]['result'] == payload


@pytest.mark.parametrize('method,validator', [
    ('_validate_release', 'validate_release'),
    ('_validate_staged_release', 'load_release'),
])
@pytest.mark.parametrize('payload', [
    pytest.param(None, id='optional-version'),
    pytest.param({'version': 'compat-v2'}, id='required-version'),
    pytest.param({}, id='empty-version-is-still-required'),
])
def test_validation_methods_propagate_real_contract_errors(
        release_db, validation_calls, method, validator, payload):
    from ipfparser.contracts import ContractError

    directory = Path(release_db.BASE_PATH_OUTPUT)
    release_db.data['item_type'] = []
    (directory / 'item_type.json').write_text('[]', encoding='utf-8')
    if payload is None:
        (directory / 'version.json').unlink()
    else:
        (directory / 'version.json').write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ContractError) as caught:
        if method == '_validate_release':
            release_db._validate_release(payload)
        else:
            release_db._validate_staged_release(directory, payload)

    assert len(validation_calls) == 1
    call = validation_calls[0]
    assert call['name'] == validator
    assert call['require_version'] is (payload is not None)
    assert caught.value is call['error']
    assert 'result' not in call
    if payload == {}:
        assert (caught.value.path, caught.value.code, caught.value.message) == (
            'version.version', 'required', 'missing release version')
    else:
        assert (caught.value.path, caught.value.code, caught.value.message) == (
            'item_type', 'type', 'expected an object of item groups')
