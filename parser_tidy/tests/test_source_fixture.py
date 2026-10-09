"""Real IES/Lua inputs → item domain → published JSON, without game data."""
import csv
import json
from pathlib import Path
import shutil

import pytest

from DB import ToS_DB
import items
import luautil
from harness.parser_fixture import FIXTURE, parse_workspace, prepare_workspace

EXPECTED = json.loads((FIXTURE / 'expected_items.json').read_text(encoding='utf-8'))


@pytest.fixture
def source_workspace(tmp_path):
    return prepare_workspace(tmp_path)


@pytest.fixture
def parsed_release(source_workspace):
    db = parse_workspace(source_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    return db, release, json.loads((release / 'items_by_name.json').read_text())


def snapshot(release):
    return {path.name: path.read_bytes() for path in release.glob('*.json')}


def change_column(path, name, value):
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    rows[0][name] = value
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_real_source_matches_independent_expected_output(parsed_release, name):
    _, _, output = parsed_release
    assert set(output) == set(EXPECTED)
    for field, expected in EXPECTED[name].items():
        assert output[name][field] == expected, '{}.{}'.format(name, field)
    assert 'PackageContents_Raw' not in output[name]


def test_lua_calculations_reach_json_as_numbers(parsed_release):
    _, _, output = parsed_release
    sword = output['harness_sword']
    assert sword['AnvilATK'] == list(range(7, 281, 7))
    assert sword['AnvilPrice'] == list(range(100, 4001, 100))
    assert sword['AnvilDEF'] == []
    assert all(type(value) is int for value in sword['AnvilATK'] + sword['AnvilPrice'])
    assert type(output['harness_ore']['TimeCoolDown']) is float
    assert type(output['harness_ore']['Weight']) is float


def test_missing_package_reference_stays_unresolved_without_fallback(parsed_release):
    _, _, output = parsed_release
    assert 'expired_material' not in output
    package = output['harness_mixed']['PackageContents']
    assert package['items'][0]['name'] == 'Fixture Ore'
    assert package['unresolved'] == EXPECTED['harness_mixed']['PackageContents']['unresolved']


def test_second_build_is_identical_and_restores_module_state(source_workspace):
    lua_state = (luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE)
    item_state = (items.EQUIPMENT_STAT_COLUMNS, items.equipment_grade_ratios, items.goddess_atk_list)
    first = parse_workspace(source_workspace)
    release = Path(first.BASE_PATH_OUTPUT)
    before = snapshot(release)
    second = parse_workspace(source_workspace)
    assert snapshot(release) == before
    assert first.data is not second.data
    assert first.file_dict is not second.file_dict
    assert (luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE) == lua_state
    assert (items.EQUIPMENT_STAT_COLUMNS, items.equipment_grade_ratios, items.goddess_atk_list) == item_state
    assert not release.with_name(release.name + '.staging').exists()
    assert not release.with_name(release.name + '.backup').exists()


def test_changed_ies_and_lua_inputs_recompute_output(source_workspace):
    first = parse_workspace(source_workspace)
    assert first.data['items_by_name']['harness_sword']['Stat_ATTACK_PHYSICAL_MIN'] == 140
    constants = source_workspace / 'itos_unpack/ies.ipf/sharedconst.ies'
    change_column(constants, 'Value', '9')
    equipment = source_workspace / 'itos_unpack/ies.ipf/item_equip.ies'
    change_column(equipment, 'UseLv', '30')
    changed = parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')
    sword = changed.data['items_by_name']['harness_sword']
    assert sword['Level'] == 30
    assert sword['Stat_ATTACK_PHYSICAL_MIN'] == 270
    assert sword['Stat_ATTACK_PHYSICAL_MAX'] == 279
    assert sword['AnvilATK'][-1] == 360
    assert json.loads((Path(changed.BASE_PATH_OUTPUT) / 'version.json').read_text()) == {
        'version': 'parser-fixture-v2_001001.ipf',
    }


@pytest.mark.parametrize('grade', ['7', '-1', 'invalid'])
def test_invalid_ies_preserves_previous_release_then_retries(source_workspace, grade):
    db = parse_workspace(source_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    equipment = source_workspace / 'itos_unpack/ies.ipf/item_equip.ies'
    change_column(equipment, 'ItemGrade', grade)
    with pytest.raises(ValueError):
        parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')
    assert snapshot(release) == before
    change_column(equipment, 'ItemGrade', '1')
    parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')
    assert json.loads((release / 'version.json').read_text())['version'] == 'parser-fixture-v2_001001.ipf'


@pytest.mark.parametrize('filename', ['ies.ipf/item.ies', 'shared.ipf/item_calculate.lua',
                                     'language.ipf/wholeDicID.xml'])
def test_missing_source_is_a_failure_and_keeps_previous_release(source_workspace, filename):
    db = parse_workspace(source_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    missing = source_workspace / 'itos_unpack' / filename
    missing.unlink()
    with pytest.raises(FileNotFoundError, match='Missing parser fixture input'):
        parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')
    assert snapshot(release) == before


def test_unloadable_lua_preserves_release_and_restores_runtime(source_workspace):
    db = parse_workspace(source_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    original_lua = luautil.lua
    lua_file = source_workspace / 'itos_unpack/shared.ipf/item_calculate.lua'
    lua_file.write_text('function GET_COMMON_PROP_LIST()\nthis is not lua\nend\n')
    with pytest.raises(KeyError, match='GET_COMMON_PROP_LIST'):
        parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')
    assert snapshot(release) == before
    assert luautil.lua is original_lua
    shutil.copy2(FIXTURE / 'unpack/shared.ipf/item_calculate.lua', lua_file)
    parse_workspace(source_workspace, 'parser-fixture-v2_001001.ipf')


def test_class_level_data_from_other_runs_is_not_imported(source_workspace, monkeypatch):
    contaminated = dict(ToS_DB.data)
    contaminated['items_by_name'] = {'stale_item': {'$ID': '999', '$ID_NAME': 'stale_item'}}
    contaminated['jobs'] = {'stale_job': {'$ID': '999'}}
    monkeypatch.setattr(ToS_DB, 'data', contaminated)
    db = parse_workspace(source_workspace)
    assert 'stale_item' not in db.data['items_by_name']
    assert db.data['jobs'] == {}
    assert contaminated['items_by_name']['stale_item']['$ID'] == '999'
