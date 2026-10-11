"""Shared, dependency-free contracts for parser releases and Django imports.

Unknown fields remain extensible. Validate importer inputs without rewriting them.
"""
import json
import math
from pathlib import Path
import re

RECIPE_ID_PREFIX = 'recipe-'
RELATIONS = ('item_monster', 'map_item', 'map_npc', 'map_item_spawn')
ENTITIES = ('items_by_name', 'jobs', 'skills', 'monsters', 'npcs', 'maps',
            'attributes', 'skill_mon', 'buff', 'achievements')
REQUIRED_COLLECTIONS = ENTITIES + RELATIONS + ('item_type',)


class ContractError(ValueError):
    def __init__(self, path, code, message):
        self.path, self.code, self.message = path, code, message
        super().__init__('{} [{}]: {}'.format(path, code, message))


def fail(path, code, message):
    raise ContractError(path, code, message)


def array(value, path):
    # Parser-internal tuples serialize to JSON arrays.
    if not isinstance(value, (list, tuple)):
        fail(path, 'type', 'expected an array')
    return value


def text(value, path, limit=None, nullable=False, nonempty=False):
    if value is None and nullable:
        return
    if not isinstance(value, str):
        fail(path, 'type', 'expected a string' + (' or null' if nullable else ''))
    if nonempty and not value.strip():
        fail(path, 'empty', 'expected a nonempty string')
    if limit is not None and len(value) > limit:
        fail(path, 'length', 'maximum length is {}'.format(limit))


def identifier(value, path, limit=30):
    if type(value) not in (int, str) or not str(value).strip():
        fail(path, 'id', 'expected a nonempty string or integer ID')
    if len(str(value)) > limit:
        fail(path, 'length', 'maximum ID length is {}'.format(limit))
    return str(value)


def number(value, path, minimum=None, maximum=None, integer=False, raw=False):
    if raw and isinstance(value, str) and re.fullmatch(r'-?\d+', value):
        value = int(value)
    elif raw and not integer and isinstance(value, str) and re.fullmatch(r'-?\d+\.\d+', value):
        value = float(value)
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        fail(path, 'number', 'expected a finite number; booleans are not numbers')
    if integer and value != int(value):
        fail(path, 'integer', 'expected an integer value')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        fail(path, 'range', 'expected a value in {}..{}'.format(minimum, maximum))
    return value


def boolean(value, path, raw=False):
    if type(value) is not bool and not (raw and type(value) is int and value in (0, 1)):
        fail(path, 'type', 'expected a boolean' + (' or 0/1' if raw else ''))


def fields(row, path, strings=(), numbers=(), integers=(), booleans=(), nullable=(), raw=False):
    for name in strings + numbers + integers + booleans:
        target = path + '.' + name
        if name not in row:
            fail(target, 'required', 'missing required field')
        value = row[name]
        if value is None and name in nullable:
            continue
        if name in strings:
            text(value, target, nullable=name in nullable)
        elif name in numbers + integers:
            number(value, target, integer=name in integers, raw=raw)
        else:
            boolean(value, target)


def reference(value, path, available):
    # Targets already have their entity ID limits checked. ClassName references
    # use the name column's 100-character limit, rather than the numeric ID limit.
    key = identifier(value, path, limit=100)
    if key not in available:
        fail(path, 'reference', 'target {} not found in release'.format(key))


def canonical_item_id(entry, recipe_names):
    value = str(entry.get('$ID', ''))
    return RECIPE_ID_PREFIX + value if entry.get('$ID_NAME') in recipe_names and not value.startswith(RECIPE_ID_PREFIX) else value


def inactive_recipe(row):
    """Unnamed source placeholders have no crafting definition (BlessedStone)."""
    return row.get('Name') is None and row.get('Link_Target') is None and 'Link_Materials' not in row


def finite_tree(value, path):
    suffix = _nonfinite_suffix(value)
    if suffix is not None:
        fail('{}{}'.format(path, suffix) if suffix else path,
             'number', 'NaN and Infinity are not JSON numbers')


def _nonfinite_suffix(value):
    # Build diagnostic strings only while unwinding the first invalid branch.
    if isinstance(value, float) and not math.isfinite(value):
        return ''
    if isinstance(value, dict):
        for key, child in value.items():
            suffix = _nonfinite_suffix(child)
            if suffix is not None:
                return '[{!r}]{}'.format(key, suffix)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            suffix = _nonfinite_suffix(child)
            if suffix is not None:
                return '[{}]{}'.format(index, suffix)
    return None


def rows(collection, value):
    if not isinstance(value, (dict, list)):
        fail(collection, 'type', 'expected an object or array of rows')
    for key, row in (value.items() if isinstance(value, dict) else enumerate(value)):
        path = '{}[{!r}]'.format(collection, key)
        if not isinstance(row, dict):
            fail(path, 'type', 'expected a row object')
        yield path, row


def unique(seen, key, path):
    if key in seen:
        fail(path, 'duplicate', 'duplicate identity {}; first at {}'.format(key, seen[key]))
    seen[key] = path


def numeric_array(value, path, minimum=0):
    for index, child in enumerate(array(value, path)):
        number(child, '{}[{}]'.format(path, index), minimum=minimum)


def bonuses(value, path):
    for index, pair in enumerate(array(value, path)):
        target = '{}[{}]'.format(path, index)
        pair = array(pair, target)
        if len(pair) != 2:
            fail(target, 'shape', 'expected a stat/value pair')
        text(pair[0], target + '[0]', nonempty=True)
        if type(pair[1]) not in (str, int, float):
            fail(target + '[1]', 'type', 'expected a string or number bonus')


def package(contents, path, items):
    if not isinstance(contents, dict):
        fail(path, 'type', 'expected a package object')
    fields(contents, path, booleans=('random',))
    if 'items' not in contents:
        fail(path + '.items', 'required', 'missing required field')
    groups = [('items', contents['items'], True), ('unresolved', contents.get('unresolved', []), False)]
    for index, group in enumerate(array(contents.get('alternatives', []), path + '.alternatives')):
        groups.append(('alternatives[{}]'.format(index), group, True))
    for name, group, resolved in groups:
        for index, entry in enumerate(array(group, path + '.' + name)):
            target = '{}.{}[{}]'.format(path, name, index)
            if not isinstance(entry, dict):
                fail(target, 'type', 'expected a package item object')
            fields(entry, target, strings=('item',), integers=('count',))
            text(entry['item'], target + '.item', nonempty=True)
            number(entry['count'], target + '.count', minimum=1, integer=True)
            if resolved:
                reference(entry['item'], target + '.item', items)
                if 'name' not in entry:
                    fail(target + '.name', 'required', 'missing resolved item name')
                text(entry['name'], target + '.name', nullable=True)
            for option in array(entry.get('options', []), target + '.options'):
                option = array(option, target + '.options')
                if len(option) != 2 or not all(isinstance(part, str) for part in option):
                    fail(target + '.options', 'shape', 'expected string property/value pairs')


def validate_release(data, require_version=True):
    """Validate complete importer inputs in memory; raise the first located error."""
    if not isinstance(data, dict):
        fail('release', 'type', 'expected an object of collections')
    for name in REQUIRED_COLLECTIONS:
        if name not in data:
            fail(name, 'required', 'missing release collection')
    if require_version or 'version' in data:
        version = data.get('version')
        if not isinstance(version, dict) or 'version' not in version:
            fail('version.version', 'required', 'missing release version')
        text(version['version'], 'version.version', limit=50, nonempty=True)
    finite_tree(data, 'release')

    item_type = data['item_type']
    if not isinstance(item_type, dict):
        fail('item_type', 'type', 'expected an object of item groups')
    for name in ('EQUIPMENT', 'CARD', 'RECIPES', 'COLLECTION'):
        if name not in item_type:
            fail('item_type.' + name, 'required', 'missing importer item group')
    for name, names in item_type.items():
        for entry in array(names, 'item_type.' + name):
            text(entry, 'item_type.' + name, nonempty=True)
    recipes = set(item_type['RECIPES'])
    indexed, entity_rows = {}, {}
    for collection in ENTITIES:
        if collection in ('items_by_name', 'skills') and not isinstance(data[collection], dict):
            fail(collection, 'type', 'expected an object index')
        ids, names = {}, {}
        entity_rows[collection] = list(rows(collection, data[collection]))
        for path, row in entity_rows[collection]:
            for field in ('$ID', '$ID_NAME', 'Name'):
                if field not in row:
                    fail(path + '.' + field, 'required', 'missing required field')
            key = identifier(row['$ID'], path + '.$ID', limit=20 if collection == 'maps' else 30)
            text(row['$ID_NAME'], path + '.$ID_NAME', limit=100, nonempty=True)
            text(row['Name'], path + '.Name', nullable=collection == 'items_by_name')
            if collection == 'items_by_name':
                if isinstance(row.get('Type'), str) and row['Type'].upper() in ('RECIPE', 'RECIPES') \
                        and row['$ID_NAME'] not in recipes and not (
                            row['$ID_NAME'] == 'Default_Recipe' and key == '910000'):
                    fail(path + '.$ID_NAME', 'classification', 'recipe absent from item_type.RECIPES')
                key = canonical_item_id(row, recipes)
                identifier(key, path + '.$ID')
            unique(ids, key, path + '.$ID')
            unique(names, row['$ID_NAME'], path + '.$ID_NAME')
        indexed[collection] = (ids, names)
    items, item_names = indexed['items_by_name']
    if isinstance(data['items_by_name'], dict):
        for key, row in data['items_by_name'].items():
            if key != row['$ID_NAME']:
                fail('items_by_name[{!r}].$ID_NAME'.format(key), 'index',
                     'item name does not match the name index')
    for path, row in entity_rows['items_by_name']:
        fields(row, path, strings=('Description', 'Tradability', 'Type', 'Icon'),
               numbers=('TimeCoolDown',), integers=('Grade',), nullable=('Description', 'Icon', 'TimeCoolDown'))
        text(row['Name'], path + '.Name', limit=200, nullable=True)
        text(row['Icon'], path + '.Icon', limit=100, nullable=True)
        text(row['Type'], path + '.Type', limit=15)
        if 'Weight' not in row:
            fail(path + '.Weight', 'required', 'missing required field')
        if row['Weight'] != '':
            number(row['Weight'], path + '.Weight', minimum=0)
        if row['TimeCoolDown'] is not None:
            number(row['TimeCoolDown'], path + '.TimeCoolDown', minimum=0)
        number(row['Grade'], path + '.Grade', minimum=0, maximum=6, integer=True)
        if not re.fullmatch('[TF]{4}', row['Tradability']):
            fail(path + '.Tradability', 'flags', 'expected four T/F flags')
        if row.get('PackageContents') is not None:
            package(row['PackageContents'], path + '.PackageContents', item_names)

    for group, names in item_type.items():
        seen = {}
        for name in names:
            reference(name, 'item_type.' + group, item_names)
            unique(seen, name, 'item_type.' + group)
    # Groups with separate ORM rows are mutually exclusive in importItem.
    grouped = {}
    for group in ('EQUIPMENT', 'CARD', 'RECIPES', 'COLLECTION', 'BOOKS', 'GEMS'):
        for name in item_type.get(group, []):
            unique(grouped, name, 'item_type.' + group)
    by_name = {row['$ID_NAME']: (path, row) for path, row in entity_rows['items_by_name']}
    for name in recipes:
        path, row = by_name[name]
        if inactive_recipe(row):
            continue
        if 'Link_Materials' not in row:
            fail(path + '.Link_Materials', 'required', 'missing recipe materials')
        for index, material in enumerate(array(row['Link_Materials'], path + '.Link_Materials')):
            target = '{}.Link_Materials[{}]'.format(path, index)
            if not isinstance(material, dict):
                fail(target, 'type', 'expected a material object')
            fields(material, target, strings=('Item',), integers=('Quantity',))
            reference(material['Item'], target + '.Item', item_names)
            number(material['Quantity'], target + '.Quantity', minimum=1, integer=True)
        if row.get('Link_Target') is not None:
            reference(row['Link_Target'], path + '.Link_Target', item_names)

    for name in item_type['EQUIPMENT']:
        path, row = by_name[name]
        fields(row, path, strings=('RequiredClass', 'TypeAttack', 'TypeEquipment'),
               numbers=('Durability',), integers=('Level', 'Potential', 'SocketsLimit', 'Stars',
               'Stat_ATTACK_MAGICAL', 'Stat_ATTACK_PHYSICAL_MIN', 'Stat_ATTACK_PHYSICAL_MAX',
               'Stat_DEFENSE_MAGICAL', 'Stat_DEFENSE_PHYSICAL'),
               booleans=('Unidentified', 'UnidentifiedRandom'))
        for field in ('AnvilATK', 'AnvilDEF', 'AnvilPrice', 'TranscendPrice'):
            if field not in row:
                fail(path + '.' + field, 'required', 'missing equipment calculation')
            if row[field] is None and field in ('AnvilATK', 'AnvilDEF') and row.get('AnvilPrice') == [] \
                    and 'GoddessReinforceLevel' not in row:
                continue
            numeric_array(row[field], path + '.' + field)
        if 'GoddessReinforceLevel' in row or 'GoddessReinforceGroup' in row:
            fields(row, path, strings=('GoddessReinforceGroup',), integers=('GoddessReinforceLevel',))
            number(row['GoddessReinforceLevel'], path + '.GoddessReinforceLevel', minimum=1, maximum=2147483647)
            if row['GoddessReinforceGroup'] not in ('acc', 'armor', 'weapon') or row['Grade'] != 6:
                fail(path + '.GoddessReinforceGroup', 'value', 'expected a goddess material group')
        if 'Bonus' not in row:
            fail(path + '.Bonus', 'required', 'missing equipment bonuses')
        bonuses(row['Bonus'], path + '.Bonus')
        if not re.fullmatch('[TF]{5}', row['RequiredClass']):
            fail(path + '.RequiredClass', 'flags', 'expected five T/F class flags')
        # Preserve the existing Arcane vision output's absent-maximum sentinel.
        if not (row['TypeEquipment'] == 'Arcane' and row['Stat_ATTACK_PHYSICAL_MAX'] == 0):
            ordered(row, path, 'Stat_ATTACK_PHYSICAL_MIN', 'Stat_ATTACK_PHYSICAL_MAX')
        if row['Durability'] < 0 and row['Durability'] != -1:
            fail(path + '.Durability', 'range', 'expected nonnegative durability or -1 sentinel')
    for name in item_type['CARD']:
        path, row = by_name[name]
        fields(row, path, strings=('IconTooltip', 'TypeCard'), nullable=('IconTooltip',))
    for name in item_type['COLLECTION']:
        path, row = by_name[name]
        if 'Link_Items' not in row or 'Bonus' not in row:
            fail(path, 'required', 'missing collection items or bonuses')
        for item in array(row['Link_Items'], path + '.Link_Items'):
            reference(item, path + '.Link_Items', item_names)
        bonuses(row['Bonus'], path + '.Bonus')
    for name in item_type.get('BOOKS', []):
        path, row = by_name[name]
        if 'Text' in row:
            text(row['Text'], path + '.Text', nullable=True)

    for name in item_type.get('GEMS', []):
        path, row = by_name[name]
        if row.get('Link_Skill') is not None:
            skill_id = identifier(row['Link_Skill'], path + '.Link_Skill')
            reference(skill_id, path + '.Link_Skill', indexed['skills'][0])
        for slot in GEM_SLOTS:
            for index, bonus in enumerate(array(row.get('Bonus' + slot, []), path + '.Bonus' + slot)):
                target = '{}.Bonus{}[{}]'.format(path, slot, index)
                if not isinstance(bonus, dict):
                    fail(target, 'type', 'expected a socket bonus object')
                fields(bonus, target, strings=('Stat',))
                text(bonus['Stat'], target + '.Stat', nonempty=True)
                if 'Level' in bonus:
                    number(bonus['Level'], target + '.Level', minimum=1, maximum=2147483647, integer=True)
                if 'Value' in bonus and type(bonus['Value']) not in (str, int, float):
                    fail(target + '.Value', 'type', 'expected a string or number')

    validate_reinforcement(data, by_name, item_type['EQUIPMENT'])

    validate_other_entities(entity_rows, indexed)
    validate_relations(data, indexed)
    validate_unresolved_map_links(data, entity_rows)


GEM_SLOTS = ('Weapon', 'SubWeapon', 'TopAndBottom', 'Gloves', 'Boots')
REINFORCEMENT_COLLECTIONS = ('goddess_reinf', 'goddess_reinf_mat')
DIAGNOSTIC_COLLECTIONS = ('unresolved_map_links',)


def positive_key(value, path, maximum=2147483647):
    value = number(value, path, minimum=1, maximum=maximum, integer=True, raw=True)
    return int(value)


def validate_reinforcement(data, items, equipment):
    present = [name in data for name in REINFORCEMENT_COLLECTIONS]
    if any(present) and not all(present):
        fail('goddess_reinf', 'required', 'reinforcement tables and materials must be provided together')
    tables, materials = (data.get(name, {}) for name in REINFORCEMENT_COLLECTIONS)
    if not isinstance(tables, dict) or not isinstance(materials, dict):
        fail('goddess_reinf', 'type', 'expected reinforcement objects keyed by level')
    levels, seen = {}, {}
    for key, table in tables.items():
        path = 'goddess_reinf[{!r}]'.format(key)
        level = positive_key(key, path)
        unique(seen, level, path)
        steps = {}
        for index, row in enumerate(array(table, path)):
            target = '{}[{}]'.format(path, index)
            if not isinstance…13503 tokens truncated…', ('items_by_name', 'harness_random', 'PackageContents', 'alternatives', 0, 0, 'item'), 'missing', 'reference'),
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
