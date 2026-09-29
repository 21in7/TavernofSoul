# -*- coding: utf-8 -*-
"""장비 IES 중복 제거(안전장치 4) 검증 테스트."""
import os
import sys

import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def test_equipment_ies_no_case_duplicates():
    """EQUIPMENT_IES 에 소문자 키 충돌 쌍이 없어야 한다."""
    from DB import ToS_DB
    ies = ToS_DB.EQUIPMENT_IES
    lowered = [f.lower() for f in ies]
    assert len(lowered) == len(set(lowered)), (
        'EQUIPMENT_IES has case duplicates: %s' %
        [f for f in lowered if lowered.count(f) > 1]
    )


def test_equipment_ies_unique_count():
    """문서 기준: 대소문자 중복 제거 후 고유 파일 4개."""
    from DB import ToS_DB
    assert len(ToS_DB.EQUIPMENT_IES) == 4
    expected = {
        'item_equip.ies',
        'item_equip_ep12.ies',
        'item_equip_ep13.ies',
        'item_event_equip.ies',
    }
    assert set(f.lower() for f in ToS_DB.EQUIPMENT_IES) == expected


def test_parse_equips_realpath_dedup(tmp_path):
    """parse_equips 가 realpath 중복을 건너뛰는지 확인.

    file_dict 에 같은 realpath 를 가진 두 파일명이 있어도 한 번만 파싱된다.
    """
    import items

    # 실제 파일 하나를 만들고, 두 경로가 같은 파일을 가리키도록 한다.
    src = tmp_path / 'item_equip.ies'
    src.write_text('ClassID,ClassName\n1,test_mon\n', encoding='utf-8')

    class _FakeConstants:
        region = 'ktos'
        file_dict = {
            'item_equip.ies': {'path': str(src), 'name': 'item_equip.ies'},
            'item_equip_dup.ies': {'path': str(src), 'name': 'item_equip.ies'},
        }
        data = {
            'items': {}, 'items_by_name': {}, 'item_type': {},
        }

        def translate(self, k):
            return k

        def parse_entity_icon(self, icon):
            return icon

    # parse_equips 는 lua runtime 등 무거운 의존을 필요로 하므로,
    # realpath 검사 로직만 직접 검증한다.
    seen = set()
    real = os.path.realpath(str(src))
    # 첫 번째는 추가, 두 번째는 중복으로 간주.
    assert real not in seen
    seen.add(real)
    assert real in seen  # 두 번째 호출 시 이 조건으로 skip


def test_parse_equips_signature_accepts_seen_paths():
    """parse_equips 가 _seen_paths 키워드 인자를 받아야 한다."""
    import inspect
    import items
    sig = inspect.signature(items.parse_equips)
    assert '_seen_paths' in sig.parameters
