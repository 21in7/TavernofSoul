# 지역별 경로와 추가 아이템 유형 fixture

기존 아이템·combat·world 입력에 `common/unpack/`과 지역별 `unpack/`을 순서대로 덧붙인다.
입력은 직접 작성한 CSV 형식 IES·XML/TSV·Lua다. 운영 unpack이나 번역을 복사한 실데이터 샘플은 아니다.
기대값 `expected_regions.json`은 소스의 작은 식과 번역에 맞춰 독립적으로 작성했다.
파서 출력에서 생성하지 않으며 fixture 준비 코드도 기대값에서 원본 입력을 만들지 않는다.

## 지역별 입력과 계산

| 지역 | 번역 입력 | 물리 공격력 최소~최대 | 지팡이 마법 공격력 | 갑옷 물리/마법 방어력 |
| --- | --- | --- | --- | --- |
| iTOS | English TSV + XML | 140~147 | 350 | 120 / 60 |
| kTOS | IES의 한국어 원문 | 180~189 | 450 | 150 / 75 |
| kTest | IES의 한국어 원문 | 220~231 | 550 | 180 / 90 |
| jTOS | Japanese TSV + XML | 260~273 | 650 | 210 / 105 |
| twTOS | Taiwanese TSV + XML | 300~315 | 750 | 240 / 120 |

공통 Lua는 검의 `UseLv × HARNESS_ATK_STEP`, 지팡이의 `UseLv × HARNESS_ATK_STEP × 2`,
갑옷의 `UseLv × HARNESS_DEF_STEP`과 그 절반을 계산한다. 지역별 sharedconst에는 서로 다른 계수를 둔다.
검 UseLv는 20, 지팡이는 25, 갑옷은 30이며 갑옷 ItemLv 35와 수치 계산의 UseLv를 구분한다.
강화 공격력과 방어력은 40개 정수 배열, 초월 비용은 `[3,6,…,30]`으로 출력한다.
지팡이 보너스 `INT=4.9`는 floor 후 4, 갑옷의 `STR=-3`은 음수를 유지한다.
갑옷의 MaxDur 0은 기존 sentinel -1로, 직업 `Char1;Char4`는 `FTFTF`로 변환한다.
이 값들은 실제 게임 지역 간 밸런스 차이를 표현하지 않는다.

XML은 아이템·직업·스킬·맵·속성·버프 이름을 연결한다. kTOS/kTest는 운영 `main.py`와 같이
번역 파싱을 건너뛰고 원문을 유지한다. 잘못된 XML이나 CWD의 TSV도 이 두 경로에 영향을 주지 않는다.
번역 지역은 자신의 언어 디렉터리만 사용하며 임시 작업 공간에는 중복 번역 ID의 TSV를 두지 않는다.

## 추가 유형과 참조

총 아이템은 11개다. 기본 7개에 마법 지팡이·방어구·카드·컬렉션을 추가한다.
`item.ies`의 카드 TypeCard/TooltipImage와 `cardbattle.ies`의 높이 150·다리 4·무게 22를 파싱한다.
카드 유형·이미지는 실제 ORM/HTTP까지 검사한다. 전투 카드의 세 수치는 JSON만의 필드이며
현재 Cards 모델에는 저장되지 않는다.

`collection.ies`는 원석·먼지 참조와 `STR_BM/3`, `MHP_BM/25` 보너스를 담는다.
DB 재료 관계·보너스와 상세 페이지·재료의 역참조를 검사한다.
보너스 변경, 재료 관계 제거, 카드 삭제가 기존 DB에 적용되는지도 확인한다.
레시피와 원석이 원본 ID 100을 공유하는 기존 충돌은 importer에서 recipe-100으로 처리한다.

## 지역 간 보충 데이터와 출처

비-iTOS 빌드에는 별도의 작은 `itos_unpack/ies_drop.ipf`를 준비한다.
운영 선택 규칙은 **데이터셋 디렉터리 단위의 iTOS 우선**이다.
각 행과 build_provenance의 출처는 iTOS, 입력 버전은 `regional-source-itos-v1`이다.
현재 지역에도 다른 확률의 디렉터리가 있으면 iTOS를 선택하며, 그 경우 사유는 우선 선택임을 기록한다.
iTOS의 개별 파일이 없다고 현재 지역 파일을 섞지는 않는다.
iTOS 디렉터리 자체가 없으면 현재 지역 데이터셋과 그 지역의 revision을 사용한다.

추가 스킬 403은 원본 이름·ID·직업 참조를 유지하고 빈 설명/효과와 아이콘을 보충한다.
임시 JSON 입력의 우선순위는 kTOS → kTest다. iTOS는 아이콘만 빌리고 설명/효과는 빈 값을 유지한다.
다른 지역은 빈 텍스트에 한국어 보충 값을 적용하는 기존 정책을 검사한다.
이미 번역된 Fire 설명은 지역의 값을 유지한다. 실제 JSON_<region>은 읽거나 변경하지 않는다.

## 검증과 경계

`test_regional_source_fixture.py`는 지역별 기대값, 재실행·지역 전환 시 전역 상태 격리,
번역/추가 IES 누락·손상·장비 Lua 함수 누락/실행 오류의 공개 JSON·버전 보존과 재시도를 검사한다.
명시한 RefreshScp의 계산 실패는 `items.parse_equips`가 예외로 전파한다.
실패를 숨기고 초기 0 수치를 공개하던 경로를 중단하며, 실패 메시지에 장비와 함수 이름을 넣는다.

`harness/regional_tests.py`는 5개 지역을 각각 별도의 테스트로 원본 → JSON → 실제 importer → ORM → HTTP까지
실행한다. 동일 입력 재적재, 새 수치·관계 삭제, 파싱 실패 시 공개/DB/prev 보존,
적재 도중 오류 시 DB·Version·prev 롤백과 수정 후 재시도도 확인한다.
SQLite와 MySQL 하네스에서 같은 테스트를 실행한다.

하네스만 `.ipf` 이름의 fixture 디렉터리를 Git 제외에서 해제한다.
실제 게임 패치·unpack 디렉터리는 기존 제외 정책과 별도 Git 소유권을 유지한다.
doctor는 필수 파일을 확인하고 검증은 이 파일들이 Git에서 제외되지 않았는지도 확인한다.

전체 게임 Lua·모든 지역 schema/패치 조합·여신 강화/550 장신구·젬·책 원본 파싱·이미지 생성·
전체 main.py와 브라우저 JavaScript는 포함하지 않는다. 이 샘플은 운영 데이터 호환성 전체를 보장하지 않는다.
