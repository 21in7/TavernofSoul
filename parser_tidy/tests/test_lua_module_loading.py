"""Game Lua modules retain local state and isolate unsupported engine chunks."""
from types import SimpleNamespace

import pytest
import luautil
from harness.parser_fixture import isolated_parser_state


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
    with isolated_parser_state(), pytest.raises(ValueError, match='goddess Lua module'):
        luautil.init_runtime(SimpleNamespace(PATH_INPUT_DATA=str(tmp_path)))


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
