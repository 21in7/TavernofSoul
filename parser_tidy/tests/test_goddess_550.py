# -*- coding: utf-8 -*-
"""P0-9: 가디스 강화 550(accessory 전용) 구현 검증.

핵심 원칙:
- 정적 등록(EQUIPMENT_REINFORCE_IES)과 현재 지역 파일 존재(file_dict)를 분리.
- 550 material 생성과 acc 550 Lua 호출은 file_dict 게이트로 현재 지역에
  파일이 있을 때만 수행한다.
- 550은 acc만 지원(armor/weapon 키 없음).
- 상태 잔존 방지: parse_goddess_reinf/goddess_atk_list.clear(),
  parse_goddess_EQ/c.data['goddess_reinf'] 새 dict 교체.
"""
import json
import os
import sys

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_goddess_ies(path, level, acc_only=False):
    """합성 가디스 강화 IES를 30행으로 만든다.

    acc_only=True 면 550의 5열 스키마(ClassID, BasicProp, AddAccAtk,
    BasicAccAtk, ClassName)를, 아니면 540의 10열 스키마를 따른다.
    첫 행의 BasicAccAtk 만 9999로 두어 parse_goddess_reinf 연결 검증에 쓴다.
    """
    if acc_only:
        cols = ['ClassID', 'BasicProp', 'AddAccAtk', 'BasicAccAtk', 'ClassName']
    else:
        cols = ['ClassID', 'BasicProp', 'AddAtk', 'AddDef', 'AddAccAtk',
                'BasicAtk', 'BasicDef', 'BasicAccAtk', 'EvolveAtk', 'ClassName']
    lines = [','.join(cols)]
    for i in range(1, 31):
        cid = i
        basic_prop = 100000
        add_acc_atk = 803
        basic_acc_atk = 9999 if i == 1 else 0
        if acc_only:
            row = [str(cid), str(basic_prop), str(add_acc_atk),
                   str(basic_acc_atk), 'goddess_%d' % i]
        else:
            row = [str(cid), str(basic_prop), '1', '1', str(add_acc_atk),
                   '1', '1', str(basic_acc_atk), '1', 'goddess_%d' % i]
        lines.append(','.join('"{}"'.format(c) if any(ch in c for ch in ',') else c
                              for c in row))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _make_full_file_dict(base_dir, levels, acc_only_levels=()):
    """460~주어진 레벨까지의 강화 IES로 file_dict를 만든다.

    base_dir 는 실제 디렉터리. 각 레벨별 파일을 그 안에 생성한다.
    반환값: lowercase filename -> {'path','name'} dict
    """
    file_dict = {}
    for lv in levels:
        if lv == 460:
            fname = 'item_goddess_reinforce.ies'
        else:
            fname = 'item_goddess_reinforce_%d.ies' % lv
        fpath = os.path.join(str(base_dir), fname)
        with open(fpath, 'w', encoding='utf-8') as fh:
            # _write_goddess_ies 는 Path 객체를 받으므로 래핑.
            pass
        from pathlib import Path
        _write_goddess_ies(Path(fpath), lv, acc_only=(lv in acc_only_levels))
        file_dict[fname.lower()] = {'path': fpath, 'name': fname}
    return file_dict


class _FakeConstants:
    """parse_goddess_EQ / parse_goddess_reinf 에 필요한 최소 상태.

    EQUIPMENT_REINFORCE_IES 와 file_dict, data 만 있으면 된다.
    """

    def __init__(self, file_dict):
        from DB import ToS_DB
        self.EQUIPMENT_REINFORCE_IES = ToS_DB.EQUIPMENT_REINFORCE_IES
        self.file_dict = file_dict
        self.data = {}


# ---------------------------------------------------------------------------
# A. 정적 등록 확인
# ---------------------------------------------------------------------------

def test_550_registered_in_equipment_reinforce_ies():
    """EQUIPMENT_REINFORCE_IES 에 550 이 정적 등록돼 있어야 한다."""
    from DB import ToS_DB
    assert ToS_DB.EQUIPMENT_REINFORCE_IES.get(
        'item_goddess_reinforce_550.ies') == 550


# ---------------------------------------------------------------------------
# B. 파일이 있는 경우 결정적 Lua 호출 (가짜 LUA_RUNTIME 몽키패치)
# ---------------------------------------------------------------------------

def test_550_material_built_when_file_present(tmp_path, monkeypatch):
    """550 IES 가 현재 지역에 있으면 acc 550 이 호출되고 acc-only material 이 생성된다."""
    import items
    import luautil

    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict = _make_full_file_dict(tmp_path, levels, acc_only_levels=(550,))
    c = _FakeConstants(file_dict)

    called_acc_levels = []

    def fake_acc(mat, lv):
        """가짜 setting_lv_material_acc: 호출 레벨 기록 + acc[1] 에 흔적."""
        called_acc_levels.append(lv)
        mat[lv]['acc'][1]['__lv__'] = lv

    def fake_noop(*args, **kwargs):
        pass

    fake_runtime = {
        'setting_lv_material_acc': fake_acc,
        'setting_lv_material_armor': fake_noop,
        'setting_lv_material_weapon': fake_noop,
        'setting_lv460_material': fake_noop,
    }
    monkeypatch.setattr(luautil, 'LUA_RUNTIME', fake_runtime)

    items.parse_goddess_EQ(c)

    mat = c.data['goddess_reinf_mat']
    # acc 가 470/490/510/530/550 모두 호출됐는지
    assert 550 in called_acc_levels
    assert set(called_acc_levels) == {470, 490, 510, 530, 550}
    # 550 은 acc 그룹만 (armor/weapon 키 부재)
    assert set(mat[550]) == {'acc'}
    with pytest.raises(KeyError):
        mat[550]['armor']
    with pytest.raises(KeyError):
        mat[550]['weapon']
    # acc 는 1~30 단계, 가짜 함수 결과 반영
    assert set(mat[550]['acc']) == set(range(1, 31))
    assert mat[550]['acc'][1]['__lv__'] == 550
    # goddess_reinf[550] 은 합성 IES 30행
    assert len(c.data['goddess_reinf'][550]) == 30
    # 다른 레벨은 기존대로 acc/armor/weapon 모두 보유 (회귀 없음)
    assert set(mat[540]) == {'acc', 'armor', 'weapon'}


# ---------------------------------------------------------------------------
# C. Lua 함수 부재 — 독립 테스트
# ---------------------------------------------------------------------------

def test_550_no_lua_functions_safe(tmp_path, monkeypatch):
    """550 IES 는 있지만 LUA_RUNTIME 이 비어 있어도 예외 없이 완료된다.

    acc 550 은 값이 비어 있는 30단계 구조로 유지된다.
    """
    import items
    import luautil

    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict = _make_full_file_dict(tmp_path, levels, acc_only_levels=(550,))
    c = _FakeConstants(file_dict)

    monkeypatch.setattr(luautil, 'LUA_RUNTIME', {})

    # 예외 없이 완료
    items.parse_goddess_EQ(c)

    mat = c.data['goddess_reinf_mat']
    assert 550 in mat
    assert set(mat[550]) == {'acc'}
    assert set(mat[550]['acc']) == set(range(1, 31))
    # 값은 채워지지 않음
    assert mat[550]['acc'][1] == {}


# ---------------------------------------------------------------------------
# D. 파일 부재 및 stale 상태 제거
# ---------------------------------------------------------------------------

def test_550_absent_and_stale_cleared(tmp_path, monkeypatch):
    """550 이 없는 constants(twtos 시나리오)로 재실행 시 잔존값이 제거된다."""
    import items
    import luautil

    monkeypatch.setattr(luautil, 'LUA_RUNTIME', {})

    # 1) 먼저 550 있는 constants로 데이터 채우기
    levels_full = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict_full = _make_full_file_dict(tmp_path, levels_full,
                                         acc_only_levels=(550,))
    c_full = _FakeConstants(file_dict_full)
    items.parse_goddess_reinf(c_full)
    items.parse_goddess_EQ(c_full)

    # 550 채워졌음 확인
    assert 550 in items.goddess_atk_list
    assert 550 in c_full.data['goddess_reinf']
    assert 550 in c_full.data['goddess_reinf_mat']

    # 2) 550 없는 constants(twtos)로 재실행
    levels_no550 = [460, 470, 480, 490, 500, 510, 520, 530, 540]
    file_dict_no550 = _make_full_file_dict(tmp_path, levels_no550)
    c_no550 = _FakeConstants(file_dict_no550)
    items.parse_goddess_reinf(c_no550)
    items.parse_goddess_EQ(c_no550)

    # 잔존 없음: goddess_atk_list clear 로 550 제거
    assert 550 not in items.goddess_atk_list
    # 새 dict 교체로 goddess_reinf 에 550 잔존 없음
    assert 550 not in c_no550.data['goddess_reinf']
    # 게이트로 goddess_reinf_mat 에 550 생성 안 됨
    assert 550 not in c_no550.data['goddess_reinf_mat']


# ---------------------------------------------------------------------------
# E. BasicAccAtk 입력 연결
# ---------------------------------------------------------------------------

def test_550_basicaccatk_linked(tmp_path):
    """parse_goddess_reinf 후 goddess_atk_list[550]['BasicAccAtk'] 가
    합성 550 IES 첫 행 BasicAccAtk(=9999) 와 일치한다."""
    import items

    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict = _make_full_file_dict(tmp_path, levels, acc_only_levels=(550,))
    c = _FakeConstants(file_dict)

    items.parse_goddess_reinf(c)

    assert 550 in items.goddess_atk_list
    assert items.goddess_atk_list[550]['BasicAccAtk'] == '9999'


# ---------------------------------------------------------------------------
# F. 발견 파일과 출력 레벨 집합 검증
# ---------------------------------------------------------------------------

def test_goddess_reinf_levels_match_discovered_files(tmp_path, monkeypatch):
    """goddess_reinf 키 집합 == 현재 지역 file_dict 에 존재하는 강화 IES 레벨 집합."""
    import items
    import luautil
    from DB import ToS_DB

    monkeypatch.setattr(luautil, 'LUA_RUNTIME', {})

    # 550 포함
    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict = _make_full_file_dict(tmp_path, levels, acc_only_levels=(550,))
    c = _FakeConstants(file_dict)
    items.parse_goddess_EQ(c)

    expected = {
        level for filename, level in ToS_DB.EQUIPMENT_REINFORCE_IES.items()
        if filename.lower() in file_dict
    }
    assert set(c.data['goddess_reinf']) == expected
    assert 550 in expected


def test_goddess_reinf_levels_match_when_550_absent(tmp_path, monkeypatch):
    """550 파일이 없으면 goddess_reinf 에도 550 이 없고 집합이 일치한다."""
    import items
    import luautil
    from DB import ToS_DB

    monkeypatch.setattr(luautil, 'LUA_RUNTIME', {})

    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540]
    file_dict = _make_full_file_dict(tmp_path, levels)
    c = _FakeConstants(file_dict)
    items.parse_goddess_EQ(c)

    expected = {
        level for filename, level in ToS_DB.EQUIPMENT_REINFORCE_IES.items()
        if filename.lower() in file_dict
    }
    assert set(c.data['goddess_reinf']) == expected
    assert 550 not in expected


# ---------------------------------------------------------------------------
# G. JSON 왕복 및 importer 호환성
# ---------------------------------------------------------------------------

def test_goddess_reinf_mat_json_roundtrip_importer_loop(tmp_path, monkeypatch):
    """goddess_reinf_mat 을 JSON 직렬화/복원 후 importer 4중 루프 순회가
    예외 없이 가능한지. 550 acc-only 구조(키 생략)가 안전해야 한다."""
    import items
    import luautil

    def fake_acc(mat, lv):
        mat[lv]['acc'][1]['sample_coin'] = 263

    monkeypatch.setattr(luautil, 'LUA_RUNTIME', {
        'setting_lv_material_acc': fake_acc,
    })

    levels = [460, 470, 480, 490, 500, 510, 520, 530, 540, 550]
    file_dict = _make_full_file_dict(tmp_path, levels, acc_only_levels=(550,))
    c = _FakeConstants(file_dict)
    items.parse_goddess_EQ(c)

    mat = c.data['goddess_reinf_mat']
    # JSON 키는 반드시 str 이므로 int 키를 str 로 변환해 직렬화
    serializable = {str(lv): grp for lv, grp in mat.items()}
    restored = json.loads(json.dumps(serializable))

    # importer 형태의 4중 루프: 레벨 -> 장비그룹 -> 단계 -> 재료
    # 550 은 acc 만 있으므로 armor/weapon 이 없어도 예외 없이 순회해야 한다.
    touched_550 = False
    for lv_str, groups in restored.items():
        for group_name, steps in groups.items():
            for step_str, materials in steps.items():
                for mat_name, qty in materials.items():
                    # 값 접근까지 예외 없어야 함
                    assert isinstance(qty, (int, float, str))
                    if lv_str == '550':
                        touched_550 = True
    assert touched_550, '550 acc-only 그룹이 루프에 도달해야 한다'
