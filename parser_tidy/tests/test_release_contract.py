"""Real parser releases must satisfy the same contract used by Django imports."""
import copy
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
from ipfparser.contracts import ContractError, load_json, load_release, validate_release

DELETE = object()


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


@pytest.mark.parametrize('version', [{}, {'version': ''}, {'version': 1}, {'version': 'v' * 51}])
def test_invalid_version_cannot_advance_release(release_db, version):
    before = snapshot(release_db.BASE_PATH_OUTPUT)
    with pytest.raises(ContractError, match='version.version'):
        release_db.export(version_payload=version)
    assert snapshot(release_db.BASE_PATH_OUTPUT) == before


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
