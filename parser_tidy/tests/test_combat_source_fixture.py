"""Real skill/monster/drop inputs, calculations, references, and release failures."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import luautil
import monsters
import skills
from ipfparser.contracts import ContractError
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


@pytest.mark.parametrize('value_type,class_type,attack_type,expected', [
    pytest.param('Buff', 'MAGIC', 'SLASH', ['Buff', 'Magic', 'Slash'], id='three-candidates'),
    pytest.param('', 'MAGIC', 'SLASH', ['Magic', 'Slash'], id='without-buff'),
    pytest.param('', 'SLASH', 'MAGIC', ['Slash', 'Magic'], id='source-order-not-sorted'),
    pytest.param('Buff', 'MAGIC', 'MAGIC', ['Buff', 'Magic'], id='duplicate-with-buff'),
    pytest.param('', 'MAGIC', 'MAGIC', ['Magic'], id='duplicate-without-buff'),
    pytest.param('Buff', 'HOLY', 'SLASH', ['Buff', 'Slash'], id='class-none'),
    pytest.param('Buff', 'MAGIC', 'HOLY', ['Buff', 'Magic'], id='attack-none'),
    pytest.param('Buff', '', 'SLASH', ['Buff', 'Slash'], id='class-unknown'),
    pytest.param('Buff', 'MAGIC', '', ['Buff', 'Magic'], id='attack-unknown'),
    pytest.param('', '', '', [], id='only-unknown'),
    pytest.param('', 'HOLY', '', [], id='none-and-unknown'),
])
def test_skill_attack_types_preserve_supported_source_order(
        combat_workspace, value_type, class_type, attack_type, expected):
    source = combat_workspace / 'itos_unpack/ies.ipf/skill.ies'
    for column, value in (('ValueType', value_type), ('ClassType', class_type),
                          ('AttackType', attack_type)):
        change_column(source, column, value, index=0)
    db = parse(combat_workspace)
    skill = db.data['skills_by_name']['Harness_Fire']
    assert skill['TypeAttack'] == expected
    assert db.data['skills'][skill['$ID']]['TypeAttack'] == expected
    release = Path(db.BASE_PATH_OUTPUT)
    by_id = json.loads((release / 'skills.json').read_text())
    by_name = json.loads((release / 'skills_by_name.json').read_text())
    assert by_id[str(skill['$ID'])]['TypeAttack'] == expected
    assert by_name['Harness_Fire']['TypeAttack'] == expected


def test_skill_json_bytes_are_independent_of_hash_seed(combat_workspace):
    source = combat_workspace / 'itos_unpack/ies.ipf/skill.ies'
    for column, value in (('ValueType', 'Buff'), ('ClassType', 'MAGIC'),
                          ('AttackType', 'SLASH')):
        change_column(source, column, value, index=0)
    script = """
import runpy
import sys
from pathlib import Path

tests = runpy.run_path(sys.argv[1])
tests['parse'](Path(sys.argv[2]))
"""
    exports = {}
    for seed in (0, 1, 7):
        env = os.environ.copy()
        env['PYTHONHASHSEED'] = str(seed)
        env['PYTHONPATH'] = os.pathsep.join(str(path) for path in sys.path)
        subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()),
                        str(combat_workspace)],
                       cwd=str(Path(__file__).resolve().parents[2]), env=env,
                       check=True, capture_output=True, text=True, timeout=60)
        release = combat_workspace / 'TavernofSoul/JSON_itos'
        exports[seed] = {name: (release / (name + '.json')).read_bytes()
                         for name in ('skills', 'skills_by_name')}
    for name in ('skills', 'skills_by_name'):
        assert exports[0][name] == exports[1][name] == exports[7][name], name


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


def test_multiple_source_drops_preserve_last_row_semantics(combat_workspace):
    source = combat_workspace / 'itos_unpack/ies_drop.ipf/HARNESS_WOLF.IES'
    source.write_text(source.read_text() + 'harness_ore,2500,2,4\n')
    db = parse(combat_workspace)
    wolf_drops = [row for row in db.data['item_monster'] if str(row['Monster']) == '500']
    assert len(wolf_drops) == 1
    assert (wolf_drops[0]['Chance'], wolf_drops[0]['Quantity_MIN'],
            wolf_drops[0]['Quantity_MAX']) == (25.0, 2, 4)


def test_recipe_drop_uses_canonical_identity_despite_numeric_collision(combat_workspace):
    source = combat_workspace / 'itos_unpack/ies_drop.ipf/HARNESS_WOLF.IES'
    source.write_text(source.read_text().replace('harness_ore', 'harness_recipe'))
    db = parse(combat_workspace)
    assert db.data['items_by_name']['harness_ore']['$ID'] == db.data['items_by_name']['harness_recipe']['$ID']
    assert db.data['item_monster'][0]['Item'] == 'recipe-100'


def test_invalid_earlier_variant_is_not_hidden_by_last_valid_drop(combat_workspace):
    db = parse(combat_workspace)
    before = snapshot(Path(db.BASE_PATH_OUTPUT))
    source = combat_workspace / 'itos_unpack/ies_drop.ipf/HARNESS_WOLF.IES'
    change_column(source, 'DropRatio', '-1')
    source.write_text(source.read_text() + 'harness_ore,2500,2,4\n')
    with pytest.raises(ContractError, match='Chance'):
        parse(combat_workspace, 'combat-fixture-v2')
    assert snapshot(Path(db.BASE_PATH_OUTPUT)) == before


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
    ('ies.ipf/skill.ies', 'ClassType', 'UNSUPPORTED_ATTACK_TYPE', KeyError),
    ('ies.ipf/skill.ies', 'AttackType', 'UNSUPPORTED_ATTACK_TYPE', KeyError),
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


class _SkillCleanupLinks(list):
    def __init__(self, values):
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


class _SkillCleanupObject(dict):
    def __init__(self, name, links):
        super().__init__({'$ID_NAME': name, 'Link_Skills': _SkillCleanupLinks(links)})
        self.link_reads = 0
        self.link_writes = 0

    def __getitem__(self, key):
        if key == 'Link_Skills':
            self.link_reads += 1
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key == 'Link_Skills':
            self.link_writes += 1
        super().__setitem__(key, value)


class _SkillCleanupIndex(dict):
    def __init__(self, label, entries, deletions):
        super().__init__(entries)
        self.label = label
        self.deletions = deletions

    def __delitem__(self, key):
        self.deletions.append((self.label, key))
        super().__delitem__(key)


def _skill_cleanup_db(region, entries):
    return SimpleNamespace(region=region, data={
        'skills': {str(skill['$ID']): skill for skill in entries},
        'skills_by_name': {skill['$ID_NAME']: skill for skill in entries},
        'attributes': {}, 'attributes_by_name': {},
        'jobs': {}, 'jobs_by_name': {},
    })


@pytest.mark.parametrize('shared_by_name', [True, False], ids=['shared', 'separate'])
def test_skill_cleanup_preserves_typed_links_order_aliases_and_external_lists(shared_by_name):
    inactive_string = {'$ID': '10', '$ID_NAME': 'GoneString', 'Link_Job': None}
    active = {'$ID': '40', '$ID_NAME': 'Active', 'Link_Job': 0}
    inactive_integer = {'$ID': 20, '$ID_NAME': 202, 'Link_Job': None}
    inactive_other = {'$ID': 30, '$ID_NAME': 'GoneOther', 'Link_Job': None}
    entries = [inactive_string, active, inactive_integer, inactive_other]
    db = _skill_cleanup_db('itos', entries)
    deletions = []
    for collection in ('skills', 'skills_by_name'):
        db.data[collection] = _SkillCleanupIndex(collection, db.data[collection], deletions)

    attribute = _SkillCleanupObject(101, ['10', 10, 20, '20', 'keep', 30, '30', 'keep', 10])
    job = _SkillCleanupObject('Job', [30, '30', '40', 20, '20', '10', '40', 10])
    named_attribute = attribute if shared_by_name else _SkillCleanupObject(
        101, [20, '20', 'name-only', '10', 'name-only', 30, 10])
    named_job = job if shared_by_name else _SkillCleanupObject(
        'Job', ['10', 'name-job', 30, '30', 'name-job', 20, '20'])
    db.data['attributes'] = {'1': attribute, 'attribute-alias': attribute}
    db.data['attributes_by_name'] = {101: named_attribute, 'alias': named_attribute}
    db.data['jobs'] = {'2': job, 'job-alias': job}
    db.data['jobs_by_name'] = {'Job': named_job, 'alias': named_job}
    cases = [
        (attribute, ['10', 10, 20, '20', 'keep', 30, '30', 'keep', 10],
         [10, '20', 'keep', '30', 'keep', 10]),
        (job, [30, '30', '40', 20, '20', '10', '40', 10],
         ['30', '40', '20', '40', 10]),
    ]
    if not shared_by_name:
        cases.extend([
            (named_attribute, [20, '20', 'name-only', '10', 'name-only', 30, 10],
             ['20', 'name-only', 'name-only', 10]),
            (named_job, ['10', 'name-job', 30, '30', 'name-job', 20, '20'],
             ['name-job', '30', 'name-job', '20']),
        ])
    old_lists = [dict.__getitem__(obj, 'Link_Skills') for obj, _, _ in cases]

    skills.parse_clean(db)

    assert deletions == [
        ('skills', '10'), ('skills_by_name', 'GoneString'),
        ('skills', '20'), ('skills_by_name', 202),
        ('skills', '30'), ('skills_by_name', 'GoneOther'),
    ]
    assert db.data['skills'] == {'40': active}
    assert db.data['skills_by_name'] == {'Active': active}
    for (obj, original, expected), old_links in zip(cases, old_lists):
        new_links = dict.__getitem__(obj, 'Link_Skills')
        assert new_links == expected
        assert new_links is not old_links
        assert old_links == original
        assert old_links.iterations == 1
        assert (obj.link_reads, obj.link_writes) == (1, 1)


def test_skill_cleanup_filters_objects_aliased_across_collections_once():
    db = _skill_cleanup_db('ktos', [{'$ID': '10', '$ID_NAME': 'Gone', 'Link_Job': None}])
    first = _SkillCleanupObject('First', ['10', 'keep', 'keep'])
    second = _SkillCleanupObject('Second', ['other', '10', 'other'])
    db.data['attributes'] = {'1': first, '2': second}
    db.data['attributes_by_name'] = {'First': second, 'Second': first}
    db.data['jobs'] = {'1': second, '2': first}
    db.data['jobs_by_name'] = {'First': first, 'Second': second}
    old_first = dict.__getitem__(first, 'Link_Skills')
    old_second = dict.__getitem__(second, 'Link_Skills')

    skills.parse_clean(db)

    assert dict.__getitem__(first, 'Link_Skills') == ['keep', 'keep']
    assert dict.__getitem__(second, 'Link_Skills') == ['other', 'other']
    assert (first.link_reads, first.link_writes) == (1, 1)
    assert (second.link_reads, second.link_writes) == (1, 1)
    assert old_first.iterations == old_second.iterations == 1
    assert old_first == ['10', 'keep', 'keep']
    assert old_second == ['other', '10', 'other']


@pytest.mark.parametrize('entries', [[], [
    {'$ID': '10', '$ID_NAME': 'Active', 'Link_Job': 0},
    {'$ID': '20', '$ID_NAME': 'OtherActive', 'Link_Job': ''},
]], ids=['empty', 'all-active'])
def test_skill_cleanup_without_inactive_skills_does_not_access_links(entries):
    db = _skill_cleanup_db('itos', entries)
    attribute = _SkillCleanupObject('Attribute', ['10', '10'])
    job = _SkillCleanupObject('Job', ['20'])
    db.data['attributes'] = {'1': attribute}
    db.data['jobs'] = {'2': job}
    # Absent name indexes must remain unobserved when no skill needs removal.
    del db.data['attributes_by_name']
    del db.data['jobs_by_name']
    old_attribute = dict.__getitem__(attribute, 'Link_Skills')
    old_job = dict.__getitem__(job, 'Link_Skills')

    skills.parse_clean(db)

    assert list(db.data['skills']) == [str(skill['$ID']) for skill in entries]
    assert dict.__getitem__(attribute, 'Link_Skills') is old_attribute
    assert dict.__getitem__(job, 'Link_Skills') is old_job
    assert (attribute.link_reads, attribute.link_writes) == (0, 0)
    assert (job.link_reads, job.link_writes) == (0, 0)
    assert old_attribute.iterations == old_job.iterations == 0


def test_skill_cleanup_recomputes_after_repeat_region_change_and_external_mutation():
    first = _skill_cleanup_db('ktos', [
        {'$ID': '10', '$ID_NAME': 'Gone', 'Link_Job': None},
        {'$ID': '20', '$ID_NAME': 'Active', 'Link_Job': 'Job'},
    ])
    attribute = _SkillCleanupObject('Attribute', ['10', 10, '20', '20'])
    first.data['attributes'] = {'1': attribute}
    first.data['attributes_by_name'] = {'Attribute': attribute}
    skills.parse_clean(first)
    assert dict.__getitem__(attribute, 'Link_Skills') == [10, '20', '20']
    first_links = dict.__getitem__(attribute, 'Link_Skills')

    skills.parse_clean(first)
    assert dict.__getitem__(attribute, 'Link_Skills') is first_links
    assert (attribute.link_reads, attribute.link_writes) == (1, 1)

    second = _skill_cleanup_db('jtos', [
        {'$ID': 10, '$ID_NAME': 'GoneInteger', 'Link_Job': None},
        {'$ID': '20', '$ID_NAME': 'StillActive', 'Link_Job': 'Job'},
    ])
    other_attribute = _SkillCleanupObject('OtherAttribute', ['10', 10, '20', '20'])
    second.data['attributes'] = {'2': other_attribute}
    second.data['attributes_by_name'] = {'OtherAttribute': other_attribute}
    skills.parse_clean(second)
    assert dict.__getitem__(other_attribute, 'Link_Skills') == ['10', '20', '20']
    assert dict.__getitem__(attribute, 'Link_Skills') is first_links

    # Reuse the first instance for another region after external source edits.
    first.region = 'itos'
    first.data['skills']['20']['Link_Job'] = None
    restored = {'$ID': '10', '$ID_NAME': 'Restored', 'Link_Job': 'Job'}
    first.data['skills']['10'] = restored
    first.data['skills_by_name']['Restored'] = restored
    first_links.extend(['10', '20', 20, 'tail', '10'])
    skills.parse_clean(first)
    assert dict.__getitem__(attribute, 'Link_Skills') == [10, '10', 20, 'tail', '10']
    assert first_links == [10, '20', '20', '10', '20', 20, 'tail', '10']
    assert first.data['skills'] == {'10': restored}
    assert first.data['skills_by_name'] == {'Restored': restored}
    assert (attribute.link_reads, attribute.link_writes) == (2, 2)

    final_links = dict.__getitem__(attribute, 'Link_Skills')
    skills.parse_clean(first)
    assert dict.__getitem__(attribute, 'Link_Skills') is final_links
    assert (attribute.link_reads, attribute.link_writes) == (2, 2)
