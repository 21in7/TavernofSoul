"""Game Lua modules retain local state and isolate unsupported engine chunks."""
import csv
import math
from types import SimpleNamespace

import pytest
from lupa import LuaError
from DB import ToS_DB
import items
import iesutil
import luautil
from harness.parser_fixture import isolated_parser_state


def test_ies_scalar_values_types_and_distinct_nan_objects(tmp_path):
    # Expectations are handwritten Python values, independent of the converter.
    cases = (
        ('+0007', 7), ('-0007', -7), ('0', 0), ('-0', 0),
        ('١٢', 12), ('１２', 12), (' \t42\u2003', 42), ('1_024', 1024),
        ('1.25', 1.25), ('.5', 0.5), ('2.5e2', 250.0), ('1_2.5', 12.5),
        ('-0.0', -0.0), ('-0e0', -0.0), ('0.0', 0.0),
        ('NaN', None), ('nan', None),
        ('+Inf', math.inf), ('-Inf', -math.inf),
        ('1e309', math.inf), ('-1e309', -math.inf),
        ('word', 'word'), ('1_foo', '1_foo'), ('', ''), (' ', ' '),
    )
    c = SimpleNamespace(root=tmp_path, file_dict={})
    write_ies(c, 'scalars.ies', [dict(Value=token, Twin=token)
                                for token, _ in cases] * 2, fields=('Value', 'Twin'))
    rows = iesutil.load('SCALARS.IES', c)
    assert len(rows) == 2 * len(cases)
    nans = []
    for index, row in enumerate(rows):
        _, expected = cases[index % len(cases)]
        for column in ('Value', 'Twin'):
            actual = row[column]
            if expected is None:
                assert type(actual) is float and math.isnan(actual)
                assert all(actual is not previous for previous in nans)
                nans.append(actual)
            else:
                assert type(actual) is type(expected)
                assert actual == expected
                if type(expected) is float and expected == 0.0:
                    assert math.copysign(1.0, actual) == math.copysign(1.0, expected)


def test_ies_dictreader_headers_missing_cells_and_mutable_independence(tmp_path):
    path = tmp_path / 'headers.csv'
    path.write_text('dup,,dup,tail\n'
                    'discarded,blank,007,3,001,extra\n'
                    'discarded,blank,007,3,001,extra\n'
                    'discarded,empty\n', encoding='utf-8')
    c = SimpleNamespace(file_dict={'headers.ies': {'path': str(path)}})
    rows = iesutil.load('headers.ies', c)
    expected = {'dup': 7, '': 'blank', 'tail': 3, None: ['001', 'extra']}
    assert rows == [expected, expected, {'dup': None, '': 'empty', 'tail': None}]
    assert type(rows[0]['dup']) is int and type(rows[0]['tail']) is int
    assert type(rows[0]['']) is str
    assert rows[2]['dup'] is None and rows[2]['tail'] is None
    assert list(rows[0]) == ['dup', '', 'tail', None]
    assert list(rows[2]) == ['dup', '', 'tail']
    assert rows[0] is not rows[1]
    assert rows[0][None] is not rows[1][None]
    assert all(type(value) is str for value in rows[0][None])
    again = iesutil.load('headers.ies', c)
    assert again == rows
    assert all(left is not right for left, right in zip(rows, again))
    assert again[0][None] is not rows[0][None]
    rows[0]['dup'] = 99
    rows[0][None].append('changed')
    assert rows[1] == expected and again[0] == expected


def test_ies_each_load_reads_current_file_and_discovery_mapping(tmp_path, caplog):
    current = tmp_path / 'current.csv'
    other = tmp_path / 'other.csv'
    current.write_text('Value\n0007\n', encoding='utf-8')
    other.write_text('Value\n2.5\n', encoding='utf-8')
    c = SimpleNamespace(region='ktos', file_dict={'mixed.ies': {'path': str(current)}})
    first = iesutil.load('MiXeD.IeS', c)
    assert first == [{'Value': 7}] and type(first[0]['Value']) is int
    current.write_text('Value\nword\n', encoding='utf-8')
    changed = iesutil.load('mixed.ies', c)
    assert changed == [{'Value': 'word'}] and type(changed[0]['Value']) is str
    different = SimpleNamespace(region='jtos', file_dict={'mixed.ies': {'path': str(other)}})
    loaded = iesutil.load('MIXED.IES', different)
    assert loaded == [{'Value': 2.5}] and type(loaded[0]['Value']) is float
    c.region, c.file_dict = 'jtos', different.file_dict
    switched = iesutil.load('mixed.ies', c)
    assert switched == [{'Value': 2.5}] and type(switched[0]['Value']) is float
    other.write_text('Value\n-0009\n', encoding='utf-8')
    refreshed = iesutil.load('mixed.ies', c)
    assert refreshed == [{'Value': -9}] and type(refreshed[0]['Value']) is int
    assert first == [{'Value': 7}] and changed == [{'Value': 'word'}]
    assert loaded == switched == [{'Value': 2.5}]
    caplog.clear()
    assert iesutil.load('MiSsInG.IeS', c) == []
    assert [record.getMessage() for record in caplog.records] == ['Missing ies file: missing.ies']


def test_ies_utf8_and_file_errors_propagate_and_repaired_file_reloads(tmp_path):
    path = tmp_path / 'damaged.csv'
    c = SimpleNamespace(file_dict={'damaged.ies': {'path': str(path)}})
    with pytest.raises(FileNotFoundError):
        iesutil.load('damaged.ies', c)
    path.mkdir()
    with pytest.raises(IsADirectoryError):
        iesutil.load('damaged.ies', c)
    path.rmdir()
    path.write_bytes(b'Value\n7\n\xff\n')
    with pytest.raises(UnicodeDecodeError):
        iesutil.load('damaged.ies', c)
    path.write_text('Value\n-0.0\n', encoding='utf-8')
    rows = iesutil.load('damaged.ies', c)
    assert type(rows[0]['Value']) is float and rows[0]['Value'] == 0.0
    assert math.copysign(1.0, rows[0]['Value']) == -1.0


def test_ies_csv_read_error_propagates(tmp_path):
    path = tmp_path / 'oversize.csv'
    path.write_text('Value\n' + 'x' * 32 + '\n', encoding='utf-8')
    c = SimpleNamespace(file_dict={'oversize.ies': {'path': str(path)}})
    previous_limit = csv.field_size_limit(16)
    try:
        with pytest.raises(csv.Error, match='field larger than field limit'):
            iesutil.load('oversize.ies', c)
    finally:
        csv.field_size_limit(previous_limit)
    assert iesutil.load('oversize.ies', c) == [{'Value': 'x' * 32}]


def test_ies_cache_capacity_and_short_token_length_boundaries(tmp_path):
    cases = (
        ('0007', 7), ('0', 0), ('', ''), ('1.5', 1.5), ('-0.0', -0.0),
        ('text', 'text'),
        ('0' * 127 + '7', 7), ('0' * 128 + '7', 7),
        ('x' * 128, 'x' * 128), ('x' * 129, 'x' * 129),
        (' ' * 129 + '-0.0', -0.0),
    )
    c = SimpleNamespace(root=tmp_path, file_dict={})
    # More distinct short tokens than the capacity, without a benchmark or
    # implementation mocks. Expectations describe the actual CSV values.
    write_ies(c, 'capacity.ies',
              [dict(Value=token) for token, _ in cases]
              + [dict(Value=str(10000 + index)) for index in range(4100)]
              + [dict(Value=token) for token, _ in cases], fields=('Value',))
    rows = iesutil.load('capacity.ies', c)
    assert len(rows) == 4100 + 2 * len(cases)
    for index in range(4100):
        value = rows[len(cases) + index]['Value']
        assert type(value) is int and value == 10000 + index
    for group in (rows[:len(cases)], rows[-len(cases):]):
        for row, (_, expected) in zip(group, cases):
            assert type(row['Value']) is type(expected)
            assert row['Value'] == expected
            if type(expected) is float and expected == 0.0:
                assert math.copysign(1.0, row['Value']) == -1.0


def test_legacy_line_preprocessing_executes_and_preserves_exact_source(tmp_path):
    source = r'''
-- A skipped line with ["comment"] and function ignored:method()
--[=[
missing_engine.multiline()
function ignored_method() end
]=]
fixture = {}
function fixture:calculate(t)
    local unused = require("ghost")
    local 모듈 = require('없는모듈')
    local also_unused = require "ghost"
    -- comment inside the function
    if false then local spaced = require  ("ghost") end
    local braces = "\{x\}"
    local marker = "ï»¿kept"
    return t["값"] + t[""] + t["non-word"] + t['base'], braces, marker
end
function fixture:inline(t) local unused = require("ghost") return t["값"] + 1 end
function plain_calculation()
    return 9
end
function GET_ITEM_LEVEL(item)
    return 999
end
'''.lstrip()
    # The legacy loader skips the whole BOM-prefixed line.
    (tmp_path / 'legacy.lua').write_text('\ufeffmissing_engine.bom()\n' + source, encoding='utf-8')
    expected = {
        'fixture.calculate': r'''function fixture.calculate(t)
if false then local spaced = require  ("ghost") end
local braces = "\\{x\\}"
local marker = "kept"
return t['값'] + t[''] + t["non-word"] + t['base'], braces, marker
end''',
        'fixture.inline': "function fixture.inline(t) return t['값'] + 1 end",
        'plain_calculation': 'function plain_calculation()\nreturn 9\nend',
    }
    with isolated_parser_state():
        luautil.init_global_functions(SimpleNamespace())
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))
        assert luautil.LUA_SOURCE == expected
        assert set(luautil.LUA_RUNTIME) == set(expected)
        table = luautil.lua.table_from({'값': 7, '': 2, 'non-word': 3, 'base': 4})
        assert luautil.LUA_RUNTIME['fixture.calculate'](table) == (16, r'\{x\}', 'kept')
        assert luautil.LUA_RUNTIME['fixture.inline'](table) == 8
        assert luautil.LUA_RUNTIME['plain_calculation']() == 9
        assert luautil.lua.globals().GET_ITEM_LEVEL({}) == 0
        assert luautil.lua.globals().ignored_method is None


def test_legacy_invalid_method_chunk_stays_invalid_and_later_function_loads(tmp_path):
    (tmp_path / 'invalid.lua').write_text('''
fixture = {}
function fixture:broken(t)
    return t["bad-key"] +
end
function later()
    return 23
end
'''.lstrip(), encoding='utf-8')
    with isolated_parser_state():
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))
        assert luautil.lua.globals().fixture.broken is None
        assert luautil.LUA_SOURCE == {'later': 'function later()\nreturn 23\nend'}
        assert set(luautil.LUA_RUNTIME) == {'later'}
        assert luautil.LUA_RUNTIME['later']() == 23


def test_goddess_module_preserves_local_tables_and_file_scope_initializers(tmp_path):
    (tmp_path / 'shared_item_goddess_reinforce.lua').write_text('''
local end_level = 560
local levels = {}
function initialize_levels()
    levels[end_level] = 30
end
initialize_levels()
function setting_lv_material_armor(materials, level)
    return levels[level]
end
'''.lstrip())
    with isolated_parser_state():
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))
        assert luautil.LUA_RUNTIME['setting_lv_material_armor']({}, 560) == 30


def test_bad_goddess_module_fails_instead_of_silently_omitting_materials(tmp_path):
    (tmp_path / 'shared_item_goddess_reinforce.lua').write_text('missing_engine.initialize()')
    with isolated_parser_state(), pytest.raises(ValueError, match='goddess Lua module') as failure:
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))
    assert isinstance(failure.value.__cause__, LuaError)
    assert str(tmp_path / 'shared_item_goddess_reinforce.lua') in str(failure.value)


def test_unsupported_engine_chunk_does_not_discard_later_functions(tmp_path):
    (tmp_path / 'engine.lua').write_text('''
missing_engine.initialize()
function valid_calculation()
    return 560
end
'''.lstrip())
    with isolated_parser_state():
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))
        assert luautil.LUA_RUNTIME['valid_calculation']() == 560


# Handwritten inputs and expectations; no game sources or parser outputs.
OFFLINE_ARMOR_LUA = '''
function fixture_owner_is_nil(item)
    return GetItemOwner(item) == nil
end
function SCR_REFRESH_ARMOR(item)
    local base_def = item.BaseDef + item.ItemLv * 2
    local owner = GetItemOwner(item)
    if item.GroupName == 'FreePvP' and owner ~= nil then
        -- These game map APIs are deliberately undefined in offline parsing.
        if IsPvPMineMap(owner) == 1 or IsTeamBattleLeague(owner) == 1 then
            base_def = base_def + 1000
        end
    end
    item.DEF = base_def
end
'''.lstrip()


@pytest.mark.parametrize('group,base_def,level,expected', (
    ('FreePvP', 37, 12, 61),
    ('Armor', 55, 20, 95),
))
def test_offline_armor_has_nil_owner_and_preserves_base_def(group, base_def, level, expected):
    with isolated_parser_state():
        luautil.init_global_functions(SimpleNamespace())
        luautil.lua.execute(OFFLINE_ARMOR_LUA)
        row = {'GroupName': group, 'BaseDef': base_def, 'ItemLv': level}
        globals_ = luautil.lua.globals()
        assert globals_.fixture_owner_is_nil(row) is True
        assert globals_.owner is None
        assert globals_.IsPvPMineMap is None
        assert globals_.IsTeamBattleLeague is None
        globals_.SCR_REFRESH_ARMOR(row)
        assert row['DEF'] == expected
        assert row['DEF'] > 0


def test_fake_freepvp_owner_exposes_missing_map_api_without_hiding_failure():
    with isolated_parser_state():
        luautil.init_global_functions(SimpleNamespace())
        luautil.lua.execute(OFFLINE_ARMOR_LUA)
        globals_ = luautil.lua.globals()
        original_owner = globals_.GetItemOwner
        try:
            # Negative control: change only GetItemOwner in this isolated runtime.
            luautil.lua.execute('function GetItemOwner(item) return {} end')
            row = {'GroupName': 'FreePvP', 'BaseDef': 37, 'ItemLv': 12}
            assert globals_.fixture_owner_is_nil(row) is False
            with pytest.raises(LuaError, match='IsPvPMineMap'):
                globals_.SCR_REFRESH_ARMOR(row)
            assert 'DEF' not in row
            ordinary = {'GroupName': 'Armor', 'BaseDef': 55, 'ItemLv': 20}
            globals_.SCR_REFRESH_ARMOR(ordinary)
            assert ordinary['DEF'] == 95
        finally:
            globals_.GetItemOwner = original_owner
        assert globals_.fixture_owner_is_nil(row) is True
        globals_.SCR_REFRESH_ARMOR(row)
        assert row['DEF'] == 61


SPECIAL_IES = (
    'enchant_special_option_ratio_low.ies', 'enchant_special_option_ratio.ies',
    'job.ies', 'enchant_special_option.ies', 'enchant_rank_up_ratio.ies',
)
SPECIAL_LUA = '''
local special_names = {}
local counts = {}
local job_names = {}
local function remember(row)
    if TryGetProp(row, 'Special', 0) == 1 then
        special_names[TryGetProp(row, 'Option')] = true
    end
end
function initialize_special_options()
    local tables = {
        'enchant_special_option_ratio_low', 'enchant_special_option_ratio',
        'job', 'enchant_special_option', 'enchant_rank_up_ratio'
    }
    for _, name in ipairs(tables) do
        local list, count = GetClassList(name)
        assert(list ~= nil and count > 0, 'missing rows: ' .. name)
        counts[name] = count
        for index = 0, count - 1 do
            local row = GetClassByIndexFromList(list, index)
            assert(row ~= nil, 'missing indexed row')
            if name == 'enchant_special_option_ratio_low' then remember(row) end
            if name == 'job' then job_names[index + 1] = TryGetProp(row, 'ClassName') end
        end
    end
end
initialize_special_options()
shared_enchant_special_option = {}
shared_enchant_special_option.is_special_option = function(option)
    return special_names[option] == true
end
shared_enchant_special_option.describe = function()
    return counts['enchant_special_option_ratio_low'], job_names[1], job_names[2]
end
shared_enchant_special_option.lookup = function()
    return GetClass('enchant_special_option', 'SpecialOption')['ClassID'],
           GetClassByType('enchant_rank_up_ratio', 501)['ClassName']
end
function special_option_count()
    return counts['enchant_special_option_ratio_low']
end
'''.lstrip()


def write_ies(c, filename, rows, fields=('ClassID', 'ClassName', 'Option', 'Special')):
    # Deliberately use actual mixed-case paths with lowercase discovery keys.
    path = c.root / filename.upper()
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    c.file_dict[filename.lower()] = {'path': str(path)}
    return path


def special_input(root, region='ktos', module=True):
    root.mkdir(parents=True)
    c = SimpleNamespace(root=root, PATH_INPUT_DATA=str(root), region=region,
                        file_dict={}, EQUIPMENT_IES=[], EQUIPMENT_REINFORCE_IES={})
    for name in ('sharedconst.ies', 'sharedconst_system.ies'):
        write_ies(c, name, [], fields=('ClassName', 'Value', 'UseInScript'))
    if module:
        write_ies(c, SPECIAL_IES[0], [
            dict(ClassID=40, ClassName='OldLow', Option='OLD', Special=1),
            dict(ClassID=7, ClassName='NormalLow', Option='DEF', Special=0),
            dict(ClassID=40, ClassName='FinalLow', Option='STR', Special=1),
        ])
        write_ies(c, SPECIAL_IES[1], [dict(ClassID=91, ClassName='Ratio')])
        write_ies(c, 'job.ies', [dict(ClassID=203, ClassName='Cleric'),
                               dict(ClassID=19, ClassName='Swordsman')])
        write_ies(c, SPECIAL_IES[3], [dict(ClassID=98, ClassName='SpecialOption')])
        write_ies(c, SPECIAL_IES[4], [dict(ClassID=501, ClassName='RankRatio')])
        path = root / 'Shared_Enchant_Special_Option.LUA'
        path.write_text(SPECIAL_LUA, encoding='utf-8')
        c.file_dict['shared_enchant_special_option.lua'] = {'path': str(path)}
    return c


def module_path(c):
    return c.root / 'Shared_Enchant_Special_Option.LUA'


def lookup_input(root, basic_def=640):
    c = special_input(root, module=False)
    c.EQUIPMENT_REINFORCE_IES = dict(ToS_DB.EQUIPMENT_REINFORCE_IES)
    write_ies(c, 'item_goddess_reinforce.ies', [
        dict(ClassID=9, ClassName='First', BasicDef=320),
        dict(ClassID=2, ClassName='Armor', BasicDef=basic_def),
    ], fields=('ClassID', 'ClassName', 'BasicDef'))
    write_ies(c, 'growth_by_reinforce.ies', [
        dict(ClassID=65, ClassName='Growth_Goddess_Tier1', BasicDef=28, BasicBodyDef=28),
        dict(ClassID=4, ClassName='OtherGrowth', BasicDef=12, BasicBodyDef=12),
    ], fields=('ClassID', 'ClassName', 'BasicDef', 'BasicBodyDef'))
    return c


def raw_armor_input(c, monkeypatch, refresh_source, **changes):
    # Exercise parse_equips' DictReader -> Lua path, without iesutil's numeric
    # casts (a Python integer UseLv would stringify as 460.0 in this runtime).
    row = dict(ClassID='300', ClassName='FixtureArmor', ClassType='Shirt',
               ItemGrade='6', ItemLv='460', UseLv='460', Reinforce_2='2',
               RefreshScp='SCR_REFRESH_ARMOR', MaxDur='10000', Material='Cloth',
               MaxPR='5', UseJob='All', BaseSocket='0', MaxSocket_COUNT='2',
               ItemStar='1', AttackType='None', NeedAppraisal='0', NeedRandomOption='0',
               BasicTooltipProp='DEF', StringArg='')
    row.update(changes)
    write_ies(c, 'item_equip.ies', [row], fields=tuple(row))
    c.EQUIPMENT_IES = ['item_equip.ies']
    obj = {'$ID': '300', '$ID_NAME': 'FixtureArmor'}
    c.data = {'items': {'300': obj}, 'items_by_name': {'FixtureArmor': obj},
              'item_type': {}, 'goddess_reinf': {}}
    (c.root / 'armor.lua').write_text(refresh_source + '''
function GET_TRANSCEND_MATERIAL_COUNT(item, level)
    return (level + 1) * tonumber(item.UseLv) / 460
end
''', encoding='utf-8')
    # Model rendering is outside class lookup/calculation; keep this fixture
    # independent of XAC assets while using the real equipment parser.
    monkeypatch.setattr(items.parse_xac, 'eq_model_name', lambda row, constants: 'fixture_armor')
    return obj


def test_legacy_460_csv_reaches_suffixed_armor_calculation(tmp_path, monkeypatch):
    c = lookup_input(tmp_path / 'current')
    obj = raw_armor_input(c, monkeypatch, '''
function SCR_REFRESH_ARMOR(item)
    assert(type(item.UseLv) == 'string' and tostring(item.UseLv) == '460')
    local cls = GetClassByType('item_goddess_reinforce_' .. item.UseLv,
                               tonumber(item.Reinforce_2))
    item.DEF = cls.BasicDef / 4
end
''')
    with isolated_parser_state():
        items.equipment_grade_ratios = {6: {'BasicRatio': '100'}}
        for _ in range(2):
            luautil.init(c)
            globals_ = luautil.lua.globals()
            assert luautil.lua.eval('''ies_by_ClassID.item_goddess_reinforce ==
                                      ies_by_ClassID.item_goddess_reinforce_460''') is True
            assert luautil.lua.eval('''ies_by_ClassName.item_goddess_reinforce ==
                                      ies_by_ClassName.item_goddess_reinforce_460''') is True
            for key in ('item_goddess_reinforce', 'item_goddess_reinforce_460'):
                data, count = globals_.GetClassList(key)
                assert count == 2
                assert [globals_.GetClassByIndexFromList(data, i)['ClassID'] for i in range(count)] == [9, 2]
                assert globals_.GetClass(key, 'Armor')['BasicDef'] == 640
                assert globals_.GetClassByType(key, 2)['BasicDef'] == 640
            assert globals_.GetClassList('item_goddess_reinforce_460.0') == (None, 0)
            items.parse_equips(c, 'item_equip.ies')
            assert obj['Stat_DEFENSE_PHYSICAL'] == 160
            # An addition through the alias must update canonical lookup/order.
            globals_.ies_ADD('item_goddess_reinforce_460', [
                dict(ClassID=30, ClassName='Appended', BasicDef=800)])
            data, count = globals_.GetClassList('item_goddess_reinforce')
            assert count == 3
            assert globals_.GetClassByIndexFromList(data, 2)['ClassName'] == 'Appended'
            assert globals_.GetClass('item_goddess_reinforce', 'Appended')['ClassID'] == 30


def test_growth_lookup_by_name_id_and_index_reaches_positive_armor_formula(tmp_path, monkeypatch):
    c = lookup_input(tmp_path / 'growth')
    obj = raw_armor_input(c, monkeypatch, '''
function SCR_REFRESH_ARMOR(item)
    local parts = StringSplit(item.StringArg, '/')
    local cls = GetClass(parts[1], parts[2])
    item.DEF = cls.BasicDef * tonumber(item.Reinforce_2) / 2
    item.MDEF = cls.BasicBodyDef * tonumber(item.Reinforce_2) / 2
end
''', StringArg='Growth_By_Reinforce/Growth_Goddess_Tier1', Reinforce_2='3')
    with isolated_parser_state():
        items.equipment_grade_ratios = {6: {'BasicRatio': '100'}}
        luautil.init(c)
        globals_ = luautil.lua.globals()
        data, count = globals_.GetClassList('Growth_By_Reinforce')
        assert count == 2
        assert [globals_.GetClassByIndexFromList(data, i)['ClassID'] for i in range(count)] == [65, 4]
        for cls in (globals_.GetClass('Growth_By_Reinforce', 'Growth_Goddess_Tier1'),
                    globals_.GetClassByType('Growth_By_Reinforce', 65),
                    globals_.GetClassByIndexFromList(data, 0)):
            assert (cls['ClassName'], cls['BasicDef'], cls['BasicBodyDef']) == ('Growth_Goddess_Tier1', 28, 28)
        items.parse_equips(c, 'item_equip.ies')
        assert (obj['Stat_DEFENSE_PHYSICAL'], obj['Stat_DEFENSE_MAGICAL']) == (42, 42)


def test_absent_class_lookup_keeps_nil_formula_branch_and_numeric_id_errors(tmp_path, monkeypatch):
    c = special_input(tmp_path / 'small', module=False)
    obj = raw_armor_input(c, monkeypatch, '''
function SCR_REFRESH_ARMOR(item)
    local cls = GetClass('Growth_By_Reinforce', 'Episode_1')
    local reinforcement = GetClassByType('item_goddess_reinforce_1', 1)
    if cls == nil and reinforcement == nil then
        item.DEF = tonumber(item.BasicDef) * 1.5
    else
        error('unexpected fabricated class')
    end
end
''', StringArg='Growth_By_Reinforce/Episode_1', BasicDef='40')
    with isolated_parser_state():
        items.equipment_grade_ratios = {6: {'BasicRatio': '100'}}
        luautil.init(c)
        globals_ = luautil.lua.globals()
        assert globals_.GetClassByType('Item', 300.9)['ClassName'] == 'FixtureArmor'
        assert globals_.GetClassByType('Item', 999) is None
        for key in ('growth_by_reinforce', 'item_goddess_reinforce_1'):
            assert globals_.GetClass(key, 'Episode_1') is None
            assert globals_.GetClassByType(key, 1) is None
            assert globals_.GetClassList(key) == (None, 0)
        for key in ('Item', 'absent'):
            with pytest.raises(LuaError, match='floor'):
                globals_.GetClassByType(key, 'invalid numeric ID')
        items.parse_equips(c, 'item_equip.ies')
        assert obj['Stat_DEFENSE_PHYSICAL'] == 60


def test_lookup_tables_reset_on_repeat_and_input_switch_without_stale_paths(tmp_path):
    current = lookup_input(tmp_path / 'current')
    other = lookup_input(tmp_path / 'other', basic_def=920)
    write_ies(current, 'item_goddess_reinforce_550.ies', [
        dict(ClassID=1, ClassName='Accessory550', BasicAccAtk=550),
    ], fields=('ClassID', 'ClassName', 'BasicAccAtk'))
    write_ies(current, 'item_goddess_reinforce_560.ies', [
        dict(ClassID=1, ClassName='Armor560', BasicDef=560),
    ], fields=('ClassID', 'ClassName', 'BasicDef'))
    write_ies(other, 'growth_by_reinforce.ies', [
        dict(ClassID=8, ClassName='OtherRegion', BasicDef=36, BasicBodyDef=36),
    ], fields=('ClassID', 'ClassName', 'BasicDef', 'BasicBodyDef'))
    with isolated_parser_state():
        for c in (current, current, other):
            luautil.init(c)
            globals_ = luautil.lua.globals()
            expected = 920 if c is other else 640
            assert globals_.GetClassByType('item_goddess_reinforce_460', 2)['BasicDef'] == expected
            assert globals_.GetClassList('item_goddess_reinforce_460')[1] == 2
            for level, prop in ((550, 'BasicAccAtk'), (560, 'BasicDef')):
                cls = globals_.GetClassByType('item_goddess_reinforce_' + str(level), 1)
                if c is other:
                    assert cls is None
                else:
                    assert cls[prop] == level
        assert globals_.GetClass('Growth_By_Reinforce', 'Growth_Goddess_Tier1') is None
        assert globals_.GetClassByType('Growth_By_Reinforce', 8)['BasicDef'] == 36
        for key in ('item_goddess_reinforce.ies', 'growth_by_reinforce.ies'):
            current.file_dict[key] = other.file_dict[key]
        luautil.init(current)
        for key in ('item_goddess_reinforce', 'item_goddess_reinforce_460', 'growth_by_reinforce'):
            assert luautil.lua.globals().GetClassList(key) == (None, 0)


@pytest.mark.parametrize('unavailable', ('missing_entry', 'missing_file', 'escaped_symlink'))
def test_optional_lookup_tables_require_discovered_existing_current_files(tmp_path, unavailable):
    c = lookup_input(tmp_path / 'current')
    other = lookup_input(tmp_path / 'other')
    for filename in ('item_goddess_reinforce.ies', 'growth_by_reinforce.ies'):
        path = c.root / filename.upper()
        if unavailable == 'missing_entry':
            del c.file_dict[filename]
        else:
            path.unlink()
            if unavailable == 'escaped_symlink':
                path.symlink_to(other.file_dict[filename]['path'])
    with isolated_parser_state():
        luautil.init(c)
        for key in ('item_goddess_reinforce', 'item_goddess_reinforce_460', 'growth_by_reinforce'):
            assert luautil.lua.globals().GetClassList(key) == (None, 0)


def test_removed_support_and_unregistered_ies_are_not_automatically_loaded(tmp_path, caplog):
    c = lookup_input(tmp_path / 'excluded')
    del c.EQUIPMENT_REINFORCE_IES['item_goddess_reinforce.ies']
    for filename in ('item_goddess_reinforce_580.ies', 'arbitrary.ies'):
        write_ies(c, filename, [dict(ClassID=1, ClassName='Unsupported', BasicDef=9999)],
                  fields=('ClassID', 'ClassName', 'BasicDef'))
    c.data = {}
    with isolated_parser_state():
        luautil.init(c)
        for key in ('item_goddess_reinforce', 'item_goddess_reinforce_460',
                    'item_goddess_reinforce_580', 'arbitrary'):
            assert luautil.lua.globals().GetClassList(key) == (None, 0)
        items.parse_goddess_EQ(c)
        assert c.data['goddess_reinf'] == {}
        assert 580 not in c.data['goddess_reinf_mat']
        assert c.data['goddess_reinf_unregistered'] == {'item_goddess_reinforce_580.ies': 580}
        assert 'Unregistered goddess reinforcement table: item_goddess_reinforce_580.ies' in caplog.text


@pytest.mark.parametrize('filename,key', (
    ('item_goddess_reinforce.ies', 'item_goddess_reinforce_460'),
    ('growth_by_reinforce.ies', 'Growth_By_Reinforce'),
))
def test_damaged_present_lookup_ies_propagates_and_retries(tmp_path, filename, key):
    c = lookup_input(tmp_path / 'damaged')
    path = c.root / filename.upper()
    original = path.read_bytes()
    write_ies(c, filename, [dict(ClassID='invalid ID', ClassName='Damaged')],
              fields=('ClassID', 'ClassName'))
    with isolated_parser_state():
        with pytest.raises(LuaError, match='floor'):
            luautil.init(c)
        assert luautil.LUA_RUNTIME == {} and luautil.LUA_SOURCE == {}
        path.write_bytes(original)
        luautil.init(c)
        assert luautil.lua.globals().GetClassList(key)[1] == 2


def test_explicit_equipment_refresh_error_keeps_lua_cause(tmp_path, monkeypatch):
    c = lookup_input(tmp_path / 'refresh')
    raw_armor_input(c, monkeypatch, '''
function SCR_REFRESH_ARMOR(item)
    error('fixture refresh failure')
end
''')
    with isolated_parser_state():
        items.equipment_grade_ratios = {6: {'BasicRatio': '100'}}
        luautil.init(c)
        with pytest.raises(ValueError, match='FixtureArmor using SCR_REFRESH_ARMOR') as failure:
            items.parse_equips(c, 'item_equip.ies')
        assert isinstance(failure.value.__cause__, LuaError)
        assert 'fixture refresh failure' in str(failure.value.__cause__)
        assert 'Stat_DEFENSE_PHYSICAL' not in c.data['items_by_name']['FixtureArmor']


def test_special_module_dependencies_locals_wrappers_and_hairacc_calls(tmp_path):
    c = special_input(tmp_path / 'ktos')
    (c.root / 'hairacc.lua').write_text('''
function SCR_REFRESH_HAIRACC(item)
    if shared_enchant_special_option.is_special_option(TryGetProp(item, 'Option')) then
        item['Value'] = item['Value'] + 10
    end
end
'''.lstrip(), encoding='utf-8')
    with isolated_parser_state():
        luautil.init(c)
        assert luautil.SPECIAL_OPTION_IES == SPECIAL_IES
        registry = luautil.LUA_RUNTIME
        predicate = registry['shared_enchant_special_option.is_special_option']
        assert predicate('STR') is True
        assert predicate('DEF') is False and predicate('OLD') is False
        assert predicate('unknown') is False
        assert registry['shared_enchant_special_option.describe']() == (2, 'Cleric', 'Swordsman')
        assert registry['shared_enchant_special_option.lookup']() == (98, 'RankRatio')
        assert registry['special_option_count']() == 2
        assert luautil.lua.eval('shared_enchant_special_option.is_special_option')("STR") is True
        assert 'shared_enchant_special_option.is_special_option = function' in (
            luautil.LUA_SOURCE['shared_enchant_special_option.is_special_option'])
        assert luautil.LUA_SOURCE['special_option_count'].startswith('function special_option_count(')
        assert 'remember' not in registry
        for option, expected in (('STR', 12), ('DEF', 2)):
            row = {'Option': option, 'Value': 2}
            registry['SCR_REFRESH_HAIRACC'](row)
            assert row == {'Option': option, 'Value': expected}

        globals_ = luautil.lua.globals()
        data, count = globals_.GetClassList('ENCHANT_SPECIAL_OPTION_RATIO_LOW')
        assert count == 2
        assert data[40]['ClassName'] == 'FinalLow' and data[7]['ClassName'] == 'NormalLow'
        assert globals_.GetClassByIndexFromList(data, 0)['ClassID'] == 40
        assert globals_.GetClassByIndexFromList(data, 1)['ClassID'] == 7
        assert globals_.GetClassByNameFromList(data, 'FinalLow')['ClassID'] == 40
        assert globals_.GetClass('enchant_special_option_ratio_low', 'FinalLow')['ClassID'] == 40
        assert globals_.GetClassByType('enchant_special_option_ratio_low', 40)['Option'] == 'STR'
        for index in (None, -1, 2, 0.5, '0', True, float('nan'), float('inf')):
            assert globals_.GetClassByIndexFromList(data, index) is None
        assert globals_.GetClassByIndexFromList(None, 0) is None
        assert globals_.GetClassByIndexFromList(luautil.lua.table(), 0) is None
        assert globals_.GetClassList('unknown') == (None, 0)


def test_alias_accumulation_unique_counts_and_last_id_winners(tmp_path):
    c = special_input(tmp_path / 'small', module=False)
    c.EQUIPMENT_IES = ['item_equip.ies', 'item_equip_ep12.ies']
    write_ies(c, c.EQUIPMENT_IES[0], [dict(ClassID=120, ClassName='EquipFirst'),
                                   dict(ClassID=9, ClassName='EquipSecond')])
    write_ies(c, c.EQUIPMENT_IES[1], [dict(ClassID=120, ClassName='EquipWinner'),
                                   dict(ClassID=600, ClassName='EquipThird')])
    with isolated_parser_state():
        luautil.init(c)
        globals_ = luautil.lua.globals()
        items, item_count = globals_.GetClassList('Item')
        assert item_count == 3
        assert [globals_.GetClassByIndexFromList(items, i)['ClassName'] for i in range(3)] == [
            'EquipWinner', 'EquipSecond', 'EquipThird']
        assert items[120]['ClassName'] == 'EquipWinner'
        globals_.ies_ADD('mixed', [dict(ClassID=90, ClassName='First'),
                                 dict(ClassID=3, ClassName='Second'),
                                 dict(ClassID=90, ClassName='Replacement')])
        data, count = globals_.GetClassList('mixed')
        assert count == 2
        globals_.ies_ADD('mixed', [dict(ClassID=3, ClassName='LastSecond'),
                                 dict(ClassID=8, ClassName='Third')])
        assert globals_.GetClassList('mixed')[1] == 3
        assert [globals_.GetClassByIndexFromList(data, i)['ClassName'] for i in range(3)] == [
            'Replacement', 'LastSecond', 'Third']
        assert data[90]['ClassName'] == 'Replacement' and data[3]['ClassName'] == 'LastSecond'
        assert globals_.GetClassByType('mixed', 8)['ClassName'] == 'Third'
        # Existing independent name lookup retains earlier names as well.
        assert globals_.GetClass('mixed', 'First')['ClassID'] == 90
        assert globals_.GetClass('mixed', 'LastSecond')['ClassID'] == 3
        luautil.init(c)
        assert luautil.lua.globals().GetClassList('mixed') == (None, 0)


def test_special_dependencies_are_not_registered_without_module(tmp_path):
    c = special_input(tmp_path / 'small')
    module_path(c).unlink()
    del c.file_dict['shared_enchant_special_option.lua']
    with isolated_parser_state():
        luautil.init(c)
        for filename in SPECIAL_IES:
            assert luautil.lua.globals().GetClassList(filename[:-4]) == (None, 0)
        assert luautil.lua.globals().shared_enchant_special_option is None


@pytest.mark.parametrize('failure', ('missing_entry', 'missing_file'))
def test_special_module_discovery_failure_is_explicit_and_retries(tmp_path, failure):
    c = special_input(tmp_path / 'ktos')
    entry = c.file_dict['shared_enchant_special_option.lua']
    if failure == 'missing_entry':
        del c.file_dict['shared_enchant_special_option.lua']
    else:
        module_path(c).unlink()
    with isolated_parser_state():
        with pytest.raises(ValueError) as error:
            luautil.init(c)
        assert str(module_path(c)) in str(error.value)
        c.file_dict['shared_enchant_special_option.lua'] = entry
        module_path(c).write_text(SPECIAL_LUA, encoding='utf-8')
        luautil.init(c)
        assert luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']('STR') is True


def test_repeat_changed_input_removed_functions_and_region_switch(tmp_path):
    c = special_input(tmp_path / 'ktos')
    other = special_input(tmp_path / 'jtos', region='jtos')
    legacy = special_input(tmp_path / 'twtos', region='twtos', module=False)
    with isolated_parser_state():
        for _ in range(2):
            previous_lua = luautil.lua
            previous_runtime, previous_source = luautil.LUA_RUNTIME, luautil.LUA_SOURCE
            luautil.init(c)
            assert luautil.lua is not previous_lua
            assert luautil.LUA_RUNTIME is not previous_runtime
            assert luautil.LUA_SOURCE is not previous_source
            assert luautil.LUA_RUNTIME['shared_enchant_special_option.describe']() == (2, 'Cleric', 'Swordsman')
        write_ies(c, SPECIAL_IES[0], [dict(ClassID=800, ClassName='NewLow', Option='DEX', Special=1)])
        source = SPECIAL_LUA[:SPECIAL_LUA.index('function special_option_count()')]
        source = source.replace('''shared_enchant_special_option.describe = function()
    return counts['enchant_special_option_ratio_low'], job_names[1], job_names[2]
end
''', '')
        module_path(c).write_text(source, encoding='utf-8')
        luautil.init(c)
        predicate = luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']
        assert predicate('STR') is False and predicate('DEX') is True
        assert luautil.lua.globals().GetClassList('enchant_special_option_ratio_low')[1] == 1
        assert 'shared_enchant_special_option.describe' not in luautil.LUA_RUNTIME
        assert 'shared_enchant_special_option.describe' not in luautil.LUA_SOURCE
        assert luautil.lua.globals().shared_enchant_special_option['describe'] is None
        assert 'special_option_count' not in luautil.LUA_RUNTIME
        assert 'special_option_count' not in luautil.LUA_SOURCE
        assert luautil.lua.globals().special_option_count is None
        luautil.init(other)
        predicate = luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']
        assert predicate('STR') is True and predicate('DEX') is False
        # Simulate DB's shared discovery dictionary retaining another region.
        legacy.file_dict.update({key: value for key, value in other.file_dict.items()
                                 if key in SPECIAL_IES or key.endswith('.lua')})
        luautil.init(legacy)
        assert luautil.lua.globals().shared_enchant_special_option is None
        assert 'shared_enchant_special_option.is_special_option' not in luautil.LUA_RUNTIME
        for filename in SPECIAL_IES:
            assert luautil.lua.globals().GetClassList(filename[:-4]) == (None, 0)


@pytest.mark.parametrize('filename', SPECIAL_IES)
@pytest.mark.parametrize('failure', ('missing_entry', 'missing_file', 'stale_region'))
def test_missing_current_dependencies_fail_and_retry(tmp_path, filename, failure):
    c = special_input(tmp_path / 'ktos')
    stale = special_input(tmp_path / 'previous', region='itos')
    with isolated_parser_state():
        luautil.init(c)
        entry = c.file_dict[filename]
        path = c.root / filename.upper()
        original = path.read_bytes()
        if failure == 'missing_entry':
            del c.file_dict[filename]
        elif failure == 'missing_file':
            path.unlink()
        else:
            c.file_dict[filename] = stale.file_dict[filename]
        with pytest.raises(ValueError, match=filename) as failure_info:
            luautil.init(c)
        assert str(module_path(c)) in str(failure_info.value)
        assert luautil.LUA_RUNTIME == {} and luautil.LUA_SOURCE == {}
        assert luautil.lua.globals().shared_enchant_special_option is None
        c.file_dict[filename] = entry
        path.write_bytes(original)
        luautil.init(c)
        assert luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']('STR') is True


@pytest.mark.parametrize('source', (
    'shared_enchant_special_option = {}\nmissing_engine.initialize()',
    SPECIAL_LUA.replace('initialize_special_options()\nshared_enchant',
                        "error('initializer failed')\nshared_enchant"),
    'this is not valid Lua !',
))
def test_bad_special_module_propagates_lua_cause_and_retry(tmp_path, source):
    c = special_input(tmp_path / 'ktos')
    with isolated_parser_state():
        luautil.init(c)
        module_path(c).write_text(source, encoding='utf-8')
        with pytest.raises(ValueError, match='special-option Lua module') as failure:
            luautil.init(c)
        assert isinstance(failure.value.__cause__, LuaError)
        assert str(module_path(c)) in str(failure.value)
        assert luautil.lua.globals().shared_enchant_special_option is None
        assert 'shared_enchant_special_option.is_special_option' not in luautil.LUA_RUNTIME
        module_path(c).write_text(SPECIAL_LUA, encoding='utf-8')
        luautil.init(c)
        assert luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']('STR') is True


@pytest.mark.parametrize('source', (
    'shared_enchant_special_option = {}',
    'shared_enchant_special_option = {}\nshared_enchant_special_option.is_special_option = function() return true end\n'
    'shared_enchant_special_option.is_special_option = false',
))
def test_special_module_requires_registered_callable_without_stale_function(tmp_path, source):
    c = special_input(tmp_path / 'ktos')
    with isolated_parser_state():
        luautil.init(c)
        module_path(c).write_text(source, encoding='utf-8')
        with pytest.raises(ValueError, match='Missing callable shared_enchant_special_option.is_special_option'):
            luautil.init(c)
        assert luautil.lua.globals().shared_enchant_special_option is None


@pytest.mark.parametrize('filename', ('Shared_Enchant_Special_Option.LUA', 'shared_item_goddess_reinforce.lua'))
def test_whole_modules_preserve_overrides_during_initializer_and_calls(tmp_path, filename):
    c = special_input(tmp_path / 'ktos', module=False)
    source = '''
function GET_ITEM_LEVEL(item) return 999 end
function GetItemOwner(item) return {} end
local initialized_level = GET_ITEM_LEVEL({})
local initialized_owner_is_nil = GetItemOwner({}) == nil
function observed_override()
    return initialized_level, GET_ITEM_LEVEL({}),
           initialized_owner_is_nil, GetItemOwner({}) == nil
end
'''.lstrip()
    if filename == 'Shared_Enchant_Special_Option.LUA':
        for name in SPECIAL_IES:
            write_ies(c, name, [dict(ClassID=1, ClassName='Row')])
        source += '''shared_enchant_special_option = {}
shared_enchant_special_option.is_special_option = function() return true end
'''
    path = c.root / filename
    path.write_text(source, encoding='utf-8')
    c.file_dict[filename.lower()] = {'path': str(path)}
    with isolated_parser_state():
        for _ in range(2):
            luautil.init(c)
            assert luautil.lua.globals().GET_ITEM_LEVEL({}) == 0
            assert luautil.lua.globals().GetItemOwner({}) is None
            assert luautil.LUA_RUNTIME['observed_override']() == (0, 0, True, True)
            for name in ('GET_ITEM_LEVEL', 'GetItemOwner'):
                assert name not in luautil.LUA_RUNTIME
                assert name not in luautil.LUA_SOURCE


def test_whole_module_registration_ignores_commented_declarations(tmp_path):
    c = special_input(tmp_path / 'ktos')
    module_path(c).write_text('''--[=[
function nonexistent.module_function() end
missing_table.field = function() end
]=]
''' + SPECIAL_LUA, encoding='utf-8')
    with isolated_parser_state():
        luautil.init(c)
        assert luautil.LUA_RUNTIME['shared_enchant_special_option.is_special_option']('STR') is True
        assert 'nonexistent.module_function' not in luautil.LUA_RUNTIME
        assert 'missing_table.field' not in luautil.LUA_SOURCE
