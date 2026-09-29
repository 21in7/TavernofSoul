# -*- coding: utf-8 -*-
"""ItemGrade 빈 값/유효범위 방어(정확성 수정 5) 테스트."""
import os
import sys
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def test_safe_grade_normal():
    from items import safe_item_grade
    assert safe_item_grade({'ItemGrade': '3'}) == 3
    assert safe_item_grade({'ItemGrade': '6'}) == 6
    assert safe_item_grade({'ItemGrade': '0'}) == 0


def test_safe_grade_empty_string():
    from items import safe_item_grade
    assert safe_item_grade({'ItemGrade': ''}) == 1
    assert safe_item_grade({'ItemGrade': '   '}) == 1


def test_safe_grade_missing_key():
    from items import safe_item_grade
    assert safe_item_grade({}) == 1
    assert safe_item_grade({'Other': 'x'}) == 1


def test_safe_grade_none():
    from items import safe_item_grade
    assert safe_item_grade({'ItemGrade': None}) == 1


def test_safe_grade_out_of_range():
    from items import safe_item_grade
    with pytest.raises(ValueError):
        safe_item_grade({'ItemGrade': '7'})
    with pytest.raises(ValueError):
        safe_item_grade({'ItemGrade': '-1'})
    with pytest.raises(ValueError):
        safe_item_grade({'ItemGrade': '99'})


def test_safe_grade_custom_default():
    from items import safe_item_grade
    assert safe_item_grade({'ItemGrade': ''}, default=2) == 2


def test_no_dead_branch_in_parse_equips():
    """parse_equips 의 int(ItemGrade)=='' 도달 불가 분기가 제거됐는지 확인."""
    src_path = os.path.join(PARENT, 'items.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    # 도달 불가 분기 패턴이 소스에 없어야 한다.
    assert "obj['Grade'] == \"\"" not in src, (
        'dead ItemGrade == "" branch must be removed'
    )
    # safe_item_grade 헬퍼가 사용되어야 한다.
    assert 'safe_item_grade' in src
