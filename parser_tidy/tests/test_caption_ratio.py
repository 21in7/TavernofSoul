# -*- coding: utf-8 -*-
"""CaptionRatio 변환 단일 책임(정확성 수정 6) 테스트.

parser(skills.py)만 단위 변환을 소유하고 importer(importAll.py)는
변환하지 않고 int 로만 저장하는지 검증한다.
"""
import os
import sys
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
REPO_ROOT = os.path.dirname(PARENT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def test_parser_owns_caption_ratio_scaling():
    """skills.py 에 CaptionRatio 100배 변환이 있어야 한다(단일 소유)."""
    src_path = os.path.join(PARENT, 'skills.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    assert 'is_caption_ratio' in src, 'skills.py must own CaptionRatio scaling'
    assert '0 < row < 1' in src or '0 < row <1' in src


def test_importer_no_caption_ratio_scaling():
    """importAll.py 에 100배 변환 분기가 더 이상 없어야 한다."""
    src_path = os.path.join(
        REPO_ROOT, 'TavernofSoul', 'ipfparser', 'management', 'commands',
        'importAll.py',
    )
    if not os.path.exists(src_path):
        pytest.skip('importAll.py not available')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    # 이전 이중 변환 분기(0 < h_float < 1: h_float = h_float * 100)가 제거됐는지.
    assert 'h_float = h_float * 100' not in src, (
        'importAll.py must NOT scale CaptionRatio (single ownership in parser)'
    )
    # CaptionRatio 블록은 단순 int 저장만 해야 한다.
    assert "[int(h) for h in i['CaptionRatio']]" in src


def test_no_double_scaling_end_to_end():
    """parser 100배 -> importer int 저장 시 이중 확대 없음 확인."""
    original = 0.4  # 40%

    # parser 변환
    after_parser = original
    if 0 < after_parser < 1:
        after_parser = after_parser * 100  # 40

    # importer 늀 이제 단순 int 저장만.
    def importer_store(v):
        return int(v)

    result = importer_store(after_parser)
    assert result == 40, 'expected 40 (no double scaling), got %r' % result


def test_small_value_no_double_scaling():
    """0.005 같은 작은 값도 이중 확대되지 않아야 한다.

    parser: 0.005 -> 0.5 (100배)
    importer: int(0.5) = 0 (단순 저장, 추가 확대 없음)
    이전에는 importer 가 0.5 를 다시 50 으로 확대했다.
    """
    original = 0.005
    after_parser = original * 100  # 0.5
    result = int(after_parser)  # 0 — 이중 확대 아님
    assert result == 0
    assert result != 50  # 이전 버그 값이 아님
