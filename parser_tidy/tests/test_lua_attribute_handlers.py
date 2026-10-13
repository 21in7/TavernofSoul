"""Attribute handlers and TryGetProp using real Lua without game inputs."""

from contextlib import contextmanager
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lupa import as_attrgetter

_saved_import_path = sys.path[:]
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import luautil
finally:
    sys.path[:] = _saved_import_path


LEGACY = """
function LegacyTryGetProp(item, prop, default)
    if item == nil then
        return default
    end

    local value = item[prop]

    if tonumber(value) ~= nil then
        return tonumber(value)
    end

    if value ~= nil then
        return value
    else
        return default
    end
end
"""


@contextmanager
def initialized_runtime():
    saved = luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE
    patches = []
    config = SimpleNamespace()
    try:
        # Keep init and init_global_functions real; isolate only input loaders.
        for name in ('init_global_constants', 'init_global_data', 'init_runtime'):
            loader_patch = patch.object(luautil, name)
            loader_patch.start()
            patches.append(loader_patch)
        luautil.init(config)
        luautil.lua.execute(LEGACY)
        yield luautil.lua, config
    finally:
        for loader_patch in reversed(patches):
            loader_patch.stop()
        luautil.lua, luautil.LUA_RUNTIME, luautil.LUA_SOURCE = saved


def as_row(runtime, row):
    # Keep the attribute protocol when passing userdata from Python into Lua.
    return as_attrgetter(row)


class AttributeHandlerTests(unittest.TestCase):
    # Independent source values and expected results, not production constants.
    integer_cases = (
        ('Blockable', '+0007', 7), ('HPCount', '-0008', -8),
        ('ReinforceArmor', ' \t42\u2003', 42),
        ('TranscendArmor', '1_024', 1024),
        ('ReinforceWeapon', '١٢', 12), ('TranscendWeapon', '１２', 12),
    )

    def test_each_integer_attribute_converts_without_changing_raw_row(self):
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key], type(row[key]) end')
            raw = {name: value for name, value, _ in self.integer_cases}
            row = as_row(runtime, raw)
            for name, value, expected in self.integer_cases:
                with self.subTest(name=name):
                    self.assertEqual(read(row, name), (expected, 'number'))
                    actual = luautil.attr_getter(raw, name)
                    self.assertEqual(actual, expected)
                    self.assertIs(type(actual), int)
                    self.assertEqual(raw[name], value)
                    self.assertIs(type(raw[name]), str)

    def test_each_integer_attribute_handles_present_scalar_values(self):
        cases = ((False, 0), (True, 1), (0, 0), (7, 7),
                 (3.875, 3), (-3.875, -3), ('-0', 0))
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key] end')
            for name, _, _ in self.integer_cases:
                for value, expected in cases:
                    with self.subTest(name=name, value=value):
                        raw = {name: value}
                        self.assertEqual(read(as_row(runtime, raw), name), expected)
                        self.assertIs(type(luautil.attr_getter(raw, name)), int)
                        self.assertIs(raw[name], value)

    def test_each_integer_attribute_preserves_conversion_failures(self):
        cases = (
            (None, TypeError), ('', ValueError), (' ', ValueError),
            ('7.0', ValueError), ('1e2', ValueError), ('0x10', ValueError),
            ('NaN', ValueError), ('+Inf', ValueError), ('1e309', ValueError),
            ('1__2', ValueError), ('12\x00', ValueError),
            ('invalid', ValueError), (float('nan'), ValueError),
            (float('inf'), OverflowError), (float('-inf'), OverflowError),
        )
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key] end')
            for name, _, _ in self.integer_cases:
                for value, error in cases:
                    with self.subTest(name=name, value=value):
                        raw = {name: value}
                        with self.assertRaises(error):
                            read(as_row(runtime, raw), name)
                        with self.assertRaises(error):
                            luautil.attr_getter(raw, name)
                        self.assertIs(raw[name], value)

    def test_other_fields_preserve_raw_values_and_missing_fields_return_zero(self):
        cases = (
            ('UseLv', '00560', 'string'), ('Reinforce_2', '007', 'string'),
            ('Transcend', '004', 'string'), ('Level', '7.0', 'string'),
            ('ItemGrade', '', 'string'), ('BasicTooltipProp', 'ATK,DEF', 'string'),
            ('ClassName', 'Equipment_Row', 'string'), ('Name', '장비', 'string'),
            ('Nullable', None, 'nil'), ('Flag', False, 'boolean'),
            ('Enabled', True, 'boolean'), ('DEF', 3.875, 'number'),
            ('MHP', 42, 'number'), ('blockable', 'invalid', 'string'),
            ('HPCountExtra', 'NaN', 'string'),
        )
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key], type(row[key]) end')
            raw = {name: value for name, value, _ in cases}
            row = as_row(runtime, raw)
            for name, value, lua_type in cases:
                with self.subTest(name=name):
                    self.assertEqual(read(row, name), (value, lua_type))
                    self.assertIs(luautil.attr_getter(raw, name), value)
            for name in ('missing', '') + tuple(name for name, _, _ in self.integer_cases):
                with self.subTest(missing=name):
                    self.assertEqual(read(row, name), (0, 'number'))
                    self.assertNotIn(name, raw)

    def test_lua_setter_writes_through_and_requeries_separate_rows(self):
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key] end')
            put_and_read = runtime.eval('''function(row, key, value)
                row[key] = value
                return row[key]
            end''')
            first_raw = {name: '11' for name, _, _ in self.integer_cases}
            second_raw = {name: '21' for name, _, _ in self.integer_cases}
            first, second = as_row(runtime, first_raw), as_row(runtime, second_raw)
            for name, _, _ in self.integer_cases:
                with self.subTest(name=name):
                    self.assertEqual(read(first, name), 11)
                    self.assertEqual(read(second, name), 21)
                    self.assertEqual(put_and_read(first, name, '0012'), 12)
                    self.assertEqual(first_raw[name], '0012')
                    self.assertIs(type(first_raw[name]), str)
                    self.assertEqual(read(second, name), 21)
                    second_raw[name] = '22'
                    self.assertEqual(read(second, name), 22)
                    self.assertEqual(read(first, name), 12)
                    self.assertEqual(put_and_read(first, name, False), 0)
                    self.assertIs(first_raw[name], False)
                    del first_raw[name]
                    self.assertEqual(read(first, name), 0)
            for value in ('', '00560', False, None):
                with self.subTest(raw=value):
                    self.assertEqual(put_and_read(first, 'UseLv', value), value)
                    self.assertEqual(first_raw['UseLv'], value)
                    self.assertIn('UseLv', first_raw)
            with self.assertRaises(ValueError):
                put_and_read(first, 'Blockable', 'invalid')
            self.assertEqual(first_raw['Blockable'], 'invalid')
            self.assertEqual(put_and_read(first, 'Blockable', '13'), 13)

    def test_mapping_protocol_order_subclass_overrides_and_live_reads(self):
        events = []

        class Row(dict):
            def __contains__(self, key):
                events.append(('contains', key))
                if key == 'ReinforceArmor':
                    dict.__setitem__(self, key, '13')
                return key == 'virtual' or (key != 'hidden' and dict.__contains__(self, key))

            def __getitem__(self, key):
                events.append(('getitem', key))
                if key == 'virtual':
                    return None
                if key == 'HPCount':
                    return '07'
                return dict.__getitem__(self, key)

            def __setitem__(self, key, value):
                events.append(('setitem', key, value))
                dict.__setitem__(self, key, value)

            def get(self, *args):
                raise AssertionError('The attribute bridge must use the mapping protocol')

            def __missing__(self, key):
                raise AssertionError('Missing attributes must not invoke __missing__')

        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row, key) return row[key] end')
            raw = Row(HPCount='99', ReinforceArmor='11', UseLv='00560', hidden='7')
            row = as_row(runtime, raw)
            for name, expected, present in (
                ('HPCount', 7, True), ('ReinforceArmor', 13, True),
                ('UseLv', '00560', True), ('virtual', None, True),
                ('hidden', 0, False), ('missing', 0, False),
            ):
                with self.subTest(name=name):
                    events.clear()
                    self.assertEqual(read(row, name), expected)
                    self.assertEqual(events, [('contains', name)] +
                                     ([('getitem', name)] if present else []))
            put_and_read = runtime.eval('''function(row)
                row.UseLv = '00561'
                return row.UseLv
            end''')
            events.clear()
            self.assertEqual(put_and_read(row), '00561')
            self.assertEqual(events, [('setitem', 'UseLv', '00561'),
                                     ('contains', 'UseLv'), ('getitem', 'UseLv')])
            self.assertEqual(dict.__getitem__(raw, 'UseLv'), '00561')

    def test_mapping_and_int_exceptions_propagate_without_retry(self):
        with initialized_runtime() as (runtime, _):
            read = runtime.eval('function(row) return row.Blockable end')
            for failure in ('contains', 'getitem', 'int'):
                for error_type in (TypeError, KeyError):
                    with self.subTest(failure=failure, error=error_type):
                        error = error_type('deliberate failure')
                        events = []

                        class Value:
                            def __int__(self):
                                events.append('int')
                                raise error

                        class Row(dict):
                            def __contains__(self, key):
                                events.append('contains')
                                if failure == 'contains':
                                    raise error
                                return True

                            def __getitem__(self, key):
                                events.append('getitem')
                                if failure == 'getitem':
                                    raise error
                                return Value()

                        with self.assertRaises(error_type) as raised:
                            read(as_row(runtime, Row()))
                        self.assertIs(raised.exception, error)
                        self.assertEqual(events, {
                            'contains': ['contains'],
                            'getitem': ['contains', 'getitem'],
                            'int': ['contains', 'getitem', 'int'],
                        }[failure])

    def test_ordinary_non_string_python_names_keep_raw_values(self):
        for name in (None, False, 7, 3.5, b'Blockable', ('Blockable',), frozenset({'HPCount'})):
            with self.subTest(name=name):
                raw = {name: '007'}
                self.assertEqual(luautil.attr_getter(raw, name), '007')
                self.assertIs(type(luautil.attr_getter(raw, name)), str)
                self.assertEqual(luautil.attr_getter({}, name), 0)

    def test_unhashable_python_names_use_membership_only_fallback(self):
        events = []

        class Row:
            def __contains__(self, key):
                events.append(('contains', key))
                return True

            def __getitem__(self, key):
                events.append(('getitem', key))
                return '007'

        class UnhashableName(str):
            __hash__ = None

        for name, expected in (([], '007'), ({}, '007'), (['Blockable'], '007'),
                               (UnhashableName('Blockable'), 7)):
            with self.subTest(name=name):
                events.clear()
                actual = luautil.attr_getter(Row(), name)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))
                self.assertEqual(events, [('contains', name), ('getitem', name)])
        with self.assertRaises(TypeError):
            luautil.attr_getter({}, [])

    def test_repeated_init_keeps_attribute_handlers_and_resets_runtime_state(self):
        with initialized_runtime() as (first, config):
            old_read = first.eval('function(row, key) return row[key] end')
            old_raw = {name: '31' for name, _, _ in self.integer_cases}
            old_row = as_row(first, old_raw)
            first.globals().old_row = old_row
            luautil.LUA_RUNTIME['stale'] = old_read
            luautil.LUA_SOURCE['stale'] = 'previous input'
            for base in (41, 51):
                previous = luautil.lua
                luautil.init(config)
                current = luautil.lua
                self.assertIsNot(current, previous)
                self.assertIsNone(current.globals().old_row)
                self.assertEqual(luautil.LUA_RUNTIME, {})
                self.assertEqual(luautil.LUA_SOURCE, {})
                raw = {name: str(base) for name, _, _ in self.integer_cases}
                row = as_row(current, raw)
                put_and_read = current.eval('''function(row, key, value)
                    row[key] = value
                    return row[key]
                end''')
                for name, _, _ in self.integer_cases:
                    with self.subTest(base=base, name=name):
                        self.assertEqual(put_and_read(row, name, str(base + 1)), base + 1)
                        self.assertEqual(raw[name], str(base + 1))
                        old_raw[name] = '32'
                        self.assertEqual(old_read(old_row, name), 32)


class TryGetPropTests(unittest.TestCase):
    def assert_same_number(self, actual, legacy):
        # Lua's bridge determines the Python numeric type, not the input literal.
        self.assertIs(type(actual), type(legacy))
        if math.isnan(legacy):
            self.assertTrue(math.isnan(actual))
        else:
            self.assertEqual(actual, legacy)

    def test_defaults_and_nonnumeric_values(self):
        with initialized_runtime() as (runtime, _):
            get = runtime.eval('''function(row, prop, default)
                if type(row) == 'userdata' then row = python.as_attrgetter(row) end
                return TryGetProp(row, prop, default)
            end''')
            self.assertIsNone(get(None, 'value'))
            self.assertEqual(get(None, 'value', 99), 99)
            self.assertIs(get(None, 'value', False), False)
            row = as_row(runtime, {'none': None})
            self.assertEqual(get(row, 'missing', 99), 0)
            self.assert_same_number(
                get(row, 'missing', 99),
                runtime.globals().LegacyTryGetProp(row, 'missing', 99))
            self.assertIsNone(get(row, 'none'))
            self.assertEqual(get(row, 'none', 99), 99)
            self.assertEqual(get(runtime.table(), 'missing', 99), 99)
            for value in (True, False, 'text', ''):
                actual = get(as_row(runtime, {'value': value}), 'value', 99)
                self.assertIs(type(actual), type(value))
                self.assertEqual(actual, value)
            for value in (object(), {'nested': 3}, [1, 2]):
                self.assertIs(get(as_row(runtime, {'value': value}), 'value'), value)

    def test_numeric_values_match_independent_expectations_and_legacy(self):
        cases = [
            (42, 42), ('42', 42), (1.25, 1.25), ('1.25', 1.25),
            (-7, -7), ('-7.5', -7.5), (0, 0), ('0', 0),
            (float('nan'), float('nan')), (float('inf'), float('inf')),
            (float('-inf'), float('-inf')),
            (2**52 + 1, 2**52 + 1), (str(2**52 + 1), 2**52 + 1),
        ]
        with initialized_runtime() as (runtime, _):
            for value, expected in cases:
                with self.subTest(value=value):
                    row = as_row(runtime, {'value': value})
                    actual = runtime.globals().TryGetProp(row, 'value', 99)
                    legacy = runtime.globals().LegacyTryGetProp(row, 'value', 99)
                    if math.isnan(expected):
                        self.assertTrue(math.isnan(actual))
                    else:
                        self.assertEqual(actual, expected)
                        if math.isinf(expected):
                            self.assertTrue(math.isinf(actual))
                    self.assert_same_number(actual, legacy)

    def test_precision_and_signed_zero_follow_legacy_bridge(self):
        with initialized_runtime() as (runtime, _):
            for value in (2**60 + 3, str(2**60 + 3)):
                row = as_row(runtime, {'value': value})
                self.assert_same_number(
                    runtime.globals().TryGetProp(row, 'value'),
                    runtime.globals().LegacyTryGetProp(row, 'value'))
            reciprocal = runtime.eval('''function(row)
                return 1 / TryGetProp(row, 'value'),
                       1 / LegacyTryGetProp(row, 'value')
            end''')
            for value, sign in ((0.0, 1), (-0.0, -1), ('0.0', 1), ('-0.0', -1)):
                with self.subTest(value=value):
                    row = as_row(runtime, {'value': value})
                    actual = runtime.globals().TryGetProp(row, 'value')
                    self.assertEqual(actual, 0)
                    self.assert_same_number(
                        actual, runtime.globals().LegacyTryGetProp(row, 'value'))
                    inverse, legacy_inverse = reciprocal(row)
                    self.assertTrue(math.isinf(inverse))
                    self.assertEqual(math.copysign(1, inverse), sign)
                    self.assert_same_number(inverse, legacy_inverse)

    def test_setter_and_requeries_do_not_cache_rows_or_values(self):
        with initialized_runtime() as (runtime, _):
            get = runtime.globals().TryGetProp
            put = runtime.eval('function(row, key, value) row[key] = value end')
            first_raw, second_raw = {'value': '12'}, {'value': '21'}
            first, second = as_row(runtime, first_raw), as_row(runtime, second_raw)
            self.assertEqual(get(first, 'value'), 12)
            self.assertEqual(get(second, 'value'), 21)
            put(first, 'value', '13')
            self.assertEqual(first_raw['value'], '13')
            self.assertEqual(get(first, 'value'), 13)
            self.assertEqual(get(second, 'value'), 21)
            second_raw['value'] = '22'
            self.assertEqual(get(second, 'value'), 22)
            self.assertEqual(get(first, 'value'), 13)
            put(first, 'Blockable', '7')
            self.assertEqual(first_raw['Blockable'], '7')
            self.assertIs(type(first_raw['Blockable']), str)
            self.assertEqual(runtime.eval('function(row) return row.Blockable end')(first), 7)
            self.assertIs(type(luautil.attr_getter(first_raw, 'Blockable')), int)
            actual = get(first, 'Blockable')
            self.assertEqual(actual, 7)
            self.assert_same_number(actual, runtime.globals().LegacyTryGetProp(first, 'Blockable'))
            put(first, 'Blockable', 'invalid')
            with self.assertRaises(ValueError):
                get(first, 'Blockable')

    def test_one_builtin_conversion_per_query(self):
        with initialized_runtime() as (runtime, _):
            globals_ = runtime.globals()
            builtin = globals_.tonumber
            wrapper, count, reset = runtime.eval('''function(builtin)
                local calls = 0
                return function(value)
                    calls = calls + 1
                    return builtin(value)
                end, function() return calls end, function() calls = 0 end
            end''')(builtin)
            try:
                globals_.tonumber = wrapper
                for raw, key, expected, calls in (
                    (None, 'value', 99, 0), ({'value': 8}, 'value', 8, 1),
                    ({'value': '9.5'}, 'value', 9.5, 1), ({}, 'missing', 0, 1),
                    ({'value': 'text'}, 'value', 'text', 1),
                    ({'value': None}, 'value', 99, 1),
                ):
                    reset()
                    row = None if raw is None else as_row(runtime, raw)
                    self.assertEqual(globals_.TryGetProp(row, key, 99), expected)
                    self.assertEqual(count(), calls)
            finally:
                globals_.tonumber = builtin

    def test_fresh_runtime_and_repeated_init_isolate_state(self):
        with initialized_runtime() as (first, config):
            old_get = first.globals().TryGetProp
            old_raw = {'value': '31'}
            old_row = as_row(first, old_raw)
            self.assertEqual(old_get(old_row, 'value'), 31)
            first.globals().row_marker = old_row
            first.globals().TryGetProp = first.eval('function() return -99 end')
            luautil.LUA_RUNTIME['stale'] = old_get
            luautil.LUA_SOURCE['stale'] = 'previous input'
            luautil.init(config)
            second = luautil.lua
            self.assertIsNot(first, second)
            self.assertIsNone(second.globals().row_marker)
            self.assertEqual(luautil.LUA_RUNTIME, {})
            self.assertEqual(luautil.LUA_SOURCE, {})
            self.assertEqual(second.globals().TryGetProp(as_row(second, {'value': '41'}), 'value'), 41)
            old_raw['value'] = '32'
            self.assertEqual(old_get(old_row, 'value'), 32)
        with initialized_runtime() as (fresh, _):
            self.assertIsNot(second, fresh)
            self.assertIsNone(fresh.globals().row_marker)
            self.assertEqual(fresh.globals().TryGetProp(as_row(fresh, {'value': '51'}), 'value'), 51)
