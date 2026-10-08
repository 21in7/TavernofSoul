"""Small world IES/XML/TSV inputs exercise maps, attributes and all buff files."""
import copy
import json
from pathlib import Path

import pytest

from harness.fixture_inputs import WORLD_FIXTURE
from harness.parser_fixture import change_ies_column, parse_workspace, prepare_world_workspace
from ipfparser.contracts import ContractError
import maps

EXPECTED = json.loads((WORLD_FIXTURE / 'expected_world.json').read_text(encoding='utf-8'))


@pytest.fixture
def world_workspace(tmp_path):
    return prepare_world_workspace(tmp_path)


def parse(root, version='world-v1'):
    return parse_workspace(root, version, include_world=True)


def snapshot(db):
    return {path.name: path.read_bytes() for path in Path(db.BASE_PATH_OUTPUT).glob('*.json')}


@pytest.mark.parametrize('collection', sorted(EXPECTED))
def test_actual_world_json_matches_independent_expected_values(world_workspace, collection):
    db = parse(world_workspace)
    actual = json.loads((Path(db.BASE_PATH_OUTPUT) / (collection + '.json')).read_text())
    expected = EXPECTED[collection]
    if isinstance(expected, list):
        assert actual == expected
    else:
        assert set(actual) == set(expected)
        for key, fields in expected.items():
            for field, value in fields.items():
                assert actual[key][field] == value, '{}.{}.{}'.format(collection, key, field)


def test_attribute_names_reverse_links_and_cleanup(world_workspace):
    db = parse(world_workspace)
    assert db.data['attributes']['921']['Link_Skills'] == ['Harness_Fire']
    assert db.data['skills']['400']['Link_Attributes'] == ['920', '921']
    assert db.data['jobs']['300']['Link_Attributes'] == ['922']
    assert '923' not in db.data['attributes']
    assert 'Harness_InactiveAttribute' not in db.data['attributes_by_name']
    assert '401' not in db.data['skills']
    # A reference to a cleaned-up non-job skill remains explicitly optional.
    assert db.data['attributes']['924']['Link_Skills'] == ['Harness_Orphan']
    assert '912' not in db.data['buff']


def test_rebuild_and_relink_preserve_json_without_duplicate_relations(world_workspace):
    db = parse(world_workspace)
    before = snapshot(db)
    relations = {name: copy.deepcopy(db.data[name]) for name in
                 ('map_item', 'map_npc', 'map_item_spawn', 'unresolved_drops', 'maps')}
    maps.parse_links(db)
    maps.parse_links(db)
    for name, value in relations.items():
        assert db.data[name] == value
    db.export(version_payload={'version': 'world-v1'})
    assert snapshot(db) == before
    assert snapshot(parse(world_workspace)) == before


def test_changed_group_weights_spawn_and_buff_units_recompute(world_workspace):
    parse(world_workspace)
    unpack = world_workspace / 'itos_unpack'
    change_ies_column(unpack / 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'DropRatio', '1')
    change_ies_column(unpack / 'ies_mongen.ipf/GENTYPE_harness_field.IES', 'RespawnTime', '1750')
    change_ies_column(unpack / 'ies.ipf/buff_hardskill.ies', 'ApplyTime', '8250')
    change_ies_column(unpack / 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', '6')
    changed = parse(world_workspace, 'world-v2')
    field = {row['Item']: row['Chance'] for row in changed.data['map_item'] if row['Map'] == '900'}
    assert field == {'100': 12.5, '101': 10.0, '110': 10.0}
    assert changed.data['map_npc'][0]['TimeRespawn'] == 1.75
    assert changed.data['buff']['910']['ApplyTime'] == '8250'
    assert changed.data['attributes']['920']['LevelMax'] == 6


def test_later_buff_file_has_deterministic_precedence(world_workspace):
    path = world_workspace / 'itos_unpack/ies.ipf/buff_contents.ies'
    change_ies_column(path, 'ClassID', '910')
    change_ies_column(path, 'ClassName', 'Harness_ShieldBuff')
    change_ies_column(path, 'Name', 'Later Override')
    db = parse(world_workspace)
    assert set(db.data['buff']) == {'910', '911', '913'}
    assert db.data['buff']['910']['Name'] == 'Later Override'
    assert db.data['buff']['910']['ApplyTime'] == '0'
    assert db.data['buff']['910']['UserRemove'] == 0


def test_zero_weight_group_keeps_direct_drops(world_workspace):
    path = world_workspace / 'itos_unpack/ies_drop.ipf/dropgroup/HARNESS_GROUP.IES'
    change_ies_column(path, 'DropRatio', '0', index=0)
    change_ies_column(path, 'DropRatio', '0', index=1)
    db = parse(world_workspace)
    assert [(row['Item'], row['Chance']) for row in db.data['map_item'] if row['Map'] == '900'] == [('100', 12.5)]


def test_unused_zone_rows_do_not_require_a_drop_ratio(world_workspace):
    path = world_workspace / 'itos_unpack/ies_drop.ipf/zonedrop/ZONEDROPITEMLIST_F_HARNESS_CAVE.IES'
    change_ies_column(path, 'ItemClassName', '')
    change_ies_column(path, 'DropRatio', '')
    db = parse(world_workspace)
    assert not [row for row in db.data['map_item'] if row['Map'] == '901']


INVALID_INPUTS = [
    ('map-level', 'ies.ipf/map.ies', 'QuestLevel', 'bad', 0, ValueError),
    ('map-link', 'ies.ipf/map.ies', 'PhysicalLinkZone', 'missing_map', 0, KeyError),
    ('drop-string', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', 'bad', 0, ValueError),
    ('drop-negative', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '-1', 0, ValueError),
    ('drop-range', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '10001', 0, ValueError),
    ('group-negative', 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'DropRatio', '-5', 0, ValueError),
    ('group-string', 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'DropRatio', 'bad', 0, ValueError),
    ('duplicate-drop', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'ItemClassName', 'harness_dust', 0, ContractError),
    ('spawn-time', 'ies_mongen.ipf/GENTYPE_harness_field.IES', 'RespawnTime', 'bad', 0, ValueError),
    ('spawn-population', 'ies_mongen.ipf/GENTYPE_harness_field.IES', 'MaxPop', '-10', 0, ContractError),
    ('spawn-coordinate', 'ies_mongen.ipf/ANCHOR_harness_field.IES', 'PosX', 'bad', 0, ValueError),
    ('attribute-max-level', 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', 'bad', 0, ValueError),
    ('attribute-fraction', 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', '3.5', 0, ValueError),
    ('attribute-job-level', 'ies_ability.ipf/ability.ies', 'Level', 'bad', 2, ContractError),
    ('buff-duration', 'ies.ipf/buff_hardskill.ies', 'ApplyTime', 'bad', 0, ContractError),
    ('buff-stack', 'ies.ipf/buff_hardskill.ies', 'OverBuff', 'two', 0, ContractError),
]


@pytest.mark.parametrize('case,filename,column,value,index,error', INVALID_INPUTS,
                         ids=[case[0] for case in INVALID_INPUTS])
def test_invalid_source_preserves_release_and_can_retry(world_workspace, case, filename,
                                                        column, value, index, error):
    db = parse(world_workspace)
    before = snapshot(db)
    path = world_workspace / 'itos_unpack' / filename
    original = change_ies_column(path, column, value, index)
    with pytest.raises(error):
        parse(world_workspace, 'world-v2')
    assert snapshot(db) == before
    assert not Path(db.BASE_PATH_OUTPUT + '.staging').exists()
    assert not Path(db.BASE_PATH_OUTPUT + '.backup').exists()
    change_ies_column(path, column, original, index)
    changed = parse(world_workspace, 'world-v2')
    assert json.loads((Path(changed.BASE_PATH_OUTPUT) / 'version.json').read_text()) == {'version': 'world-v2'}


@pytest.mark.parametrize('filename', [
    'ies.ipf/map.ies', 'ies_ability.ipf/ability.ies', 'ies_ability.ipf/Ability_HarnessMage.IES',
    'ies.ipf/buff_contents.ies', 'ies_mongen.ipf/ANCHOR_harness_field.IES',
    'ies_drop.ipf/dropgroup/SANCTUARY_GROUP.IES',
])
def test_missing_required_fixture_fails_before_publication(world_workspace, filename):
    db = parse(world_workspace)
    before = snapshot(db)
    path = world_workspace / 'itos_unpack' / filename
    original = path.read_bytes()
    path.unlink()
    with pytest.raises(FileNotFoundError, match='Missing parser fixture input'):
        parse(world_workspace, 'world-v2')
    assert snapshot(db) == before
    path.write_bytes(original)
    parse(world_workspace, 'world-v2')


def test_missing_attribute_column_is_not_silently_cleaned_up(world_workspace):
    db = parse(world_workspace)
    before = snapshot(db)
    path = world_workspace / 'itos_unpack/ies_ability.ipf/Ability_HarnessMage.IES'
    original = path.read_text()
    path.write_text(original.replace('MaxLevel', 'WrongColumn', 1))
    with pytest.raises(KeyError, match='MaxLevel'):
        parse(world_workspace, 'world-v2')
    assert snapshot(db) == before
    path.write_text(original)
    parse(world_workspace, 'world-v2')
