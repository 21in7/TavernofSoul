"""Registered goddess tables and gem XML exercise real source parsing and Lua."""
import json
import csv
from pathlib import Path

import pytest
from lupa import LuaError
from xml.etree.ElementTree import ParseError

from DB import ToS_DB
import items
import luautil
from harness.fixture_inputs import EQUIPMENT_FIXTURE, REGIONS
from harness.parser_fixture import (change_ies_column, isolated_parser_state, parse_workspace,
                                    prepare_equipment_workspace, prepare_regional_workspace)

EXPECTED = json.loads((EQUIPMENT_FIXTURE / 'expected_equipment.json').read_text())


def parse(root, region='itos', version='equipment-v1'):
    return parse_workspace(root, version, region=region, include_equipment=True)


def snapshot(release):
    return {path.name: path.read_bytes() for path in release.glob('*.json')}


@pytest.mark.parametrize('region', REGIONS)
def test_registered_560_table_reaches_json_and_real_lua_equipment_values(tmp_path, caplog, region):
    db = parse(prepare_equipment_workspace(tmp_path, region), region)
    assert set(db.data['goddess_reinf']) == set(EXPECTED['table_levels'])
    table = db.data['goddess_reinf'][560]
    assert len(table) == 30
    assert table[0]['BasicAtk'] == '7000' and table[0]['BasicDef'] == '9000'
    assert table[5]['BasicProp'] == '98000' and table[-1]['BasicProp'] == '50000'
    assert db.data['goddess_reinf_unregistered'] == EXPECTED['unregistered']
    assert 'Unregistered goddess reinforcement table: item_goddess_reinforce_580.ies' in caplog.text
    sword, armor, acc = (db.data['items_by_name']['harness_' + name] for name in ('sword', 'armor', 'accessory'))
    assert (sword['Stat_ATTACK_PHYSICAL_MIN'], sword['Stat_ATTACK_PHYSICAL_MAX']) == (
        EXPECTED['sword_min'], EXPECTED['sword_max'])
    assert (armor['Stat_DEFENSE_PHYSICAL'], armor['Stat_DEFENSE_MAGICAL']) == (
        EXPECTED['armor_def'], EXPECTED['armor_mdef'])
    assert (acc['Stat_ATTACK_PHYSICAL_MIN'], acc['Stat_ATTACK_PHYSICAL_MAX'], acc['Stat_ATTACK_MAGICAL']) == (
        EXPECTED['accessory_atk'],) * 3
    assert type(acc['Stat_ATTACK_MAGICAL']) is int
    assert sword['Level'] == armor['Level'] == 560 and acc['Level'] == 550
    assert sword['TranscendPrice'] == armor['TranscendPrice'] == acc['TranscendPrice'] == EXPECTED['transcend']
    assert sword['AnvilATK'] == list(range(100, 3001, 100))
    assert armor['AnvilDEF'] == list(range(200, 6001, 200))
    assert acc['AnvilATK'] == list(range(80, 2401, 80))
    output = json.loads((Path(db.BASE_PATH_OUTPUT) / 'goddess_reinf.json').read_text())
    assert set(output) == {'540', '550', '560'}


def test_trinket_uses_lua_attack_bonus_and_source_use_level_instead_of_item_level(tmp_path):
    root = prepare_equipment_workspace(tmp_path)
    path = root / 'itos_unpack/ies.ipf/item_equip.ies'
    with path.open() as source:
        reader = csv.DictReader(source)
        fields, rows = reader.fieldnames, list(reader)
    rows[0].update(ClassType='Trinket', ItemLv='999')
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    sword = parse(root).data['items_by_name']['harness_sword']
    assert sword['Level'] == 999
    assert sword['GoddessReinforceLevel'] == 560
    assert sword['GoddessReinforceGroup'] == 'weapon'
    assert sword['AnvilATK'] == list(range(30, 901, 30))


@pytest.mark.parametrize('failure', ('missing_reinforcement', 'missing_predicate', 'bad_result', 'negative_gem_level'))
def test_new_calculation_failures_preserve_public_json_and_retry(tmp_path, failure):
    root = prepare_equipment_workspace(tmp_path)
    release = Path(parse(root).BASE_PATH_OUTPUT)
    before = snapshot(release)
    path = root / 'itos_unpack/shared.ipf/equipment_calculate.lua'
    if failure == 'negative_gem_level':
        path = root / 'itos_unpack/xml.ipf/socket_property.xml'
    original = path.read_bytes()
    if failure == 'missing_reinforcement':
        path.write_text(original.decode().replace('function SCR_GET_GODDESS_REINFORCE(', 'function REMOVED_REINFORCE('))
    elif failure == 'missing_predicate':
        path.write_text(original.decode().replace('function IS_WEAPON_TYPE(', 'function REMOVED_PREDICATE('))
    elif failure == 'bad_result':
        path.write_text(original.decode().replace('return result', 'return -1'))
    else:
        path.write_text(original.decode().replace('Level="2"', 'Level="-2"'))
    with pytest.raises(ValueError):
        parse(root, version='equipment-v2')
    assert snapshot(release) == before
    path.write_bytes(original)
    parse(root, version='equipment-v2')
    assert json.loads((release / 'version.json').read_text()) == {'version': 'equipment-v2'}


def test_real_lua_material_groups_free_steps_quantities_and_json_keys(tmp_path):
    db = parse(prepare_equipment_workspace(tmp_path))
    materials = db.data['goddess_reinf_mat']
    assert set(materials[560]) == {'weapon', 'armor'}
    assert set(materials[550]) == {'acc'}
    for level, group, name in ((560, 'weapon', 'weapon'), (560, 'armor', 'armor'), (550, 'acc', 'accessory')):
        assert set(materials[level][group]) == set(range(1, 31))
        assert all(materials[level][group][step] == {} for step in range(1, 6))
        assert materials[level][group][6] == EXPECTED[name + '_material_6']
        assert materials[level][group][30] == EXPECTED[name + '_material_30']
    assert materials[540]['weapon'][6]['harness_ore'] == 24
    restored = json.loads((Path(db.BASE_PATH_OUTPUT) / 'goddess_reinf_mat.json').read_text())
    assert restored['560']['weapon']['30'] == EXPECTED['weapon_material_30']
    assert 'acc' not in restored['560'] and 'weapon' not in restored['550']


def test_real_gem_xml_positive_negative_split_slots_level_zero_and_skill_links(tmp_path):
    db = parse(prepare_equipment_workspace(tmp_path))
    assert set(db.data['item_type']['GEMS']) == {'harness_gem', 'Gem_Harness_Fire'}
    gem = db.data['items_by_name']['harness_gem']
    assert gem['TypeGem'] == 'Gem'
    assert gem['BonusWeapon'] == gem['BonusSubWeapon'] == EXPECTED['gem_weapon']
    assert gem['BonusTopAndBottom'] == EXPECTED['gem_armor']
    assert gem['BonusGloves'] == gem['BonusBoots'] == EXPECTED['gem_hand_foot']
    skill = db.data['items_by_name']['Gem_Harness_Fire']
    assert skill['TypeGem'] == 'Gem_Skill' and skill['Link_Skill'] == '400'
    assert skill['BonusWeapon'] == skill['BonusSubWeapon'] == EXPECTED['skill_gem']
    assert skill['BonusTopAndBottom'] == []


def test_repeat_and_switch_to_older_sources_clears_560_550_and_unregistered_state(tmp_path):
    root = prepare_equipment_workspace(tmp_path / 'current')
    db = parse(root)
    before = snapshot(Path(db.BASE_PATH_OUTPUT))
    assert snapshot(Path(parse(root).BASE_PATH_OUTPUT)) == before
    legacy = prepare_regional_workspace(tmp_path / 'legacy', 'twtos')
    db = parse_workspace(legacy, 'legacy-v1', region='twtos', include_regional=True)
    assert db.data['goddess_reinf'] == {} and db.data['goddess_reinf_unregistered'] == {}
    assert 560 not in db.data['goddess_reinf_mat'] and 550 not in db.data['goddess_reinf_mat']
    assert snapshot(Path(parse(root).BASE_PATH_OUTPUT)) == before


def test_unregistered_table_is_reported_without_running_its_material_branch(tmp_path, monkeypatch):
    root = prepare_equipment_workspace(tmp_path)
    db = ToS_DB()
    db.data, db.file_dict = {}, {}
    db.build('itos', str(root / 'parser_tidy'))
    registry = dict(db.EQUIPMENT_REINFORCE_IES)
    registry.pop('item_goddess_reinforce_560.ies')
    monkeypatch.setattr(db, 'EQUIPMENT_REINFORCE_IES', registry)
    with isolated_parser_state():
        luautil.init(db)
        items.parse_goddess_EQ(db)
    assert 560 not in db.data['goddess_reinf'] and 560 not in db.data['goddess_reinf_mat']
    assert db.data['goddess_reinf_unregistered']['item_goddess_reinforce_560.ies'] == 560


@pytest.mark.parametrize('filename', ('item_goddess_reinforce_560.ies', 'item_gem.ies', 'socket_property.xml'))
def test_required_source_missing_preserves_release_and_retries(tmp_path, filename):
    root = prepare_equipment_workspace(tmp_path)
    db = parse(root)
    release, before = Path(db.BASE_PATH_OUTPUT), snapshot(Path(db.BASE_PATH_OUTPUT))
    path = root / 'itos_unpack' / ('xml.ipf' if filename.endswith('.xml') else 'ies.ipf') / filename
    original = path.read_bytes()
    path.unlink()
    with pytest.raises(FileNotFoundError, match=filename):
        parse(root, version='equipment-v2')
    assert snapshot(release) == before
    path.write_bytes(original)
    parse(root, version='equipment-v2')
    assert json.loads((release / 'version.json').read_text())['version'] == 'equipment-v2'


@pytest.mark.parametrize('failure', ('bad_table', 'empty_table', 'missing_function', 'empty_materials',
                                    'negative_quantity', 'runtime_error', 'bad_xml'))
def test_calculation_or_source_failure_preserves_release_and_retries(tmp_path, failure):
    root = prepare_equipment_workspace(tmp_path)
    db = parse(root)
    release, before = Path(db.BASE_PATH_OUTPUT), snapshot(Path(db.BASE_PATH_OUTPUT))
    unpack = root / 'itos_unpack'
    if failure in ('bad_table', 'empty_table'):
        source = unpack / 'ies.ipf/item_goddess_reinforce_560.ies'
        original = source.read_bytes()
        if failure == 'bad_table':
            change_ies_column(source, 'BasicAtk', 'invalid')
        else:
            source.write_bytes(original.splitlines(keepends=True)[0])
    elif failure == 'bad_xml':
        source = unpack / 'xml.ipf/socket_property.xml'
        original = source.read_bytes()
        source.write_text('invalid xml')
    else:
        source = unpack / 'shared.ipf/equipment_calculate.lua'
        original = source.read_bytes()
        text = original.decode()
        if failure == 'missing_function':
            text = text.replace('function setting_lv_material_weapon(', 'function REMOVED_WEAPON(')
        elif failure == 'empty_materials':
            text = text.replace('if level ~= 540 and level ~= 560 then return end', 'if level ~= 540 then return end')
        elif failure == 'negative_quantity':
            text = text.replace('step * multiplier', '-step * multiplier')
        else:
            text = text.replace('local multiplier = (level - 500) / 10', 'local multiplier = error("fixture material failure")')
        source.write_text(text)
    exception = ParseError if failure == 'bad_xml' else LuaError if failure == 'runtime_error' else ValueError
    with pytest.raises(exception):
        parse(root, version='equipment-v2')
    assert snapshot(release) == before
    source.write_bytes(original)
    parse(root, version='equipment-v2')
    assert json.loads((release / 'version.json').read_text())['version'] == 'equipment-v2'


@pytest.mark.parametrize('phase', ('DEF', 'ATK', 'price'))
def test_legacy_anvil_error_mid_loop_preserves_release_and_retries(tmp_path, monkeypatch, phase):
    root = prepare_equipment_workspace(tmp_path)
    equipment = root / 'itos_unpack/ies.ipf/item_equip.ies'
    change_ies_column(equipment, 'ItemGrade', '1')
    change_ies_column(equipment, 'BasicTooltipProp', 'ATK,DEF')
    # Install independent formulas after every init, so fixture globals loaded
    # under the same names cannot replace the functions used by this test.
    original_init = luautil.init
    active_phase = 'none'
    formulas = '''
function GET_REINFORCE_ADD_VALUE(pc, item, zero, one)
    if item.Reinforce_2 == 7 and 'FAIL_PHASE' == 'DEF' then
        error('fixture legacy anvil failure at DEF level 7')
    end
    return 200 + item.Reinforce_2 * 3
end
function GET_REINFORCE_ADD_VALUE_ATK(item, zero, one, pc)
    if item.Reinforce_2 == 7 and 'FAIL_PHASE' == 'ATK' then
        error('fixture legacy anvil failure at ATK level 7')
    end
    return 100 + item.Reinforce_2 * 2
end
function GET_REINFORCE_PRICE(item, materials, pc)
    if item.Reinforce_2 == 7 and 'FAIL_PHASE' == 'price' then
        error('fixture legacy anvil failure at price level 7')
    end
    return 1000 + item.Reinforce_2 * 5
end
'''

    def init_with_formulas(c):
        original_init(c)
        luautil.lua.execute(formulas.replace('FAIL_PHASE', active_phase))
        for name in ('GET_REINFORCE_ADD_VALUE', 'GET_REINFORCE_ADD_VALUE_ATK',
                     'GET_REINFORCE_PRICE'):
            luautil.LUA_RUNTIME[name] = luautil.lua.globals()[name]

    monkeypatch.setattr(luautil, 'init', init_with_formulas)
    db = parse(root)
    sword = db.data['items_by_name']['harness_sword']
    assert sword['AnvilDEF'] == list(range(200, 318, 3))
    assert sword['AnvilATK'] == list(range(100, 179, 2))
    assert sword['AnvilPrice'] == [1000 + 5 * lv for lv in range(40) for _ in range(2)]
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    assert json.loads(before['version.json']) == {'version': 'equipment-v1'}

    active_phase = phase
    with pytest.raises(LuaError, match='fixture legacy anvil failure at ' + phase + ' level 7'):
        parse(root, version='equipment-v2')
    assert snapshot(release) == before

    active_phase = 'none'
    parse(root, version='equipment-v2')
    after = snapshot(release)
    assert json.loads(after['version.json']) == {'version': 'equipment-v2'}
    assert {name: data for name, data in after.items() if name != 'version.json'} == {
        name: data for name, data in before.items() if name != 'version.json'}

