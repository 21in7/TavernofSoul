# 파서 릴리스와 Django 적재 계약

공통 구현은 `TavernofSoul/ipfparser/contracts.py`다. Django 의존성 없이 같은 검사를 양쪽에서 사용한다.
검사는 입력을 정규화하거나 수정하지 않고, 첫 오류의 컬렉션·행·필드·오류 코드를 반환한다.

```text
item_monster[0].Chance [range]: expected a value in 0..100
items_by_name['harness_recipe'].Link_Target [reference]: target missing not found in release
```

`ToS_DB.export()`는 메모리 데이터를 검사한 뒤 JSON을 staging에 기록한다.
기록한 스냅샷도 다시 검사한 후 공개 파일 교체를 시작한다.
메모리 계약 실패 시 staging·backup·기존 공개 파일을 건드리지 않는다.
staging 검사 실패 시 임시 출력만 정리하고 공개 파일과 버전을 보존한다.

`importAll`은 공개 JSON을 임시 디렉터리에 복사하고 **실제로 적재할 스냅샷**을 검사한다.
계약 오류는 DB 쿼리와 트랜잭션 시작 전에 `CommandError`로 중단된다.
DB·Version·`prev/`는 유지하며, 수정한 릴리스로 재시도할 수 있다.
유효한 계약 이후 발생한 DB 적재 오류에도 기존 트랜잭션·비교 기준 롤백을 유지한다.
장비에 명시한 RefreshScp가 없거나 Lua 계산에 실패하면 파서가 오류를 전파하고 공개 전에 중단한다.
JSON 계약이 0 수치를 허용한다는 이유로 계산 실패를 유효한 기본 수치로 처리하지 않는다.

## 릴리스 형식과 ID

다음 15개 컬렉션 파일과 `version.json`은 적재에 필수다. 빈 컬렉션도 파일은 있어야 한다.

| 컬렉션 | 형식·기본 규칙 |
| --- | --- |
| `items_by_name` | `$ID_NAME`과 키가 일치하는 객체 인덱스 |
| `skills` | 객체 인덱스; importer가 `.values()`로 읽음 |
| `jobs`, `monsters`, `npcs`, `maps`, `attributes`, `skill_mon`, `buff`, `achievements` | 객체 또는 행 배열 |
| `item_type` | 분류명 → 아이템 이름 배열; EQUIPMENT·CARD·RECIPES·COLLECTION 필수 |
| `item_monster`, `map_item`, `map_npc`, `map_item_spawn` | 관계 행 배열 |
| `version` | 비어 있지 않은 문자열 `version`, 최대 50자 |

엔티티는 `$ID`, `$ID_NAME`, `Name`이 필요하다.
ID는 비어 있지 않은 문자열 또는 정수이며 boolean은 허용하지 않는다.
유일성·관계 비교에서는 `100`과 `"100"`을 같은 ID로 취급한다.
지도 ID는 최대 20자, 다른 ID는 30자다. 엔티티별 ID와 `$ID_NAME` 중복을 거부한다.
몬스터와 NPC는 같은 ORM 테이블을 쓰므로 두 컬렉션 사이의 ID 중복도 거부한다.

레시피는 `item_type.RECIPES`로 식별하며 적재 ID가 `recipe-<원본 ID>`다.
일반 아이템과 레시피가 같은 숫자 ID를 쓰는 것은 허용한다.
공통 canonical 함수로 검사와 importer의 ID 규칙을 맞춘다. 원본 JSON의 ID는 변경하지 않는다.
ORM 유형 행을 만드는 EQUIPMENT·CARD·RECIPES·COLLECTION·BOOKS 간 중복 분류는 거부한다.

추가 필드와 컬렉션은 허용한다. 모든 JSON에서 잘못된 문법·중복 객체 키·NaN·Infinity를 거부한다.
`1e999`처럼 읽을 때 무한대로 넘치는 값도 거부한다.
필수 컬렉션 외의 lookup·자산·provenance 파일은 JSON 형식을 검사하며 별도 도메인 schema를 강제하지 않는다.

`export(version_payload=None)`은 기존 호출 호환을 위해 버전 파일을 새로 만들지 않는다.
이 경로도 15개 데이터 컬렉션은 검사한다. 실제 적재는 항상 유효한 버전 파일이 필요하다.

## 필드·관계·범위

| 대상 | 검사 내용 |
| --- | --- |
| 아이템 | importer가 읽는 이름·설명·아이콘·Type·Grade·Weight·TimeCoolDown·Tradability, 등급 0..6, 무게·쿨다운 ≥ 0, 거래 플래그 T/F 4개 |
| 레시피 | Link_Materials 배열, 기존 아이템 이름, 정수 Quantity ≥ 1, 선언한 Link_Target의 존재 |
| 패키지 | random boolean, items·alternatives의 아이템 참조, 정수 count ≥ 1, options의 문자열 쌍, resolved name의 타입 |
| 장비 | 필수 수치·계산 배열·Bonus 쌍·boolean, 클래스 플래그 T/F 5개, 물리 공격력 최소 ≤ 최대, 내구도 ≥ 0 또는 -1 |
| 카드·컬렉션·책 | 카드 세부 필드, 컬렉션 재료 참조와 Bonus 쌍, 제공된 책 Text의 타입 |
| 직업·플레이어 스킬 | 필수 텍스트·boolean·정수, Link_Job, 기본 SP·오버히트·쿨다운 ≥ 0, 제공된 레벨별 배열의 숫자 타입 |
| 몬스터·NPC | importer가 읽는 필수 필드, 몬스터 정수 스탯, HP·레벨·EXP·JOBEXP ≥ 0, 물리·마법 공격력 최소 ≤ 최대 |
| 몬스터 스킬 | 필수 필드, CD·AAR ≥ 0, 제공된 타수 ≥ 1, Monster ID 참조 |
| 맵·관계 | 맵 필드와 Link_Maps 참조, 관계 부모 존재, 부모 쌍 중복 거부, Population·TimeRespawn ≥ 0, Positions의 2차원 숫자 좌표 |
| 드롭 관계 | Chance 0..100, 정수 수량 ≥ 0, 최소 ≤ 최대, 아이템·몬스터·지도 부모 참조 |
| 속성 | 필수 필드·boolean·LevelMax 정수 값, Link_Jobs 참조, Link_Skills 문자열 배열 |
| 버프·업적 | importer 필수 필드와 숫자·boolean 타입; 버프 UserRemove는 boolean 또는 정수 0/1 |

일반 숫자는 문자열과 boolean을 허용하지 않으며 유한해야 한다.
정수 필드는 소수 부분이 없어야 한다. 원본 문자열을 유지하는 몬스터 스킬 CD/AAR/SFR/HitCount,
속성 LevelMax, 버프 ApplyTime/OverBuff만 정수 문자열도 허용한다.
선택된 이름·아이콘·ID 필드에는 ORM 길이 제한도 적용한다.
전체 MySQL 저장 크기나 ListCharField의 직렬화 한도를 검증하는 것은 아니다.
MySQL 하네스는 strict SQL에서 직렬화한 배열이 VARCHAR 한도를 넘으면 실제 DB 오류가 발생하고,
importer가 앞선 DB 변경·Version·prev를 보존하는지 검사한다. 수정 후 재적재 경로도 확인한다.

## 기존에 허용하던 값

- 레시피 Link_Target은 누락 또는 null을 허용한다.
- 아이템 Name·Description·Icon 등 지정된 nullable 필드와 빈 Weight를 허용한다. importer는 빈 Weight를 0으로 저장한다.
- 장비 Durability의 -1, 속성 LevelMax의 -1, 지도 필드의 기존 -1을 유지한다.
- Link_Job이 null인 스킬은 importer가 건너뛴다. 선택적 계산 배열은 미제공·null·빈 문자열을 유지한다.
  CaptionRatio 계열은 음수 보정도 허용한다.
- 몬스터 스킬의 비어 있는 SFR은 0, 미제공·null·빈 HitCount는 1로 적재되는 기존 경로를 유지한다.
- 속성 Link_Skills의 은퇴/비직업 스킬은 importer가 건너뛴다. 해당 이름이 반드시 현재 스킬 컬렉션에 있을 필요는 없다.
- `PackageContents.unresolved`와 `unresolved_drops`는 해결되지 않은 참조를 보존한다.
  unresolved를 정상 DB 관계와 같은 참조 실패로 처리하지 않는다.
- 지도 좌표는 음수와 소수를 허용한다.

## 여신 강화와 젬 경계

`item_type.GEMS`는 optional 유형 그룹이며 별도 ORM 그룹과 중복할 수 없다.
젬 Link_Skill은 스킬 ID이고 누락/null은 연결 없음이다. 유효한 값은 기존 skills 컬렉션을 참조해야 한다.
importer는 스킬 적재 뒤 Gems를 반영한다. 다섯 슬롯의 보너스 배열은 `Gems.socket_bonuses`에
JSON 문자열로 저장한다. 각 보너스의 Stat은 비어 있지 않은 문자열이고 Value는 optional 문자열/수치다.
새 파서는 양수 정수 Level을 보존하고 레벨 0을 제외한다. 이전 JSON에 Level이 없으면
누락 상태 그대로 적재·표시하며 배열 순서로 레벨을 추측하지 않는다. 음수 페널티도 유지한다.

`goddess_reinf`·`goddess_reinf_mat`는 optional 적재 컬렉션이다. 둘 다 제공하거나 둘 다 생략한다.
둘 다 생략한 이전 릴리스는 지원하며 기존 강화 DB 행을 제거한다.
테이블 레벨·ClassID와 재료의 단계는 정규화 후 중복이 없어야 한다. 강화 단계는 1부터 연속이며 최대 30이다.
BasicProp은 0..100000, 알려진 기본/증가 수치와 재료 수량은 0..2147483647 정수다.
CSV 수치 문자열은 테이블에서 허용하지만 재료 수량은 JSON 숫자다. 빈 재료 객체는 무료 단계이고
그룹/단계 누락은 비용 미제공이다. 비어 있지 않은 재료 단계는 등록된 테이블 행을 참조한다.
등록 테이블마다 `GoddessReinforcement`의 레벨/단계 유일 행에 확률·원본 행·그룹별 재료를 저장한다.
460의 기존 armor wrapper는 공통 재료이므로 적재 시 세 그룹에 제공한다.
재료 ClassName은 해당 릴리스의 Items가 있으면 화면에서 이름/링크로 해결하고, 없으면 원본 이름을 표시한다.
미해결 통화에 가짜 아이템/FK를 만들지 않는다.
560 재료의 필수 함수 누락·빈 계산·0 미만/소수/비유한 수량은 파서에서 차단한다.
550 장신구 BasicAccAtk의 공개 장비 필드는 문자열이 아닌 정수다.
레벨·단계 dict 키는 JSON에서 문자열이며 560 armor/weapon과 550 acc의 지원 그룹을 구분한다.
`GoddessReinforceLevel`은 원본 UseLv이고 표시용 Level/ItemLv와 구분한다.
`GoddessReinforceGroup`은 acc/armor/weapon이다. 두 필드는 함께 제공하고 등록 테이블을 참조한다.
AnvilATK/DEF는 원본 SCR_GET_GODDESS_REINFORCE로 계산한 단계별 누적값이며 빈 배열이 아니면
테이블 행 수와 같아야 한다. Trinket 공격력은 원본 ATK 함수의 0.3 배율·내림을 적용한다.
무기 판별은 항상 false였던 대체 함수를 제거하고 원본 IS_WEAPON_TYPE을 사용한다.
성장형 장비의 StringArg에 별도 테이블 참조가 있으면 이 계산 경로를 제공하지 않는다.
화면은 이 값·확률·재료를 사용하며 기존 고정 여신 배열로 보충하지 않는다.
계산기 초월 보너스의 기존 등급별 비율은 유지한다. 진화·세트/착용 조건별 방어구 공격력 전환은 포함하지 않는다.
`goddess_reinf_unregistered`는 진단용 보조 출력이다. 미등록 파일을 자동 등록하거나 DB 강화 행으로 만들지 않는다.

## 단위의 소유권

| 값 | 공개 JSON 단위 | 변환 담당 |
| --- | --- | --- |
| 아이템 TimeCoolDown | 초 | 파서: 원본 ms / 1000 |
| 장비 Durability | 원본 값 / 100 | 파서 |
| 여신 강화 BasicProp | 원본 0..100000 | ORM 원본 유지; view에서 /1000하여 퍼센트 표시 |
| 스킬 BasicCoolDown·CoolDown, 몬스터 스킬 CD, 버프 ApplyTime | ms | 파서 출력 유지; 화면에서 초로 표시 |
| 지도 관계 TimeRespawn | 초 | 파서: 원본 ms / 1000 |
| 몬스터·일반 맵 드롭 Chance | 퍼센트 0..100 | 파서: DropRatio / 100 |
| unknownsanctuary 맵 Chance | 퍼센트 0..100 | 파서: DropRatio / 10000 |
| 맵 그룹 Chance | 퍼센트 0..100 | 맵 확률 × 그룹 가중치 / 가중치 합계 |
| CaptionRatio 계열 | 파서가 계산·변환한 값 | 파서: 0 < 값 < 1이면 100배; importer에서 재확대하지 않음 |

숫자 하나로 잘못된 단위를 판별할 수는 없다. 12.5%와 0.125%는 둘 다 유효한 범위다.
계약 검사는 타입과 범위를 확인하고, 원본 fixture의 독립적인 기대값이 변환을 검증한다.
버프·맵의 선택한 단위 경로는 world 원본 fixture로 검증한다.
아이템의 소수 초 쿨다운은 JSON에서 허용하지만 현재 DB IntegerField의 정밀도는 이번 작업에서 바꾸지 않는다.

## 검증과 남은 범위

`make check`로 전체 하네스를 실행한다.
`test_release_contract.py`는 실제 아이템·combat 파서 출력에
직접 작성한 `harness/fixtures/contract_extensions.json`을 더해 계약을 검사한다.
누락·중복·타입·범위·참조 오류가 공개 출력 전에 차단되는지, staging 손상도 차단되는지 확인한다.

`harness/contract_tests.py`는 같은 고정 입력을 실제 migrations·ORM으로 적재한다.
첫 적재와 기존 릴리스 갱신에서 계약 오류 시 DB 쿼리가 0개인지, DB·버전·비교 기준이 유지되는지,
스냅샷 복사 후 손상을 검출하는지, 수정 후 재시도와 적재 도중 실패 롤백을 검사한다.
같은 입력 재적재는 데이터와 관계를 유지한다. importSkills의 updated 감사 시각은 전진할 수 있다.

맵·카드·컬렉션·책·속성·버프·업적의 확장 입력은 고정 JSON이며 원본 IES/Lua 파싱 coverage가 아니다.
맵·속성·버프에는 별도의 `world/` 원본 fixture와 `test_world_source_fixture.py`,
`harness/world_tests.py`가 있다. 이 경로의 실제 원본 파싱·DB·HTTP coverage와
위 고정 JSON의 계약 coverage를 구분한다. 세부 범위는 [하네스 안내](harness.md)를 참고한다.
전체 지역 게임 데이터·운영 MySQL·기존 DB의 일괄 보정은 실행하지 않는다.
