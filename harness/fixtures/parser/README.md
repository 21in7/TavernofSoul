# 아이템 원본 입력 fixture

이 디렉터리의 IES·Lua·XML·TSV는 하네스를 위해 직접 작성한 작은 입력이다.
IES는 네이티브 도구가 변환한 뒤 파서에 전달하는 **CSV 형식**을 사용한다.
게임의 바이너리 IES나 실제 지역 데이터·장비 계산식을 복제한 샘플은 아니다.
Lua 계산은 대체 Python 함수 없이 실제 `lupa` 런타임에서 실행한다.

## 입력과 확인값

| 입력 | 확인하는 동작 |
| --- | --- |
| `unpack/ies.ipf/item.ies` | 문자열 ID, 빈 등급 기본값, 소수 무게, ms → 초, 거래 플래그, CSV 쉼표 인용, 패키지 토큰 |
| `unpack/ies.ipf/item_equip.ies` | 장비 레벨·내구도 변환과 Lua refresh 호출 |
| `unpack/ies.ipf/recipe.ies` | 재료와 같은 숫자 ID를 가진 레시피, 재료 2종의 수량, 제작 대상 |
| `unpack/ies.ipf/item_grade.ies` | 장비 등급 테이블 읽기 |
| `unpack/ies.ipf/sharedconst*.ies` | Lua가 사용할 공유 상수 읽기 |
| `unpack/ies.ipf/xac.ies` | 빈 모델 목록의 헤더 읽기; 모델·이미지 생성은 포함하지 않음 |
| `unpack/shared.ipf/item_calculate.lua` | 레벨 × 상수의 공격력, 강화 수치·비용, 초월 비용, STR 보너스 |
| `unpack/language.ipf/wholeDicID.xml`, `translation/items.tsv` | 원문 → 사전 ID → 번역 이름·설명 |

아이템 7개는 재료 2개, 장비 1개, 레시피 1개, 패키지 3개다.
패키지는 고정 지급, 미해결 참조가 섞인 지급, 랜덤 묶음을 포함한다.
미해결 아이템은 새 아이템으로 만들지 않고 `PackageContents.unresolved`에 보존한다.

기본 장비의 공격력은 `20 × 7 = 140`, 최대 공격력은 `147`이다.
강화 공격력은 `7..280`, 강화 비용은 `100..4000`, 초월 비용은 `3..30`이다.
내구도 `2500`은 `25`, 쿨다운 `2000ms`는 `2.0초`로 출력된다.
Django의 기존 정수 쿨다운 필드에는 `2`로 저장되는 경로를 확인한다.
소수 초 쿨다운의 DB 저장 정확성은 이 fixture의 검증 범위가 아니다.

`expected_items.json`은 사람이 별도로 작성한 주요 출력 필드의 기대값이다.
테스트 중 파서 출력으로 기대값을 생성하지 않는다. 전체 JSON schema를 대신하지는 않는다.

## 실행 경로와 실패 검증

`harness/parser_fixture.py`는 입력을 임시 프로젝트로 복사하고 실제
`parse_xac.parse_xac → translation.makeDictionary → items.parse → ToS_DB.export`를 실행한다.
각 실행은 새 DB 컨테이너와 실제 Lua 런타임을 쓰고 전역 상태를 복원한다.

- `make check-parser`: 기대값, 숫자 자료형, 입력 변경 시 재계산, 반복 실행 일관성,
  잘못된 등급·누락된 필수 입력·Lua 로드 실패 시 공개 JSON·버전 보존과 재시도.
- `make check-pipeline`: 같은 원본부터 JSON·실제 importer·SQLite DB·HTTP 검색/상세까지 검사.
  레시피 ID 정규화, 관계, Lua 수치, 패키지 미해결 정보, 재적재, 변경 반영,
  실패 후 기존 화면 데이터 유지와 복구를 포함한다.

`doctor`와 fixture 실행기는 필요한 샘플이 빠지면 실패한다.
이 필수 입력 목록은 하네스의 재현 조건이며 운영 파서의 선택적 파일 정책을 바꾸지 않는다.
카드·젬·컬렉션 등 선택적 입력이 없는 경로는 도메인 coverage에 포함하지 않는다.
스킬·몬스터·몬스터 드롭은 [별도 fixture](../combat/README.md)로 검증한다.
전체 `main.py`, 맵·아이콘 생성과 실제 MySQL은 후속 범위다.
