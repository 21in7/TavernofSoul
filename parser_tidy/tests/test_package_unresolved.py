# -*- coding: utf-8 -*-
"""패키지 미해결(unresolved) 참조 분리 회귀 테스트.

PROFILING_REVIEW.md: 만료 이벤트 Item 참조 2건
(Event_misc_reinforce_percentUp_470_NoTrade_limit) 은 원본 Item 정의가 없다.
이전 구현은 이를 name=None 인 성공 항목으로 남겨 미해결 참조를 정상으로
위장했다. 새 구현은:

- items_by_name 에 존재하는 참조만 PackageContents.items 의 정상 항목.
- 존재하지 않는 참조는 원문(item/count/options)을 보존해
  PackageContents.unresolved 로 분리.
- 가짜 fallback item 은 생성하지 않는다.
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import csv
import glob

import pytest


class _FakeConstants:
    """resolve_package_contents 에 필요한 최소 constants 표면.

    items.py 의 resolve_package_contents 는 constants.data['items'] 와
    constants.data['items_by_name'] 만 읽는다.
    """

    def __init__(self, items_by_name):
        # items dict 는 값 객체를 공유해야 pop/slice 가 items_by_name 에도 반영된다.
        self.data = {
            'items': dict(items_by_name),
            'items_by_name': items_by_name,
        }


def _make_obj(class_name, script, string_arg, number_arg1=''):
    obj = {
        '$ID': class_name,
        '$ID_NAME': class_name,
        'Name': class_name,
        'PackageContents_Raw': (script, string_arg, number_arg1),
    }
    return obj


class TestUnresolvedSeparation:
    """resolve_package_contents 의 unresolved 분리 동작을 검증."""

    def test_existing_reference_goes_to_items(self):
        import items
        target = _make_obj(
            'pkg_normal', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'misc_ore23/5',
        )
        # 참조 대상 아이템이 items_by_name 에 존재.
        ref_item = {'$ID': '9001', '$ID_NAME': 'misc_ore23', 'Name': 'Ore'}
        by_name = {
            'misc_ore23': ref_item,
            'pkg_normal': target,
        }
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        pc = target['PackageContents']
        assert pc['items'] == [{
            'item': 'misc_ore23', 'name': 'Ore', 'count': 5, 'options': [],
        }]
        assert 'unresolved' not in pc

    def test_missing_reference_goes_to_unresolved(self):
        import items
        target = _make_obj(
            'pkg_expired', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'Event_misc_reinforce_percentUp_470_NoTrade_limit/1',
        )
        # 참조 대상 아이템이 items_by_name 에 없다(만료 이벤트).
        by_name = {'pkg_expired': target}
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        pc = target['PackageContents']
        # items 에는 정상 항목이 없다.
        assert pc['items'] == []
        # unresolved 에 원문이 보존된다.
        assert pc['unresolved'] == [{
            'item': 'Event_misc_reinforce_percentUp_470_NoTrade_limit',
            'count': 1,
            'options': [],
        }]

    def test_missing_reference_preserves_options(self):
        """unresolved 항목은 item/count 뿐 아니라 options 도 보존한다."""
        import items
        target = _make_obj(
            'pkg_expired_opt', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'Event_misc_reinforce_percentUp_470_NoTrade_limit/1/Reinforce_2/7',
        )
        by_name = {'pkg_expired_opt': target}
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        pc = target['PackageContents']
        assert pc['items'] == []
        assert len(pc['unresolved']) == 1
        u = pc['unresolved'][0]
        assert u['item'] == 'Event_misc_reinforce_percentUp_470_NoTrade_limit'
        assert u['count'] == 1
        assert ('Reinforce_2', '7') in u['options']

    def test_mixed_references_split_correctly(self):
        """정상 참조와 미해결 참조가 같은 패키지에 섞여 있을 때 분리."""
        import items
        target = _make_obj(
            'pkg_mixed', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'misc_ore23/5;Event_misc_reinforce_percentUp_470_NoTrade_limit/1',
        )
        ref_item = {'$ID': '9001', '$ID_NAME': 'misc_ore23', 'Name': 'Ore'}
        by_name = {'misc_ore23': ref_item, 'pkg_mixed': target}
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        pc = target['PackageContents']
        assert len(pc['items']) == 1
        assert pc['items'][0]['item'] == 'misc_ore23'
        assert len(pc['unresolved']) == 1
        assert pc['unresolved'][0]['item'] == \
            'Event_misc_reinforce_percentUp_470_NoTrade_limit'

    def test_no_fallback_item_created(self):
        """미해결 참조에 대해 가짜 fallback item 이 생성되지 않아야 한다.

        이전 구현은 items_by_name 에 없는 참조를 name=None 성공 항목으로
        남겼다. 새 구현은 fallback 을 만들지 않고 unresolved 로 보낸다.
        """
        import items
        target = _make_obj(
            'pkg_no_fallback', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'DoesNotExistItem/3',
        )
        by_name = {'pkg_no_fallback': target}
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        # items_by_name 에 새 항목이 추가되지 않았는지 확인.
        assert 'DoesNotExistItem' not in c.data['items_by_name']
        # items dict 에도 새 항목이 없어야 한다.
        assert all(
            v.get('$ID_NAME') != 'DoesNotExistItem'
            for v in c.data['items'].values()
        )

    def test_unresolved_does_not_block_package_creation(self):
        """unresolved 만 있고 정상 items 가 없어도 PackageContents 는 생성된다.

        단, resolved 카운트에는 포함되지 않는다(items 또는 alternatives 가
        있어야 resolved). 하지만 PackageContents.unresolved 자체는 보존되어야
        한다(나중에 원본 복구 시 참조 가능).
        """
        import items
        target = _make_obj(
            'pkg_only_unresolved', 'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT',
            'Event_misc_reinforce_percentUp_470_NoTrade_limit/1',
        )
        by_name = {'pkg_only_unresolved': target}
        c = _FakeConstants(by_name)
        items.resolve_package_contents(c)
        # PackageContents 는 존재해야 한다.
        assert 'PackageContents' in target
        assert target['PackageContents']['unresolved']
        assert target['PackageContents']['items'] == []


# ---------------------------------------------------------------------------
# 실제 ktos 원본 통합 테스트: 만료 이벤트 참조 2건이 unresolved 로 집계
# ---------------------------------------------------------------------------

KTOS_IES = os.path.join(PARENT, '..', 'ktos_unpack', 'ies.ipf')
# 만료 이벤트 Item 참조. PROFILING_REVIEW.md 에 명시된 2건.
EXPIRED_EVENT_ITEM = 'Event_misc_reinforce_percentUp_470_NoTrade_limit'


def _collect_ktos_package_raw():
    """ktos 원본 item*.ies 에서 PackageContents_Raw 후보를 수집."""
    raw = []
    if not os.path.isdir(KTOS_IES):
        pytest.skip('ktos_unpack ies.ipf not available')
    candidates = sorted(glob.glob(os.path.join(KTOS_IES, 'item*.ies')))
    for path in candidates:
        try:
            with open(path, encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=',', quotechar='"')
                for row in reader:
                    s = (row.get('Script') or '').strip()
                    sa = (row.get('StringArg') or '').strip()
                    if s.startswith('SCR_USE_STRING') and sa:
                        raw.append((row.get('ClassName'), s, sa,
                                   (row.get('NumberArg1') or '').strip()))
        except (FileNotFoundError, KeyError):
            continue
    return raw


class TestKtosUnresolvedIntegration:
    def test_expired_event_item_not_in_any_item_definition(self):
        """만료 이벤트 Item 이 실제로 item 정의에 존재하지 않는지 확인.

        이것이 unresolved 분리의 전제 조건이다.
        """
        if not os.path.isdir(KTOS_IES):
            pytest.skip('ktos_unpack ies.ipf not available')
        # 모든 item*.ies 의 ClassName 집합을 수집.
        all_classnames = set()
        for path in sorted(glob.glob(os.path.join(KTOS_IES, 'item*.ies'))):
            try:
                with open(path, encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter=',', quotechar='"')
                    for row in reader:
                        cn = row.get('ClassName')
                        if cn:
                            all_classnames.add(cn)
            except (FileNotFoundError, KeyError):
                continue
        assert EXPIRED_EVENT_ITEM not in all_classnames, (
            '만료 이벤트 Item %s 이 정의에 존재하면 unresolved 분리 전제가 깨짐'
            % EXPIRED_EVENT_ITEM
        )

    def test_expired_event_references_parsed_as_two_entries(self):
        """ktos 원본에서 만료 이벤트 Item 참조가 2건 파싱되는지 확인.

        PROFILING_REVIEW.md: '직접 Item 참조 중 Event_misc_reinforce_percentUp_470_NoTrade_limit 2건'
        """
        from package_parser import parse_package_stringarg
        raw = _collect_ktos_package_raw()
        if not raw:
            pytest.skip('no package raw data found')
        expired_refs = 0
        for cn, script, sa, na1 in raw:
            r = parse_package_stringarg(script, sa, na1)
            for it in r['items']:
                if it['item'] == EXPIRED_EVENT_ITEM:
                    expired_refs += 1
            for alt in r['alternatives']:
                for it in alt:
                    if it['item'] == EXPIRED_EVENT_ITEM:
                        expired_refs += 1
        assert expired_refs == 2, (
            '만료 이벤트 Item 참조는 2건이어야 함(현재 %d건)' % expired_refs
        )
