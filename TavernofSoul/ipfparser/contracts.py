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
    if isinstance(value, float) and not math.isfinite(value):
        fail(path, 'number', 'NaN and Infinity are not JSON numbers')
    if isinstance(value, dict):
        for key, child in value.items():
            finite_tree(child, '{}[{!r}]'.format(path, key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            finite_tree(child, '{}[{}]'.format(path, index))


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


GEM_SLOTS = ('Weapon', 'SubWeapon', 'TopAndBottom', 'Gloves', 'Boots')
REINFORCEMENT_COLLECTIONS = ('goddess_reinf', 'goddess_reinf_mat')


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
            if not isinstance(row, dict):
                fail(target, 'type', 'expected an IES row')
            fields(row, target, strings=('ClassName',), integers=('ClassID', 'BasicProp'), raw=True)
            step = positive_key(row['ClassID'], target + '.ClassID', maximum=30)
            unique(steps, step, target)
            number(row['BasicProp'], target + '.BasicProp', minimum=0, maximum=100000, integer=True, raw=True)
            for column in ('AddAtk', 'AddDef', 'AddAccAtk', 'BasicAtk', 'BasicDef', 'BasicAccAtk', 'EvolveAtk'):
                if column in row:
                    number(row[column], target + '.' + column, minimum=0, maximum=2147483647, integer=True, raw=True)
        if not steps or set(steps) != set(range(1, len(steps) + 1)):
            fail(path, 'steps', 'expected consecutive reinforcement steps starting at 1')
        levels[level] = steps
    seen = {}
    for key, groups in materials.items():
        path = 'goddess_reinf_mat[{!r}]'.format(key)
        level = positive_key(key, path)
        unique(seen, level, path)
        if not isinstance(groups, dict):
            fail(path, 'type', 'expected material groups')
        for group, steps in groups.items():
            if group not in ('acc', 'armor', 'weapon') or not isinstance(steps, dict):
                fail(path, 'group', 'expected acc, armor or weapon step objects')
            step_seen = {}
            for key, values in steps.items():
                target = '{}.{}[{!r}]'.format(path, group, key)
                step = positive_key(key, target, maximum=30)
                unique(step_seen, step, target)
                if not isinstance(values, dict):
                    fail(target, 'type', 'expected material ClassName/quantity pairs')
                for name, quantity in values.items():
                    text(name, target, nonempty=True, limit=100)
                    number(quantity, target + '.' + name, minimum=0, maximum=2147483647, integer=True)
                if values and step not in levels.get(level, {}):
                    fail(target, 'reference', 'material step has no registered reinforcement row')
    for name in equipment:
        path, row = items[name]
        if 'GoddessReinforceLevel' not in row:
            continue
        level, group = row['GoddessReinforceLevel'], row['GoddessReinforceGroup']
        steps = levels.get(level)
        if not steps:
            fail(path + '.GoddessReinforceLevel', 'reference', 'registered reinforcement table missing')
        for field in ('AnvilATK', 'AnvilDEF'):
            values = row[field]
            if values and len(values) != len(steps):
                fail(path + '.' + field, 'steps', 'expected one calculation per reinforcement step')
            for value in values:
                number(value, path + '.' + field, minimum=0, maximum=2147483647, integer=True)
        # Missing groups/steps mean unavailable costs, not a free enhancement.


def ordered(row, path, low, high):
    if row[low] > row[high]:
        fail(path + '.' + low, 'order', '{} must not exceed {}'.format(low, high))


def validate_drop_values(row, path):
    fields(row, path, numbers=('Chance',), integers=('Quantity_MIN', 'Quantity_MAX'))
    number(row['Chance'], path + '.Chance', minimum=0, maximum=100)
    for field in ('Quantity_MIN', 'Quantity_MAX'):
        number(row[field], path + '.' + field, minimum=0, integer=True)
    ordered(row, path, 'Quantity_MIN', 'Quantity_MAX')


def validate_other_entities(entity_rows, indexed):
    for path, row in entity_rows['jobs']:
        fields(row, path, strings=('Icon', 'Description', 'JobTree'), booleans=('IsStarter',))
        text(row['Name'], path + '.Name', limit=30)
        text(row['$ID_NAME'], path + '.$ID_NAME', limit=30)
        text(row['Icon'], path + '.Icon', limit=30)
        text(row['JobTree'], path + '.JobTree', limit=15)
    for path, row in entity_rows['skills']:
        fields(row, path, strings=('Icon', 'Description', 'Effect', 'Element', 'RequiredStance',
               'RequiredStanceCompanion'), integers=('BasicSP', 'MaxLevel', 'UnlockClassLevel', 'OverHeat'), nullable=('Element',))
        text(row['Name'], path + '.Name', limit=30)
        text(row['Icon'], path + '.Icon', limit=50)
        if 'Link_Job' not in row:
            fail(path + '.Link_Job', 'required', 'missing skill job link')
        if row['Link_Job'] is not None:
            reference(row['Link_Job'], path + '.Link_Job', indexed['jobs'][0])
        for field in ('BasicSP', 'OverHeat'):
            number(row[field], path + '.' + field, minimum=0, integer=True)
        if 'BasicCoolDown' in row:
            number(row['BasicCoolDown'], path + '.BasicCoolDown', minimum=0, integer=True)
        for field in ('sfr', 'CaptionRatio', 'CaptionRatio2', 'CaptionRatio3', 'CaptionTime',
                      'SkillSR', 'SpendItemCount', 'SpendPoison', 'SpendSP', 'CoolDown'):
            if field in row and row[field] is not None and row[field] != '':
                numeric_array(row[field], path + '.' + field,
                              minimum=None if field.startswith('CaptionRatio') else 0)
    combined = dict(indexed['monsters'][0])
    for key, location in indexed['npcs'][0].items():
        unique(combined, key, location)
    stats = ('Stat_CON', 'Stat_DEX', 'Stat_INT', 'Stat_SPR', 'Stat_STR', 'Stat_HP',
             'Stat_ATTACK_MAGICAL_MIN', 'Stat_ATTACK_MAGICAL_MAX', 'Stat_ATTACK_PHYSICAL_MIN',
             'Stat_ATTACK_PHYSICAL_MAX', 'Stat_DEFENSE_MAGICAL', 'Stat_DEFENSE_PHYSICAL',
             'Stat_Accuracy', 'Stat_Evasion', 'Stat_CriticalDamage', 'Stat_CriticalDefense',
             'Stat_CriticalRate', 'Stat_BlockRate', 'Stat_BlockPenetration')
    for path, row in entity_rows['monsters']:
        fields(row, path, strings=('Armor', 'Description', 'Element', 'Icon', 'Race', 'Rank', 'Size'),
               integers=('Level', 'EXP', 'EXPClass') + stats, nullable=('Icon', 'Size'))
        for field in ('Level', 'EXP', 'EXPClass', 'Stat_HP'):
            number(row[field], path + '.' + field, minimum=0, integer=True)
        ordered(row, path, 'Stat_ATTACK_PHYSICAL_MIN', 'Stat_ATTACK_PHYSICAL_MAX')
        ordered(row, path, 'Stat_ATTACK_MAGICAL_MIN', 'Stat_ATTACK_MAGICAL_MAX')
    for path, row in entity_rows['npcs']:
        fields(row, path, strings=('Description', 'Icon'), nullable=('Icon',))
    for path, row in entity_rows['skill_mon']:
        fields(row, path, strings=('Attribute',), integers=('CD', 'AAR'), raw=True)
        number(row['CD'], path + '.CD', minimum=0, integer=True, raw=True)
        if number(row['AAR'], path + '.AAR', integer=True, raw=True) != -99:
            number(row['AAR'], path + '.AAR', minimum=0, integer=True, raw=True)
        if 'SFR' not in row:
            fail(path + '.SFR', 'required', 'missing monster skill factor')
        if row['SFR'] not in (None, ''):
            number(row['SFR'], path + '.SFR', raw=True)
        if row.get('HitCount') not in (None, ''):
            number(row['HitCount'], path + '.HitCount', minimum=1, integer=True, raw=True)
        if 'Monster' not in row:
            fail(path + '.Monster', 'required', 'missing monster links')
        for index, monster in enumerate(array(row['Monster'], path + '.Monster')):
            reference(monster, '{}.Monster[{}]'.format(path, index), indexed['monsters'][0])
    for path, row in entity_rows['maps']:
        fields(row, path, strings=('Type',), booleans=('HasChallengeMode', 'HasWarp'),
               integers=('Level', 'Prop_EliteMonsterCapacity', 'Prop_MaxHateCount', 'Stars'))
        if 'Link_Maps' not in row:
            fail(path + '.Link_Maps', 'required', 'missing map links')
        for link in array(row['Link_Maps'], path + '.Link_Maps'):
            reference(link, path + '.Link_Maps', indexed['maps'][0])
    for path, row in entity_rows['attributes']:
        fields(row, path, strings=('Description', 'Icon', 'DescriptionRequired'),
               booleans=('IsToggleable',), integers=('LevelMax',), raw=True,
               nullable=('Icon', 'DescriptionRequired'))
        for field in ('Link_Jobs', 'Link_Skills'):
            if field not in row:
                fail(path + '.' + field, 'required', 'missing attribute links')
        for job in array(row['Link_Jobs'], path + '.Link_Jobs'):
            reference(job, path + '.Link_Jobs', indexed['jobs'][0])
        # Retired/non-job skills are explicitly optional in importAttrib.
        for skill in array(row['Link_Skills'], path + '.Link_Skills'):
            text(skill, path + '.Link_Skills', nonempty=True)
    for path, row in entity_rows['buff']:
        fields(row, path, strings=('Description', 'Icon', 'Keyword', 'Group1', 'Group2', 'Group3', 'GroupIndex'),
               integers=('ApplyTime', 'OverBuff'), raw=True,
               nullable=('Description', 'Icon', 'Keyword', 'Group1', 'Group2', 'Group3', 'GroupIndex'))
        if 'UserRemove' not in row:
            fail(path + '.UserRemove', 'required', 'missing remove flag')
        boolean(row['UserRemove'], path + '.UserRemove', raw=True)
    for path, row in entity_rows['achievements']:
        fields(row, path, strings=('Icon', 'Desc', 'DescTitle', 'Group'), booleans=('Hidden',),
               nullable=('Icon', 'Group'))


def validate_relations(data, indexed):
    item_ids = indexed['items_by_name'][0]
    monster_ids = {**indexed['monsters'][0], **indexed['npcs'][0]}
    for collection in RELATIONS:
        if not isinstance(data[collection], list):
            fail(collection, 'type', 'expected an array of relations')
        seen = {}
        parents = ('Monster', 'Item') if collection == 'item_monster' else \
                  ('Map', 'NPC') if collection == 'map_npc' else ('Map', 'Item')
        for path, row in rows(collection, data[collection]):
            for field in parents:
                if field not in row:
                    fail(path + '.' + field, 'required', 'missing relation parent')
                available = indexed['maps'][0] if field == 'Map' else \
                            monster_ids if field in ('Monster', 'NPC') else item_ids
                reference(row[field], path + '.' + field, available)
            unique(seen, tuple(str(row[field]) for field in parents), path)
            if collection in ('item_monster', 'map_item'):
                validate_drop_values(row, path)
            else:
                fields(row, path, numbers=('TimeRespawn',), integers=('Population',))
                number(row['TimeRespawn'], path + '.TimeRespawn', minimum=0)
                number(row['Population'], path + '.Population', minimum=0, integer=True)
                if 'Positions' not in row:
                    fail(path + '.Positions', 'required', 'missing spawn positions')
                for index, position in enumerate(array(row['Positions'], path + '.Positions')):
                    target = '{}.Positions[{}]'.format(path, index)
                    if len(array(position, target)) != 2:
                        fail(target, 'shape', 'expected a two-dimensional map position')
                    numeric_array(position, target, minimum=None)


def load_json(path):
    """Reject duplicate keys and nonstandard NaN/Infinity before they lose context."""
    path = Path(path)
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                fail(str(path), 'duplicate_key', 'duplicate JSON key {!r}'.format(key))
            result[key] = value
        return result
    def constant(value):
        fail(str(path), 'number', '{} is not a JSON number'.format(value))
    try:
        with path.open(encoding='utf-8') as stream:
            value = json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    except ContractError:
        raise
    except (OSError, ValueError) as exc:
        fail(str(path), 'json', 'cannot load JSON: {}'.format(exc))
    if not isinstance(value, (dict, list)):
        fail(str(path), 'type', 'expected a JSON object or array')
    finite_tree(value, str(path))
    return value


def load_release(directory, require_version=True):
    """Validate the snapshot to be imported, retaining only importer collections."""
    directory = Path(directory)
    required = REQUIRED_COLLECTIONS + (('version',) if require_version else ())
    for name in required:
        if not (directory / (name + '.json')).is_file():
            fail(name + '.json', 'required', 'missing release file')
    data = {}
    for path in sorted(directory.glob('*.json')):
        value = load_json(path)
        if path.stem in REQUIRED_COLLECTIONS + REINFORCEMENT_COLLECTIONS + ('version',):
            data[path.stem] = value
    validate_release(data, require_version=require_version)
    return data.get('version')
