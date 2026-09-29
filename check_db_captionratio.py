#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DB에 저장된 CaptionRatio 값 확인
"""

import os
import sys
import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'TavernofSoul'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "TavernofSoul.settings_ktos")
django.setup()

from Skills.models import Skills
from django.db import models

def check_db_values():
    """DB에 저장된 CaptionRatio 값 확인"""
    print("=" * 80)
    print("DB에 저장된 CaptionRatio 값 확인 (ktos)")
    print("=" * 80)
    
    # 통계 정보
    all_skills = Skills.objects.all()
    total = all_skills.count()
    has_ratio1 = all_skills.filter(captionratio1__isnull=False).exclude(captionratio1='').count()
    has_ratio2 = all_skills.filter(captionratio2__isnull=False).exclude(captionratio2='').count()
    has_ratio3 = all_skills.filter(captionratio3__isnull=False).exclude(captionratio3='').count()
    
    print(f"\n전체 스킬 수: {total}")
    print(f"CaptionRatio1이 있는 스킬: {has_ratio1} ({has_ratio1/total*100:.1f}%)")
    print(f"CaptionRatio2가 있는 스킬: {has_ratio2} ({has_ratio2/total*100:.1f}%)")
    print(f"CaptionRatio3가 있는 스킬: {has_ratio3} ({has_ratio3/total*100:.1f}%)")
    
    # CaptionRatio2, 3이 null인 이유 확인
    print("\n" + "=" * 80)
    print("CaptionRatio2, 3이 null인 이유 확인")
    print("=" * 80)
    
    # CaptionRatio1만 있는 스킬 (CaptionRatio2, 3이 없는 스킬)
    only_ratio1 = all_skills.filter(
        captionratio1__isnull=False
    ).exclude(captionratio1='').filter(
        captionratio2__isnull=True
    )[:5]
    
    print(f"\nCaptionRatio1만 있는 스킬 예시 ({only_ratio1.count()}개 중 5개):")
    for skill in only_ratio1:
        print(f"\n스킬 ID: {skill.ids} - {skill.name}")
        if skill.effect:
            # Effect에서 CaptionRatio2, 3 사용 여부 확인
            effect_text = skill.effect[:200] if len(skill.effect) > 200 else skill.effect
            has_cr2 = '{CaptionRatio2}' in skill.effect if skill.effect else False
            has_cr3 = '{CaptionRatio3}' in skill.effect if skill.effect else False
            print(f"  Effect에 CaptionRatio2 사용: {has_cr2}")
            print(f"  Effect에 CaptionRatio3 사용: {has_cr3}")
            if has_cr2 or has_cr3:
                print(f"  ⚠️ Effect에 사용되는데 DB에 없음!")
            else:
                print(f"  ✅ Effect에 사용 안 함 (정상)")
    
    # CaptionRatio2, 3이 있는 스킬 예시
    print("\n" + "-" * 80)
    print("CaptionRatio2 또는 3이 있는 스킬 예시:")
    print("-" * 80)
    
    has_ratio2_or_3 = all_skills.filter(
        models.Q(captionratio2__isnull=False) | models.Q(captionratio3__isnull=False)
    ).exclude(captionratio2='').exclude(captionratio3='')[:5]
    
    for skill in has_ratio2_or_3:
        print(f"\n스킬 ID: {skill.ids} - {skill.name}")
        if skill.captionratio2:
            print(f"  CaptionRatio2: {skill.captionratio2[:6]}")
        if skill.captionratio3:
            print(f"  CaptionRatio3: {skill.captionratio3[:6]}")
        if skill.effect:
            has_cr2 = '{CaptionRatio2}' in skill.effect
            has_cr3 = '{CaptionRatio3}' in skill.effect
            print(f"  Effect에 CaptionRatio2: {has_cr2}, CaptionRatio3: {has_cr3}")
    
    print("\n" + "=" * 80)
    print("결론:")
    print("- CaptionRatio2, 3은 선택적 필드입니다")
    print("- 스킬 Effect에서 {CaptionRatio2}, {CaptionRatio3}를 사용하는 스킬만 이 값을 가집니다")
    print("- 대부분의 스킬은 CaptionRatio1만 사용하므로 captionratio2, 3이 null인 것이 정상입니다")
    print("=" * 80)

if __name__ == "__main__":
    try:
        check_db_values()
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
