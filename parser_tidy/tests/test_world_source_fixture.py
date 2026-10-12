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


def _npc_link_source(root, names=('alpha',)):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'map.ies'
    path.write_text('ClassName,Width,Height\n' + ''.join(
        '{},200,100\n'.format(name) for name in names), encoding='utf-8')
    objects = {str(index): {'$ID': str(index), '$ID_NAME': name, 'bbox': [3, 4, 0, 0]}
               for index, name in enumerate(names, 900)}
    npc = {'$ID': '700'}
    monster = {'$ID': '701'}
    lookup = {'vendor': (npc, 'NPC'), 'beast': (monster, 'Monster')}
    return SimpleNamespace(
        PATH_INPUT_DATA=str(root), region='itos',
        file_dict={'map.ies': {'path': str(path)}},
        data={'maps': objects, 'maps_by_name': {obj['$ID_NAME']: obj for obj in objects.values()},
              'npcs_by_name': {'vendor': npc}, 'monsters_by_name': {'beast': monster},
              'items_by_name': {'recipe_token': {'$ID': '100', '$ID_NAME': 'recipe_token'}},
              'item_type': {'RECIPES': ['recipe_token']}, 'map_npc': [],
              'map_item_spawn': [], 'map_item': [],
              'unresolved_drops': [{'collection': 'monster', 'Token': 'keep'}]},
        getNPCbyName=lookup.get,
    )


def _write_spawn_source(root, filename, body):
    directory = root / 'ies_mongen.ipf'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(body, encoding='utf-8')


def test_npc_directory_index_once_preserves_independent_multimap_relations(tmp_path, monkeypatch):
    db = _npc_link_source(tmp_path, ('alpha', 'beta', 'missing_anchor', 'missing_gentype'))
    _write_spawn_source(tmp_path, 'ANCHOR_ALPHA.IES',
                        'GenType,PosX,PosZ\n'
                        'a,10,4\na,-10,14\nb,0,0\nitem,4,-10\n'
                        'unknown,0,0\nunknown_item,0,0\nunused,0,0\n')
    _write_spawn_source(tmp_path, 'GenType_Alpha.Ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\n'
                        'a,vendor,,2,1500\nb,vendor,,3,9000\n'
                        'item,vendor,ITEM:recipe_token:SPAWN,4,2500\n'
                        'unknown,missing_npc,,99,1000\n'
                        'unknown_item,vendor,ITEM:missing_item:SPAWN,99,1000\n'
                        'no_anchor,vendor,,99,1000\n')
    _write_spawn_source(tmp_path, 'anchor_beta.ies', 'GenType,PosX,PosZ\na,-6,8\n')
    _write_spawn_source(tmp_path, 'gentype_beta.ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,beast,,6,750\n')
    _write_spawn_source(tmp_path, 'gentype_missing_anchor.ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,vendor,,1,1000\n')
    _write_spawn_source(tmp_path, 'anchor_missing_gentype.ies', 'GenType,PosX,PosZ\na,0,0\n')
    Path(db.file_dict['map.ies']['path']).write_text(
        'ClassName,Width,Height\nalpha,200,100\nbeta,80,60\n'
        'missing_anchor,200,100\nmissing_gentype,200,100\n', encoding='utf-8')
    db.data['maps']['901']['bbox'] = [1, 2, 0, 0]
    listdir = maps.os.listdir
    calls = []

    def record_listing(path):
        calls.append(path)
        return listdir(path)

    monkeypatch.setattr(maps.os, 'listdir', record_listing)
    maps.parse_links_npcs(db)
    assert calls == [str(tmp_path / 'ies_mongen.ipf')]
    assert db.data['map_npc'] == [
        {'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 5,
         'Positions': [[52, 19], [42, 14], [47, 21]], 'TimeRespawn': 1.5},
        {'NPC': '701', 'Map': '901', 'Type': 'Monster', 'Population': 6,
         'Positions': [[16, 9]], 'TimeRespawn': 0.75},
    ]
    assert db.data['map_item_spawn'] == [
        {'Item': 'recipe-100', 'Map': '900', 'Population': 4,
         'Positions': [[49, 26]], 'TimeRespawn': 2.5},
    ]
    assert db.data['unresolved_drops'] == [{'collection': 'monster', 'Token': 'keep'}]


def test_empty_maps_do_not_access_missing_spawn_directory(tmp_path, monkeypatch):
    db = _npc_link_source(tmp_path, ())
    calls = []
    listdir = maps.os.listdir

    def record_listing(path):
        calls.append(path)
        return listdir(path)

    monkeypatch.setattr(maps.os, 'listdir', record_listing)
    maps.parse_links_npcs(db)
    assert calls == []
    assert db.data['map_npc'] == []
    assert db.data['map_item_spawn'] == []
    assert not (tmp_path / 'ies_mongen.ipf').exists()


@pytest.mark.parametrize('error', [FileNotFoundError, PermissionError])
def test_nonempty_maps_preserve_spawn_directory_errors(tmp_path, monkeypatch, error):
    db = _npc_link_source(tmp_path)
    calls = []
    listdir = maps.os.listdir

    def failing_listing(path):
        calls.append(path)
        if error is FileNotFoundError:
            return listdir(path)
        raise PermissionError('spawn directory denied')

    monkeypatch.setattr(maps.os, 'listdir', failing_listing)
    with pytest.raises(error):
        maps.parse_links_npcs(db)
    assert calls == [str(tmp_path / 'ies_mongen.ipf')]


@pytest.mark.parametrize('reverse', [False, True])
def test_spawn_case_collisions_use_last_listing_entry(tmp_path, monkeypatch, reverse):
    db = _npc_link_source(tmp_path)
    names = ['anchor_alpha.ies', 'ANCHOR_ALPHA.IES', 'gentype_alpha.ies', 'GENTYPE_ALPHA.IES']
    _write_spawn_source(tmp_path, names[0], 'GenType,PosX,PosZ\na,0,0\n')
    _write_spawn_source(tmp_path, names[1], 'GenType,PosX,PosZ\na,20,-20\n')
    _write_spawn_source(tmp_path, names[2],
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,vendor,,2,1000\n')
    _write_spawn_source(tmp_path, names[3],
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,beast,,7,2500\n')
    calls = []

    def ordered_listing(path):
        calls.append(path)
        return names[::-1] if reverse else names[:]

    monkeypatch.setattr(maps.os, 'listdir', ordered_listing)
    maps.parse_links_npcs(db)
    assert calls == [str(tmp_path / 'ies_mongen.ipf')]
    expected = ({'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 2,
                 'Positions': [[47, 21]], 'TimeRespawn': 1.0} if reverse else
                {'NPC': '701', 'Map': '900', 'Type': 'Monster', 'Population': 7,
                 'Positions': [[57, 31]], 'TimeRespawn': 2.5})
    assert db.data['map_npc'] == [expected]


def test_empty_directory_index_is_reused_and_missing_names_use_literal_fallback(tmp_path, monkeypatch):
    db = _npc_link_source(tmp_path, ('alpha', 'beta'))
    for name in ('alpha', 'beta'):
        _write_spawn_source(tmp_path, 'anchor_{}.ies'.format(name), 'GenType,PosX,PosZ\na,0,0\n')
        _write_spawn_source(tmp_path, 'gentype_{}.ies'.format(name),
                            'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,vendor,,1,1000\n')
    calls = []

    def empty_listing(path):
        calls.append(path)
        return []

    monkeypatch.setattr(maps.os, 'listdir', empty_listing)
    maps.parse_links_npcs(db)
    assert calls == [str(tmp_path / 'ies_mongen.ipf')]
    assert db.data['map_npc'] == [
        {'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 1,
         'Positions': [[47, 21]], 'TimeRespawn': 1.0},
        {'NPC': '700', 'Map': '901', 'Type': 'NPC', 'Population': 1,
         'Positions': [[47, 21]], 'TimeRespawn': 1.0},
    ]


def test_spawn_index_refreshes_after_region_path_and_directory_changes(tmp_path, monkeypatch):
    itos_root = tmp_path / 'itos'
    jtos_root = tmp_path / 'jtos'
    db = _npc_link_source(itos_root)
    _write_spawn_source(itos_root, 'anchor_alpha.ies', 'GenType,PosX,PosZ\na,0,0\n')
    _write_spawn_source(itos_root, 'gentype_alpha.ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,vendor,,1,1000\n')
    _write_spawn_source(jtos_root, 'ANCHOR_ALPHA.IES', 'GenType,PosX,PosZ\na,20,-20\n')
    _write_spawn_source(jtos_root, 'GENTYPE_ALPHA.IES',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,beast,,7,2500\n')
    listdir = maps.os.listdir
    calls = []

    def record_listing(path):
        calls.append(path)
        return listdir(path)

    monkeypatch.setattr(maps.os, 'listdir', record_listing)
    maps.parse_links_npcs(db)
    first = {'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 1,
             'Positions': [[47, 21]], 'TimeRespawn': 1.0}
    assert db.data['map_npc'] == [first]
    db.region = 'jtos'
    db.PATH_INPUT_DATA = str(jtos_root)
    maps.parse_links_npcs(db)
    second = {'NPC': '701', 'Map': '900', 'Type': 'Monster', 'Population': 7,
              'Positions': [[57, 31]], 'TimeRespawn': 2.5}
    assert db.data['map_npc'] == [first, second]
    (jtos_root / 'ies_mongen.ipf/ANCHOR_ALPHA.IES').unlink()
    (jtos_root / 'ies_mongen.ipf/GENTYPE_ALPHA.IES').unlink()
    _write_spawn_source(jtos_root, 'Anchor_Alpha.Ies', 'GenType,PosX,PosZ\na,-20,20\n')
    _write_spawn_source(jtos_root, 'Gentype_Alpha.Ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\na,vendor,,4,750\n')
    maps.parse_links_npcs(db)
    third = {'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 4,
             'Positions': [[37, 11]], 'TimeRespawn': 0.75}
    assert db.data['map_npc'] == [first, second, third]
    db.region = 'itos'
    db.PATH_INPUT_DATA = str(itos_root)
    maps.parse_links_npcs(db)
    assert db.data['map_npc'] == [first, second, third, first]
    assert calls == [str(root / 'ies_mongen.ipf')
                     for root in (itos_root, jtos_root, jtos_root, itos_root)]


def test_direct_spawn_links_append_but_parent_relink_resets_relations(tmp_path, monkeypatch):
    db = _npc_link_source(tmp_path)
    _write_spawn_source(tmp_path, 'anchor_alpha.ies', 'GenType,PosX,PosZ\na,0,0\nitem,4,-10\n')
    _write_spawn_source(tmp_path, 'gentype_alpha.ies',
                        'GenType,ClassType,ArgStr2,MaxPop,RespawnTime\n'
                        'a,vendor,,1,1000\nitem,vendor,ITEM:recipe_token:SPAWN,4,2500\n')
    expected_npcs = [{'NPC': '700', 'Map': '900', 'Type': 'NPC', 'Population': 1,
                      'Positions': [[47, 21]], 'TimeRespawn': 1.0}]
    expected_items = [{'Item': 'recipe-100', 'Map': '900', 'Population': 4,
                       'Positions': [[49, 26]], 'TimeRespawn': 2.5}]
    maps.parse_links_npcs(db)
    maps.parse_links_npcs(db)
    assert db.data['map_npc'] == expected_npcs * 2
    assert db.data['map_item_spawn'] == expected_items * 2
    # Isolate the parent's reset from unrelated item/drop/floor source parsing.
    for name in ('parse_links_items', 'parse_links_items_rewards', 'parse_links_maps'):
        monkeypatch.setattr(maps, name, lambda constants: None)
    db.data['unresolved_drops'].append({'collection': 'map_item', 'Token': 'stale'})
    for _ in range(2):
        maps.parse_links(db)
        assert db.data['map_npc'] == expected_npcs
        assert db.data['map_item_spawn'] == expected_items
        assert db.data['unresolved_drops'] == [{'collection': 'monster', 'Token': 'keep'}]


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
