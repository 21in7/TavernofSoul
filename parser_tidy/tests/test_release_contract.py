"""Real parser releases must satisfy the same contract used by Django imports."""
import copy
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from DB import ToS_DB
from harness.contract_fixture import add_contract_edges
from harness.parser_fixture import parse_workspace, prepare_combat_workspace
from ipfparser import contracts
from ipfparser.contracts import ContractError, finite_tree, load_json, load_release, validate_release

DELETE = object()


def assert_contract_error(error, path, code, message):
    assert (error.path, error.code, error.message) == (path, code, message)
    assert str(error) == '{} [{}]: {}'.format(path, code, message)


def assert_nonfinite_error(error, path):
    assert error.path == path
    assert error.code == 'number'
    assert error.message == 'NaN and Infinity are not JSON numbers'
    assert str(error) == path + ' [number]: NaN and Infinity are not JSON numbers'


@pytest.mark.parametrize('value,path', [
    pytest.param(float('nan'), 'payload', id='root-nan'),
    pytest.param(float('inf'), 'payload', id='root-positive-infinity'),
    pytest.param(float('-inf'), 'payload', id='root-negative-infinity'),
    pytest.param({'rows': [0, (1, {'metric': float('nan')})]},
                 "payload['rows'][1][1]['metric']", id='nested-dict-list-tuple'),
    pytest.param({'줄\n\\키': [(0, float('inf'))]},
                 r"payload['줄\n\\키'][0][1]", id='escaped-unicode-key'),
    pytest.param({"quote'\"": float('-inf')},
                 r"""payload['quote\'"']""", id='quoted-key'),
    pytest.param({(3, '키'): [float('nan')]},
                 "payload[(3, '키')][0]", id='tuple-key-repr'),
    pytest.param({'z': {'deep': [float('nan')]}, 'a': float('inf')},
                 "payload['z']['deep'][0]", id='insertion-order-depth-first'),
    pytest.param({'a': float('inf'), 'z': float('nan')},
                 "payload['a']", id='reversed-insertion-order'),
    pytest.param([0, float('-inf'), float('nan')],
                 'payload[1]', id='list-index-order'),
    pytest.param((0, float('nan'), float('inf')),
                 'payload[1]', id='tuple-index-order'),
    pytest.param([{}, ('NaN', 0), {'last': float('-inf')}],
                 "payload[2]['last']", id='after-valid-branches'),
])
def test_finite_tree_reports_exact_first_error(value, path):
    with pytest.raises(ContractError) as error:
        finite_tree(value, 'payload')
    assert_nonfinite_error(error.value, path)


@pytest.mark.parametrize('value', [
    None, True, False, 0, -7, 10 ** 400, '', 'NaN', 'Infinity',
    0.0, -1.5, sys.float_info.max, -sys.float_info.max,
    {}, [], (), {'mixed': [None, True, 'NaN', (1, 2.5), {}, [], ()]},
])
def test_finite_tree_accepts_values_without_rewriting(value):
    before = copy.deepcopy(value)
    assert finite_tree(value, 'payload') is None
    assert value == before


@pytest.mark.parametrize('number', [float('nan'), float('inf'), float('-inf')],
                         ids=['nan', 'positive-infinity', 'negative-infinity'])
def test_finite_tree_supports_container_and_float_subclasses(number):
    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    class TupleSubclass(tuple):
        pass

    class FloatSubclass(float):
        pass

    values = ListSubclass([FloatSubclass(sys.float_info.max), TupleSubclass(())])
    tree = DictSubclass({'values': values})
    assert finite_tree(FloatSubclass(1.5), 'payload') is None
    assert finite_tree(tree, 'payload') is None
    values.append(TupleSubclass((0, FloatSubclass(number))))
    for value, path in [(FloatSubclass(number), 'payload'),
                        (tree, "payload['values'][2][1]")]:
        with pytest.raises(ContractError) as error:
            finite_tree(value, 'payload')
        assert_nonfinite_error(error.value, path)
    assert tree['values'] is values
    assert type(values[2]) is TupleSubclass
    assert type(values[2][1]) is FloatSubclass


def test_finite_tree_preserves_input_and_rechecks_mutated_shared_objects():
    entry = {'metric': 1.0}
    pair = ('NaN', entry)
    entries = [pair, {}]
    tree = {'entries': entries, 'alias': entry}
    before = copy.deepcopy(tree)
    assert finite_tree(tree, 'payload') is None
    assert tree == before

    entry['metric'] = float('inf')
    before = copy.deepcopy(tree)
    with pytest.raises(ContractError) as error:
        finite_tree(tree, 'payload')
    assert_nonfinite_error(error.value, "payload['entries'][0][1]['metric']")
    assert tree == before

    entry['metric'] = 2.0
    assert finite_tree(tree, 'payload') is None
    entries.append({'latest': float('-inf')})
    before = copy.deepcopy(tree)
    with pytest.raises(ContractError) as error:
        finite_tree(tree, 'fresh')
    assert_nonfinite_error(error.value, "fresh['entries'][2]['latest']")
    assert tree == before
    assert tree['entries'] is entries
    assert entries[0] is pair
    assert pair[1] is tree['alias'] is entry


def test_load_json_rejects_nested_exponent_overflow_with_exact_path(tmp_path):
    path = tmp_path / 'overflow.json'
    path.write_text('{"rows": [0, {"값": [1, 1e999]}]}', encoding='utf-8')
    with pytest.raises(ContractError) as error:
        load_json(path)
    assert_nonfinite_error(error.value, str(path) + "['rows'][1]['값'][1]")


@pytest.fixture(scope='module')
def good_release(tmp_path_factory):
    workspace = prepare_combat_workspace(tmp_path_factory.mktemp('contract-source'))
    db = add_contract_edges(parse_workspace(workspace, include_combat=True))
    db.export(version_payload={'version': 'contract-v1'})
    return db


@pytest.fixture
def release_db(good_release, tmp_path):
    db = ToS_DB()
    db.data = copy.deepcopy(good_release.data)
    db.BASE_PATH_OUTPUT = str(tmp_path / 'release')
    shutil.copytree(good_release.BASE_PATH_OUTPUT, db.BASE_PATH_OUTPUT)
    return db


def snapshot(directory):
    return {path.name: path.read_bytes() for path in Path(directory).glob('*.json')}


@pytest.fixture
def export_observation(release_db, monkeypatch):
    """Observe the real export boundaries; never stub either validator."""
    import DB
    release = Path(release_db.BASE_PATH_OUTPUT)
    staging = Path(str(release) + '.staging')
    backup = Path(str(release) + '.backup')
    observed = {name: [] for name in ('writes', 'staged', 'copies', 'promotions')}
    real_write = DB._atomic_write_json
    real_load = DB.load_release
    real_copy = DB.shutil.copy2
    real_replace = DB.os.replace

    def record_write(filepath, value):
        observed['writes'].append(Path(filepath))
        return real_write(filepath, value)

    def record_staged(directory, **kwargs):
        observed['staged'].append(Path(directory))
        return real_load(directory, **kwargs)

    def record_copy(src, dst, *args, **kwargs):
        if Path(dst).parent == backup:
            observed['copies'].append(Path(dst))
        return real_copy(src, dst, *args, **kwargs)

    def record_replace(src, dst):
        if Path(src).parent == staging and Path(dst).parent == release:
            observed['promotions'].append(Path(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(DB, '_atomic_write_json', record_write)
    monkeypatch.setattr(DB, 'load_release', record_staged)
    monkeypatch.setattr(DB.shutil, 'copy2', record_copy)
    monkeypatch.setattr(DB.os, 'replace', record_replace)
    return observed


def assert_failed_export_preserved_release(db, before, observed):
    assert observed['copies'] == observed['promotions'] == []
    assert snapshot(db.BASE_PATH_OUTPUT) == before
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'contract-v1'}
    assert not Path(db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


@pytest.mark.parametrize('require_version,has_version', [(True, True), (False, True), (False, False)])
def test_load_release_checks_each_json_once_and_rechecks_changed_snapshot(
        release_db, monkeypatch, require_version, has_version):
    directory = Path(release_db.BASE_PATH_OUTPUT)
    assert (directory / 'dictionary.json').is_file()
    # Include both retained optional collections and an unknown auxiliary file.
    for filename, content in [('goddess_reinf.json', '{}'), ('goddess_reinf_mat.json', '{}'),
                              ('unresolved_map_links.json', '[]'), ('future.json', '{"metric": [1]}')]:
        (directory / filename).write_text(content, encoding='utf-8')
    if not has_version:
        (directory / 'version.json').unlink()
    calls = Counter()
    real_finite = contracts.finite_tree

    def record_finite(value, path):
        calls[str(path)] += 1
        return real_finite(value, path)

    monkeypatch.setattr(contracts, 'finite_tree', record_finite)
    before = snapshot(directory)
    expected = Counter({str(directory / filename): 1 for filename in before})
    assert load_release(directory, require_version=require_version) == (
        {'version': 'contract-v1'} if has_version else None)
    assert calls == expected  # No final finite_tree(..., 'release') call.
    assert snapshot(directory) == before

    # A later call must enumerate and read fresh files, including auxiliaries.
    (directory / 'future.json').write_text('{"metric": [2]}', encoding='utf-8')
    (directory / 'new_auxiliary.json').write_text('[{"metric": 3}]', encoding='utf-8')
    (directory / 'version.json').write_text('{"version": "contract-v2"}', encoding='utf-8')
    calls.clear()
    before = snapshot(directory)
    assert load_release(directory, require_version=require_version) == {'version': 'contract-v2'}
    assert calls == Counter({str(directory / filename): 1 for filename in before})
    assert snapshot(directory) == before


@pytest.mark.parametrize('require_version', [False, True])
@pytest.mark.parametrize('location', ['auxiliary', 'extension-collection', 'extension-field', 'version'])
def test_memory_api_rechecks_nested_shared_mutation_without_changing_input(
        release_db, monkeypatch, require_version, location):
    data = release_db.data
    data['version'] = {'version': 'contract-v1'}
    owners = {
        'auxiliary': (data['dictionary'], "release['dictionary']"),
        'extension-collection': (data, 'release'),
        'extension-field': (data['items_by_name']['harness_ore'], "release['items_by_name']['harness_ore']"),
        'version': (data['version'], "release['version']"),
    }
    owner, prefix = owners[location]
    entry = {'metric': 1.0}
    pair = ('NaN', entry)
    entries = [pair]
    owner['RegressionExtra'] = {'entries': entries, 'alias': entry}
    calls = []
    real_finite = contracts.finite_tree

    def record_finite(value, path):
        calls.append((value, path))
        return real_finite(value, path)

    monkeypatch.setattr(contracts, 'finite_tree', record_finite)

    def check(value, invalid=False):
        entry['metric'] = value
        before = json.dumps(data)  # Stable even for NaN, whose equality is unusual.
        calls.clear()
        if invalid:
            with pytest.raises(ContractError) as error:
                validate_release(data, require_version=require_version)
            assert_nonfinite_error(error.value, prefix + "['RegressionExtra']['entries'][0][1]['metric']")
        else:
            assert validate_release(data, require_version=require_version) is None
        assert len(calls) == 1
        assert calls[0][0] is data and calls[0][1] == 'release'
        assert json.dumps(data) == before
        assert owner['RegressionExtra']['entries'] is entries
        assert entries[0] is pair
        assert pair[1] is owner['RegressionExtra']['alias'] is entry

    check(1.0)
    for value in (float('nan'), float('inf'), float('-inf')):
        check(value, invalid=True)
        check(2.0)


@pytest.mark.parametrize('with_version', [False, True])
@pytest.mark.parametrize('failure', ['nonfinite-auxiliary', 'domain'])
def test_real_export_rejects_memory_before_any_write_and_allows_retry(
        release_db, export_observation, with_version, failure):
    db = release_db
    before = snapshot(db.BASE_PATH_OUTPUT)
    version = {'version': 'contract-v2'} if with_version else None
    if failure == 'nonfinite-auxiliary':
        shared = {'metric': float('inf')}
        db.data['dictionary']['RegressionExtra'] = {'entries': [shared], 'alias': shared}
        expected = ("release['dictionary']['RegressionExtra']['entries'][0]['metric']",
                    'number', 'NaN and Infinity are not JSON numbers')
    else:
        original = db.data['items_by_name']['harness_ore']['Grade']
        db.data['items_by_name']['harness_ore']['Grade'] = 7
        expected = ("items_by_name['harness_ore'].Grade", 'range', 'expected a value in 0..6')
    unchanged = json.dumps(db.data)
    with pytest.raises(ContractError) as error:
        db.export(version_payload=version)
    assert_contract_error(error.value, *expected)
    assert json.dumps(db.data) == unchanged
    assert export_observation['writes'] == export_observation['staged'] == []
    assert_failed_export_preserved_release(db, before, export_observation)

    if failure == 'nonfinite-auxiliary':
        shared['metric'] = 1.0  # Keep the same shared object for the retry.
    else:
        db.data['items_by_name']['harness_ore']['Grade'] = original
    db.export(version_payload=version)
    assert export_observation['promotions']
    assert load_release(db.BASE_PATH_OUTPUT) == {
        'version': 'contract-v2' if with_version else 'contract-v1'}
    if not with_version:
        assert snapshot(db.BASE_PATH_OUTPUT)['version.json'] == before['version.json']
    assert not Path(db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


def test_memory_failure_preserves_existing_staging_and_recovery_sentinel(
        release_db, export_observation):
    db = release_db
    staging = Path(db.BASE_PATH_OUTPUT + '.staging')
    backup = Path(db.BASE_PATH_OUTPUT + '.backup')
    staging.mkdir()
    backup.mkdir()
    stale = staging / 'stale.json'
    sentinel = backup / '.promotion-in-progress'
    stale_bytes = b'{"stale": true}\n'
    sentinel_bytes = b'previous promotion requires manual recovery\n'
    stale.write_bytes(stale_bytes)
    sentinel.write_bytes(sentinel_bytes)
    before = snapshot(db.BASE_PATH_OUTPUT)
    db.data['dictionary']['RegressionExtra'] = {'metric': float('-inf')}
    with pytest.raises(ContractError) as error:
        db.export(version_payload={'version': 'contract-v2'})
    assert_nonfinite_error(error.value, "release['dictionary']['RegressionExtra']['metric']")
    assert export_observation == {name: [] for name in ('writes', 'staged', 'copies', 'promotions')}
    assert stale.read_bytes() == stale_bytes
    assert sentinel.read_bytes() == sentinel_bytes
    assert snapshot(db.BASE_PATH_OUTPUT) == before

    db.data['dictionary']['RegressionExtra']['metric'] = 1.0
    # Fixing the memory error does not bypass the existing recovery guard.
    with pytest.raises(RuntimeError, match='non-empty backup dir exists'):
        db.export(version_payload={'version': 'contract-v2'})
    assert sentinel.read_bytes() == sentinel_bytes
    assert snapshot(db.BASE_PATH_OUTPUT) == before
    assert export_observation['writes'] == export_observation['staged'] == []
    assert export_observation['copies'] == export_observation['promotions'] == []

    # Model explicit recovery of the synthetic leftover, not automatic removal.
    shutil.rmtree(backup)
    db.export(version_payload={'version': 'contract-v2'})
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'contract-v2'}
    assert export_observation['promotions']
    assert not staging.exists()
    assert not backup.exists()


# Decoder errors name the file; exponent overflow is found by finite_tree and
# retains its nested location. These expectations are independent of the reader.
STRICT_FILE_CASES = [
    pytest.param('{"value": 1, "value": 2}', '', 'duplicate_key',
                 "duplicate JSON key 'value'", id='duplicate-root-key'),
    pytest.param('{"rows": [{"metric": 1, "metric": 2}]}', '', 'duplicate_key',
                 "duplicate JSON key 'metric'", id='duplicate-nested-key'),
    pytest.param('{"rows": [{"metric": NaN}]}', '', 'number',
                 'NaN is not a JSON number', id='nested-nan'),
    pytest.param('{"rows": [{"metric": Infinity}]}', '', 'number',
                 'Infinity is not a JSON number', id='nested-positive-infinity'),
    pytest.param('{"rows": [{"metric": -Infinity}]}', '', 'number',
                 '-Infinity is not a JSON number', id='nested-negative-infinity'),
    pytest.param('{"rows": [{"metric": 1e999}]}', "['rows'][0]['metric']", 'number',
                 'NaN and Infinity are not JSON numbers', id='nested-exponent-overflow'),
    pytest.param('{"value":', '', 'json',
                 'cannot load JSON: Expecting value: line 1 column 10 (char 9)', id='malformed'),
] + [pytest.param(content, '', 'type', 'expected a JSON object or array', id='root-' + name)
     for name, content in [('null', 'null'), ('number', '42'), ('string', '"NaN"'), ('boolean', 'true')]]
STRICT_FILES = ['items_by_name.json', 'dictionary.json', 'unresolved_map_links.json',
                'version.json', 'future.json']


@pytest.mark.parametrize('require_version', [False, True])
@pytest.mark.parametrize('filename', STRICT_FILES)
@pytest.mark.parametrize('content,suffix,code,message', STRICT_FILE_CASES)
def test_load_release_strictly_checks_all_file_roles_and_retries_after_repair(
        release_db, require_version, filename, content, suffix, code, message):
    directory = Path(release_db.BASE_PATH_OUTPUT)
    # Optional/extension files are included even when this fixture omits them.
    (directory / 'unresolved_map_links.json').write_text('[]', encoding='utf-8')
    (directory / 'future.json').write_text('{}', encoding='utf-8')
    target = directory / filename
    original = target.read_bytes()
    before = snapshot(directory)
    target.write_text(content, encoding='utf-8')
    corrupted = snapshot(directory)
    with pytest.raises(ContractError) as error:
        load_release(directory, require_version=require_version)
    assert_contract_error(error.value, str(target) + suffix, code, message)
    assert snapshot(directory) == corrupted  # Validator never repairs snapshots.
    target.write_bytes(original)
    assert load_release(directory, require_version=require_version) == {'version': 'contract-v1'}
    assert snapshot(directory) == before


@pytest.mark.parametrize('with_version', [False, True])
@pytest.mark.parametrize('filename', STRICT_FILES)
@pytest.mark.parametrize('content,suffix,code,message', STRICT_FILE_CASES)
def test_real_staging_strict_errors_preserve_public_bytes_and_allow_retry(
        release_db, export_observation, monkeypatch, with_version, filename,
        content, suffix, code, message):
    import DB
    db = release_db
    db.data['unresolved_map_links'] = []
    db.data['future'] = {}
    # With no explicit payload, a version already present in data is still a
    # written JSON file and must be validated under require_version=False.
    if filename == 'version.json' and not with_version:
        db.data['version'] = {'version': 'contract-v2'}
    version = {'version': 'contract-v2'} if with_version else None
    staging = Path(db.BASE_PATH_OUTPUT + '.staging')
    target = staging / filename
    before = snapshot(db.BASE_PATH_OUTPUT)
    memory_before = copy.deepcopy(db.data)
    real_write = DB._atomic_write_json
    corrupted = []

    def corrupt_after_write(filepath, value):
        real_write(filepath, value)
        if Path(filepath) == target:
            target.write_text(content, encoding='utf-8')
            corrupted.append(target)

    with monkeypatch.context() as patch:
        patch.setattr(DB, '_atomic_write_json', corrupt_after_write)
        with pytest.raises(ContractError) as error:
            db.export(version_payload=version)
    assert_contract_error(error.value, str(target) + suffix, code, message)
    assert corrupted == [target]
    assert db.data == memory_before
    assert export_observation['writes']
    assert export_observation['staged'] == [staging]
    assert_failed_export_preserved_release(db, before, export_observation)

    db.export(version_payload=version)
    expected_version = 'contract-v2' if with_version or filename == 'version.json' else 'contract-v1'
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': expected_version}
    assert export_observation['promotions']
    if expected_version == 'contract-v1':
        assert snapshot(db.BASE_PATH_OUTPUT)['version.json'] == before['version.json']
    assert not staging.exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


DOMAIN_BOUNDARY_CASES = [
    pytest.param('items_by_name', (), [], 'items_by_name', 'type',
                 'expected an object index', id='required-index-root'),
    pytest.param('map_npc', (), {}, 'map_npc', 'type',
                 'expected an array of relations', id='required-relation-root'),
    pytest.param('items_by_name', ('harness_ore', 'Grade'), DELETE,
                 "items_by_name['harness_ore'].Grade", 'required', 'missing required field', id='missing-field'),
    pytest.param('items_by_name', ('harness_ore', 'Grade'), 7,
                 "items_by_name['harness_ore'].Grade", 'range', 'expected a value in 0..6', id='grade-range'),
    pytest.param('skills', ('400', 'Link_Job'), 'absent-job',
                 "skills['400'].Link_Job", 'reference', 'target absent-job not found in release', id='reference'),
    pytest.param('unresolved_map_links', (), {}, 'unresolved_map_links', 'type',
                 'expected an array of diagnostic rows', id='optional-diagnostic-root'),
    pytest.param('unresolved_map_links', (), [{}], 'unresolved_map_links[0].Map', 'required',
                 'missing diagnostic context', id='optional-diagnostic-field'),
    pytest.param('goddess_reinf', (), [], 'goddess_reinf', 'type',
                 'expected reinforcement objects keyed by level', id='optional-table-root'),
    pytest.param('goddess_reinf_mat', (), [], 'goddess_reinf', 'type',
                 'expected reinforcement objects keyed by level', id='optional-material-root'),
]


@pytest.mark.parametrize('require_version', [False, True])
@pytest.mark.parametrize('boundary', ['memory-export', 'load-release', 'staging'])
@pytest.mark.parametrize('collection,keys,value,path,code,message', DOMAIN_BOUNDARY_CASES)
def test_exact_domain_errors_remain_strict_at_real_release_boundaries(
        release_db, export_observation, monkeypatch, tmp_path, require_version,
        boundary, collection, keys, value, path, code, message):
    import DB
    db = release_db
    optional = {'goddess_reinf': {}, 'goddess_reinf_mat': {}, 'unresolved_map_links': []}
    db.data.update(copy.deepcopy(optional))
    original = db.data[collection]
    invalid = copy.deepcopy(original)
    if keys:
        target = invalid
        for key in keys[:-1]:
            target = target[key]
        if value is DELETE:
            del target[keys[-1]]
        else:
            target[keys[-1]] = value
    else:
        invalid = copy.deepcopy(value)
    before = snapshot(db.BASE_PATH_OUTPUT)
    version = {'version': 'contract-v2'} if require_version else None

    if boundary == 'load-release':
        incoming = tmp_path / 'incoming-domain-release'
        shutil.copytree(db.BASE_PATH_OUTPUT, incoming)
        for name, payload in optional.items():
            (incoming / (name + '.json')).write_text(json.dumps(payload), encoding='utf-8')
        target = incoming / (collection + '.json')
        original_bytes = target.read_bytes()
        target.write_text(json.dumps(invalid), encoding='utf-8')
        unchanged = snapshot(incoming)
        with pytest.raises(ContractError) as error:
            load_release(incoming, require_version=require_version)
        assert_contract_error(error.value, path, code, message)
        assert snapshot(incoming) == unchanged
        target.write_bytes(original_bytes)
        assert load_release(incoming, require_version=require_version) == {'version': 'contract-v1'}
        assert export_observation['writes'] == export_observation['staged'] == []
    elif boundary == 'memory-export':
        db.data[collection] = invalid
        memory = dict(db.data)
        if require_version:
            memory['version'] = version
        unchanged = copy.deepcopy(memory)
        with pytest.raises(ContractError) as error:
            validate_release(memory, require_version=require_version)
        assert_contract_error(error.value, path, code, message)
        assert memory == unchanged
        with pytest.raises(ContractError) as error:
            db.export(version_payload=version)
        assert_contract_error(error.value, path, code, message)
        assert memory == unchanged
        assert export_observation['writes'] == export_observation['staged'] == []
        assert_failed_export_preserved_release(db, before, export_observation)
        db.data[collection] = original
    else:
        real_write = DB._atomic_write_json
        corrupted = []

        def corrupt_after_write(filepath, payload):
            real_write(filepath, payload)
            if Path(filepath).name == collection + '.json':
                Path(filepath).write_text(json.dumps(invalid), encoding='utf-8')
                corrupted.append(Path(filepath))

        unchanged = copy.deepcopy(db.data)
        with monkeypatch.context() as patch:
            patch.setattr(DB, '_atomic_write_json', corrupt_after_write)
            with pytest.raises(ContractError) as error:
                db.export(version_payload=version)
        assert_contract_error(error.value, path, code, message)
        assert corrupted == [Path(db.BASE_PATH_OUTPUT + '.staging') / (collection + '.json')]
        assert db.data == unchanged
        assert export_observation['staged'] == [Path(db.BASE_PATH_OUTPUT + '.staging')]

    assert_failed_export_preserved_release(db, before, export_observation)
    if boundary != 'load-release':
        db.export(version_payload=version)
        assert export_observation['promotions']
        assert load_release(db.BASE_PATH_OUTPUT) == {
            'version': 'contract-v2' if require_version else 'contract-v1'}
        if not require_version:
            assert snapshot(db.BASE_PATH_OUTPUT)['version.json'] == before['version.json']
        assert not Path(db.BASE_PATH_OUTPUT + '.staging').exists()
        assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


VERSION_DOMAIN_CASES = [
    pytest.param({}, 'required', 'missing release version', id='missing-version-value'),
    pytest.param([], 'required', 'missing release version', id='array-version-root'),
    pytest.param({'version': ''}, 'empty', 'expected a nonempty string', id='empty-version'),
    pytest.param({'version': 1}, 'type', 'expected a string', id='numeric-version'),
    pytest.param({'version': 'v' * 51}, 'length', 'maximum length is 50', id='long-version'),
]


@pytest.mark.parametrize('require_version', [False, True])
@pytest.mark.parametrize('payload,code,message', VERSION_DOMAIN_CASES)
def test_present_version_domain_is_strict_even_when_optional_and_retry_is_fresh(
        release_db, require_version, payload, code, message):
    directory = Path(release_db.BASE_PATH_OUTPUT)
    memory = dict(release_db.data, version=payload)
    memory_before = copy.deepcopy(memory)
    with pytest.raises(ContractError) as error:
        validate_release(memory, require_version=require_version)
    assert_contract_error(error.value, 'version.version', code, message)
    assert memory == memory_before
    target = directory / 'version.json'
    before = snapshot(directory)
    original = target.read_bytes()
    target.write_text(json.dumps(payload), encoding='utf-8')
    corrupted = snapshot(directory)
    with pytest.raises(ContractError) as error:
        load_release(directory, require_version=require_version)
    assert_contract_error(error.value, 'version.version', code, message)
    assert snapshot(directory) == corrupted
    target.write_bytes(original)
    memory['version'] = {'version': 'contract-v1'}
    assert validate_release(memory, require_version=require_version) is None
    assert load_release(directory, require_version=require_version) == {'version': 'contract-v1'}
    assert snapshot(directory) == before


@pytest.mark.parametrize('require_version', [False, True])
def test_absent_version_policy_and_missing_required_file_are_unchanged(release_db, require_version):
    directory = Path(release_db.BASE_PATH_OUTPUT)
    version_path = directory / 'version.json'
    version_bytes = version_path.read_bytes()
    version_path.unlink()
    memory = dict(release_db.data)
    memory.pop('version', None)
    unchanged = copy.deepcopy(memory)
    before = snapshot(directory)
    if require_version:
        with pytest.raises(ContractError) as error:
            validate_release(memory, require_version=True)
        assert_contract_error(error.value, 'version.version', 'required', 'missing release version')
        with pytest.raises(ContractError) as error:
            load_release(directory, require_version=True)
        assert_contract_error(error.value, 'version.json', 'required', 'missing release file')
    else:
        assert validate_release(memory, require_version=False) is None
        assert load_release(directory, require_version=False) is None
    assert memory == unchanged
    assert snapshot(directory) == before
    version_path.write_bytes(version_bytes)
    memory['version'] = {'version': 'contract-v1'}
    assert validate_release(memory, require_version=require_version) is None
    assert load_release(directory, require_version=require_version) == {'version': 'contract-v1'}

    # require_version=False only makes version optional, never data collections.
    target = directory / 'buff.json'
    original = target.read_bytes()
    target.unlink()
    with pytest.raises(ContractError) as error:
        load_release(directory, require_version=require_version)
    assert_contract_error(error.value, 'buff.json', 'required', 'missing release file')
    missing = memory.pop('buff')
    with pytest.raises(ContractError) as error:
        validate_release(memory, require_version=require_version)
    assert_contract_error(error.value, 'buff', 'required', 'missing release collection')
    target.write_bytes(original)
    memory['buff'] = missing
    assert validate_release(memory, require_version=require_version) is None
    assert load_release(directory, require_version=require_version) == {'version': 'contract-v1'}


def test_export_deserializes_each_staging_json_once_including_version(release_db, monkeypatch):
    staging = Path(release_db.BASE_PATH_OUTPUT + '.staging')
    # Derive the expected files from the output collections, independently of
    # the export's written list and the files observed by the reader.
    expected = {staging / (name + '.json') for name in release_db.data}
    expected.add(staging / 'version.json')
    reads = Counter()
    finite_checks = Counter()
    real_load = json.load
    real_finite = contracts.finite_tree

    def count_finite(value, path):
        finite_checks[str(path)] += 1
        return real_finite(value, path)

    def count_staging_load(stream, *args, **kwargs):
        path = Path(stream.name)
        if path.parent == staging:
            reads[path] += 1
        return real_load(stream, *args, **kwargs)

    # Fixture parsing and publication assertions must not affect this count.
    with monkeypatch.context() as patch:
        patch.setattr(json, 'load', count_staging_load)
        patch.setattr(contracts, 'finite_tree', count_finite)
        release_db.export(version_payload={'version': 'contract-v2'})

    assert reads == Counter({path: 1 for path in expected})
    # The real export still validates independent memory before writing. Each
    # decoded staging file is then checked once, without a release-wide rewalk.
    assert finite_checks == Counter({'release': 1, **{str(path): 1 for path in expected}})
    assert load_release(release_db.BASE_PATH_OUTPUT) == {'version': 'contract-v2'}


@pytest.mark.parametrize('content,code', [
    ('{"value":', 'json'),
    ('{"value": 1, "value": 2}', 'duplicate_key'),
    ('{"value": NaN}', 'number'),
    ('42', 'type'),
], ids=['malformed', 'duplicate-key', 'nonfinite', 'scalar-root'])
def test_auxiliary_staging_corruption_fails_before_promotion(
        release_db, monkeypatch, content, code):
    import DB
    release = Path(release_db.BASE_PATH_OUTPUT)
    staging = Path(release_db.BASE_PATH_OUTPUT + '.staging')
    # dictionary is exported but not retained for importer domain validation.
    target = staging / 'dictionary.json'
    assert 'dictionary' in release_db.data
    before = snapshot(release)
    assert 'version.json' in before
    corrupted = []
    promotions = []
    real_write = DB._atomic_write_json
    real_replace = DB.os.replace

    def corrupt_after_write(filepath, value):
        real_write(filepath, value)
        if Path(filepath) == target:
            target.write_text(content, encoding='utf-8')
            corrupted.append(target)

    def record_promotion(src, dst):
        if Path(src).parent == staging and Path(dst).parent == release:
            promotions.append(Path(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(DB, '_atomic_write_json', corrupt_after_write)
    monkeypatch.setattr(DB.os, 'replace', record_promotion)
    with pytest.raises(ContractError) as error:
        release_db.export(version_payload={'version': 'contract-v2'})

    assert corrupted == [target]
    assert error.value.code == code
    assert error.value.path == str(target)
    assert promotions == []
    assert snapshot(release) == before  # Includes every public JSON and version.
    assert load_release(release) == {'version': 'contract-v1'}
    assert not staging.exists()
    assert not Path(release_db.BASE_PATH_OUTPUT + '.backup').exists()


CASES = [
    ('missing-collection', ('buff',), DELETE, 'required'),
    ('skills-object', ('skills',), [], 'type'),
    ('missing-name', ('items_by_name', 'harness_ore', 'Name'), DELETE, 'required'),
    ('boolean-id', ('items_by_name', 'harness_ore', '$ID'), True, 'id'),
    ('empty-id', ('items_by_name', 'harness_ore', '$ID'), '', 'id'),
    ('duplicate-item-id', ('items_by_name', 'harness_dust', '$ID'), 100, 'duplicate'),
    ('wrong-index', ('items_by_name', 'harness_ore', '$ID_NAME'), 'WrongIndex', 'index'),
    ('item-name-length', ('items_by_name', 'harness_ore', 'Name'), 'a' * 201, 'length'),
    ('missing-grade', ('items_by_name', 'harness_ore', 'Grade'), DELETE, 'required'),
    ('grade-range', ('items_by_name', 'harness_ore', 'Grade'), 7, 'range'),
    ('grade-string', ('items_by_name', 'harness_ore', 'Grade'), '1', 'number'),
    ('weight-boolean', ('items_by_name', 'harness_ore', 'Weight'), False, 'number'),
    ('negative-cooldown', ('items_by_name', 'harness_ore', 'TimeCoolDown'), -1, 'range'),
    ('trade-flags', ('items_by_name', 'harness_ore', 'Tradability'), 'TTT', 'flags'),
    ('missing-group', ('item_type', 'CARD'), DELETE, 'required'),
    ('recipe-classification', ('item_type', 'RECIPES'), [], 'classification'),
    ('group-reference', ('item_type', 'CARD'), ['MissingCard'], 'reference'),
    ('duplicate-group', ('item_type', 'CARD'), ['harness_card', 'harness_card'], 'duplicate'),
    ('recipe-material', ('items_by_name', 'harness_recipe', 'Link_Materials', 0, 'Item'), 'missing', 'reference'),
    ('recipe-quantity', ('items_by_name', 'harness_recipe', 'Link_Materials', 0, 'Quantity'), 0, 'range'),
    ('recipe-target', ('items_by_name', 'harness_recipe', 'Link_Target'), 'missing', 'reference'),
    ('package-reference', ('items_by_name', 'harness_package', 'PackageContents', 'items', 0, 'item'), 'missing', 'reference'),
    ('package-count', ('items_by_name', 'harness_package', 'PackageContents', 'items', 0, 'count'), 0, 'range'),
    ('package-options', ('items_by_name', 'harness_package', 'PackageContents', 'items', 0, 'options'), [['grade', 1]], 'shape'),
    ('random-reference', ('items_by_name', 'harness_random', 'PackageContents', 'alternatives', 0, 0, 'item'), 'missing', 'reference'),
    ('equipment-attack-order', ('items_by_name', 'harness_sword', 'Stat_ATTACK_PHYSICAL_MIN'), 9999, 'order'),
    ('equipment-durability', ('items_by_name', 'harness_sword', 'Durability'), -2, 'range'),
    ('equipment-array', ('items_by_name', 'harness_sword', 'AnvilATK'), ['7'], 'number'),
    ('equipment-flags', ('items_by_name', 'harness_sword', 'RequiredClass'), 'TTTT', 'flags'),
    ('equipment-bonus', ('items_by_name', 'harness_sword', 'Bonus'), [['STR']], 'shape'),
    ('card-field', ('items_by_name', 'harness_card', 'TypeCard'), DELETE, 'required'),
    ('collection-reference', ('items_by_name', 'harness_collection', 'Link_Items'), ['missing'], 'reference'),
    ('book-type', ('items_by_name', 'harness_book', 'Text'), [], 'type'),
    ('job-flag', ('jobs', '300', 'IsStarter'), 1, 'type'),
    ('skill-job', ('skills', '400', 'Link_Job'), 'missing', 'reference'),
    ('skill-factor-type', ('skills', '400', 'sfr'), ['100'], 'number'),
    ('skill-resource', ('skills', '400', 'SpendSP'), [-1], 'range'),
    ('skill-ms', ('skills', '400', 'BasicCoolDown'), 0.5, 'integer'),
    ('monster-attack-order', ('monsters', 500, 'Stat_ATTACK_PHYSICAL_MIN'), 1000, 'order'),
    ('monster-hp', ('monsters', 500, 'Stat_HP'), -1, 'range'),
    ('npc-monster-id', ('npcs', '800', '$ID'), '500', 'duplicate'),
    ('monster-skill-reference', ('skill_mon', '600', 'Monster'), [999], 'reference'),
    ('monster-skill-hits', ('skill_mon', '600', 'HitCount'), '0', 'range'),
    ('monster-skill-ms', ('skill_mon', '600', 'CD'), '3 seconds', 'number'),
    ('monster-skill-factor', ('skill_mon', '600', 'SFR'), 'NaN', 'number'),
    ('monster-skill-negative-aar', ('skill_mon', '600', 'AAR'), '-1', 'range'),
    ('active-recipe-missing-materials', ('items_by_name', 'harness_recipe', 'Link_Materials'), DELETE, 'required'),
    ('required-anvil-calculation', ('items_by_name', 'harness_sword', 'AnvilATK'), None, 'type'),
    ('drop-percent', ('item_monster', 0, 'Chance'), 100.1, 'range'),
    ('drop-order', ('item_monster', 0, 'Quantity_MIN'), 4, 'order'),
    ('drop-reference', ('item_monster', 0, 'Item'), 'missing', 'reference'),
    ('map-links', ('maps', '900', 'Link_Maps'), ['missing'], 'reference'),
    ('map-item-reference', ('map_item', 0, 'Item'), 'missing', 'reference'),
    ('map-npc-reference', ('map_npc', 0, 'NPC'), 'missing', 'reference'),
    ('map-respawn', ('map_npc', 0, 'TimeRespawn'), -1, 'range'),
    ('map-position', ('map_npc', 0, 'Positions'), [[1, 2, 3]], 'shape'),
    ('map-population', ('map_item_spawn', 0, 'Population'), -1, 'range'),
    ('attribute-job', ('attributes', '920', 'Link_Jobs'), ['missing'], 'reference'),
    ('attribute-level', ('attributes', '920', 'LevelMax'), 'five', 'number'),
    ('buff-ms', ('buff', '910', 'ApplyTime'), '3s', 'number'),
    ('buff-remove', ('buff', '910', 'UserRemove'), 2, 'type'),
    ('achievement-flag', ('achievements', '930', 'Hidden'), 'false', 'type'),
    ('nonfinite-extra-field', ('items_by_name', 'harness_ore', 'NewMetric'), float('nan'), 'number'),
]


@pytest.mark.parametrize('case,path,value,code', CASES, ids=[case[0] for case in CASES])
def test_invalid_release_is_rejected_before_publication(release_db, case, path, value, code):
    before = snapshot(release_db.BASE_PATH_OUTPUT)
    target = release_db.data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    with pytest.raises(ContractError) as error:
        release_db.export(version_payload={'version': 'contract-v2'})
    assert error.value.code == code
    assert path[0] in str(error.value)
    assert snapshot(release_db.BASE_PATH_OUTPUT) == before
    assert not Path(release_db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(release_db.BASE_PATH_OUTPUT + '.backup').exists()


def test_valid_release_preserves_legacy_and_optional_values(release_db):
    before = copy.deepcopy(release_db.data)
    validate_release(release_db.data, require_version=False)
    assert release_db.data == before  # Validation never rewrites parser data.
    ore = release_db.data['items_by_name']['harness_ore']
    recipe = release_db.data['items_by_name']['harness_recipe']
    assert str(ore['$ID']) == str(recipe['$ID']) == '100'
    recipe['Link_Target'] = None
    release_db.data['items_by_name']['harness_sword']['Durability'] = -1
    release_db.data['attributes']['920']['LevelMax'] = -1
    release_db.data['skills']['400']['Link_Job'] = None
    release_db.data['skills']['400']['CaptionRatio'] = [-10]
    release_db.data['skill_mon']['600']['SFR'] = ''
    release_db.data['skill_mon']['600']['HitCount'] = None
    release_db.export(version_payload={'version': 'contract-v2'})
    assert load_release(release_db.BASE_PATH_OUTPUT) == {'version': 'contract-v2'}
    assert release_db.data['unresolved_drops'][0]['item_classname'] == 'expired_drop'


def test_real_source_template_nullable_arrays_arcane_and_long_name_reference(release_db):
    data = release_db.data
    template = copy.deepcopy(data['items_by_name']['harness_ore'])
    template.update({'$ID': '910000', '$ID_NAME': 'Default_Recipe', 'Type': 'RECIPE'})
    data['items_by_name']['Default_Recipe'] = template
    long_name = 'harness_material_' + 'x' * 50
    material = copy.deepcopy(template)
    material.update({'$ID': '9900', '$ID_NAME': long_name, 'Type': 'MATERIAL'})
    data['items_by_name'][long_name] = material
    data['items_by_name']['harness_recipe']['Link_Materials'][0]['Item'] = long_name
    sword = data['items_by_name']['harness_sword']
    sword.update({'AnvilATK': None, 'AnvilDEF': None, 'AnvilPrice': [],
                  'TypeEquipment': 'Arcane', 'Stat_ATTACK_PHYSICAL_MAX': 0})
    validate_release(data, require_version=False)
    sword['TypeEquipment'] = 'Sword'
    with pytest.raises(ContractError, match='order'):
        validate_release(data, require_version=False)


def test_duplicate_relations_use_normalized_ids(release_db):
    row = copy.deepcopy(release_db.data['item_monster'][0])
    row['Item'], row['Monster'] = str(row['Item']), str(row['Monster'])
    release_db.data['item_monster'].append(row)
    with pytest.raises(ContractError, match='duplicate identity'):
        release_db.export(version_payload={'version': 'contract-v2'})


def test_duplicate_names_and_swapped_name_indexes(release_db):
    data = release_db.data
    data['jobs']['copy'] = copy.deepcopy(data['jobs']['300'])
    data['jobs']['copy']['$ID'] = '301'
    with pytest.raises(ContractError, match=r'\$ID_NAME \[duplicate\]'):
        validate_release(data, require_version=False)
    del data['jobs']['copy']
    items = data['items_by_name']
    items['harness_ore'], items['harness_dust'] = items['harness_dust'], items['harness_ore']
    with pytest.raises(ContractError, match=r'\$ID_NAME \[index\]'):
        validate_release(data, require_version=False)


@pytest.mark.parametrize('with_version', [False, True])
@pytest.mark.parametrize('boundary', ['memory-export', 'staging'])
@pytest.mark.parametrize('payload,code,message', VERSION_DOMAIN_CASES)
def test_invalid_version_cannot_advance_release(
        release_db, export_observation, monkeypatch, with_version, boundary,
        payload, code, message):
    import DB
    db = release_db
    before = snapshot(db.BASE_PATH_OUTPUT)
    staging = Path(db.BASE_PATH_OUTPUT + '.staging')
    valid_version = {'version': 'contract-v2'}
    if not with_version:
        db.data['version'] = copy.deepcopy(payload if boundary == 'memory-export' else valid_version)
    version = payload if with_version and boundary == 'memory-export' else (
        valid_version if with_version else None)
    memory_before = copy.deepcopy(db.data)
    payload_before = copy.deepcopy(payload)
    real_write = DB._atomic_write_json
    corrupted = []

    def corrupt_after_write(filepath, value):
        real_write(filepath, value)
        if Path(filepath) == staging / 'version.json':
            Path(filepath).write_text(json.dumps(payload), encoding='utf-8')
            corrupted.append(Path(filepath))

    with monkeypatch.context() as patch:
        if boundary == 'staging':
            patch.setattr(DB, '_atomic_write_json', corrupt_after_write)
        with pytest.raises(ContractError) as error:
            db.export(version_payload=version)
    assert_contract_error(error.value, 'version.version', code, message)
    assert db.data == memory_before
    assert payload == payload_before
    if boundary == 'memory-export':
        assert export_observation['writes'] == export_observation['staged'] == []
    else:
        assert corrupted == [staging / 'version.json']
        assert export_observation['staged'] == [staging]
    assert_failed_export_preserved_release(db, before, export_observation)

    if not with_version:
        db.data['version'] = valid_version
    db.export(version_payload=valid_version if with_version else None)
    assert export_observation['promotions']
    assert load_release(db.BASE_PATH_OUTPUT) == valid_version
    assert not staging.exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


@pytest.mark.parametrize('content,code', [
    ('{"a": 1, "a": 2}', 'duplicate_key'),
    ('{"a": {"id": 1, "id": 2}}', 'duplicate_key'),
    ('{"a": NaN}', 'number'), ('{"a": Infinity}', 'number'),
    ('{"a": -Infinity}', 'number'), ('{"a": 1e999}', 'number'),
    ('{"a":', 'json'), ('null', 'type'),
])
def test_strict_json_reader_rejects_ambiguous_values(tmp_path, content, code):
    path = tmp_path / 'bad.json'
    path.write_text(content)
    with pytest.raises(ContractError) as error:
        load_json(path)
    assert error.value.code == code
    assert str(path) in error.value.path


def test_snapshot_requires_all_files_and_checks_auxiliary_json(release_db):
    directory = Path(release_db.BASE_PATH_OUTPUT)
    (directory / 'future.json').write_text('{"a":1e999}')
    with pytest.raises(ContractError, match='future.json'):
        load_release(directory)
    (directory / 'future.json').unlink()
    (directory / 'buff.json').unlink()
    with pytest.raises(ContractError, match='buff.json.*required'):
        load_release(directory)


def test_valid_json_corruption_in_staging_cannot_be_published(release_db, monkeypatch):
    import DB
    before = snapshot(release_db.BASE_PATH_OUTPUT)
    real_write = DB._atomic_write_json
    def corrupt_after_write(filepath, value):
        real_write(filepath, value)
        if Path(filepath).name == 'items_by_name.json':
            data = json.loads(Path(filepath).read_text())
            data['harness_ore']['Grade'] = 7
            Path(filepath).write_text(json.dumps(data))
    monkeypatch.setattr(DB, '_atomic_write_json', corrupt_after_write)
    with pytest.raises(ContractError, match='Grade.*range'):
        release_db.export(version_payload={'version': 'contract-v2'})
    assert snapshot(release_db.BASE_PATH_OUTPUT) == before
    assert not Path(release_db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(release_db.BASE_PATH_OUTPUT + '.backup').exists()


@pytest.fixture
def map_link_release(release_db):
    # Hand-authored source context, independent of the map parser's diagnostics.
    source = copy.deepcopy(release_db.data['maps']['900'])
    source.update({'$ID': '970', '$ID_NAME': 'contract_source_map',
                   'Name': 'Contract Source', 'Link_Maps': ['971'], 'Link_Maps_Floors': []})
    target = copy.deepcopy(source)
    target.update({'$ID': '971', '$ID_NAME': 'contract_other_map',
                   'Name': 'Contract Target', 'Link_Maps': []})
    release_db.data['maps'].update({'970': source, '971': target})
    release_db.data['unresolved_map_links'] = [{
        'Map': '970', 'MapClassName': 'contract_source_map',
        'Token': 'contract_missing', 'Raw': 'contract_other_map/contract_missing/970',
        'SourceFile': 'ies.ipf/map.ies', 'SourceField': 'PhysicalLinkZone', 'SourceRow': 17,
    }]
    release_db.export(version_payload={'version': 'contract-map-v1'})
    return release_db


MAP_LINK_DIAGNOSTIC_CASES = [
    ('collection-object', (), {}, 'type'),
    ('collection-null', (), None, 'type'),
    ('row-not-object', (0,), 'missing', 'type'),
    ('unknown-source-id', (0, 'Map'), '999999', 'reference'),
    ('other-existing-source-id', (0, 'Map'), '971', 'reference'),
    ('wrong-source-class', (0, 'MapClassName'), 'contract_other_map', 'reference'),
    ('boolean-map-id', (0, 'Map'), True, 'id'),
    ('empty-map-id', (0, 'Map'), '', 'id'),
    ('nonnumeric-map-id', (0, 'Map'), 'contract_source_map', 'range'),
    ('nonpositive-map-id', (0, 'Map'), '0', 'range'),
    ('class-type', (0, 'MapClassName'), 970, 'type'),
    ('class-empty', (0, 'MapClassName'), ' ', 'empty'),
    ('token-type', (0, 'Token'), 970, 'type'),
    ('token-empty', (0, 'Token'), ' ', 'empty'),
    ('known-target-is-not-unresolved', (0, 'Token'), 'contract_other_map', 'reference'),
    ('token-is-only-a-substring', (0, 'Token'), 'missing', 'value'),
    ('token-is-not-a-single-raw-token', (0, 'Token'), 'contract_missing/970', 'value'),
    ('raw-does-not-contain-token', (0, 'Raw'), 'contract_other_map/another_missing', 'value'),
    ('raw-type', (0, 'Raw'), [], 'type'),
    ('raw-empty', (0, 'Raw'), '', 'empty'),
    ('file-type', (0, 'SourceFile'), ['ies.ipf/map.ies'], 'type'),
    ('file-empty', (0, 'SourceFile'), ' ', 'empty'),
    ('absolute-posix-file', (0, 'SourceFile'), '/machine/unpack/ies.ipf/map.ies', 'path'),
    ('absolute-windows-file', (0, 'SourceFile'), 'C:/unpack/ies.ipf/map.ies', 'path'),
    ('windows-separators', (0, 'SourceFile'), 'ies.ipf\\map.ies', 'path'),
    ('parent-traversal', (0, 'SourceFile'), '../ies.ipf/map.ies', 'path'),
    ('internal-parent-traversal', (0, 'SourceFile'), 'ies.ipf/../map.ies', 'path'),
    ('current-directory-component', (0, 'SourceFile'), './ies.ipf/map.ies', 'path'),
    ('empty-path-component', (0, 'SourceFile'), 'ies.ipf//map.ies', 'path'),
    ('control-in-path', (0, 'SourceFile'), 'ies.ipf/ma\x01p.ies', 'path'),
    ('field-type', (0, 'SourceField'), False, 'type'),
    ('field-empty', (0, 'SourceField'), '', 'empty'),
    ('wrong-source-field', (0, 'SourceField'), 'WorldMap', 'value'),
    ('string-source-row', (0, 'SourceRow'), '17', 'type'),
    ('boolean-source-row', (0, 'SourceRow'), True, 'type'),
    ('float-source-row', (0, 'SourceRow'), 17.0, 'type'),
    ('fractional-source-row', (0, 'SourceRow'), 17.5, 'type'),
    ('header-source-row', (0, 'SourceRow'), 1, 'range'),
    ('negative-source-row', (0, 'SourceRow'), -1, 'range'),
    ('duplicate-normalized-source-id', None, None, 'duplicate'),
] + [
    ('missing-' + field, (0, field), DELETE, 'required')
    for field in ('Map', 'MapClassName', 'Token', 'Raw', 'SourceFile', 'SourceField', 'SourceRow')
]


def invalid_map_link_diagnostics(valid, path, value):
    result = copy.deepcopy(valid)
    if path is None:
        duplicate = copy.deepcopy(result[0])
        duplicate['Map'] = 970  # Equivalent to the first row's string ID.
        result.append(duplicate)
    elif not path:
        result = copy.deepcopy(value)
    else:
        target = result
        for key in path[:-1]:
            target = target[key]
        if value is DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = copy.deepcopy(value)
    return result


@pytest.mark.parametrize('boundary', ['memory-export', 'load-release', 'staging'])
@pytest.mark.parametrize('case,path,value,code', MAP_LINK_DIAGNOSTIC_CASES,
                         ids=[case[0] for case in MAP_LINK_DIAGNOSTIC_CASES])
def test_invalid_map_link_context_is_rejected_at_both_release_boundaries(
        map_link_release, tmp_path, monkeypatch, boundary, case, path, value, code):
    db = map_link_release
    before = snapshot(db.BASE_PATH_OUTPUT)
    invalid = invalid_map_link_diagnostics(db.data['unresolved_map_links'], path, value)
    if boundary == 'memory-export':
        db.data['unresolved_map_links'] = invalid
        unchanged = copy.deepcopy(db.data)
        with pytest.raises(ContractError) as error:
            validate_release(db.data, require_version=False)
        assert error.value.code == code
        assert db.data == unchanged
        with pytest.raises(ContractError) as error:
            db.export(version_payload={'version': 'contract-map-v2'})
    elif boundary == 'load-release':
        incoming = tmp_path / 'incoming-release'
        shutil.copytree(db.BASE_PATH_OUTPUT, incoming)
        (incoming / 'unresolved_map_links.json').write_text(json.dumps(invalid), encoding='utf-8')
        with pytest.raises(ContractError) as error:
            load_release(incoming)
    else:
        import DB
        real_write = DB._atomic_write_json
        corrupted = []

        def corrupt_diagnostic_file(filepath, payload):
            real_write(filepath, payload)
            if Path(filepath).name == 'unresolved_map_links.json':
                Path(filepath).write_text(json.dumps(invalid), encoding='utf-8')
                corrupted.append(str(filepath))

        monkeypatch.setattr(DB, '_atomic_write_json', corrupt_diagnostic_file)
        with pytest.raises(ContractError) as error:
            db.export(version_payload={'version': 'contract-map-v2'})
        assert len(corrupted) == 1
    assert error.value.code == code
    assert 'unresolved_map_links' in error.value.path
    assert snapshot(db.BASE_PATH_OUTPUT) == before
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'contract-map-v1'}
    assert not Path(db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()


def test_valid_map_link_diagnostics_preserve_raw_numeric_tokens_and_roundtrip(map_link_release):
    db = map_link_release
    numeric = copy.deepcopy(db.data['unresolved_map_links'][0])
    numeric['Token'] = '970'  # An existing ID is not a ClassName reference.
    db.data['unresolved_map_links'].append(numeric)
    before = copy.deepcopy(db.data)
    validate_release(db.data, require_version=False)
    assert db.data == before
    db.export(version_payload={'version': 'contract-map-v2'})
    path = Path(db.BASE_PATH_OUTPUT) / 'unresolved_map_links.json'
    assert load_json(path) == before['unresolved_map_links']
    assert db.data['maps']['970']['Link_Maps'] == ['971']
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'contract-map-v2'}
    files = snapshot(db.BASE_PATH_OUTPUT)
    db.export(version_payload={'version': 'contract-map-v2'})
    assert snapshot(db.BASE_PATH_OUTPUT) == files


def test_existing_release_without_map_link_diagnostics_remains_compatible(map_link_release):
    db = map_link_release
    del db.data['unresolved_map_links']
    (Path(db.BASE_PATH_OUTPUT) / 'unresolved_map_links.json').unlink()
    validate_release(db.data, require_version=False)
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'contract-map-v1'}
    db.export(version_payload={'version': 'legacy-map-v2'})
    assert 'unresolved_map_links' not in db.data
    assert not (Path(db.BASE_PATH_OUTPUT) / 'unresolved_map_links.json').exists()
    assert load_release(db.BASE_PATH_OUTPUT) == {'version': 'legacy-map-v2'}


@pytest.mark.parametrize('target', ['contract_missing', 'contract_other_map', '999999'])
def test_unresolved_diagnostics_do_not_relax_normal_map_foreign_keys(map_link_release, target):
    db = map_link_release
    before = snapshot(db.BASE_PATH_OUTPUT)
    db.data['maps']['970']['Link_Maps'].append(target)
    with pytest.raises(ContractError) as error:
        db.export(version_payload={'version': 'contract-map-v2'})
    assert error.value.code == 'reference'
    assert 'Link_Maps' in error.value.path
    assert snapshot(db.BASE_PATH_OUTPUT) == before
    directory = Path(db.BASE_PATH_OUTPUT)
    valid_maps = load_json(directory / 'maps.json')
    valid_maps['970']['Link_Maps'].append(target)
    # The importer reads a separate snapshot; leave the public release intact.
    incoming = directory.parent / ('fk-snapshot-' + target)
    shutil.copytree(directory, incoming)
    (incoming / 'maps.json').write_text(json.dumps(valid_maps), encoding='utf-8')
    with pytest.raises(ContractError) as error:
        load_release(incoming)
    assert error.value.code == 'reference'
    assert 'Link_Maps' in error.value.path
    assert snapshot(db.BASE_PATH_OUTPUT) == before


def test_export_without_version_payload_still_checks_complete_collections(release_db):
    before = (Path(release_db.BASE_PATH_OUTPUT) / 'version.json').read_bytes()
    release_db.export()
    assert (Path(release_db.BASE_PATH_OUTPUT) / 'version.json').read_bytes() == before


def test_contract_import_works_from_flat_parser_without_pythonpath():
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, '-c',
        'from DB import ToS_DB; from ipfparser.contracts import validate_release; '
        'assert callable(validate_release)'], cwd=str(root / 'parser_tidy'), env=env,
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
