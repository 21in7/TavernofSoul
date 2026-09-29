# -*- coding: utf-8 -*-
"""패키지 구성물 StringArg 토큰 파서.

items.py 의 resolve_package_contents() 에서 토큰 해석 로직만 순수 함수로
분리했다. 테스트 가능하고 items.py 의 의존(constants, log)과 분리된다.

StringArg 토큰 문법 (Script 변형별):

1. SCR_USE_STRING_GIVE_ITEM (정확히)
   "ClassName"             -> 단일 아이템 1개 지급

2. SCR_USE_STRING_GIVE_ITEM_NUMBER (정확히)
   "ClassName"             -> 단일 아이템 NumberArg1 개 지급

3. *_NUMBER_SPLIT / RANDOM_*_NUMBER_SPLIT 계열
   "item/count;item/count;..."
   각 토큰은 최소 "item/count" 형식이며 뒤에 property/value 쌍이 0개 이상
   올 수 있다:
     "item/count/prop/value/prop/value"
   이 경우 prop/value 는 인스턴스 옵션(강화 수치, 초월 등)으로 보존한다.

4. SCR_USE_STRING_RANDOM_GIVE_ITEM_NUMBER_SPLIT
   RANDOM 계열의 별칭. random=True 로 표시.

5. SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_ITEM_NUMBER_SPLIT
   "item/count*item/count;..."   ';' 가 그룹 구분, '*' 가 같은 그룹내 선택지.

6. *_SPLIT_GROWTH 계열 (SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH 등)
   StringArg 가 "Melee" / "Magic" 처럼 Item 목록이 아니라 성장 선택 규칙.
   구성물 목록을 생성하지 않고 growth_selection 범주로 보고만 한다.

7. SCR_USE_STRING_SET_ACCOUNT_PROP
   StringArg 가 "EVENT_FIELD_BOSS_10TH/None" 처럼 account.ies 의 계정
   속성명/값이다. Item ClassName 이 아니므로 구성물을 생성하지 않고
   account_prop 범주로 보고만 한다.

선행 '/' 가 잘못 들어간 원본 토큰(item_premium.ies JPN_2212package_Reward)
은 정규화로 복구한다.
"""
import logging

log = logging.getLogger("parse.package")


# 구성물을 만들지 않고 미해석 범주로만 보고하는 스크립트.
GROWTH_SCRIPTS = frozenset([
    'SCR_USE_STRING_GIVE_ITEM_NUMBER_SPLIT_GROWTH',
    'SCR_USE_GLOBAL_1911_GROWTH_PACKAGE',
    'SCR_USE_GROWTH_REINFORCE_TIER3_set',
])

# random 지급으로 해석하는 스크립트 접두사.
RANDOM_PREFIXES = (
    'SCR_USE_STRING_RANDOM',
    'SCR_USE_STRING_GIVE_RANDOM',
)

# 패키지 구성물 지급 스크립트 공통 접두사.
# items.py 의 PackageContents_Raw 수집 조건이 이 접두사로 일관되게 매칭해야
# GIVE_RANDOM_MUTIPLE 계열이 누락되지 않는다.
PACKAGE_SCRIPT_PREFIX = 'SCR_USE_STRING_'


def is_package_script(script):
    """해당 Script 가 패키지 구성물 지급 스크립트인지 판별.

    SCR_USE_STRING_ 로 시작하면 패키지 스크립트로 간주한다.
    GROWTH 계열도 패키지 스크립트(미해석 보고 대상)이므로 포함.
    parse_package_stringarg 가 인식하지 못하면 warnings 로 보고되므로
    안전하게 넓게 수집한다.
    """
    return bool(script) and script.startswith(PACKAGE_SCRIPT_PREFIX)


def _normalize_token(token):
    """선행 '/' 가 잘못 들어간 토큰을 정규화.

    예: "/Multiple_Token_TurbulentCore_Auto_NoTrade/10"
       -> "Multiple_Token_TurbulentCore_Auto_NoTrade/10"
    """
    return token.lstrip('/')


def parse_split_token(token):
    """NUMBER_SPLIT 계열 단일 토큰을 (item, count, options) 로 파싱.

    문법: item/count(/prop/value)*

    반환:
        (class_name, count, options) — options 는 [(prop, value_str), ...]
        파싱 실패 시 (None, 0, []).

    구현 메모:
        rpartition('/') 대신 앞에서부터 item, count 를 먼저 읽고 나머지를
        property/value 쌍으로 처리한다. 이전 rpartition 구현은
        "item/count/prop/value" 에서 마지막 value 를 count 로, 그 앞 전체를
        item 이름으로 잘못 저장했다(259개 잘못된 참조의 원인).
    """
    token = _normalize_token(token).strip()
    if not token:
        return None, 0, []
    parts = token.split('/')
    if len(parts) < 2:
        return None, 0, []
    class_name = parts[0].strip()
    try:
        count = int(parts[1])
    except ValueError:
        return None, 0, []
    options = []
    rest = parts[2:]
    # property/value 쌍 단위로 소비.
    i = 0
    while i + 1 < len(rest):
        prop = rest[i].strip()
        value = rest[i + 1].strip()
        if prop and value:
            options.append((prop, value))
        i += 2
    # 짝이 맞지 않는 남은 토큰이 있으면 경고 대상이지만 여기서는 무시한다.
    return class_name, count, options


def parse_multiple_token(token):
    """RANDOM_MUTIPLE 계열 단일 ';' 토큰을 alternatives 목록으로 파싱.

    문법: item/count*item/count*...

    반환:
        [(class_name, count, options), ...] — 하나라도 파싱 실패하면 빈 리스트.
    """
    token = _normalize_token(token).strip()
    if not token:
        return []
    alternatives = []
    for piece in token.split('*'):
        piece = piece.strip()
        if not piece:
            continue
        cn, count, opts = parse_split_token(piece)
        if cn is None or count <= 0:
            # 그룹 내 일부라도 깨지면 전체 그룹을 신뢰할 수 없다.
            return []
        alternatives.append((cn, count, opts))
    return alternatives


def is_random_script(script):
    return script.startswith(RANDOM_PREFIXES)


def is_growth_script(script):
    return script in GROWTH_SCRIPTS


def parse_package_stringarg(script, string_arg, number_arg1=''):
    """단일 아이템의 StringArg 를 정규화된 구성물描述로 변환.

    반환 dict 스키마:
        {
            'kind': 'fixed' | 'random' | 'multiple' | 'growth_selection',
            'random': bool,
            'items': [ {'item', 'count', 'options'}, ... ],   # growth 제외
            'alternatives': [ [ {'item','count','options'}, ... ], ... ],  # multiple
            'warnings': [str, ...],
        }
    """
    result = {
        'kind': 'fixed',
        'random': is_random_script(script),
        'items': [],
        'alternatives': [],
        'warnings': [],
    }

    if is_growth_script(script):
        result['kind'] = 'growth_selection'
        result['random'] = False
        result['warnings'].append(
            'growth selection script=%s stringarg=%r (not interpreted)' % (script, string_arg)
        )
        return result

    string_arg = (string_arg or '').strip()
    if not string_arg:
        result['warnings'].append('empty stringarg script=%s' % script)
        return result

    # 단일 아이템 지급 (SPLIT 아님)
    if script == 'SCR_USE_STRING_GIVE_ITEM':
        result['items'].append({
            'item': string_arg, 'count': 1, 'options': [],
        })
        return result
    if script == 'SCR_USE_STRING_GIVE_ITEM_NUMBER':
        try:
            count = int(number_arg1)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            result['warnings'].append(
                'invalid number_arg1=%r script=%s' % (number_arg1, script)
            )
            return result
        result['items'].append({
            'item': string_arg, 'count': count, 'options': [],
        })
        return result

    # NUMBER_SPLIT 계열 (일반 / random / multiple)
    if script == 'SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_ITEM_NUMBER_SPLIT':
        result['kind'] = 'multiple'
        result['random'] = True
        for token in string_arg.split(';'):
            token = _normalize_token(token).strip()
            if not token:
                continue
            alts = parse_multiple_token(token)
            if not alts:
                result['warnings'].append('unparseable multiple token=%r' % token)
                continue
            result['alternatives'].append([
                {'item': cn, 'count': c, 'options': opts} for cn, c, opts in alts
            ])
        return result

    # SET_ACCOUNT_PROP: StringArg 가 "EVENT_FIELD_BOSS_10TH/None" 처럼
    # account.ies 의 계정 속성명이지 Item ClassName 이 아니다.
    # 구성물을 만들지 않고 account_prop 범주로만 보고한다.
    if script == 'SCR_USE_STRING_SET_ACCOUNT_PROP':
        result['kind'] = 'account_prop'
        result['random'] = False
        result['warnings'].append(
            'account prop script=%s stringarg=%r (not an item)' % (script, string_arg)
        )
        return result

    # 일반 *_NUMBER_SPLIT 계열: "item/count(/prop/value)*;..."
    if '_NUMBER_SPLIT' in script or '_SPLIT' in script:
        for token in string_arg.split(';'):
            token = _normalize_token(token).strip()
            if not token:
                continue
            cn, count, opts = parse_split_token(token)
            if cn is None or count <= 0:
                result['warnings'].append(
                    'skipped token=%r script=%s' % (token, script)
                )
                continue
            result['items'].append({
                'item': cn, 'count': count, 'options': opts,
            })
        if is_random_script(script):
            result['kind'] = 'random'
        return result

    # 알려지지 않은 스크립트 — 보고만 하고 구성물은 만들지 않는다.
    result['warnings'].append('unknown script=%s stringarg=%r' % (script, string_arg))
    return result
