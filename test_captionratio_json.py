#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
스킬 CaptionRatio 파싱 테스트 스크립트 (JSON 파일 기반)
"""

import json
import os
from pathlib import Path

def test_captionratio_from_json():
    """JSON 파일에서 CaptionRatio 값들을 확인"""
    print("=" * 80)
    print("스킬 CaptionRatio 파싱 테스트 (JSON 파일 기반)")
    print("=" * 80)
    
    # JSON 파일 경로 확인
    base_paths = [
        '/home/ubuntu/TavernofSoul/TavernofSoul/TavernofSoul',
        '/home/ubuntu/TavernofSoul',
    ]
    
    skills_json_path = None
    for base in base_paths:
        potential_path = os.path.join(base, 'skills.json')
        if os.path.exists(potential_path):
            skills_json_path = potential_path
            break
    
    if not skills_json_path:
        # settings에서 JSON_ROOT 확인
        try:
            import sys
            sys.path.insert(0, '/home/ubuntu/TavernofSoul/TavernofSoul')
            from django.conf import settings
            json_root = getattr(settings, 'JSON_ROOT', None)
            if json_root:
                skills_json_path = os.path.join(json_root, 'skills.json')
        except:
            pass
    
    if not skills_json_path or not os.path.exists(skills_json_path):
        print(f"skills.json 파일을 찾을 수 없습니다.")
        print("다음 경로들을 확인했습니다:")
        for base in base_paths:
            print(f"  - {os.path.join(base, 'skills.json')}")
        return
    
    print(f"\nJSON 파일 경로: {skills_json_path}\n")
    
    # JSON 파일 로드
    try:
        with open(skills_json_path, 'r', encoding='utf-8') as f:
            skills_data = json.load(f)
    except Exception as e:
        print(f"JSON 파일을 로드할 수 없습니다: {e}")
        return
    
    print(f"총 {len(skills_data)}개의 스킬을 확인합니다.\n")
    
    # CaptionRatio가 있는 스킬들 찾기
    skills_with_ratio = []
    for skill_id, skill_data in skills_data.items():
        if 'CaptionRatio' in skill_data or 'CaptionRatio2' in skill_data or 'CaptionRatio3' in skill_data:
            skills_with_ratio.append((skill_id, skill_data))
            if len(skills_with_ratio) >= 20:  # 최대 20개만
                break
    
    if not skills_with_ratio:
        print("CaptionRatio가 있는 스킬을 찾을 수 없습니다.")
        return
    
    print(f"샘플로 {len(skills_with_ratio)}개의 스킬을 확인합니다.\n")
    
    for skill_id, skill in skills_with_ratio:
        print(f"\n스킬 ID: {skill_id}")
        print(f"스킬 이름: {skill.get('Name', 'N/A')}")
        print(f"스킬 ID_NAME: {skill.get('$ID_NAME', 'N/A')}")
        
        # CaptionRatio1
        if 'CaptionRatio' in skill:
            ratio1_list = skill['CaptionRatio']
            if ratio1_list:
                print(f"CaptionRatio1 (레벨 0-10): {ratio1_list[:11] if len(ratio1_list) > 11 else ratio1_list}")
                # 소수 값이 있는지 확인
                try:
                    has_decimal = any(0 < float(x) < 1 for x in ratio1_list[:11] if x is not None)
                    print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
                    if has_decimal:
                        decimal_values = [x for x in ratio1_list[:11] if x is not None and 0 < float(x) < 1]
                        print(f"  ⚠️  소수 값들: {decimal_values[:5]}... (퍼센트 변환이 필요)")
                except:
                    pass
        
        # CaptionRatio2
        if 'CaptionRatio2' in skill:
            ratio2_list = skill['CaptionRatio2']
            if ratio2_list:
                print(f"CaptionRatio2 (레벨 0-10): {ratio2_list[:11] if len(ratio2_list) > 11 else ratio2_list}")
                try:
                    has_decimal = any(0 < float(x) < 1 for x in ratio2_list[:11] if x is not None)
                    print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
                    if has_decimal:
                        decimal_values = [x for x in ratio2_list[:11] if x is not None and 0 < float(x) < 1]
                        print(f"  ⚠️  소수 값들: {decimal_values[:5]}... (퍼센트 변환이 필요)")
                except:
                    pass
        
        # CaptionRatio3
        if 'CaptionRatio3' in skill:
            ratio3_list = skill['CaptionRatio3']
            if ratio3_list:
                print(f"CaptionRatio3 (레벨 0-10): {ratio3_list[:11] if len(ratio3_list) > 11 else ratio3_list}")
                try:
                    has_decimal = any(0 < float(x) < 1 for x in ratio3_list[:11] if x is not None)
                    print(f"  → 소수 값(0~1) 포함 여부: {has_decimal}")
                    if has_decimal:
                        decimal_values = [x for x in ratio3_list[:11] if x is not None and 0 < float(x) < 1]
                        print(f"  ⚠️  소수 값들: {decimal_values[:5]}... (퍼센트 변환이 필요)")
                except:
                    pass
        
        print("-" * 80)

    # 통계 정보
    print("\n" + "=" * 80)
    print("통계 정보")
    print("=" * 80)
    
    total_with_ratio1 = sum(1 for s in skills_data.values() if 'CaptionRatio' in s and s['CaptionRatio'])
    total_with_ratio2 = sum(1 for s in skills_data.values() if 'CaptionRatio2' in s and s['CaptionRatio2'])
    total_with_ratio3 = sum(1 for s in skills_data.values() if 'CaptionRatio3' in s and s['CaptionRatio3'])
    
    # 소수 값을 가진 스킬 개수
    decimal_ratio1_count = 0
    decimal_ratio2_count = 0
    decimal_ratio3_count = 0
    
    for skill in skills_data.values():
        if 'CaptionRatio' in skill and skill['CaptionRatio']:
            try:
                if any(0 < float(x) < 1 for x in skill['CaptionRatio'][:11] if x is not None):
                    decimal_ratio1_count += 1
            except:
                pass
        if 'CaptionRatio2' in skill and skill['CaptionRatio2']:
            try:
                if any(0 < float(x) < 1 for x in skill['CaptionRatio2'][:11] if x is not None):
                    decimal_ratio2_count += 1
            except:
                pass
        if 'CaptionRatio3' in skill and skill['CaptionRatio3']:
            try:
                if any(0 < float(x) < 1 for x in skill['CaptionRatio3'][:11] if x is not None):
                    decimal_ratio3_count += 1
            except:
                pass
    
    print(f"전체 스킬 수: {len(skills_data)}")
    print(f"CaptionRatio1이 있는 스킬: {total_with_ratio1}")
    print(f"  → 소수 값을 가진 스킬: {decimal_ratio1_count}")
    print(f"CaptionRatio2가 있는 스킬: {total_with_ratio2}")
    print(f"  → 소수 값을 가진 스킬: {decimal_ratio2_count}")
    print(f"CaptionRatio3가 있는 스킬: {total_with_ratio3}")
    print(f"  → 소수 값을 가진 스킬: {decimal_ratio3_count}")

if __name__ == "__main__":
    test_captionratio_from_json()
