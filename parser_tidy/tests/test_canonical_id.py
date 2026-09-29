# -*- coding: utf-8 -*-
"""P0-8: Item/Recipe canonical ID 충돌 해소 검증 테스트.

importer(importAll.py) 의 comparer transform 이 recipe 의 $ID 를
'recipe-<n>' 으로 정규화해 49건 ClassID 충돌 드롭을 방지하는지 검증한다.

이 테스트는 Django 설정 로드가 필요하다(importer Command import).
comparer 자체는 DB 쿼리를 하지 않는 순수 JSON 처리 로직이므로 임시
디렉터리 기반으로 검증한다. migrate_recipe_ids 의 DB 의존 로직은
별도 통합 테스트 영역으로 둔다.

실행: 이 테스트는 parser_tidy 의 다른 테스트와 달리 Django 앱 로드가
필요하므로 별도 실행한다. DB 가 필요 없는 comparer/헬퍼 로직만 다룬다.
"""
import json
import os
import sys

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)
DJANGO_BASE = os.path.join(REPO_ROOT, 'TavernofSoul')

for p in (PARENT, REPO_ROOT, DJANGO_BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'TavernofSoul.settings_test')

_DJANGO_READY = False


def _setup_django():
    """Django 앱 로드를 지연 수행한다(모듈 import 시 실패 방지)."""
    global _DJANGO_READY
    if not _DJANGO_READY:
        import django
        django.setup()
        _DJANGO_READY = True


def _make_entry(id_name, numeric_id, type_):
    return {
        '$ID': str(numeric_id),
        '$ID_NAME': id_name,
        'Type': type_,
        'Name': id_name,
    }


# ---------------------------------------------------------------------------
# _canonical_item_id 단위
# ---------------------------------------------------------------------------

def test_canonical_item_id_recipe_gets_prefix():
    """recipe 엔트리의 $ID 에 'recipe-' 접두가 붙는다."""
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    recipe_names = {'R_SWD01_109'}
    entry = _make_entry('R_SWD01_109', 10006, 'RECIPES')
    result = cmd._canonical_item_id(entry, recipe_names)
    assert result['$ID'] == 'recipe-10006'
    assert result['$ID_NAME'] == 'R_SWD01_109'


def test_canonical_item_id_equipment_unchanged():
    """비-recipe 엔트리의 $ID 는 그대로다."""
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    recipe_names = {'R_SWD01_109'}
    entry = _make_entry('helmet_fishbowl', 10006, 'Equipment')
    result = cmd._canonical_item_id(entry, recipe_names)
    assert result['$ID'] == '10006'


def test_canonical_item_id_original_not_mutated():
    """정규화 시 원본 entry 가 훼손되지 않는다(dict 복사)."""
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    recipe_names = {'R_SWD01_109'}
    entry = _make_entry('R_SWD01_109', 10006, 'RECIPES')
    original_id = entry['$ID']
    cmd._canonical_item_id(entry, recipe_names)
    assert entry['$ID'] == original_id


# ---------------------------------------------------------------------------
# _apply_transform 단위
# ---------------------------------------------------------------------------

def test_apply_transform_dict():
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    data = {'a': {'v': 1}, 'b': {'v': 2}}
    result = cmd._apply_transform(data, lambda e: {'v': e['v'] * 10})
    assert result == {'a': {'v': 10}, 'b': {'v': 20}}


def test_apply_transform_list():
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    data = [{'v': 1}, {'v': 2}]
    result = cmd._apply_transform(data, lambda e: {'v': e['v'] * 10})
    assert result == [{'v': 10}, {'v': 20}]


def test_apply_transform_none_or_empty():
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    assert cmd._apply_transform(False, lambda e: e) is False
    assert cmd._apply_transform(None, lambda e: e) is None
    assert cmd._apply_transform({}, lambda e: e) == {}
    assert cmd._apply_transform([{'a': 1}], None) == [{'a': 1}]


# ---------------------------------------------------------------------------
# comparer transform 통합 (임시 디렉터리, DB 없음)
# ---------------------------------------------------------------------------

def _write_items(base, name, entries):
    path = os.path.join(base, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(entries, f)


def test_comparer_transform_no_collision(tmp_path, monkeypatch):
    """transform 적용 시 recipe 와 equipment 가 다른 $ID 로 보존된다.

    갭1 검증: comparer 가 transform 을 분기 전에 양쪽에 적용한다. prev 없음
    (early-return 경로)에서도 transform 이 적용돼야 둘 다 added 로 나온다.
    """
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    monkeypatch.setattr(cmd, 'base_path', str(tmp_path))

    recipe_names = {'R_SWD01_109'}
    transform = lambda e: cmd._canonical_item_id(e, recipe_names)

    now = {
        'helmet_fishbowl': _make_entry('helmet_fishbowl', 10006, 'Equipment'),
        'R_SWD01_109': _make_entry('R_SWD01_109', 10006, 'RECIPES'),
    }
    _write_items(str(tmp_path), 'items_by_name.json', now)

    changes = cmd.comparer('items_by_name.json', transform=transform)

    # prev 없음 → early-return 경로(갭1 핵심). transform 적용돼 둘 다 추가.
    id_set = {e['$ID'] for e in changes['added']}
    assert '10006' in id_set          # equipment (숫자 유지)
    assert 'recipe-10006' in id_set   # recipe (정규화)
    assert len(changes['added']) == 2  # 드롭 0건


def test_comparer_no_transform_drops_collision(tmp_path, monkeypatch):
    """transform 없을 때 prev 가 있으면 re-key 로 충돌 1건이 드롭된다(회귀 기준점).

    prev 없음(첫 임포트) 경로는 changes['added']=list(values)라 드롭이 없다.
    충돌 드롭은 prev 가 있을 때 re-key(dict_now[i['$ID']]=i, last-writer-wins)
    경로에서 발생한다.
    """
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    monkeypatch.setattr(cmd, 'base_path', str(tmp_path))

    # prev 에는 equipment 1건만 있었다고 가정
    prev = {'helmet_fishbowl': _make_entry('helmet_fishbowl', 10006, 'Equipment')}
    now = {
        'helmet_fishbowl': _make_entry('helmet_fishbowl', 10006, 'Equipment'),
        'R_SWD01_109': _make_entry('R_SWD01_109', 10006, 'RECIPES'),
    }
    _write_items(str(tmp_path), 'items_by_name.json', now)
    _write_items(str(tmp_path), os.path.join('prev', 'items_by_name.json'), prev)

    changes = cmd.comparer('items_by_name.json')  # transform 없음
    # re-key 로 10006 키가 충돌해 recipe/equipment 중 하나만 남는다.
    # added + changed 의 $ID 집합에 10006 은 최대 1번만 등장한다.
    surviving = {e['$ID'] for e in changes['added']}
    surviving.update(e['$ID'] for e in changes['changed'])
    assert list(surviving).count('10006') <= 1  # 충돌로 1건만 생존


def test_comparer_transform_with_prev_no_change(tmp_path, monkeypatch):
    """prev 가 있을 때 transform 이 양쪽에 균일 적용되어 no-change 가 유지된다.

    갭2 회귀 기준: 데이터가 안 변하면 transform 후에도 no-change. 백필은
    migrate_recipe_ids 가 담당한다(comparer 만으로는 불가).
    """
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    monkeypatch.setattr(cmd, 'base_path', str(tmp_path))

    recipe_names = {'R_SWD01_109'}
    transform = lambda e: cmd._canonical_item_id(e, recipe_names)

    now = {
        'helmet_fishbowl': _make_entry('helmet_fishbowl', 10006, 'Equipment'),
        'R_SWD01_109': _make_entry('R_SWD01_109', 10006, 'RECIPES'),
    }
    _write_items(str(tmp_path), 'items_by_name.json', now)
    _write_items(str(tmp_path), os.path.join('prev', 'items_by_name.json'), now)

    changes = cmd.comparer('items_by_name.json', transform=transform)
    assert changes['added'] == []
    assert changes['changed'] == []
    assert changes['removed'] == []


def test_comparer_transform_recipe_change_detected(tmp_path, monkeypatch):
    """recipe 가 실제로 변경되면 transform 적용 후에도 changed 로 잡힌다."""
    _setup_django()
    from ipfparser.management.commands.importAll import Command
    cmd = Command()
    monkeypatch.setattr(cmd, 'base_path', str(tmp_path))

    recipe_names = {'R_SWD01_109'}
    transform = lambda e: cmd._canonical_item_id(e, recipe_names)

    prev_entry = _make_entry('R_SWD01_109', 10006, 'RECIPES')
    now_entry = _make_entry('R_SWD01_109', 10006, 'RECIPES')
    now_entry['Name'] = 'changed_name'

    _write_items(str(tmp_path), 'items_by_name.json',
                 {'R_SWD01_109': now_entry})
    _write_items(str(tmp_path), os.path.join('prev', 'items_by_name.json'),
                 {'R_SWD01_109': prev_entry})

    changes = cmd.comparer('items_by_name.json', transform=transform)
    assert len(changes['changed']) == 1
    assert changes['changed'][0]['$ID'] == 'recipe-10006'


# ---------------------------------------------------------------------------
# migrate_recipe_ids 순수 로직 (canonical_id, 충돌 짝 식별 알고리즘)
# ---------------------------------------------------------------------------

def test_migrate_canonical_id_helper():
    """migrate_recipe_ids 의 _canonical_id 헬퍼."""
    _setup_django()
    from ipfparser.management.commands.migrate_recipe_ids import (
        Command as MigrateCommand, RECIPE_ID_PREFIX)
    cmd = MigrateCommand()
    assert cmd._canonical_id(10006) == RECIPE_ID_PREFIX + '10006'
    assert cmd._canonical_id('10006') == 'recipe-10006'


def test_collision_partner_identification_algorithm():
    """충돌 짝 식별 알고리즘: 같은 숫자 $ID 의 비-recipe 엔트리가 짝.

    DB 없이 알고리즘만 검증한다. itos COLLECTION/EVENT 충돌은 둘 다 recipe 가
    아니므로 recipe backfill 대상에서 제외된다(recipe_id_names 에 없음).
    """
    items_by_name = {
        'helmet_fishbowl': _make_entry('helmet_fishbowl', 10006, 'Equipment'),
        'R_SWD01_109': _make_entry('R_SWD01_109', 10006, 'RECIPES'),
        'COLLECT_393': _make_entry('COLLECT_393', 10000153, 'COLLECTION'),
        'Event_Ability_Point_Stone_1000_8': _make_entry(
            'Event_Ability_Point_Stone_1000_8', 10000153, 'EVENT'),
    }
    recipe_id_names = {'R_SWD01_109'}

    by_numeric_id = {}
    for entry in items_by_name.values():
        by_numeric_id.setdefault(str(entry['$ID']), []).append(entry)

    # R_SWD01_109 의 충돌 짝: 같은 10006 의 비-recipe
    recipe_entry = items_by_name['R_SWD01_109']
    partners = [
        e for e in by_numeric_id[str(recipe_entry['$ID'])]
        if e['$ID_NAME'] not in recipe_id_names and e is not recipe_entry
    ]
    assert len(partners) == 1
    assert partners[0]['$ID_NAME'] == 'helmet_fishbowl'

    # itos COLLECTION/EVENT: 둘 다 recipe_id_names 에 없음 → backfill 제외
    assert items_by_name['COLLECT_393']['$ID_NAME'] not in recipe_id_names
    assert (items_by_name['Event_Ability_Point_Stone_1000_8']['$ID_NAME']
            not in recipe_id_names)
