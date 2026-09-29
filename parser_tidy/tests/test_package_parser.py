# -*- coding: utf-8 -*-
"""패키지 토큰 파서 단위 테스트.

이 테스트는 PROFILING_REVIEW.md 의 패키지 오해석(259개 잘못된 참조) 기준선을
검증한다. 이전 rpartition('/') 구현은 통과하지 못해야 하고, 새 item/count/
(prop/value)* 구현은 통과해야 한다.
"""
import os
import sys

# 테스트 대상 모듈을 import 가능하게 parser_tidy 를 경로에 추가.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import pytest

from package_parser import (
    parse_split_token,
    parse_multiple_token,
    parse_package_stringarg,
    is_growth_script,
    is_package_script,
    GROWTH_SCRIPTS,
)


# ---------------------------------------------------------------------------
# parse_split_token — 핵심 수정 대상
# ---------------------------------------------------------------------------

class TestSplitToken:
    def test_simple_item_count(self):
        cn, count, opts = parse_split_token('misc_Brikynite/32')
        assert cn == 'misc_Brikynite'
        assert count == 32
        assert opts == []

    def test_item_count_with_one_option_pair(self):
        """Legendcard_Leticia/5/ItemExp/60 — 이전 구현의 대표 오류 사례."""
        cn, count, opts = parse_split_token('Legendcard_Leticia/5/ItemExp/60')
        assert cn == 'Legendcard_Leticia'
        assert count == 5
        assert opts == [('ItemExp', '60')]

    def test_item_count_with_two_option_pairs(self):
        """EP13_RAID_PLATE_TOP/1/Transcend/10/Reinforce_2/7."""
        cn, count, opts = parse_split_token('EP13_RAID_PLATE_TOP/1/Transcend/10/Reinforce_2/7')
        assert cn == 'EP13_RAID_PLATE_TOP'
        assert count == 1
        assert opts == [('Transcend', '10'), ('Reinforce_2', '7')]

    def test_leading_slash_normalized(self):
        """/Multiple_Token_X/10 — 선행 슬래시 정규화."""
        cn, count, opts = parse_split_token('/Multiple_Token_TurbulentCore_Auto_NoTrade/10')
        assert cn == 'Multiple_Token_TurbulentCore_Auto_NoTrade'
        assert count == 10

    def test_empty_token(self):
        assert parse_split_token('') == (None, 0, [])
        assert parse_split_token('   ') == (None, 0, [])

    def test_no_slash(self):
        # 단일 ClassName 만 있으면 SPLIT 토큰으로서는 파싱 불가.
        assert parse_split_token('JustClassName') == (None, 0, [])

    def test_non_numeric_count(self):
        cn, count, opts = parse_split_token('item/abc')
        assert cn is None
        assert count == 0


# ---------------------------------------------------------------------------
# parse_multiple_token — RANDOM_MUTIPLE 계열
# ---------------------------------------------------------------------------

class TestMultipleToken:
    def test_single_alternative_group(self):
        # "item/count*item/count"
        alts = parse_multiple_token('EP12_TOP04_001/1*EP12_LEG04_001/1')
        assert len(alts) == 2
        assert alts[0][0] == 'EP12_TOP04_001'
        assert alts[0][1] == 1
        assert alts[1][0] == 'EP12_LEG04_001'

    def test_invalid_piece_rejects_whole_group(self):
        alts = parse_multiple_token('validitem/1*badpiece')
        assert alts == []


# ---------------------------------------------------------------------------
# parse_package_stringarg — Script별 라우팅
# ---------------------------------------------------------------------------

class TestPackageStringarg:
    def test_give_item_single(self):
        r = parse_package_stringarg('SCR_USE_STRING_GIVE_ITEM', 'Seal_Boruta_Sword')
        assert r['kind'] == 'fixed'
        assert len(r['items']) == 1
        assert r['items'][0]['item'] == 'Seal_Boruta_Sword'
        assert r['items'][0]['count'] == 1

    def test_give_item_number(self):
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER', 'misc_ore23', '5'
        )
        assert r['items'][0]['item'] == 'misc_ore23'
        assert r['items'][0]['count'] == 5

    def test_give_item_number_invalid_count(self):
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER', 'misc_ore23', ''
        )
        assert r['items'] == []
        assert r['warnings']

    def test_number_split_multiple_tokens(self):
        sa = 'Helmet_xmastreecos/1;costume_Com_273/1;'
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT', sa
        )
        assert r['kind'] == 'fixed'
        assert len(r['items']) == 2
        assert r['items'][0]['item'] == 'Helmet_xmastreecos'
        assert r['items'][1]['item'] == 'costume_Com_273'

    def test_number_split_with_instance_option(self):
        """Leticia_Card_Lv7_2401: Legendcard_Leticia/1/ItemExp/550."""
        sa = 'Legendcard_Leticia/1/ItemExp/550;'
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_NOTRADE', sa
        )
        assert len(r['items']) == 1
        it = r['items'][0]
        assert it['item'] == 'Legendcard_Leticia'
        assert it['count'] == 1
        assert it['options'] == [('ItemExp', '550')]

    def test_number_split_opt_with_two_option_pairs(self):
        """Epo_Disnai: item/1/Reinforce_2/8/Transcend/3."""
        sa = 'Episode12_EP12_FIELD_TOP_002/1/Reinforce_2/8/Transcend/3;'
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_OPT', sa
        )
        it = r['items'][0]
        assert it['item'] == 'Episode12_EP12_FIELD_TOP_002'
        assert it['count'] == 1
        assert ('Reinforce_2', '8') in it['options']
        assert ('Transcend', '3') in it['options']

    def test_random_multiple(self):
        sa = 'EP12_TOP04_001/1*EP12_LEG04_001/1*EP12_HAND04_001/1;EP12_TOP04_002/1*EP12_LEG04_002/1;'
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_ITEM_NUMBER_SPLIT', sa
        )
        assert r['kind'] == 'multiple'
        assert r['random'] is True
        assert len(r['alternatives']) == 2
        assert len(r['alternatives'][0]) == 3
        # multiple 계열은 items 가 비어 있고 alternatives 만 있다.
        # resolver 가 entries 뿐 아니라 alternatives 도 검사해야 한다.
        assert r['items'] == []

    def test_random_split_marked_random(self):
        sa = 'TSW02_101_16/1;TSW02_102_16/1;'
        r = parse_package_stringarg(
            'SCR_USE_STRING_RANDOM_GIVE_ITEM_NUMBER_SPLIT', sa
        )
        assert r['kind'] == 'random'
        assert r['random'] is True

    def test_growth_script_not_interpreted(self):
        """GROWTH 6건은 미해석 범주로 보고, items 를 만들지 않는다."""
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH', 'Melee'
        )
        assert r['kind'] == 'growth_selection'
        assert r['items'] == []
        assert r['warnings']  # 보고 포함

    def test_growth_other_scripts(self):
        assert is_growth_script('SCR_USE_GLOBAL_1911_GROWTH_PACKAGE')
        assert is_growth_script('SCR_USE_GROWTH_REINFORCE_TIER3_set')
        assert not is_growth_script('SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT')

    def test_leading_slash_token_recovered(self):
        """JPN_2212package_Reward 의 '/Multiple_Token_.../10' 정규화."""
        sa = ('EP12_EXPERT_MODE_MULTIPLE_NoTrade/10;'
              '/Multiple_Token_TurbulentCore_Auto_NoTrade/10')
        r = parse_package_stringarg(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT', sa
        )
        names = [it['item'] for it in r['items']]
        assert 'Multiple_Token_TurbulentCore_Auto_NoTrade' in names
        assert all('/' not in n for n in names), names

    def test_account_prop_not_interpreted_as_item(self):
        """P1 회귀: SET_ACCOUNT_PROP 의 StringArg 는 account.ies 의 계정
        속성명이지 Item ClassName 이 아니다. 구성물을 생성하면 안 된다.

        이전 구현은 EVENT_FIELD_BOSS_10TH 를 아이템 1개로 변환해
        portion_reset_10th_boss_loot 에 잘못된 PackageContents 를 만들었다.
        """
        r = parse_package_stringarg(
            'SCR_USE_STRING_SET_ACCOUNT_PROP', 'EVENT_FIELD_BOSS_10TH/None'
        )
        assert r['kind'] == 'account_prop'
        assert r['items'] == []
        assert r['alternatives'] == []
        assert not r['random']
        assert r['warnings'], 'account_prop must be reported'


# ---------------------------------------------------------------------------
# is_package_script — 수집 조건 (P1 회귀: MUTIPLE 누락)
# ---------------------------------------------------------------------------

class TestIsPackageScript:
    def test_give_item(self):
        assert is_package_script('SCR_USE_STRING_GIVE_ITEM')

    def test_number_split(self):
        assert is_package_script('SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT')

    def test_random_give_item(self):
        assert is_package_script('SCR_USE_STRING_RANDOM_GIVE_ITEM_NUMBER_SPLIT')

    def test_give_random_multiple(self):
        """P1 회귀: MUTIPLE 계열이 수집 조건에서 누락되지 않아야 한다."""
        assert is_package_script(
            'SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_ITEM_NUMBER_SPLIT'
        )

    def test_growth_is_package(self):
        # GROWTH 도 패키지 스크립트(미해석 보고 대상).
        assert is_package_script(
            'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH'
        )

    def test_non_package_script(self):
        assert not is_package_script('SCR_GET_MON_EXP')
        assert not is_package_script('')
        assert not is_package_script('SCR_USE_GLOBAL_1911_GROWTH_PACKAGE')
        assert not is_package_script('SCR_REFRESH_WEAPON')


# ---------------------------------------------------------------------------
# resolve_package_contents — multiple(alternatives) 결과 생성 회귀
# ---------------------------------------------------------------------------

class TestResolveMultiple:
    """P1 회귀: RANDOM_MUTIPLE 패키지가 alternatives-only 일 때 결과 누락.

    resolver 가 entries 가 아닌 alternatives 만 있어도 PackageContents 를
    생성하는지 검증한다. 실제 items.py 의 resolve_package_contents 는
    constants 의존이 있어 여기서는 모듈 소스 검증 + parse 결과로 대체한다.
    """

    def test_resolver_source_checks_alternatives(self):
        """items.py 소스가 entries 또는 alternatives 조건을 사용하는지 확인."""
        src_path = os.path.join(PARENT, 'items.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        # 이전 버그: 'if entries:' 만 검사.
        assert 'if entries or alternatives:' in src, (
            'resolve_package_contents must check entries OR alternatives '
            '(multiple packages have alternatives only)'
        )

    def test_resolver_skips_account_prop(self):
        """items.py 가 account_prop 범주를 구성물 미생성으로 처리하는지 확인."""
        src_path = os.path.join(PARENT, 'items.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        assert "parsed['kind'] == 'account_prop'" in src, (
            'resolve_package_contents must skip account_prop packages '
            '(SET_ACCOUNT_PROP StringArg is an account property, not an item)'
        )

    def test_collection_uses_is_package_script(self):
        """items.py 수집 조건이 is_package_script 를 사용하는지 확인."""
        src_path = os.path.join(PARENT, 'items.py')
        with open(src_path, encoding='utf-8') as f:
            src = f.read()
        assert 'package_parser.is_package_script(script)' in src
        # 이전 접두사 하드코딩이 제거됐는지.
        assert "startswith(('SCR_USE_STRING_GIVE_ITEM'" not in src


# ---------------------------------------------------------------------------
# 회귀: 실제 ktos 원본의 잘못된 참조가 0개가 되는지 확인 (원본 의존)
# ---------------------------------------------------------------------------

KTOS_IES = os.path.join(
    PARENT, '..', 'ktos_unpack', 'ies.ipf'
)


def _collect_ktos_package_raw():
    """ktos 원본 item*.ies 에서 PackageContents_Raw 후보를 수집."""
    import csv
    import glob
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


class TestKtosRegression:
    def test_no_misinterpreted_item_names(self):
        """모든 파싱 결과의 item 이름에 '/'가 포함되면 안 된다.

        이전 rpartition 구현은 259개의 잘못된 참조를 만들었다.
        """
        raw = _collect_ktos_package_raw()
        if not raw:
            pytest.skip('no package raw data found')
        bad = []
        growth_count = 0
        for cn, script, sa, na1 in raw:
            r = parse_package_stringarg(script, sa, na1)
            if r['kind'] == 'growth_selection':
                growth_count += 1
                continue
            for it in r['items']:
                if '/' in it['item']:
                    bad.append((cn, it['item']))
            for alt in r['alternatives']:
                for it in alt:
                    if '/' in it['item']:
                        bad.append((cn, it['item']))
        assert not bad, 'misinterpreted item names: %d examples: %s' % (
            len(bad), bad[:5]
        )

    def test_growth_six_reported(self):
        raw = _collect_ktos_package_raw()
        if not raw:
            pytest.skip('no package raw data found')
        growth = [(cn, script) for cn, script, sa, na1 in raw
                  if is_growth_script(script)]
        # SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH 가 6건. 추가로
        # SCR_USE_GROWTH_REINFORCE_TIER3_set 1건, SCR_USE_GLOBAL_1911_GROWTH_PACKAGE
        # 1건도 GROWTH 계열이라 미해석 처리한다(총 8건).
        split_growth = [g for g in growth if '_SPLIT_GROWTH' in g[1]]
        assert len(split_growth) == 6, (
            'expected 6 _SPLIT_GROWTH packages, got %d' % len(split_growth)
        )
        # 전체 GROWTH 계열은 최소 6건 이상.
        assert len(growth) >= 6

    def test_multiple_packages_produce_alternatives(self):
        """P1 회귀: txbox_wonderers_armor_* 두 패키지가 alternatives 를 가져야 한다.

        이전에는 수집 조건 누락 + resolver 의 entries-only 검사로
        PackageContents 가 None 이 됐다.
        """
        raw = _collect_ktos_package_raw()
        if not raw:
            pytest.skip('no package raw data found')
        multiple_raw = [(cn, s, sa, na1) for cn, s, sa, na1 in raw
                        if s == 'SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_ITEM_NUMBER_SPLIT']
        # is_package_script 가 이 스크립트를 인식하는지.
        for cn, s, sa, na1 in multiple_raw:
            assert is_package_script(s), (
                '%s script %s must be collected as package' % (cn, s)
            )
            r = parse_package_stringarg(s, sa, na1)
            assert r['kind'] == 'multiple'
            # items 는 비어 있고 alternatives 만 있다.
            assert r['items'] == []
            assert r['alternatives'], (
                '%s should produce alternatives' % cn
            )
