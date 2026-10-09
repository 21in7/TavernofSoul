# -*- coding: utf-8 -*-
"""P0-10: 드롭 provenance 검증 테스트.

검증 대상:
- drop_source.get_drop_source: 데이터셋 단위 fallback, source_region/input_version
- monsters.parse_links_items: provenance 필드, 미해결 참조 누적, 하드코딩 제거
- maps.parse_links_items: 직접 zonedrop 유실 버그 복원, 셰도잉 수정,
  provenance 필드, 미해결 참조 누적
- 파이프라인: monsters→maps 순차 unresolved 보존, DB.build() 새 객체 교체
- 하드코딩 제거: monsters/maps 에 itos_unpack 라이브 코드 0건
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

class _FakeConstants:
    """drop 소비 parser 에 필요한 최소 constants 표면."""

    def __init__(self, region, path_input_data, data=None,
                 items_by_name=None, monsters=None, maps_by_name=None):
        self.region = region
        self.PATH_INPUT_DATA = path_input_data
        self.data = data if data is not None else {}
        if items_by_name is not None:
            self.data['items_by_name'] = items_by_name
        if monsters is not None:
            self.data['monsters'] = monsters
        if maps_by_name is not None:
            self.data['maps_by_name'] = maps_by_name
        self.data.setdefault('maps', {})
        self.data.setdefault('item_type', {'RECIPES': []})


def _write_lines(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def _ies_header_row(cols, *values):
    """CSV 행 생성: 값에 쉼표가 있으면 큰따옴표로 감싼다."""
    def fmt(v):
        s = str(v)
        return '"{}"'.format(s) if ',' in s else s
    return ','.join(fmt(v) for v in values)


# ---------------------------------------------------------------------------
# A. get_drop_source 단위 테스트
# ---------------------------------------------------------------------------

def test_get_drop_source_itos_first(tmp_path):
    """iTOS ies_drop.ipf 가 있으면 iTOS 를 소스로 선택한다."""
    import drop_source
    project = tmp_path
    itos_ipf = project / 'itos_unpack' / 'ies_drop.ipf'
    itos_ipf.mkdir(parents=True)
    # revision.csv
    (project / 'downloader').mkdir(parents=True)
    (project / 'downloader' / 'revision.csv').write_text(
        'itos,405135\nktos,405134\n', encoding='utf-8')

    c = _FakeConstants('ktos', str(project / 'ktos_unpack'))
    src = drop_source.get_drop_source(c)

    assert src['drop_ipf'] == str(itos_ipf)
    assert src['source_region'] == 'itos'
    assert src['input_version'] == '405135'
    assert src['fallback_reason'] is not None  # ktos 이므로 fallback 사유 기록


def test_get_drop_source_current_region_only(tmp_path):
    """iTOS 없고 현재 지역에만 있으면 현재 지역을 소스로."""
    import drop_source
    project = tmp_path
    ktos_ipf = project / 'ktos_unpack' / 'ies_drop.ipf'
    ktos_ipf.mkdir(parents=True)

    c = _FakeConstants('ktos', str(project / 'ktos_unpack'))
    src = drop_source.get_drop_source(c)

    assert src['drop_ipf'] == str(ktos_ipf)
    assert src['source_region'] == 'ktos'
    assert src['fallback_reason'] is None


def test_get_drop_source_none(tmp_path):
    """둘 다 없으면 drop_ipf=None, 예외 없음."""
    import drop_source
    c = _FakeConstants('ktos', str(tmp_path / 'ktos_unpack'))
    src = drop_source.get_drop_source(c)
    assert src['drop_ipf'] is None
    assert src['source_region'] is None
    assert src['input_version'] is None
    assert src['fallback_reason'] is not None


def test_get_drop_source_dataset_level_no_file_fallback(tmp_path):
    """데이터셋 단위 제한: iTOS 디렉터리가 있으면 개별 파일이 현재 지역에만
    있어도 iTOS 가 선택된다(의도된 제한의 회귀 방지)."""
    import drop_source
    project = tmp_path
    # iTOS 디렉터리는 있지만 파일은 없다.
    (project / 'itos_unpack' / 'ies_drop.ipf').mkdir(parents=True)
    # 현재 지역에도 ies_drop.ipf 가 있다.
    (project / 'ktos_unpack' / 'ies_drop.ipf').mkdir(parents=True)

    c = _FakeConstants('ktos', str(project / 'ktos_unpack'))
    src = drop_source.get_drop_source(c)
    # iTOS 우선
    assert src['source_region'] == 'itos'


def test_get_drop_source_version_missing(tmp_path):
    """revision.csv 가 없으면 input_version=None, 예외 없음."""
    import drop_source
    project = tmp_path
    (project / 'itos_unpack' / 'ies_drop.ipf').mkdir(parents=True)
    c = _FakeConstants('ktos', str(project / 'ktos_unpack'))
    src = drop_source.get_drop_source(c)
    assert src['input_version'] is None


def test_get_drop_source_trailing_slash(tmp_path):
    """PATH_INPUT_DATA 에 trailing slash 가 있어도 동일 결과(normpath)."""
    import drop_source
    project = tmp_path
    (project / 'itos_unpack' / 'ies_drop.ipf').mkdir(parents=True)
    c = _FakeConstants('ktos', str(project / 'ktos_unpack') + '/')
    src = drop_source.get_drop_source(c)
    assert src['drop_ipf'] is not None


def test_get_drop_source_cwd_independent(tmp_path, monkeypatch):
    """다른 CWD 에서 호출해도 같은 결과(절대경로 기반)."""
    import drop_source
    project = tmp_path
    itos_ipf = project / 'itos_unpack' / 'ies_drop.ipf'
    itos_ipf.mkdir(parents=True)
    c = _FakeConstants('ktos', str(project / 'ktos_unpack'))

    monkeypatch.chdir('/')
    src = drop_source.get_drop_source(c)
    assert src['drop_ipf'] == str(itos_ipf)


# ---------------------------------------------------------------------------
# B. monsters provenance
# ---------------------------------------------------------------------------

def _setup_monsters_env(tmp_path, with_itos=True, version='405135'):
    project = tmp_path
    itos_ipf = project / 'itos_unpack' / 'ies_drop.ipf'
    if with_itos:
        itos_ipf.mkdir(parents=True)
    if version:
        (project / 'downloader').mkdir(parents=True, exist_ok=True)
        (project / 'downloader' / 'revision.csv').write_text(
            'itos,{}\n'.format(version), encoding='utf-8')

    items_by_name = {
        'Item_A': {'$ID': '1', 'Name': 'A'},
        'Item_B': {'$ID': '2', 'Name': 'B'},
    }
    monsters = {
        'Mon_1': {'$ID': 'M1', '$ID_NAME': 'Mon_1'},
    }
    data = {
        'item_monster': [],
        'unresolved_drops': [],
        'build_provenance': {},
    }
    c = _FakeConstants('ktos', str(project / 'ktos_unpack'), data=data,
                       items_by_name=items_by_name, monsters=monsters)
    return c, itos_ipf


def test_monsters_provenance_fields(tmp_path):
    """item_monster 레코드에 SourceRegion/InputVersion 이 있다."""
    import monsters as monsters_mod
    c, itos_ipf = _setup_monsters_env(tmp_path)
    # 몬스터 Mon_1 의 드롭 파일: Item_A(정상), Item_Unknown(미해결)
    cols = ['ItemClassName', 'DropRatio', 'Money_Max', 'Money_Min']
    rows = [_ies_header_row(cols, 'Item_A', '50', '3', '1'),
            _ies_header_row(cols, 'Item_Unknown', '10', '1', '1'),
            _ies_header_row(cols, '', '0', '0', '0')]  # 빈 이름: 정상 skip
    _write_lines(str(itos_ipf / 'Mon_1.ies'), [','.join(cols)] + rows)

    monsters_mod.parse_links_items(c)

    assert len(c.data['item_monster']) == 1
    rec = c.data['item_monster'][0]
    assert rec['Item'] == '1'
    assert rec['Monster'] == 'M1'
    assert rec['Quantity_MAX'] == 3   # 몬스터 드롭은 수량 의미 유지
    assert rec['Quantity_MIN'] == 1
    assert rec['SourceRegion'] == 'itos'
    assert rec['InputVersion'] == '405135'

    # build_provenance 기록
    prov = c.data['build_provenance']['item_monster']
    assert prov['source_region'] == 'itos'
    assert prov['input_version'] == '405135'


def test_monsters_unresolved_accumulated(tmp_path):
    """미해결 참조가 unresolved_drops 에 누적된다(몬스터 문맥 포함)."""
    import monsters as monsters_mod
    c, itos_ipf = _setup_monsters_env(tmp_path)
    cols = ['ItemClassName', 'DropRatio', 'Money_Max', 'Money_Min']
    rows = [_ies_header_row(cols, 'Item_Unknown1', '10', '1', '1'),
            _ies_header_row(cols, 'Item_Unknown2', '20', '1', '1')]
    _write_lines(str(itos_ipf / 'Mon_1.ies'), [','.join(cols)] + rows)

    monsters_mod.parse_link_items = monsters_mod.parse_links_items  # 별칭 방어
    monsters_mod.parse_links_items(c)

    unresolved = c.data['unresolved_drops']
    assert len(unresolved) == 2
    assert all(u['collection'] == 'item_monster' for u in unresolved)
    assert all(u['monster'] == 'M1' for u in unresolved)
    assert {u['item_classname'] for u in unresolved} == {
        'Item_Unknown1', 'Item_Unknown2'}
    assert all(u['source_region'] == 'itos' for u in unresolved)


def test_monsters_no_drop_source_noop(tmp_path):
    """드롭 소스가 전무하면 경고 후 no-op(예외 없음, 레코드 0)."""
    import monsters as monsters_mod
    c, _ = _setup_monsters_env(tmp_path, with_itos=False)
    monsters_mod.parse_links_items(c)
    assert c.data['item_monster'] == []
    assert c.data['unresolved_drops'] == []


# ---------------------------------------------------------------------------
# C. maps provenance + 복원 버그
# ---------------------------------------------------------------------------

def _setup_maps_env(tmp_path, with_itos=True, version='405135'):
    project = tmp_path
    itos_ipf = project / 'itos_unpack' / 'ies_drop.ipf'
    if with_itos:
        (itos_ipf / 'zonedrop').mkdir(parents=True)
        (itos_ipf / 'dropgroup').mkdir(parents=True)
    if version:
        (project / 'downloader').mkdir(parents=True, exist_ok=True)
        (project / 'downloader' / 'revision.csv').write_text(
            'itos,{}\n'.format(version), encoding='utf-8')

    items_by_name = {
        'Item_A': {'$ID': '1', 'Name': 'A'},
        'Item_B': {'$ID': '2', 'Name': 'B'},
    }
    # map dict 의 값 객체
    map_obj = {'$ID': 'MAP1', '$ID_NAME': 'c_Klaipe'}
    maps = {'c_Klaipe': map_obj}
    maps_by_name = {'c_Klaipe': map_obj}
    data = {
        'map_item': [],
        'unresolved_drops': [],
        'build_provenance': {},
    }
    c = _FakeConstants('ktos', str(project / 'ktos_unpack'), data=data,
                       items_by_name=items_by_name, maps_by_name=maps_by_name)
    c.data['maps'] = maps
    return c, itos_ipf


def test_maps_direct_drop_restored(tmp_path):
    """직접 zonedrop 아이템이 map_item 에 생성된다(유실 버그 회귀 방지).

    과거: drops 에 Money_* 키가 없어 레코드 생성 시 KeyError → bare except 흡수.
    현재: Quantity_MAX/MIN == 0(수량 미제공 호환값)으로 생성.
    """
    import maps as maps_mod
    c, itos_ipf = _setup_maps_env(tmp_path)

    cols = ['ItemClassName', 'DropRatio', 'DropGroup', 'Money_Max', 'Money_Min']
    rows = [_ies_header_row(cols, 'Item_A', '50', '', '999', '888')]
    _write_lines(str(itos_ipf / 'zonedrop' / 'ZoneDropItemList_c_Klaipe.ies'),
                 [','.join(cols)] + rows)

    maps_mod.parse_links_items(c)

    assert len(c.data['map_item']) == 1
    rec = c.data['map_item'][0]
    assert rec['Item'] == '1'
    assert rec['Map'] == 'MAP1'
    assert rec['Quantity_MAX'] == 0  # 수량 미제공 호환값 (실버 필드 해석 안 함)
    assert rec['Quantity_MIN'] == 0
    assert rec['SourceRegion'] == 'itos'
    assert rec['InputVersion'] == '405135'


def test_maps_dropgroup_restored(tmp_path):
    """dropgroup 유래 아이템도 map_item 에 생성, Quantity 0."""
    import maps as maps_mod
    c, itos_ipf = _setup_maps_env(tmp_path)

    zone_cols = ['ItemClassName', 'DropRatio', 'DropGroup']
    zone_rows = [_ies_header_row(zone_cols, '', '100', 'Group_X')]
    _write_lines(str(itos_ipf / 'zonedrop' / 'ZoneDropItemList_c_Klaipe.ies'),
                 [','.join(zone_cols)] + zone_rows)

    grp_cols = ['ItemClassName', 'DropRatio']
    grp_rows = [_ies_header_row(grp_cols, 'Item_A', '60'),
                _ies_header_row(grp_cols, 'Item_B', '40')]
    _write_lines(str(itos_ipf / 'dropgroup' / 'Group_X.ies'),
                 [','.join(grp_cols)] + grp_rows)

    maps_mod.parse_links_items(c)

    items = sorted(rec['Item'] for rec in c.data['map_item'])
    assert items == ['1', '2']
    for rec in c.data['map_item']:
        assert rec['Quantity_MAX'] == 0
        assert rec['Quantity_MIN'] == 0


def test_maps_dropgroup_zero_sum_skip(tmp_path):
    """dropgroup 합계 0이면 예외 없이 skip(과거 ZeroDivisionError 사망 경로)."""
    import maps as maps_mod
    c, itos_ipf = _setup_maps_env(tmp_path)

    zone_cols = ['ItemClassName', 'DropRatio', 'DropGroup']
    zone_rows = [_ies_header_row(zone_cols, '', '100', 'Group_Zero')]
    _write_lines(str(itos_ipf / 'zonedrop' / 'ZoneDropItemList_c_Klaipe.ies'),
                 [','.join(zone_cols)] + zone_rows)

    grp_cols = ['ItemClassName', 'DropRatio']
    grp_rows = [_ies_header_row(grp_cols, 'Item_A', '0')]
    _write_lines(str(itos_ipf / 'dropgroup' / 'Group_Zero.ies'),
                 [','.join(grp_cols)] + grp_rows)

    # 예외 없이 완료
    maps_mod.parse_links_items(c)
    assert c.data['map_item'] == []


def test_maps_f_variant_uses_source(tmp_path):
    """zonedropitemlist_f_ 변형도 소스 drop_ipf 기준으로 해결된다."""
    import maps as maps_mod
    c, itos_ipf = _setup_maps_env(tmp_path)

    # f_ 변형만 존재
    cols = ['ItemClassName', 'DropRatio', 'DropGroup']
    rows = [_ies_header_row(cols, 'Item_A', '30', '')]
    _write_lines(str(itos_ipf / 'zonedrop' / 'zonedropitemlist_f_c_Klaipe.ies'),
                 [','.join(cols)] + rows)

    maps_mod.parse_links_items(c)
    assert len(c.data['map_item']) == 1
    assert c.data['map_item'][0]['Item'] == '1'


def test_maps_unresolved_accumulated(tmp_path):
    """maps 미해결 참조가 unresolved_drops 에 누적(map 문맥 포함)."""
    import maps as maps_mod
    c, itos_ipf = _setup_maps_env(tmp_path)

    cols = ['ItemClassName', 'DropRatio', 'DropGroup']
    rows = [_ies_header_row(cols, 'Item_Ghost', '30', '')]
    _write_lines(str(itos_ipf / 'zonedrop' / 'ZoneDropItemList_c_Klaipe.ies'),
                 [','.join(cols)] + rows)

    maps_mod.parse_links_items(c)
    unresolved = c.data['unresolved_drops']
    assert len(unresolved) == 1
    assert unresolved[0]['collection'] == 'map_item'
    assert unresolved[0]['map'] == 'MAP1'
    assert unresolved[0]['map_name'] == 'c_Klaipe'
    assert unresolved[0]['item_classname'] == 'Item_Ghost'


# ---------------------------------------------------------------------------
# D. 파이프라인 수준
# ---------------------------------------------------------------------------

def test_pipeline_unresolved_preserved_across_monsters_maps(tmp_path):
    """monsters → maps 순차 호출 시 양쪽 unresolved 가 모두 보존된다."""
    import monsters as monsters_mod
    import maps as maps_mod

    project = tmp_path
    itos_ipf = project / 'itos_unpack' / 'ies_drop.ipf'
    (itos_ipf).mkdir(parents=True)
    (itos_ipf / 'zonedrop').mkdir(parents=True)

    items_by_name = {'Item_A': {'$ID': '1', 'Name': 'A'}}
    monsters = {'Mon_1': {'$ID': 'M1', '$ID_NAME': 'Mon_1'}}
    map_obj = {'$ID': 'MAP1', '$ID_NAME': 'c_Klaipe'}
    maps = {'c_Klaipe': map_obj}

    # 공유 data (리셋 규칙 검증: 한쪽이 리셋하지 않는다)
    shared_data = {
        'item_monster': [],
        'map_item': [],
        'unresolved_drops': [],
        'build_provenance': {},
    }
    c = _FakeConstants('ktos', str(project / 'ktos_unpack'), data=shared_data,
                       items_by_name=items_by_name, monsters=monsters,
                       maps_by_name={'c_Klaipe': map_obj})
    c.data['maps'] = maps

    # 몬스터 드롭: 미해결 1건
    mcols = ['ItemClassName', 'DropRatio', 'Money_Max', 'Money_Min']
    _write_lines(str(itos_ipf / 'Mon_1.ies'),
                 [','.join(mcols), _ies_header_row(mcols, 'Mon_Ghost', '10', '1', '1')])
    monsters_mod.parse_links_items(c)
    assert len(c.data['unresolved_drops']) == 1

    # 맵 드롭: 미해결 1건
    zcols = ['ItemClassName', 'DropRatio', 'DropGroup']
    _write_lines(str(itos_ipf / 'zonedrop' / 'ZoneDropItemList_c_Klaipe.ies'),
                 [','.join(zcols), _ies_header_row(zcols, 'Map_Ghost', '30', '')])
    maps_mod.parse_links_items(c)

    # 양쪽 모두 보존
    assert len(c.data['unresolved_drops']) == 2
    collections = {u['collection'] for u in c.data['unresolved_drops']}
    assert collections == {'item_monster', 'map_item'}


def test_db_data_has_new_collection_keys():
    """DB.data 클래스 속성에 두 신규 키가 선언돼 있다."""
    from DB import ToS_DB
    assert 'unresolved_drops' in ToS_DB.data
    assert 'build_provenance' in ToS_DB.data
    assert ToS_DB.data['unresolved_drops'] == []
    assert ToS_DB.data['build_provenance'] == {}


def test_db_build_resets_provenance_collections(tmp_path):
    """DB 인스턴스의 build() 호출 후 unresolved_drops/build_provenance 가
    빈 새 객체로 교체된다(클래스 수준 mutable 공유 방지).

    build() 는 directoryDictionary/importJSON 등 부작용이 많으므로, 필요한
    입력 디렉터리만 최소 구성하고 data 교체 결과만 검증한다.
    """
    from DB import ToS_DB
    c = ToS_DB()
    # 이전 상태 시뮬레이션
    c.data['unresolved_drops'] = [{'stale': True}]
    c.data['build_provenance'] = {'stale': True}

    # build() 는 PATH_INPUT_DATA 디렉터리를 순회한다. 빈 디렉터리면 OK.
    project = tmp_path
    (project / 'ktos_unpack').mkdir(parents=True)
    c.build('ktos', str(project / 'parser_tidy'))

    # 새 객체로 교체
    assert c.data['unresolved_drops'] == []
    assert c.data['build_provenance'] == {}


# ---------------------------------------------------------------------------
# E. 하드코딩 제거 확인
# ---------------------------------------------------------------------------

def test_no_hardcoded_itos_unpack_in_parsers():
    """monsters.py 와 maps.py 에 itos_unpack 라이브 코드가 없어야 한다."""
    for fname in ('monsters.py', 'maps.py'):
        path = os.path.join(PARENT, fname)
        with open(path, encoding='utf-8') as fh:
            for lineno, line in enumerate(fh, 1):
                stripped = line.lstrip()
                if stripped.startswith('#'):
                    continue
                assert 'itos_unpack' not in line, (
                    '{}:{} still references itos_unpack: {}'.format(
                        fname, lineno, line))
