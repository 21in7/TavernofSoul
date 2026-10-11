"""TryGetProp compatibility using real Lua, without loading game inputs."""

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
