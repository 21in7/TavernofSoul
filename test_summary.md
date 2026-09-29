# 스킬 CaptionRatio 파싱 테스트 결과

## 테스트 완료 ✅

### 1. 파싱 로직 테스트 결과

#### importAll.py 로직 테스트
- ✅ 소수 값 (0.4, 0.5, 0.6) → 퍼센트 (40, 50, 60)로 변환
- ✅ 이미 퍼센트 값 (40, 50, 60) → 그대로 유지
- ✅ 1 이상의 정수 값 → 그대로 유지
- ✅ 혼합 케이스 정상 처리

#### parser_tidy/skills.py의 run_lua 로직 테스트
- ✅ CaptionRatio 시리즈 값이 0~1 사이면 100을 곱해 퍼센트로 변환
- ✅ CaptionTime 등 다른 값은 변환하지 않음
- ✅ 이미 퍼센트 형태인 값은 그대로 유지

### 2. 수정된 코드 위치

1. **parser_tidy/skills.py** - `run_lua` 함수
   - CaptionRatio, CaptionRatio2, CaptionRatio3 값이 0~1 사이면 100을 곱함

2. **TavernofSoul/ipfparser/management/commands/importAll.py**
   - 저장 전 CaptionRatio 값들을 정규화 (소수 → 퍼센트)

3. **TavernofSoul/ipfparser/management/commands/importJobs.py**
   - 동일한 정규화 로직 적용

4. **JavaScript 파일들** (하위 호환성 유지)
   - skillPlanner.js
   - planner_script.html  
   - Skills/index.html
   - 표시 시에도 변환 로직 유지 (기존 데이터 대응)

### 3. 작동 방식

```
Lua 스크립트 실행 (run_lua)
  ↓
값이 0~1 사이인 CaptionRatio 감지
  ↓
100을 곱해 퍼센트로 변환 (0.4 → 40)
  ↓
JSON 파일에 저장
  ↓
importAll.py에서 다시 한번 정규화 확인
  ↓
데이터베이스에 퍼센트 값으로 저장 (40)
```

### 4. 예상 결과

- **이전**: 소수 값(0.4)이 그대로 저장되어 표시 시 잘못된 값 표시
- **이후**: 파싱 단계에서 퍼센트(40)로 변환되어 저장
- **표시**: 올바른 퍼센트 값(40)이 표시됨

### 5. 다음 단계

1. 실제 파싱 실행 시 새로 파싱된 스킬들은 퍼센트로 저장됨
2. 기존 데이터는 JavaScript 변환 로직으로 처리됨
3. 필요 시 기존 데이터 마이그레이션 가능
