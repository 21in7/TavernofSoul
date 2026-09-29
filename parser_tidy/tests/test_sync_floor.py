# -*- coding: utf-8 -*-
"""SyncFloor 반올림 회귀 테스트.

게임 원본 `shared.ipf/script/lib_math.lua:31` 의 SyncFloor 는 반올림이다:

    function SyncFloor(value)
        value = math.floor((value*1.0)+0.5) / 1.0;
        return(value);
    end

parser_tidy 는 이 함수를 luautil.LUA_OVERRIDE 로 스텁 교체하는데(게임 원본을
로드하지 않고 override 가 이긴다 — luautil.lua_function_load 의 override 검사),
예전 스텁이 항등함수(`return item`)였다. 그 때문에
`SCR_Get_SkillFactor` 계열의 0.1 자리 반올림이 빠져, 성장계수가 누적되면서
레벨별 스킬계수(sfr)가 1 낮게 나오는 셀이 생겼다(ktos 9,071셀 중 329셀).

이 테스트는 스텁이 다시 항등함수로 되돌아가는 것을 막는다.
검증 기준값은 parser_tidy/skill_factor_report.xlsx `파서_sfr_대조` 시트와 같은
게임식 계산: floor( floor(base*10+0.5)*0.1 + floor(grow*10+0.5)*0.1*(lv-1) )
"""
import math
import os
import sys

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import luautil  # noqa: E402


# ktos skill.ies 의 SklFactor / SklFactorByLevel 원본값.
#   Swordman_Bash  : 항등 스텁이면 Lv4/Lv14 가 1 낮게 나오던 대표 케이스
#   Swordman_Thrust: 반올림 전후가 같아야 하는(회귀 없음) 대조 케이스
BASH_FACTOR = 1834.699951
BASH_FACTOR_BY_LEVEL = 688.099976
THRUST_FACTOR = 1677.900024
THRUST_FACTOR_BY_LEVEL = 252.0

# 게임 원본 calc_property_skill.lua:1536 의 본문 그대로.
SCR_GET_SKILLFACTOR = '''
    function SCR_Get_SkillFactor(skill)
        local sklFactor;
        sklFactor = SyncFloor(skill.SklFactor * 10) * 0.1
                  + SyncFloor(skill.SklFactorByLevel * 10) * 0.1 * (skill.Level - 1);
        return math.floor(sklFactor);
    end
'''


def game_skill_factor(base, grow, level):
    """엑셀 대조 시트와 동일한 게임식 계산(파이썬 구현)."""
    return math.floor(
        math.floor(base * 10 + 0.5) * 0.1
        + math.floor(grow * 10 + 0.5) * 0.1 * (level - 1)
    )


def _override_source(name):
    """LUA_OVERRIDE 에서 주어진 함수 정의 소스를 찾아 반환."""
    found = [s for s in luautil.LUA_OVERRIDE if 'function %s(' % name in s]
    assert len(found) == 1, (
        'expected exactly one %s definition in LUA_OVERRIDE, got %d'
        % (name, len(found))
    )
    return found[0]


@pytest.fixture(scope='module')
def lua():
    """LUA_OVERRIDE 의 SyncFloor 와 게임 원본 수식만 올린 독립 LUA 런타임.

    luautil 모듈 전역 런타임을 건드리지 않도록 새 런타임을 만든다.
    SyncFloor 정의는 하드코딩하지 않고 LUA_OVERRIDE 에서 가져오므로,
    스텁이 바뀌면 이 테스트가 바로 반응한다.
    """
    from lupa import LuaRuntime

    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_override_source('SyncFloor'))
    runtime.execute(SCR_GET_SKILLFACTOR)
    return runtime


class TestSyncFloorStub:
    def test_override_is_not_identity(self):
        """LUA_OVERRIDE 의 SyncFloor 가 항등함수로 되돌아가면 안 된다."""
        src = _override_source('SyncFloor')
        assert 'math.floor' in src and '0.5' in src, (
            'SyncFloor override must round (lib_math.lua:31), got:\n%s' % src
        )

    def test_inline_definition_matches(self):
        """init_global_functions 안의 SyncFloor 정의도 함께 반올림이어야 한다.

        luautil.py 에는 SyncFloor 정의가 두 곳(LUA_OVERRIDE, 그리고
        init_global_functions 의 lua 청크)에 있다. 실행 순서상 override 가
        이기지만, 두 정의가 갈라지면 이후 유지보수에서 혼선이 생긴다.
        """
        with open(os.path.join(PARENT, 'luautil.py'), encoding='utf-8') as f:
            src = f.read()
        assert 'function SyncFloor(item)' not in src, (
            'identity SyncFloor stub (`function SyncFloor(item) return item end`) '
            'must not exist in luautil.py'
        )
        assert src.count('function SyncFloor(value)') == 2, (
            'expected both SyncFloor definitions (LUA_OVERRIDE and '
            'init_global_functions) to be the rounding version'
        )

    @pytest.mark.parametrize('value,expected', [
        (0.0, 0.0),
        (3.4, 3.0),
        (3.5, 4.0),
        (3.6, 4.0),
        (-2.4, -2.0),
        # lua math.floor(-2.5+0.5) == -2 — 파이썬 round() 의 banker's rounding 과 다르다.
        (-2.5, -2.0),
        (-2.6, -3.0),
        # 실제 스킬계수 입력: base*10 / grow*10
        (BASH_FACTOR * 10, 18347.0),
        (BASH_FACTOR_BY_LEVEL * 10, 6881.0),
        (THRUST_FACTOR * 10, 16779.0),
        # lua 산술이 자동 변환하던 숫자 문자열도 동일하게 반올림된다.
        ('3.5', 4.0),
    ])
    def test_rounds_like_game(self, lua, value, expected):
        sync_floor = lua.eval('SyncFloor')
        assert sync_floor(value) == expected

    def test_non_numeric_passes_through(self, lua):
        """숫자가 아닌 입력은 예전 항등 스텁과 동일하게 통과시켜야 한다.

        게임에서는 산술 오류가 될 입력이 이 스텁 환경에는 실제로 들어온다:
        GET_TRANSCEND_MATERIAL_COUNT(item_transcend_shared.lua:275)가 가디스
        (Grade 6) 장비에서 재료 '목록 테이블'을 SyncFloor 에 넘기고,
        items.py:597~608 이 그 테이블이 그대로 돌아오는 것에 의존해
        Premium_item_transcendence_Stone 개수를 꺼낸다. 여기서 math.floor 를
        무조건 적용하면 'attempt to perform arithmetic on a table value' 로
        items.parse 전체가 죽는다.
        """
        sync_floor = lua.eval('SyncFloor')
        table = lua.eval('{Premium_item_transcendence_Stone = 7}')
        assert dict(sync_floor(table))['Premium_item_transcendence_Stone'] == 7
        assert sync_floor('None') == 'None'
        assert sync_floor(None) is None

    def test_override_guards_non_numeric(self):
        """소스 수준에서도 비숫자 가드가 남아 있어야 한다."""
        src = _override_source('SyncFloor')
        assert 'tonumber' in src, (
            'SyncFloor override must keep the non-numeric passthrough guard '
            '(goddess TranscendPrice path depends on it)'
        )


class TestSkillFactor:
    """SCR_Get_SkillFactor 가 게임과 같은 레벨별 값을 내는지."""

    def _factor(self, lua, base, grow, level):
        skill = lua.eval('{}')
        skill['SklFactor'] = base
        skill['SklFactorByLevel'] = grow
        skill['Level'] = level
        return int(lua.eval('SCR_Get_SkillFactor')(skill))

    @pytest.mark.parametrize('level,expected', [
        (1, 1834),
        # 항등 스텁에서는 3898 이 나왔다 (보고된 off-by-one 케이스).
        (4, 3899),
        # 항등 스텁에서는 10779.
        (14, 10780),
        (15, 11468),
    ])
    def test_bash_matches_game(self, lua, level, expected):
        got = self._factor(lua, BASH_FACTOR, BASH_FACTOR_BY_LEVEL, level)
        assert got == expected
        # 엑셀 대조 시트의 수식과도 일치해야 한다.
        assert got == game_skill_factor(
            BASH_FACTOR, BASH_FACTOR_BY_LEVEL, level,
        )

    @pytest.mark.parametrize('level', list(range(1, 16)))
    def test_thrust_unchanged(self, lua, level):
        """반올림 도입으로 원래 맞던 스킬이 틀어지지 않아야 한다."""
        got = self._factor(lua, THRUST_FACTOR, THRUST_FACTOR_BY_LEVEL, level)
        assert got == game_skill_factor(
            THRUST_FACTOR, THRUST_FACTOR_BY_LEVEL, level,
        )
        # Thrust 는 항등 스텁에서도 같은 값이었다: 1677 + 252*(lv-1)
        assert got == 1677 + 252 * (level - 1)

    def test_identity_stub_would_be_off_by_one(self, lua):
        """항등 스텁이 왜 틀렸는지를 고정한다 — 회귀 시 진단용.

        SyncFloor 가 항등함수면 Bash Lv4 는 3898, Lv14 는 10779 가 된다.
        """
        def identity_variant(base, grow, level):
            return math.floor(base * 10 * 0.1 + grow * 10 * 0.1 * (level - 1))

        assert identity_variant(BASH_FACTOR, BASH_FACTOR_BY_LEVEL, 4) == 3898
        assert identity_variant(BASH_FACTOR, BASH_FACTOR_BY_LEVEL, 14) == 10779
        # 현재 구현은 그 값이 아니어야 한다.
        assert self._factor(lua, BASH_FACTOR, BASH_FACTOR_BY_LEVEL, 4) == 3899
        assert self._factor(lua, BASH_FACTOR, BASH_FACTOR_BY_LEVEL, 14) == 10780
