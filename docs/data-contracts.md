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

`unresolved_map_links.json`은 선택적 진단 컬렉션이며 객체 행의 JSON 배열이다.
새 파서는 해결되지 않은 지도 링크가 없어도 `[]`을 export한다.
이 파일이 없는 이전 릴리스는 그대로 호환되지만, 제공된 파일은 아래 진단 계약을 검사한다.
변경 범위는 parser export와 importer 계약 경계이며 운영 DB 스키마를 변경하거나 진단용 ORM 관계를 만들지 않는다.

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
명시한 선택적 계약 컬렉션 외의 lookup·자산·provenance 파일은 JSON 형식을 검사하며 별도 도메인 schema를 강제하지 않는다.

`finite_tree`의 private `_nonfinite_suffix`는 dict·list·tuple의 자식이 정확한 내장
`str`·`int`·`bool` 또는 `None`이면 재귀 호출을 생략한다. 정확한 내장 `float` 자식은
부모에서 `math.isfinite`로 검사한다. 타입 판별은 `type(child) is ...`와 `child is None`을
사용하며, 동등성 기반 타입 membership을 사용하지 않는다. 사용자 metaclass의 `__eq__`가
하위 클래스를 내장 scalar 타입과 같다고 주장해도 잘못된 값을 숨길 수 없어야 한다.
컨테이너·하위 클래스·알 수 없는 객체는 재귀하여 기존 `isinstance` 처리로 돌아간다.
dict·list·tuple 하위 클래스는 순회하고 float 하위 클래스와 scalar 루트의 비유한 float도 거부한다.
알 수 없는 객체의 속성을 새로 순회하거나 새 타입 거부 정책을 추가하지 않는다.

정상 순회 중 진단 경로 문자열을 만들지 않고, 첫 비유한 float의 분기를 되짚을 때만 구성한다.
dict 삽입 순서와 list·tuple 인덱스 순서에 따른 깊이 우선 첫 오류 위치를 유지한다.
dict 키의 `{!r}`·인덱스의 `[{}]` 표현과 `ContractError`의 path·code·message·문자열 표현도 동일하다.
유한 float·임의 크기 정수·bool·None·문자열 `'NaN'`·`'Infinity'`의 기존 허용을 유지한다.
공개 API·정상 반환값·입력 객체 identity와 alias·직렬화 bytes 및 JSON·도메인 계약 정책은 바뀌지 않는다.

### 메모리 API와 파일 스냅샷의 검증 책임

| 경계 | 책임과 순서 |
| --- | --- |
| 공개 `validate_release(data, require_version=True)` | private `_validate_release_structure`로 릴리스 객체·필수 컬렉션·version 검사 → `finite_tree(data, 'release')`로 전체 메모리 검사 → private `_validate_release_domain`으로 도메인 검사 |
| `load_json(path)` | 엄격한 디코딩으로 문법·중복 키·NaN/±Infinity 거부 → 객체/배열 루트 확인 → 파일 경로를 기준으로 `finite_tree` 실행; `1e999` 오버플로도 거부 |
| `load_release(directory, require_version=True)` | 필수 파일 존재 확인 → 정렬한 모든 `*.json`을 각각 `load_json`으로 검사 → 보관한 컬렉션에 같은 private 구조·도메인 검사 적용 |
| `load_import_snapshot(directory, require_version=True)` | `load_release`와 동일한 새 파일 검사·구조/도메인 검사 완료 → importer 소비 컬렉션·선택적 강화·version만 반환 |

`load_release`에서 제거하는 것은 파일별 전체 유한성 검사 뒤의
`finite_tree(data, 'release')` 중복 순회 하나다. 보조·알 수 없는 확장 JSON도 보관 여부와 무관하게
엄격히 읽으며, 선택적 강화·진단 컬렉션과 기록된 `version.json`도 예외가 아니다.
도메인 함수는 기존 필드·타입·범위·유일성·참조 검사를 담당하며 도메인 숫자의 유한성 검사도 유지한다.
도메인 오류와 JSON 오류의 기존 `ContractError` path·code·message와 첫 오류 순서를 유지한다.
이 분리는 [ADR 0008](adr/0008-json-validation-single-pass.md)의 내부 책임 결정이다.
공개 API에 검사 우회 flag를 추가하지 않는다.

파일별 검사 완료는 그 호출에서 디코딩한 값에만 적용한다. 스냅샷 bytes를 수정·보정하지 않으며
파일·지역·호출 사이에 검증 결과를 캐시하지 않는다. 재시도 시 변경·추가 파일을 새로 읽는다.
공개 메모리 API도 매번 보조 값과 dict/list/tuple의 중첩·공유 객체를 포함해 전체 입력을 검사하므로
이전 성공 후 외부 mutation이 생겨도 재검사한다. 입력·alias를 바꾸지 않는다.
scalar fast path에도 공유 컨테이너 identity 캐시·전역 결과 캐시·호출/build/지역 간 상태는 없다.

`require_version=False`는 version의 부재만 허용하며 필수 데이터 컬렉션을 선택적으로 만들지 않는다.
version이 제공되면 두 경계 모두 비어 있지 않은 최대 50자 문자열 계약을 계속 검사하며,
파일은 엄격한 JSON 검사도 거친다.
`load_release`는 기존처럼 version 객체 또는 부재 시 `None`을 반환하고 메모리 검사 API는 성공 시 `None`을 반환한다.
`load_import_snapshot`은 실제 제공된 `REQUIRED_COLLECTIONS + REINFORCEMENT_COLLECTIONS + ('version',)`
값의 새 dict를 반환한다. 선택적 진단 컬렉션은 기존 도메인 검사까지 마친 후
반환값에서 버리고 보조/확장 파일도 기존 strict decoding/유한성 검사를 받는다.
보관 대상만 검사하는 변경은 아니다. 두 파일 API는 missing-file 순서, sorted JSON 첫 오류와
기존 path/code/message를 동일하게 유지하며 공개 memory API의 검사 순서는 바꾸지 않는다.
consumed-only retention은 검사 완료 후 반환된 snapshot에 적용한다. 구조·도메인 검사에
필요한 진단 값은 그 검사 동안 일시 보관할 수 있으므로 최대 검증 메모리의 상한을 주장하지 않는다.

### Importer 호출 소유와 ORM 의미

[ADR 0012](adr/0012-importer-single-run-snapshot.md)의 스냅샷은 한 `handle`의 private
staging에만 속한다. 활성 handle의 base와 입력 파일 디렉터리가 그 staging인 소비 컬렉션에
한해서 재사용하고 각 mutable 소비자 및 version payload에 `deepcopy`를 제공한다.
consumer의 배열/중첩 객체 변경은 다음 consumer나 검증 원본으로 전파되지 않는다.
직접 호출·`prev/`·다른 디렉터리·미보관 파일은 매번 새 `load_json`이며 새 변경/손상을 검출한다.
재검사 시작 전에 이전 snapshot을 버리고 성공·실패·재시도에서 staging/path·previous-path·
item ID·skill-name·관계 재조정 상태를 정리하고 base를 복원한다. 검증 실패는 DB 쿼리 전에
중단하며 트랜잭션과 prev 공개/복원 및 정확한 bytes를 유지한다. global cache는 없다.

스킬/직업 SELECT prefetch는 canonical ID의 `str` 키를 사용하고 중복 legacy ID를 임의로
고르지 않는다. ambiguous 참조는 원래 consumer의 `get()`에서 `MultipleObjectsReturned`,
누락 직업은 기존 `DoesNotExist`를 발생시키며 조회 오류를 누락으로 숨기지 않는다.
기존 행의 `update=0` skip·신규 생성·`Link_Job=None`·삭제 목록의 기존 상호작용과 루프 순서,
행별 `save()` 및 created/updated audit 의미를 유지한다. bulk write나 동일 save 생략은 없다.
item membership set은 함수 내부에서만 만들며 호출자의 분류 목록·순서·우선순위와 누락
그룹 오류를 보존한다. Recipe canonical ID와 분류 정책을 바꾸지 않는다.

API/ORM 회귀는 기존 scoped `test_release_contract.py`, `test_import_safety.py`,
`harness/contract_tests.py`에서 consumed-only·diagnostic/aux strict order·nested copy·fresh
direct/prev·failure/retry/state cleanup 및 실제 save/audit/삭제·missing/ambiguous 참조를
검증해야 한다. 기존 tests/제외를 보존하고 skip을 추가하지 않는다. supplied 성능·bytes와
2691 selected zero-skip 결과는 후보 근거이며 최종 `make check` 통과를 뜻하지 않는다.
이전 full workflow timeout/readonly cleanup 실패와 후속 인계는
[하네스](harness.md#이번-importercleanup-수리의-후보-근거와-검증-대기)에 기록한다.

### Export staging과 공개·복원 경계

직렬화 전 메모리 검사와 기록 후 staging 검사는 서로 다른 입력 경계이므로 둘 다 유지한다.
메모리 실패는 staging 잔재·backup·복구 sentinel·공개 bytes·version을 건드리기 전에 중단한다.
staging 실패는 임시 출력만 정리하고 백업·승급 전에 중단한다.
유효한 staging 이후에도 기존 백업 copy·승급 전 `.promotion-in-progress` sentinel·파일별 `os.replace`,
롤백 시 이전 파일 복원과 신규 파일 제거를 유지한다. 완전한 롤백 또는 전체 성공 후에는 백업을 정리하고,
불완전한 롤백이면 백업을 보존해 다음 실행을 중단한다. 롤백 실패 marker 작성 실패도 이 정책을 바꾸지 않는다.
기록된 version은 같은 승급·롤백 대상이고 별도 `parser_version.csv`의 불일치 재시도 정책은 유지한다.
파일별 교체 중 독자의 신구 혼합 관찰과 정전 수준 내구성의 한계도 그대로다.

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
| 몬스터 스킬 | 필수 필드, CD ≥ 0, AAR ≥ 0 또는 원본 -99, 유한한 소수 SFR, 제공된 타수 ≥ 1, Monster ID 참조 |
| 맵·관계 | 맵 필드와 Link_Maps 참조, 관계 부모 존재, 부모 쌍 중복 거부, Population·TimeRespawn ≥ 0, Positions의 2차원 숫자 좌표 |
| 드롭 관계 | Chance 0..100, 정수 수량 ≥ 0, 최소 ≤ 최대, 아이템·몬스터·지도 부모 참조 |
| 속성 | 필수 필드·boolean·LevelMax 정수 값, Link_Jobs 참조, Link_Skills 문자열 배열 |
| 버프·업적 | importer 필수 필드와 숫자·boolean 타입; 버프 UserRemove는 boolean 또는 정수 0/1 |

스킬 `TypeAttack`은 `ValueType=Buff` 후보 → `ClassType` 후보 → `AttackType` 후보 순서에서
`None`과 `TOSAttackType.UNKNOWN`을 제외한 지원 값만 첫 등장 순서로 중복 없이 출력하는 배열이다.
유효한 후보가 없으면 빈 배열이며, 지원하지 않는 입력 토큰의 기존 `KeyError`는 그대로 전파한다.

`skills.parse_clean`의 비활성 판정은 `Link_Job is None`이다. `0`·빈 문자열을 같은 판정으로
확장하지 않는다. 현재 skills 순서로 `skills[str($ID)]`와 `skills_by_name[$ID_NAME]`를 삭제하며,
이름 키는 원래 타입으로 사용한다. 삭제한 원본 ID를 호출 내 set에 모아 속성·직업의
`Link_Skills`에서 같은 값을 제거한다. 문자열 `'10'`과 정수 `10`을 임의 통합하지 않는다.
이 cleanup의 원본 타입 비교와 릴리스 FK 검사의 정규화된 ID 비교는 서로 다른 책임이다.
살아남은 링크의 타입·순서·중복을 유지하고 새 list를 할당해 외부가 참조하는 이전 list를 변경하지 않는다.
숫자 키 인덱스와 대응 이름 인덱스가 별도 객체이면 각각 필터링하며, 공유 alias는
컬렉션을 넘어 객체 identity 기준으로 한 번만 처리한다. 비활성 항목이 없으면 링크 접근·교체를 하지 않는다.
삭제 ID와 처리 객체의 set은 해당 호출에서만 유효하다. 같은 객체 반복 호출, 다른 지역이나
외부에서 스킬 활성 상태·링크를 수정한 뒤 재호출할 때도 현재 데이터에서 다시 계산한다.
기존 `attributes.parse_clean`의 일괄 역방향 링크 정리와 같은 타입·순서·목록 보존 원칙을 따른다.

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

## 해결되지 않은 지도 링크

`PhysicalLinkZone`은 `/`로 구분한 원본 ClassName 목록이다.
알려진 참조는 원본 순서대로 모두 지도 ID로 변환해 기존 `Link_Maps`에 보존한다.
없는 대상은 새 지도나 ID를 만들지 않고 `unresolved_map_links`에 원문과 출처를 보존한다.
숫자 토큰도 문자 그대로 ClassName으로 취급하며, 기존 지도 ID와 같아도 ID 참조로 재해석하지 않는다.
빈 slash 토큰은 링크나 진단을 만들지 않는다.

각 진단 행에는 다음 필드가 모두 필요하다.

| 필드 | 형식·검증 규칙 |
| --- | --- |
| `Map` | 원본 지도 ID; 양의 정수 형태의 문자열 또는 정수, 최대 20자. boolean은 거부하며 릴리스의 기존 지도를 참조해야 함 |
| `MapClassName` | 비어 있지 않은 문자열; `Map`이 가리키는 지도의 `$ID_NAME`과 정확히 일치 |
| `Token` | 비어 있지 않은 원문 문자열; `Raw.split('/')`의 한 토큰과 정확히 일치하며 릴리스에 같은 ClassName의 지도가 없어야 함 |
| `Raw` | 비어 있지 않은 문자열; 전체 원본 `PhysicalLinkZone` 값을 수정 없이 보존 |
| `SourceFile` | 비어 있지 않은 unpack 루트 상대 POSIX 파일 경로; 예: `ies.ipf/map.ies` |
| `SourceField` | 문자열 `PhysicalLinkZone` |
| `SourceRow` | 헤더를 1행으로 센 CSV 레코드 번호; 2 이상의 JSON 정수. 문자열·boolean·소수형은 거부 |

`SourceFile`에는 머신 절대 경로를 내보내지 않는다. 선행 `/`, 역슬래시, `:`,
ASCII 제어문자와 DEL, 빈 경로 구성요소, `.`과 `..` 구성요소는 거부한다.
진단 배열의 null·객체 형식, 객체가 아닌 행, 필수 문맥 누락, 잘못된 타입·빈 문자열도 거부한다.
중복은 `(Map, SourceFile, SourceField, SourceRow, Token)`으로 판별하며 정수·문자열 지도 ID는 같은 ID로 비교한다.
이미 해결 가능한 ClassName을 unresolved로 표시하거나 `Raw`의 일부 문자열만 토큰으로 기록한 진단은 유효하지 않다.
이 규칙은 메모리 export, staging 스냅샷과 importer가 읽는 릴리스 스냅샷에 적용한다.

`DB.build()`는 진단 리스트를 새 객체로 초기화한다. `parse_links_maps()`도 호출할 때마다
진단과 지도 링크·층 목록을 재구성하므로 반복 호출에서 중복이나 이전 진단이 남지 않는다.
정상 층 그룹화와 ground가 없을 때의 경고·선택적 그룹화 생략은 유지한다.
정상 `Link_Maps`의 FK는 계속 릴리스의 기존 지도 ID를 엄격하게 참조해야 하며,
진단 존재가 잘못된 정상 링크를 허용하는 근거가 되지 않는다.

진단을 보존한 파싱 결과는 원본의 참조 오류를 드러내는 결과다.
계약을 통과해 export할 수 있어도 모든 참조를 성공적으로 완전히 해석했다는 뜻은 아니다.
진단의 부재만으로 전체 원본 파싱 정확성을 증명할 수도 없다.

## 몬스터 드롭의 유일성

`Item_Monster`는 몬스터·아이템 FK 쌍마다 한 행을 저장하고 DB 제약으로 중복을 거부한다.
importer는 이 쌍에 `update_or_create`를 사용한다. 원본 버전 정보만 바뀐 업데이트나
동일 릴리스 재적재도 새 관계를 만들지 않는다.
몬스터 드롭 파서는 같은 쌍의 원본 행이 여럿이면 기존 comparer와 같은 마지막 행을 출력한다.
확률·수량을 더하거나 새로운 확률 계산을 도입하지 않는다.
마이그레이션 `Monsters.0010`은 기존 중복 중 가장 큰 PK를 남긴 후 유일성 제약을 추가한다.
이후 변경된 관계는 릴리스 값으로 갱신한다. 역방향 마이그레이션은 삭제 행을 복원하지 않으므로
운영 정리 전에 해당 관계 테이블과 이전 비교 기준을 백업한다.

`Skills.element`의 nullable 모델·마이그레이션은 기존 운영 스키마를 명시한다.
원본에 속성이 없는 스킬의 값을 임의의 문자열로 바꾸지 않는다.
`Equipments.anvil_price`는 기존 운영 스키마처럼 5,000자를 제공한다. 41단계의 큰 정수 비용을
저장하는 기존 배열이 선언상 410자 제한 때문에 새 DB에서 실패하지 않도록 한다.
MySQL 하네스는 410자를 넘는 비용 배열의 실제 저장·조회도 확인한다.

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
| 지도 Prop_RewardEXPBM | 원본 RewardEXPBM의 수치 스케일 | 파서: float로 보존; 별도 단위 변환 없음 |
| 몬스터 드롭 Chance | 퍼센트 0..100 | 파서: DropRatio / 100 |
| 맵 드롭 Chance | 퍼센트 0..100 | 파서: DropRatio × 100 / BaseRatio; 분모가 없는 구형 입력만 일반 10000·unknownsanctuary 1000000 사용 |
| 맵 그룹 Chance | 퍼센트 0..100 | 맵 확률 × 그룹 가중치 / 가중치 합계 |
| CaptionRatio 계열 | 파서가 계산·변환한 값 | 파서: 0 < 값 < 1이면 100배; importer에서 재확대하지 않음 |

숫자 하나로 잘못된 단위를 판별할 수는 없다. 12.5%와 0.125%는 둘 다 유효한 범위다.
계약 검사는 타입과 범위를 확인하고, 원본 fixture의 독립적인 기대값이 변환을 검증한다.
버프·맵의 선택한 단위 경로는 world 원본 fixture로 검증한다.
아이템의 소수 초 쿨다운은 JSON에서 허용하지만 현재 DB IntegerField의 정밀도는 이번 작업에서 바꾸지 않는다.

`Prop_RewardEXPBM`은 `parse_maps()`와 `parse_links_items_rewards()`의 신규 지도 생성 경로 모두
원본 `RewardEXPBM` 열을 float로 읽는다. `0`, `12.5` 같은 값과 소수 부분을 그대로 보존하며,
퍼센트·배율 등 다른 단위로 변환하거나 `MaxHateCount`로 대체하지 않는다.
구형 고정 입력에 `RewardEXPBM` 열이 없으면 `0.0`을 기본값으로 사용한다.
계약은 제공된 공개 필드가 boolean·문자열이 아닌 유한한 숫자인지 검사한다.

## 스킬 엔진 XML의 제한된 확장

`skill_bytool.parse()`만 `parser_tidy/game_xml.py`의 helper를 통해 엔진 XML을 읽는다.
`fromstring(text)`는 `_CONTROLS`에 해당하는 literal 문자가 하나도 없으면
`ET.fromstring(text)`를 직접 호출한다. legacy masker와 marker 충돌·복원 경로를 실행하지 않는다.
이때 일반 노드 순서·속성·text·tail·표준 공백 정규화와 잘못된 XML의 `ParseError`
code·position·message는 ElementTree와 같다. 문자 참조·DTD entity는 표준 파서가 처리하므로
원문에 literal 제어문자가 없다는 이유로 `&#1;` 등을 허용하지 않는다.
제어문자가 있으면 다음의 기존 제한적 마스킹·충돌 검사·복원 경로를 그대로 사용한다.

허용하는 확장은 실제 시작 태그의 정확히 `ScriptName`이라는 속성에서,
작은따옴표 또는 큰따옴표로 둘러싼 값 안에 직접 들어 있는 XML 1.0 불허 ASCII 제어문자뿐이다.
범위는 U+0000..U+001F 중 tab(U+0009)·LF(U+000A)·CR(U+000D)을 제외한 문자다.
속성명은 대소문자를 구분하며 접두사·접미사·namespace가 붙은 다른 이름은 해당하지 않는다.

helper는 해당 문자만 충돌 없는 XML 유효 marker로 치환하고 표준 ElementTree로 엄격하게 파싱한 뒤
원래 제어문자를 `ScriptName` 속성 값에 복원한다. 문자 참조나 DTD entity 확장으로 발생하는
marker 충돌도 피하며, 따옴표 안의 `>`를 태그 끝으로 오인하지 않는다.
표준 ElementTree가 제공하는 트리·노드 순서·속성·텍스트·tail을 보존하고 정상 XML의 표준 처리도 유지한다.
노드를 버리거나 문자열 전체에서 제어문자를 삭제하는 복구를 하지 않는다.

다른 속성·텍스트·tail의 불허 제어문자, comments·CDATA·PI 안의 가짜 `ScriptName` 속성에 있는 불허 제어문자,
`&#1;` 같은 불허 문자 참조와 그 밖의 잘못된 markup은 계속 `ElementTree.ParseError`다.
helper가 이를 복구하지 않으며, 호출자인 `skill_bytool.parse()`의 기존 ParseError 경고 처리도 유지한다.
원본 파일이나 bytes는 쓰지 않는다. 기존 UTF-8 replacement 디코딩 동작과 Lua 함수 실행 의미는 확장하지 않는다.

## 맵 생성점 파일 인덱스의 호출 내 수명

`maps.parse_links_npcs`는 map CSV에 행이 있을 때 처음 필요한 시점에만
현재 `PATH_INPUT_DATA/ies_mongen.ipf`를 `os.listdir`로 한 번 조회한다.
소문자 이름을 원래 파일명에 매핑해 anchor/gentype 조회에 같은 인덱스를 사용한다.
대소문자만 다른 이름이 겹치면 정렬 없이 listing의 마지막 항목을 선택한다.
빈 directory 인덱스도 재사용하며 이름이 없으면 기존 literal 파일명으로 읽기를 시도한다.
빈 map 입력에서는 생성점 directory를 조회하지 않아 새 조회 오류를 만들지 않는다.
map 행이 있으면 directory 부재·권한 오류는 기존처럼 전파한다.

인덱스는 함수 반환·오류 시 수명이 끝나며 전역·함수간 캐시를 두지 않는다.
같은 객체 재호출, 지역·원본 경로 변경, 파일 추가·삭제·이름 변경 뒤 호출은 새 listing으로 구성한다.
한 호출 중 directory 변경을 map마다 다시 조회하는 방식은 사용하지 않는다.
map/NPC/item linkage, 아이템 canonical ID, 중심·MAP_SCALE·bbox 좌표 변환,
동일 대상 생성점과 Population 병합·TimeRespawn 변환·원본 순서는 유지한다.
없는 anchor/gentype 파일, 미해결 NPC/item과 anchor 없는 GenType의 기존 생략 동작도 유지한다.
이 인덱스 변경이 미해결 항목을 새 관계나 진단으로 만들지는 않는다.
직접 호출은 기존 관계 배열에 추가하며, 상위 `maps.parse_links`의 관계 초기화와
지도 미해결 진단 재구성·몬스터 미해결 진단 보존 책임을 바꾸지 않는다.

## 실제 릴리스 호환과 명시적 보정

- ClassName 참조는 이름의 100자 제한을 따른다. 엔티티 숫자 ID 제한과 구분한다.
  대소문자를 구분하며 importer는 검증된 ClassName → canonical ID 인덱스로 레시피·컬렉션·젬 FK를 조회한다.
  MySQL의 이름 검색 collation이 `GoldMoru_Box_S`와 `goldmoru_box_S`를 동일하게 취급해도 두 아이템을 유지한다.
- `Default_Recipe`(910000)는 item.ies의 일반 제작서 템플릿이며 RECIPES 분류 대상이 아니다.
  다른 활성 레시피의 분류 누락은 계속 거부한다.
- 이름·타깃이 null이고 Link_Materials가 없는 RECIPES 행은 비활성 원본 placeholder다.
  일반 Items 행은 유지하지만 Recipes·재료·타깃 관계를 만들지 않으며 기존 crafting 행도 제거한다.
  이름이나 타깃이 있는 레시피의 재료 누락은 오류다.
- TimeCoolDown·플레이어 스킬 Element의 null은 원본/ORM 값을 유지한다.
  AnvilPrice가 빈 배열이고 등록 여신 강화 정보가 없는 장비만 AnvilATK/DEF의 null을 허용한다.
  선언한 Lua 계산 실패는 여전히 공개 전에 중단된다.
- TypeEquipment=Arcane의 기존 공개 데이터에서 최대 공격력 미제공에 쓰던 MAXATK=0 호환값을 유지한다.
  최소·최대 값을 임의로 바꾸지 않는다. 다른 장비와 몬스터의 최소·최대 역전은 거부한다.
- 몬스터 스킬 SFR은 원본 소수 문자열도 허용하고 FloatField에 소수를 보존한다.
  기존 `int()` 실패 후 0으로 저장하던 경로는 제거한다. AAR의 원본 -99는 보존하되 다른 음수는 거부한다.
- 몬스터·맵 드롭 및 맵 아이템 스폰은 source ClassName으로 `recipe-<id>` FK를 출력한다.
  같은 숫자 ID를 가진 일반 아이템과 레시피를 구분한다. 원본 아이템 `$ID`는 그대로다.
- 파서는 몬스터·맵 드롭의 같은 부모/아이템 쌍을 마지막 원본 행으로 정리한다.
  확률을 합산하지 않는다. 몬스터 드롭은 모든 원본 행의 값 검사를 먼저 수행해 잘못된 앞 행을 숨기지 않는다.
  완성된 JSON의 중복 관계는 공통 계약에서 계속 거부한다.

`harness/release_repair.py`는 기존 JSON을 **새 디렉터리**로 보정하는 명시적 도구다.
현재 지역 unpack revision과 릴리스 버전이 일치해야 하며 원본 IES에서 드롭을 재구성한다.
550 여신 장신구의 정수 문자열과 소수 몬스터 스킬 계수도 정상 타입으로 출력한다.
원본 JSON·prev·DB·unpack·버전 CSV를 변경하지 않으며 전체 계약 통과 후에만 보정 결과를 쓴다.
다른 지역보다 먼저 파싱된 kTOS/jTOS의 과거 iTOS 출처 버전은 보고서에 남기고 현재 출처 버전을 기록한다.
공개 적용은 이 도구의 실행과 별개이며 검증 결과와 백업을 갖춘 별도 데이터 보정 작업으로 수행한다.
importAll에는 잘못된 확률을 임의로 축소하거나 계약을 우회하는 자동 fallback을 넣지 않는다.

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
운영 MySQL·기존 DB의 일괄 보정은 이번 변경 범위에 포함하지 않는다.

이번 지도·XML 수정의 회귀 테스트는 작성된 상태이며 이 문서 작업자는 실행하지 않았다.
`test_world_source_fixture.py`와 독립적인 `expected_world.json`에는 `MaxHateCount`와 다른
RewardEXPBM의 0·12.5·2.5 기대값, 두 생성 경로의 열 누락 시 0.0 호환,
알려진 링크 순서와 정확한 진단·export·반복 실행·빌드 초기화 기대값이 있다.
`test_release_contract.py`에는 잘못된 참조·필수 문맥 누락·타입·형식·중복 거부,
이전 릴리스 호환과 정상 `Link_Maps` FK의 엄격한 검사에 대한 테스트가 있다.
`test_game_xml.py`에는 양쪽 따옴표·quoted `>`·marker 충돌·정상 XML·잘못된 markup,
comments·CDATA·PI의 가짜 속성, 허용 범위 밖 제어문자의 ParseError 기대값이 있다.
합성 XML의 정상 버전과 제어문자 버전은 같은 메타데이터를 기대하며,
독립적인 buff name `Regression_ShieldBuff`, 2.5초·75%와 모든 노드·원래 ScriptName 값·파일 bytes 보존을 확인하도록 작성했다.
이 설명은 테스트 통과 보고가 아니며, 실제 패치 407263의 kTOS·iTOS·jTOS 전체 파싱 정확성은 아직 검증하지 않았다.

`make check` 전체, 현재 원본을 사용하는 별도 격리 세 지역 검증, Claude 검토, Git 작업,
GitHub 앱 게시, 성공 CI 후 머지와 원격·로컬 병합 브랜치 정리는 main Codex의 후속 책임이다.
이번 네 최적화의 추가 회귀 명세도 문서 작업자는 실행하지 않았다.
`test_game_xml.py`는 legacy masker를 호출하면 실패하는 fixture로 무control 직접 파싱을 구분하고,
표준 트리와 오류의 동일성·문자 참조/DTD marker 충돌·ScriptName 경계를 비교한다.
`test_release_contract.py`는 파일별 finite_tree 횟수와 마지막 재순회 부재,
독립 메모리 API의 중첩·공유 객체 mutation 재검사, 모든 파일 역할의 엄격한 JSON 오류와
정확한 도메인 path·code·message, memory-before-write·staged-before-promotion·version·수정 후 재시도를 명세한다.
scalar fast path의 회귀 근거는 primitive 잎 사이의 중첩·하위 클래스 실패,
내장 scalar와 같다고 주장하는 metaclass, scalar 루트와 정확한 float 잎의 비유한 값,
알 수 없는 객체의 기존 동작 및 정확한 첫 오류 path·code·message·문자열을 포함해야 한다.
공개 `validate_release`의 공유 객체 mutation과 `load_json`·`load_release`의 파일 교체 후
성공→실패→수정 재시도에서 반환값·원본·alias·파일 bytes 보존을 확인한다. 이 명세의 존재는 통과 증거가 아니다.
`test_atomic_release.py`의 기존 백업·sentinel·승급 실패·불완전 롤백·복구 경계도 유지 대상이다.
`test_combat_source_fixture.py`의 독립 synthetic 기대값은 원본 ID 타입·삭제 순서·생존 중복,
별도 이름 객체·컬렉션간 alias의 객체당 한 번 처리·외부 list 보존·비활성 0건·재호출·지역 격리를 다룬다.
`test_world_source_fixture.py`는 독립 생성 관계·좌표·인구 기대값과 directory 조회 횟수,
빈 map·빈 index·조회 오류·대소문자 충돌의 마지막 항목 우선·지역/경로/파일 변경 재조회,
직접 호출의 추가와 상위 relink의 초기화를 구분한다.

제공된 prototype/local diagnostic 수치와 기존 XML 테스트 통과 관측은
최종 구현의 전체 회귀·전체 파서·CI 성공 또는 누적 개선율의 증거가 아니다.
수치와 측정 조건의 한계는 [ADR 0008](adr/0008-json-validation-single-pass.md#진단-근거와-검증-상태)에 기록한다.
최종 지역별 전체 실데이터 및 누적 성능 비교는 메인 `/root`가 별도로 수행한다.
이번 scalar 순회 변경의 문서 작업자는 architecture·이 계약·harness만 수정하며 기존 사용자 변경을 보존한다.
ADR 0008의 책임을 유지하는 국소 구현 개선이므로 새 ADR이나 기존 ADR 변경은 필요하지 않다.
독립 의미 검토·오케스트레이터의 전체 `make check`와 반영 후 메인의 최종 전후 실데이터 시간·지역별
JSON bytes 비교는 아직 필요한 증거이며, 어떤 GitHub 게시 도구 호출보다 먼저 확인해야 한다.
측정·검토 인계의 조건은 [하네스 안내](harness.md#최적화-회귀와-성능-근거)에 둔다.
검사·benchmark·네트워크·다운로드·cron·importAll·Git·workflow·재위임은 수행하지 않는다.
기존 model/provider/effort/network/worker 설정과 기본 Git 역할,
GitHub CI 성공 확인 후 SHA 고정 merge 정책은 유지한다. 문서 의미 검토는 실행·게시 완료의 증거가 아니다.
