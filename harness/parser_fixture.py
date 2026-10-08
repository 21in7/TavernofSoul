"""Build selected domains from real CSV IES, XML/TSV, and Lua in a temporary project."""
from contextlib import contextmanager
import csv
from pathlib import Path
import shutil
from types import SimpleNamespace

from lupa import LuaRuntime

from DB import ToS_DB
import items
import luautil
import parse_xac
import translation
import jobs
import skills
import monsters
import skill_bytool
import attributes
import buff
import maps
from drop_source import get_drop_source
from harness.fixture_inputs import (COMBAT_FIXTURE, COMBAT_INPUTS, FIXTURE,
                                    REQUIRED_INPUTS, WORLD_FIXTURE, WORLD_INPUTS,
                                    REGIONAL_FIXTURE, REGIONAL_INPUTS, REGIONS,
                                    TRANSLATION_DIRECTORIES, EQUIPMENT_FIXTURE, EQUIPMENT_INPUTS)



def prepare_workspace(root, region='itos'):
    if region not in REGIONS:
        raise ValueError('Unsupported fixture region: ' + region)
    root = Path(root)
    shutil.copytree(FIXTURE / 'unpack', root / (region + '_unpack'))
    if region in TRANSLATION_DIRECTORIES:
        shutil.copytree(FIXTURE / 'translation', root / 'Translation' / TRANSLATION_DIRECTORIES[region])
    (root / 'parser_tidy').mkdir()
    (root / 'TavernofSoul' / ('JSON_' + region)).mkdir(parents=True)
    (root / 'TavernofSoul' / 'staticfiles_itos').mkdir()
    return root


def prepare_combat_workspace(root, region='itos'):
    root = prepare_workspace(root, region)
    shutil.copytree(COMBAT_FIXTURE / 'unpack', root / (region + '_unpack'), dirs_exist_ok=True)
    (root / 'downloader').mkdir()
    shutil.copy2(COMBAT_FIXTURE / 'revision.csv', root / 'downloader/revision.csv')
    return root


def prepare_world_workspace(root, region='itos'):
    root = prepare_combat_workspace(root, region)
    shutil.copytree(WORLD_FIXTURE / 'unpack', root / (region + '_unpack'), dirs_exist_ok=True)
    if region in TRANSLATION_DIRECTORIES:
        shutil.copy2(WORLD_FIXTURE / 'translation/world.tsv',
                     root / 'Translation' / TRANSLATION_DIRECTORIES[region] / 'world.tsv')
    return root


def prepare_regional_workspace(root, region):
    root = prepare_world_workspace(root, region)
    unpack = root / (region + '_unpack')
    shutil.copytree(REGIONAL_FIXTURE / 'common/unpack', unpack, dirs_exist_ok=True)
    shutil.copytree(REGIONAL_FIXTURE / region / 'unpack', unpack, dirs_exist_ok=True)
    if region in TRANSLATION_DIRECTORIES:
        directory = root / 'Translation' / TRANSLATION_DIRECTORIES[region]
        for name in ('items.tsv', 'world.tsv'):
            (directory / name).unlink()
        shutil.copy2(REGIONAL_FIXTURE / region / 'translation/regional.tsv',
                     directory / 'regional.tsv')
    # Model the current cross-region policy: non-iTOS builds use the iTOS dataset.
    if region != 'itos':
        (root / 'itos_unpack').mkdir()
        shutil.move(str(unpack / 'ies_drop.ipf'), str(root / 'itos_unpack/ies_drop.ipf'))
    (root / 'downloader/revision.csv').write_text(
        ''.join(name + ',regional-source-' + name + '-v1\n' for name in REGIONS), encoding='utf-8')
    for fallback in ('ktos', 'ktest'):
        shutil.copytree(REGIONAL_FIXTURE / 'fallback' / fallback,
                        root / 'TavernofSoul' / ('JSON_' + fallback), dirs_exist_ok=True)
    return root


def change_ies_column(path, column, value, index=0):
    """Edit one source cell for mutation/failure cases; return its original value."""
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    previous = rows[index][column]
    rows[index][column] = value
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return previous


def prepare_equipment_workspace(root, region='itos'):
    root = prepare_regional_workspace(root, region)
    shutil.copytree(EQUIPMENT_FIXTURE / 'unpack', root / (region + '_unpack'), dirs_exist_ok=True)
    return root


@contextmanager
def isolated_parser_state():
    # Fresh real runtimes prevent repeated tests from sharing Lua functions/tables.
    lua_state = (luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE)
    item_state = (items.EQUIPMENT_STAT_COLUMNS, items.equipment_grade_ratios, items.goddess_atk_list)
    effects = skills.EFFECTS
    monster_names = ('statbase_monster', 'statbase_monster_type', 'statbase_monster_race',
                     'monster_const', 'monster_const_stat')
    monster_state = {name: getattr(monsters, name) for name in monster_names}
    luautil.lua = LuaRuntime(attribute_handlers=(luautil.attr_getter, luautil.attr_setter),
                            unpack_returned_tuples=True)
    luautil.LUA_RUNTIME, luautil.LUA_SOURCE = {}, {}
    items.EQUIPMENT_STAT_COLUMNS, items.equipment_grade_ratios, items.goddess_atk_list = [], {}, {}
    skills.EFFECTS = []
    for name in monster_names:
        setattr(monsters, name, {})
    try:
        yield
    finally:
        luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE = lua_state
        items.EQUIPMENT_STAT_COLUMNS, items.equipment_grade_ratios, items.goddess_atk_list = item_state
        skills.EFFECTS = effects
        for name, value in monster_state.items():
            setattr(monsters, name, value)


def parse_workspace(root, version='parser-fixture-v1_001001.ipf', include_combat=False,
                    include_world=False, region='itos', include_regional=False, include_equipment=False):
    if region not in REGIONS:
        raise ValueError('Unsupported fixture region: ' + region)
    root = Path(root)
    unpack = root / (region + '_unpack')
    include_regional = include_regional or include_equipment
    include_world = include_world or include_regional
    include_combat = include_combat or include_world
    inputs = REQUIRED_INPUTS + (COMBAT_INPUTS if include_combat else ()) + \
             (WORLD_INPUTS if include_world else ()) + (REGIONAL_INPUTS if include_regional else ()) + \
             (EQUIPMENT_INPUTS if include_equipment else ())
    source = get_drop_source(SimpleNamespace(region=region, PATH_INPUT_DATA=str(unpack)))
    drop_directory = Path(source['drop_ipf']) if source['drop_ipf'] else unpack / 'ies_drop.ipf'
    required = [drop_directory / name[len('ies_drop.ipf/'):] if name.startswith('ies_drop.ipf/')
                else unpack / name for name in inputs
                if name != 'language.ipf/wholeDicID.xml' or region in TRANSLATION_DIRECTORIES]
    if region in TRANSLATION_DIRECTORIES:
        directory = root / 'Translation' / TRANSLATION_DIRECTORIES[region]
        if include_regional:
            required.append(directory / 'regional.tsv')
        else:
            required.append(directory / 'items.tsv')
            if include_world:
                required.append(directory / 'world.tsv')
    if include_combat:
        required.append(root / 'downloader/revision.csv')
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError('Missing parser fixture input: ' + ', '.join(missing))
    db = ToS_DB()
    # Class-level containers may carry data from other parser runs.
    db.data = {name: [] if isinstance(value, list) else {} for name, value in ToS_DB.data.items()}
    db.file_dict = {}
    db.build(region, str(root / 'parser_tidy'))
    with isolated_parser_state():
        parse_xac.parse_xac(db)
        if region in TRANSLATION_DIRECTORIES:
            translation.makeDictionary(db)
        if include_combat:
            luautil.init(db)
            jobs.parse(db)
            skill_bytool.parse(db)
            skills.parse(db)
            if include_world:
                attributes.parse(db)
                attributes.parse_links(db)
                attributes.parse_clean(db)
            skills.parse_clean(db)
        if include_world:
            buff.parse(db)
        items.parse(db)
        if include_combat:
            monsters.parse(db)
            monsters.parse_links(db)
            monsters.parse_skill_mon(db)
        if include_world:
            maps.parse(db)
            maps.parse_links(db)
    # Publish only after the selected domain has finished parsing.
    db.export(version_payload={'version': version})
    return db
