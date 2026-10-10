"""Small world IES/XML/TSV inputs exercise maps, attributes and all buff files."""
import copy
import csv
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from DB import ToS_DB
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


@pytest.fixture
def floor_source(tmp_path):
    path = tmp_path / 'map.ies'
    path.write_text(
        'ClassID,ClassName,Name,ChallengeMode,WarpCost,QuestLevel,EliteMonsterCapacity,'
        'MaxHateCount,MapRank,MapType,WorldMap,PhysicalLinkZone\n'
        '900,harness_existing_ground,Existing Ground,NO,0,1,0,0,1,Field,52/25/0,harness_upper_2\n'
        '901,harness_upper_2,Upper Two,NO,0,1,0,0,1,Field,16/50/2,harness_existing_ground/harness_upper_3\n'
        '902,harness_upper_3,Upper Three,NO,0,1,0,0,1,Field,16/50/3,harness_upper_2/harness_upper_4\n'
        '903,harness_upper_4,Upper Four,NO,0,1,0,0,1,Field,16/50/4,harness_upper_3/harness_upper_5\n'
        '904,harness_upper_5,Upper Five,NO,0,1,0,0,1,Field,16/50/5,harness_upper_4\n'
        '905,harness_floor_ground,Floor Ground,NO,0,1,0,0,1,Field,7/8/1,harness_floor_upper\n'
        '906,harness_floor_upper,Floor Upper,NO,0,1,0,0,1,Field,7/8/2,harness_floor_ground\n',
        encoding='utf-8',
    )
    return SimpleNamespace(
        file_dict={'map.ies': {'path': str(path)}},
        data={'maps': {}, 'maps_by_name': {}, 'maps_by_position': {}},
        translate=lambda name: name,
    )


def test_optional_floor_grouping_preserves_maps_and_physical_links_on_rebuild(floor_source, caplog):
    db = floor_source
    maps.parse_maps(db)
    expected = {
        '900': ('harness_existing_ground', 'Existing Ground', [52, 25, 0], ['901'], []),
        '901': ('harness_upper_2', 'Upper Two', [16, 50, 2], ['900', '902'], []),
        '902': ('harness_upper_3', 'Upper Three', [16, 50, 3], ['901', '903'], []),
        '903': ('harness_upper_4', 'Upper Four', [16, 50, 4], ['902', '904'], []),
        '904': ('harness_upper_5', 'Upper Five', [16, 50, 5], ['903'], []),
        '905': ('harness_floor_ground', 'Floor Ground', [7, 8, 1], ['906'], ['906']),
        '906': ('harness_floor_upper', 'Floor Upper', [7, 8, 2], ['905'], []),
    }
    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            maps.parse_links_maps(db)
        assert set(db.data['maps']) == set(expected)
        assert set(db.data['maps_by_name']) == {row[0] for row in expected.values()}
        assert set(db.data['maps_by_position']) == {
            '52-25-0', '16-50-2', '16-50-3', '16-50-4', '16-50-5', '7-8-1', '7-8-2',
        }
        for map_id, (name, title, position, links, floors) in expected.items():
            obj = db.data['maps'][map_id]
            assert obj['$ID'] == map_id
            assert obj['$ID_NAME'] == name
            assert obj['Name'] == title
            assert obj['WorldMap'] == position
            assert obj['Link_Maps'] == links
            assert obj['Link_Maps_Floors'] == floors
            assert db.data['maps_by_name'][name] is obj
            assert db.data['maps_by_position']['-'.join(str(i) for i in position)] is obj
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 4
        for floor, record in zip(range(2, 6), warnings):
            message = record.getMessage()
            assert db.file_dict['map.ies']['path'] in message
            assert 'harness_upper_{}'.format(floor) in message
            assert '16-50-1' in message


def test_missing_floor_ground_preserves_known_links_and_unresolved_context(floor_source, caplog):
    db = floor_source
    path = Path(db.file_dict['map.ies']['path'])
    raw = 'harness_existing_ground/missing_map/900/harness_upper_3/missing_map'
    change_ies_column(path, 'PhysicalLinkZone', raw, index=1)
    maps.parse_maps(db)
    original_ids = set(db.data['maps'])
    original_classes = set(db.data['maps_by_name'])
    expected = [
        {'Map': '901', 'MapClassName': 'harness_upper_2', 'Token': token,
         'Raw': raw, 'SourceFile': 'map.ies', 'SourceField': 'PhysicalLinkZone',
         'SourceRow': 3}
        for token in ('missing_map', '900')
    ]
    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            maps.parse_links_maps(db)
        assert db.data['maps']['901']['Link_Maps'] == ['900', '902']
        assert db.data['unresolved_map_links'] == expected
        assert set(db.data['maps']) == original_ids
        assert set(db.data['maps_by_name']) == original_classes
        assert db.data['maps']['905']['Link_Maps_Floors'] == ['906']
        assert db.data['maps']['901']['Link_Maps_Floors'] == []
        warnings = [record.getMessage() for record in caplog.records
                    if record.levelno == logging.WARNING]
        assert len(warnings) == 4
        assert all('16-50-1' in message for message in warnings)
    previous_diagnostics = db.data['unresolved_map_links']
    change_ies_column(path, 'PhysicalLinkZone', 'harness_upper_3/harness_existing_ground', index=1)
    maps.parse_links_maps(db)
    assert db.data['maps']['901']['Link_Maps'] == ['902', '900']
    assert db.data['unresolved_map_links'] == []
    assert db.data['unresolved_map_links'] is not previous_diagnostics
    assert previous_diagnostics == expected


@pytest.mark.parametrize('builder', [maps.parse_maps, maps.parse_links_items_rewards],
                         ids=['parse-maps', 'reward-map-creation'])
@pytest.mark.parametrize('missing_column', [False, True], ids=['reward-column', 'legacy-column-missing'])
def test_reward_expbm_uses_its_own_float_column_in_both_creation_paths(
        world_workspace, builder, missing_column):
    root = world_workspace / 'itos_unpack'
    path = root / 'ies.ipf/map.ies'
    if missing_column:
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            fields = [field for field in reader.fieldnames if field != 'RewardEXPBM']
            rows = list(reader)
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
    db = SimpleNamespace(
        PATH_INPUT_DATA=str(root), file_dict={'map.ies': {'path': str(path)}},
        data={'maps': {}, 'maps_by_name': {}, 'maps_by_position': {}},
        translate=lambda value: value,
    )
    builder(db)
    expected = {'harness_field': 0.0, 'harness_cave': 12.5,
                'id_unknownsanctuary_harness': 2.5}
    assert set(db.data['maps_by_name']) == set(expected)
    for name, value in expected.items():
        row = db.data['maps_by_name'][name]
        assert type(row['Prop_RewardEXPBM']) is float
        assert row['Prop_RewardEXPBM'] == (0.0 if missing_column else value)
        assert row['Prop_RewardEXPBM'] != row['Prop_MaxHateCount']
    # The separately authored world oracle must also check the public field.
    if not missing_column:
        for map_id, value in [('900', 0.0), ('901', 12.5), ('902', 2.5)]:
            assert EXPECTED['maps'][map_id]['Prop_RewardEXPBM'] == value


def test_build_initializes_a_fresh_unresolved_map_link_list(tmp_path, monkeypatch):
    db = ToS_DB()
    stale = [{'Token': 'prior_region_missing'}]
    db.data = {'unresolved_map_links': stale}
    # Isolate build's initialization from file discovery and legacy JSON loads.
    monkeypatch.setattr(db, 'directoryDictionary', lambda directory: None)
    monkeypatch.setattr(db, 'importJSON', lambda path: {})
    for region in ('itos', 'jtos'):
        db.build(region, str(tmp_path / 'parser_tidy'))
        fresh = db.data['unresolved_map_links']
        assert fresh == []
        assert fresh is not stale
        assert stale == [{'Token': 'prior_region_missing'}]
        fresh.append({'Token': 'prior_region_missing'})
        stale = fresh


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
                 ('map_item', 'map_npc', 'map_item_spawn', 'unresolved_drops',
                  'unresolved_map_links', 'maps')}
    maps.parse_links(db)
    maps.parse_links(db)
    for name, value in relations.items():
        assert db.data[name] == value
    db.export(version_payload={'version': 'world-v1'})
    assert snapshot(db) == before
    assert snapshot(parse(world_workspace)) == before


def test_changed_physical_links_export_exact_diagnostics_and_rebuild_cleanly(world_workspace):
    db = parse(world_workspace)
    path = world_workspace / 'itos_unpack/ies.ipf/map.ies'
    raw = 'id_unknownsanctuary_harness/2/harness_cave/missing_new/2'
    change_ies_column(path, 'PhysicalLinkZone', raw)
    expected = [
        {'Map': '900', 'MapClassName': 'harness_field', 'Token': token,
         'Raw': raw, 'SourceFile': 'ies.ipf/map.ies',
         'SourceField': 'PhysicalLinkZone', 'SourceRow': 2}
        for token in ('2', 'missing_new')
    ]
    for _ in range(2):
        maps.parse_links_maps(db)
        assert db.data['maps']['900']['Link_Maps'] == ['902', '901']
        assert db.data['maps']['900']['Link_Maps_Floors'] == ['901']
        assert set(db.data['maps']) == {'900', '901', '902'}
        assert db.data['unresolved_map_links'] == expected
    db.export(version_payload={'version': 'world-v1'})
    exported = Path(db.BASE_PATH_OUTPUT) / 'unresolved_map_links.json'
    assert json.loads(exported.read_text()) == expected
    before = snapshot(db)
    rebuilt = parse(world_workspace)
    assert snapshot(rebuilt) == before
    change_ies_column(path, 'PhysicalLinkZone', 'harness_cave/id_unknownsanctuary_harness')
    maps.parse_links_maps(rebuilt)
    assert rebuilt.data['unresolved_map_links'] == []
    rebuilt.export(version_payload={'version': 'world-v2'})
    assert json.loads(exported.read_text()) == []
    clean_snapshot = snapshot(rebuilt)
    clean_rebuild = parse(world_workspace, 'world-v2')
    assert clean_rebuild.data['unresolved_map_links'] == []
    assert snapshot(clean_rebuild) == clean_snapshot


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
    ('drop-string', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', 'bad', 0, ValueError),
    ('drop-negative', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '-1', 0, ValueError),
    ('drop-range', 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '10001', 0, ValueError),
    ('group-negative', 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'DropRatio', '-5', 0, ValueError),
    ('group-string', 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'DropRatio', 'bad', 0, ValueError),
    ('spawn-time', 'ies_mongen.ipf/GENTYPE_harness_field.IES', 'RespawnTime', 'bad', 0, ValueError),
    ('spawn-population', 'ies_mongen.ipf/GENTYPE_harness_field.IES', 'MaxPop', '-10', 0, ContractError),
    ('spawn-coordinate', 'ies_mongen.ipf/ANCHOR_harness_field.IES', 'PosX', 'bad', 0, ValueError),
    ('attribute-max-level', 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', 'bad', 0, ValueError),
    ('attribute-fraction', 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', '3.5', 0, ValueError),
    ('attribute-job-level', 'ies_ability.ipf/ability.ies', 'Level', 'bad', 2, ContractError),
    ('buff-duration', 'ies.ipf/buff_hardskill.ies', 'ApplyTime', 'bad', 0, ContractError),
    ('buff-stack', 'ies.ipf/buff_hardskill.ies', 'OverBuff', 'two', 0, ContractError),
]


def test_explicit_million_base_and_last_variant(world_workspace):
    path = world_workspace / 'itos_unpack/ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies'
    path.write_text('ItemClassName,BaseRatio,DropRatio,DropGroup\n'
                    'harness_ore,1000000,32000,\n'
                    'harness_ore,1000000,10400,\n')
    db = parse(world_workspace)
    rows = [row for row in db.data['map_item'] if row['Map'] == '900']
    assert len(rows) == 1
    assert rows[0]['Chance'] == 1.04
    maps.parse_links(db)
    assert [row for row in db.data['map_item'] if row['Map'] == '900'] == rows


@pytest.mark.parametrize('base', ['0', '-1', 'bad'])
def test_invalid_explicit_drop_base_preserves_release(world_workspace, base):
    db = parse(world_workspace)
    before = snapshot(db)
    path = world_workspace / 'itos_unpack/ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies'
    path.write_text('ItemClassName,BaseRatio,DropRatio,DropGroup\nharness_ore,' + base + ',32000,\n')
    with pytest.raises(ValueError):
        parse(world_workspace, 'world-v2')
    assert snapshot(db) == before


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
