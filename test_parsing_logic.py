#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CaptionRatio 파싱 로직 테스트
"""

def test_normalize_ratio():
    """파싱 로직 테스트"""
    print("=" * 80)
    print("CaptionRatio 파싱 로직 테스트")
    print("=" * 80)
    
    # 테스트 케이스들
    test_cases = [
        # (입력값, 기대 출력값, 설명)
        ([0.4, 0.5, 0.6], [40, 50, 60], "소수 값들 (0~1) -> 퍼센트로 변환"),
        ([40, 50, 60], [40, 50, 60], "이미 퍼센트 값들 -> 그대로 유지"),
        ([1, 2, 3], [1, 2, 3], "1 이상의 정수 값들 -> 그대로 유지"),
        ([0.1, 0.2, 1.5], [10, 20, 1], "혼합 케이스 (소수 + 1 이상)"),
        ([0.05, 5, 0.95], [5, 5, 95], "소수와 정수 혼합"),
        ([], [], "빈 리스트"),
    ]
    
    print("\n1. importAll.py의 변환 로직 테스트\n")
    
    for input_vals, expected, description in test_cases:
        print(f"테스트: {description}")
        print(f"  입력: {input_vals}")
        
        # 실제 파싱 로직 (importAll.py에서 사용하는 로직)
        try:
            normalized_ratio = []
            for h in input_vals:
                try:
                    h_float = float(h)
                    if 0 < h_float < 1:
                        h_float = h_float * 100
                    normalized_ratio.append(int(h_float))
                except (ValueError, TypeError):
                    normalized_ratio.append(int(h))
        except:
            normalized_ratio = []
        
        print(f"  출력: {normalized_ratio}")
        print(f"  기대: {expected}")
        
        if normalized_ratio == expected:
            print(f"  ✅ 통과")
        else:
            print(f"  ❌ 실패")
        print()
    
    print("\n2. parser_tidy/skills.py의 run_lua 로직 테스트\n")
    
    # Lua에서 반환되는 값들을 시뮬레이션
    lua_test_cases = [
        # (Lua 반환값, key_dict, 기대 출력값, 설명)
        (0.4, 'CaptionRatio', 40, "소수 값 CaptionRatio -> 퍼센트 변환"),
        (40, 'CaptionRatio', 40, "이미 퍼센트 값 CaptionRatio -> 유지"),
        (0.5, 'CaptionRatio2', 50, "소수 값 CaptionRatio2 -> 퍼센트 변환"),
        (100, 'CaptionRatio3', 100, "큰 정수 값 CaptionRatio3 -> 유지"),
        (5, 'CaptionTime', 5, "CaptionTime은 변환 안 함"),
    ]
    
    for lua_value, key_dict, expected, description in lua_test_cases:
        print(f"테스트: {description}")
        print(f"  Lua 반환값: {lua_value}, key_dict: {key_dict}")
        
        # 실제 파싱 로직 (parser_tidy/skills.py에서 사용하는 로직)
        is_caption_ratio = key_dict in ['CaptionRatio', 'CaptionRatio2', 'CaptionRatio3']
        
        if lua_value == -1:
            result = 0
        elif lua_value != lua_value:  # NaN 체크
            result = 0
        elif is_caption_ratio and 0 < lua_value < 1:
            result = lua_value * 100
        else:
            result = lua_value
        
        print(f"  출력: {result}")
        print(f"  기대: {expected}")
        
        if abs(result - expected) < 0.001:  # 부동소수점 오차 고려
            print(f"  ✅ 통과")
        else:
            print(f"  ❌ 실패")
        print()
    
    print("=" * 80)
    print("결론:")
    print("1. importAll.py의 로직: 리스트의 각 값이 0~1 사이면 100을 곱함")
    print("2. parser_tidy/skills.py의 로직: CaptionRatio 시리즈 값이 0~1 사이면 100을 곱함")
    print("3. 두 로직 모두 소수 값(0.4 등)을 퍼센트(40 등)로 변환합니다.")
    print("=" * 80)

if __name__ == "__main__":
    test_normalize_ratio()
