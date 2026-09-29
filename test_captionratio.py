#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
스킬 CaptionRatio 파싱 테스트 스크립트
"""

import os
import sys
import django

# Django 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'TavernofSoul'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "TavernofSoul.settings")
django.setup()

from Skills.models import Skills

def test_captionratio_parsing():
    """실제 데이터베이스에서 CaptionRatio 값들을 확인"""
    print("=" * 80)
    print("스킬 CaptionRatio 파싱 테스트")
    print("=" * 80)
    
    # CaptionRatio가 있는 스킬들을 샘플로 가져옴
    skills_with_ratio = Skills.objects.filter(
        captionratio1__isnull=False
    ).exclude(captionratio1='').order_by('ids')[:20]
    
    if not skills_with_ratio.exists():
        print("CaptionRatio가 있는 스킬을 찾을 수 없습니다.")
        return
    
    print(f"\n총 {skills_with_ratio.count()}개의 스킬을 확인합니다.\n")
    
    for skill in skills_with_ratio:
        print(f"\n스킬 ID: {skill.ids}")
        print(f"스킬 이름: {skill.name}")
        print(f"직업: {skill.job.name if skill.job else 'N/A'}")
        
        # CaptionRatio1
        if skill.captionratio1:
            ratio1_list = skill.captionratio1
            print(f"CaptionRatio1 (레벨 0-10): {ratio1_list[:11] if len(ratio1_list) > 11 else ratio1_list}")
            if ratio1_list:
                # 소수 값이 있는지 확인
                has_decimal = any(0 < float(x) < 1 for x in ratio1_list[:11] if x)
                print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
                if has_decimal:
                    print(f"  ⚠️  소수 값이 있습니다! 퍼센트 변환이 필요할 수 있습니다.")
        
        # CaptionRatio2
        if skill.captionratio2:
            ratio2_list = skill.captionratio2
            print(f"CaptionRatio2 (레벨 0-10): {ratio2_list[:11] if len(ratio2_list) > 11 else ratio2_list}")
            if ratio2_list:
                has_decimal = any(0 < float(x) < 1 for x in ratio2_list[:11] if x)
                print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
        
        # CaptionRatio3
        if skill.captionratio3:
            ratio3_list = skill.captionratio3
            print(f"CaptionRatio3 (레벨 0-10): {ratio3_list[:11] if len(ratio3_list) > 11 else ratio3_list}")
            if ratio3_list:
                has_decimal = any(0 < float(x) < 1 for x in ratio3_list[:11] if x)
                print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
        
        print("-" * 80)

    # 통계 정보
    print("\n" + "=" * 80)
    print("통계 정보")
    print("=" * 80)
    
    all_skills = Skills.objects.all()
    skills_with_ratio1 = all_skills.filter(captionratio1__isnull=False).exclude(captionratio1='')
    skills_with_ratio2 = all_skills.filter(captionratio2__isnull=False).exclude(captionratio2='')
    skills_with_ratio3 = all_skills.filter(captionratio3__isnull=False).exclude(captionratio3='')
    
    print(f"전체 스킬 수: {all_skills.count()}")
    print(f"CaptionRatio1이 있는 스킬: {skills_with_ratio1.count()}")
    print(f"CaptionRatio2가 있는 스킬: {skills_with_ratio2.count()}")
    print(f"CaptionRatio3가 있는 스킬: {skills_with_ratio3.count()}")

if __name__ == "__main__":
    test_captionratio_parsing()
