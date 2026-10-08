"""Real skill/monster/drop inputs, calculations, references, and release failures."""
import json
from pathlib import Path

import pytest

import luautil
import monsters
import skills
from harness.fixture_inputs import COMBAT_FIXTURE
from harness.parser_fixture import (change_ies_column as change_column,
                                    parse_workspace, prepare_combat_workspace)

EXPECTED = json.loads((COMBAT_FIXTURE / 'expected_combat.json').read_text())


def snapshot(release):
    return {path.name: path.read_bytes() for path in release.glob('*.json')}


@pytest.fixture
def combat_workspace(tmp_path):
    return prepare_combat_workspace(tmp_path)


def parse(root, version='combat-fixture-v1_001001.ipf'):
    return parse_workspace(root, version, include_combat=True)


@pytest.mark.parametrize('collection', sorted(EXPECTED))
def test_real_sources_match_independent_combat_expectations(combat_workspace, collection):
    db = parse(combat_workspace)
    output = json.loads((Path(db.BASE_PATH_OUTPUT) / (collection + '.json')).read_text())
    expected = EXPECTED[collection]
    if collection in ('jobs_by_name', 'skills_by_name', 'monsters_by_name', 'skill_mon'):
        assert set(output) == set(expected)
        for name, fields in expected.items():
            for field, value in fields.items():
                assert output[name][field] == value, '{}.{}.{}'.format(collection, name, field)
    else:
        assert output == expected


def test_changed_skill_monster_lua_and_drop_sources_recompute(combat_workspace):
    parse(combat_workspace)
    unpack = combat_workspace / 'itos_unpack'
    change_column(unpack / 'ies.ipf/skill.ies', 'SklFactor', '200')
    change_column(unpack / 'ies.ipf/monster.ies', 'Level', '12')
    change_column(unpack / 'ies_drop.ipf/HARNESS_WOLF.IES', 'DropRatio', '2500')
    lua_file = unpack / 'shared.ipf/combat_calculate.lua'
    lua_file.write_text(lua_file.read_text().replace('HARNESS_SKILL_STEP = 10', 'HARNESS_SKILL_STEP = 20'))
    changed = parse(combat_workspace, 'combat-fixture-v2_001001.ipf')
    assert changed.data['skills_by_name']['Harness_Fire']['sfr'][3] == 260
    wolf = changed.data['monsters_by_name']['harness_wolf']
    assert (wolf['Stat_HP'], wolf['Stat_ATTACK_PHYSICAL_MIN'], wolf['EXP']) == (600, 36, 1200)
    assert changed.data['item_monster'][0]['Chance'] == 25.0
    assert json.loads((Path(changed.BASE_PATH_OUTPUT) / 'version.json').read_text()) == {
        'version': 'combat-fixture-v2_001001.ipf',
    }


def test_rebuild_is_identical_and_restores_preexisting_global_state(combat_workspace, monkeypatch):
    effects = ['Effect_FromAnotherRun']
    overrides = {'harness_wolf': {'MHP': '99999'}}
    monkeypatch.setattr(skills, 'EFFECTS', effects)
    monkeypatch.setattr(monsters, 'monster_const_stat', overrides)
    original_lua = luautil.lua
    first = parse(combat_workspace)
    release = Path(first.BASE_PATH_OUTPUT)
    before = snapshot(release)
    second = parse(combat_workspace)
    assert snapshot(release) == before
    assert second.data['monsters_by_name']['harness_wolf']['Stat_HP'] == 500
    assert 'Effect_FromAnotherRun' not in second.data['skills_by_name']['Harness_Fire']
    assert skills.EFFECTS is effects
    assert monsters.monster_const_stat is overrides
    assert luautil.lua is original_lua


def test_field_override_order_and_removed_rows_do_not_leak_between_runs(combat_workspace):
    first = parse(combat_workspace)
    assert first.data['monsters_by_name']['harness_boar']['Stat_HP'] == 3333
    for path in (combat_workspace / 'itos_unpack/ies.ipf').glob('field_monster_status_*.ies'):
        path.write_text(path.read_text().splitlines()[0] + '\n')
    second = parse(combat_workspace)
    boar = second.data['monsters_by_name']['harness_boar']
    assert (boar['Stat_HP'], boar['EXP'], boar['EXPClass']) == (1000, 2000, 600)


@pytest.mark.parametrize('level,hp,exp,jobexp', [('0', 50, 100, 30), ('999', 49950, 0, 0)])
def test_monster_level_floor_and_experience_guard(combat_workspace, level, hp, exp, jobexp):
    change_column(combat_workspace / 'itos_unpack/ies.ipf/monster.ies', 'Level', level)
    db = parse(combat_workspace)
    wolf = db.data['monsters_by_name']['harness_wolf']
    assert wolf['Level'] == max(1, int(level))
    assert (wolf['Stat_HP'], wolf['EXP'], wolf['EXPClass']) == (hp, exp, jobexp)


@pytest.mark.parametrize('filename,column,value,error', [
    ('ies.ipf/skill.ies', 'BasicSP', 'bad', ValueError),
    ('ies.ipf/skilltree.ies', 'ClassName', 'Missing_Job_Fire', KeyError),
    ('ies.ipf/monster.ies', 'Level', 'bad', ValueError),
    ('ies.ipf/field_monster_status_harness_z.ies', 'MHP', 'bad', ValueError),
    ('ies_drop.ipf/HARNESS_WOLF.IES', 'Money_Max', 'bad', ValueError),
])
def test_bad_sources_preserve_release_and_version_then_retry(combat_workspace, filename, column, value, error):
    db = parse(combat_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    original_lua = luautil.lua
    path = combat_workspace / 'itos_unpack' / filename
    original = change_column(path, column, value)
    with pytest.raises(error):
        parse(combat_workspace, 'combat-fixture-v2_001001.ipf')
    assert snapshot(release) == before
    assert luautil.lua is original_lua
    change_column(path, column, original)
    parse(combat_workspace, 'combat-fixture-v2_001001.ipf')
    assert json.loads((release / 'version.json').read_text())['version'] == 'combat-fixture-v2_001001.ipf'


@pytest.mark.parametrize('filename', ['ies.ipf/skill.ies', 'ies.ipf/monster_const.ies',
                                     'ies_drop.ipf/HARNESS_WOLF.IES'])
def test_required_combat_input_missing_is_failure(combat_workspace, filename):
    db = parse(combat_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    (combat_workspace / 'itos_unpack' / filename).unlink()
    with pytest.raises(FileNotFoundError, match='Missing parser fixture input'):
        parse(combat_workspace, 'combat-fixture-v2_001001.ipf')
    assert snapshot(release) == before


def test_missing_monster_lua_function_preserves_previous_output(combat_workspace):
    db = parse(combat_workspace)
    release = Path(db.BASE_PATH_OUTPUT)
    before = snapshot(release)
    path = combat_workspace / 'itos_unpack/shared.ipf/combat_calculate.lua'
    original = path.read_text()
    path.write_text(original.replace('function SCR_GET_MON_EXP(', 'function RENAMED_EXP('))
    with pytest.raises(KeyError, match='SCR_GET_MON_EXP'):
        parse(combat_workspace, 'combat-fixture-v2_001001.ipf')
    assert snapshot(release) == before
    path.write_text(original)
    parse(combat_workspace, 'combat-fixture-v2_001001.ipf')


def test_missing_drop_item_never_creates_fallback_item(combat_workspace):
    db = parse(combat_workspace)
    assert 'expired_drop' not in db.data['items_by_name']
    assert len(db.data['item_monster']) == 2
    assert len(db.data['unresolved_drops']) == 1
    assert db.data['build_provenance']['item_monster']['input_version'] == 'drop-fixture-v1'


def test_skill_fallback_uses_the_input_project(combat_workspace):
    fallback = combat_workspace / 'TavernofSoul/JSON_ktos'
    fallback.mkdir()
    (fallback / 'skills_by_name.json').write_text(json.dumps({
        'Harness_Fire': {'Icon': 'fixture_fallback_icon', 'Description': 'Do not borrow Korean text'},
    }))
    (fallback / 'assets_icons.json').write_text('{"fixture_fallback_icon": "fixture_fallback_icon"}')
    db = parse(combat_workspace)
    skill = db.data['skills_by_name']['Harness_Fire']
    assert skill['Icon'] == 'fixture_fallback_icon'
    assert skill['Description'] == 'A Lua calculated skill'
