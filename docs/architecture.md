# 프로젝트 지도와 데이터 경계

TavernofSoul은 다운로더, 파서, Django 적재·서빙의 세 영역으로 구성된다.
`harness/`는 개발 중 이 영역을 검증하는 공통 실행 환경이다.

여신 강화 IES의 발견과 지원 등록은 별개다. `EQUIPMENT_REINFORCE_IES`에 등록한 파일만
강화 수치와 Lua 조회 테이블에 제공하며, 미등록 파일은 별도 JSON 진단과 경고에 남긴다.
560 재료 생성은 파일 존재를 확인한 뒤 무기/방어구 함수만 호출한다.
Gems의 스킬 FK 적재는 해당 릴리스의 스킬 적재 이후, 같은 importer 트랜잭션에서 수행한다.
강화 테이블/재료는 GoddessReinforcement에, 젬 소켓 보너스는 Gems에 적재한다.
장비의 강화 누적값은 파서가 원본 Lua로 계산하며 UseLv와 재료 그룹을 함께 저장한다.
상세 화면 계산기는 DB의 누적값·확률·재료를 사용한다. 새 컬렉션도 같은 importer 트랜잭션과 prev 롤백에 포함한다.
별도 브라우저 하네스는 이 원본 fixture를 메모리 SQLite에 적재한 임시 Django 서버와 실제 Chromium을 연결한다.
Ubuntu 20.04 ARM 호스트에서는 엔진만 지원 Ubuntu 컨테이너로 실행하며 운영 DB·JSON·cron을 사용하지 않는다.
고정 실데이터 하네스는 iTOS·kTOS 550/560 장비·젬의 원본 hash/revision을 보존하고 같은 격리 경로로 검사한다.
별도 운영 smoke는 공개 두 도메인에 GET/HEAD만 보내며 HTTPS·정적 자산·검색·계산기·젬 연결을 확인한다.
실데이터 샘플과 운영 도메인 결과는 기본 오프라인/합성 fixture 결과와 구분한다.

```text
패치 서버
  → downloader/downloader.py + IPFUnpacker / unpacker_pak
  → <region>_unpack/, Translation/, 다운로드 버전 CSV
  → parser_tidy/main.py + ToS_DB
  → TavernofSoul/JSON_<region>/*.json + version.json
  → ipfparser.management.commands.importAll
  → 지역별 Django DB + JSON_<region>/prev/
  → Django ORM / views / templates / API
```

## 책임과 소유권

| 영역 | 책임 | 주요 진입점 |
| --- | --- | --- |
| 다운로더 | 패치 조회·다운로드·복호화·압축 해제·번역 준비 | `downloader/downloader.py` |
| 파서 | 게임 형식 해석·도메인 값·관계 구성·JSON 출력 | `parser_tidy/main.py`, `DB.py` |
| Django importer | JSON 차이 계산·ID 정규화·DB 적재·비교 기준 갱신 | `importAll.py` |
| Django 서빙 | 검색·관계 조회·화면/API 제공 | `TavernofSoul/urls.py`, 각 앱 |
| 개발 하네스 | 격리 환경·검증 실행·기계가 읽을 수 있는 결과 | `Makefile`, `harness/runner.py` |

운영에서는 `cron_<region>.sh`가 다운로드, 파싱, 적재를 순서대로 호출한다.
파서 실패 시 import를 중단하는 기존 동작은 `test_cron_guard.py`가 검증한다.
다운로더는 변경 0, 변경 없음 1, 실패 2를 반환한다.
모든 지역 cron의 다운로드 실패 중단은 `downloader/tests/test_downloader.py`가 검증한다.

## 다운로더 → 파서 계약

- 다운로드는 임시 `.part` 파일에서 완료한 뒤 공개한다. 비어 있거나 응답 길이가 다르면 실패한다.
- data 패치는 IPF 도구의 복호화·추출과 unpack 디렉터리 복사를 거친다.
- release 패치는 PAK 해제와 지역별 번역 복사를 거친다.
- 각 스트림의 버전 CSV는 해당 패치의 해제·복사 성공 후 원자 교체로 전진한다.
  여러 패치 중 실패가 발생하면 마지막 완료 버전부터 재시도한다.
- 실패 시 cron은 파서를 실행하지 않는다. 개별 파일 복사까지는 일부 반영되었을 수 있으므로
  디렉터리 전체의 원자 교체나 데이터셋 무결성 manifest로 설명하지 않는다.
- 하네스는 실제 Python 다운로드·PAK 해제를 검사한다. 네이티브 IPF는 대체 실행 파일을 사용한다.

## 파서 → importer 계약

- 입력 JSON은 컬렉션별 객체 또는 배열이다. `version.json`에는 비어 있지 않은 `version`이 필요하다.
- 일반 엔티티는 `$ID`, `$ID_NAME`을 가진다. 관계 컬렉션은 해당 부모 ID 필드를 가진다.
- 아이템의 이름별 인덱스는 `items_by_name.json`; 유형별 분류는 `item_type.json`이다.
- 레시피 이름은 `item_type.RECIPES`에 포함되어야 한다. importer는 레시피의 ID에
  `recipe-`를 붙여 일반 아이템과 동일한 숫자 ID를 공유해도 둘을 보존한다.
- 레시피 재료·대상은 아이템의 `$ID_NAME`을 참조한다. 누락 참조는 적재 실패로 처리한다.
- 패키지 토큰은 파서가 `PackageContents`로 해석한다. importer는 이를 JSON 문자열로 저장한다.
  미해결 참조는 파서에서 `unresolved`로 구분한다.
- 파서는 JSON을 staging에 직렬화·검증한 뒤 공개 파일을 교체한다.
  교체는 파일별이며 실패 시 백업으로 롤백한다. 독자가 실행 중 항상 단일 버전을 본다는 보장은 없다.
- `parser_version.csv`와 공개 `version.json`은 저장 위치가 다르다.
  불일치 시 파서를 재실행하는 기존 로직을 유지한다.
- importer는 입력 스냅샷을 임시 디렉터리에 준비하고 DB 트랜잭션 안에서 적재와 `prev/` 공개를 수행한다.
  예외가 발생하면 이전 비교 기준을 복원한다. 프로세스 강제 종료·정전 전체의 원자성은 별도 문제다.

파서와 importer는 `ipfparser/contracts.py`의 공통 검사로 필수 컬렉션·필드·타입,
정규화한 ID 유일성·참조·수치 범위를 확인한다. 파서는 메모리와 기록한 staging 데이터를,
importer는 복사한 스냅샷을 DB 쿼리 전에 검사한다.
검사 범위·기존 sentinel과 optional 값·단위의 소유권은 [데이터 계약](data-contracts.md)을 참고한다.
모든 자산·보조 인덱스·게임 계산식의 schema를 강제하는 것은 아니다.

## 첫 검증 경로

`harness/fixtures/minimal_release.json`은 재료, 숫자 ID가 겹치는 레시피,
패키지 원시 토큰과 importer에 필요한 빈 컬렉션을 포함한다.

```text
고정 입력
  → 실제 resolve_package_contents
  → 실제 ToS_DB.export (임시 JSON 디렉터리)
  → 실제 importAll (메모리 SQLite, 실제 migrations)
  → ORM 관계 확인
  → Django test client로 아이템 검색·상세 HTML 확인
```

네트워크 다운로드, 전체 원본 파일 파싱, 아이콘/맵 생성, 운영 MySQL, 브라우저 JavaScript는
이 첫 경로의 검증 범위에 포함되지 않는다.

## 아이템 원본부터 서빙까지

`harness/fixtures/parser/`는 직접 작성한 CSV 형식 IES, XML/TSV 번역,
Lua 계산식과 독립적인 기대값을 포함한다. 입력 파일 안내는
[fixture README](../harness/fixtures/parser/README.md)를 참고한다.

```text
임시 unpack IES + 번역 XML/TSV + 공유 상수/Lua
  → 실제 parse_xac + translation.makeDictionary + items.parse
  → 실제 ToS_DB.export
  → 실제 importAll + ORM
  → 아이템·장비·레시피·패키지 검색/상세 HTTP
```

원본 ID는 문자열이고 JSON의 쿨다운은 ms를 초로, 장비 내구도는 원본의 1/100로 변환한다.
Lua 계산 결과는 JSON 숫자로 출력한다. 하네스는 장비 수치와 소수 무게·거래 플래그,
레시피 재료·대상, 패키지 정상/미해결 참조를 검사한다.
같은 입력의 반복 실행과 변경 입력의 재계산, 파싱 실패 시 공개 JSON·버전 보존 및 복구를 확인한다.
DB의 버전은 이력으로 쌓이며 같은 버전은 중복 생성하지 않는다.

이 경로는 아이템 도메인 중 작은 선택 범위를 검증한다.
네이티브 바이너리 변환, 게임 전체 Lua 계산식, 다른 도메인, 전체 `main.py` 실행은 포함하지 않는다.

## 스킬·몬스터·드롭 연결

`harness/fixtures/combat/`는 아이템 샘플에 직업·스킬트리·스킬·몬스터·드롭 IES,
스킬 도구 XML과 Lua를 더한다. 실제 파서 모듈을 운영 순서에 따라 호출하고
같은 JSON을 Django로 적재한다. 세부 입력은 [fixture 안내](../harness/fixtures/combat/README.md)에 있다.

- 직업과 플레이어 스킬의 ID는 문자열이고 스킬의 `Link_Job`은 직업 ID를 참조한다.
- 스킬 비율은 파서가 `0 < 값 < 1`인 계산 결과를 100배해 출력하고 importer는 재확대하지 않는다.
  기본 쿨다운과 레벨별 쿨다운은 ms이며 기본 쿨다운의 화면 표시는 초다.
- 몬스터 ID는 JSON에서 숫자다. 갑옷 `Iron`은 `Plate`, `WIDLING`은 `BEAST`로 변환한다.
  field status 보정은 파일명 정렬 순서로 적용하고 EXP·JOBEXP 의미를 유지한다.
- 몬스터 스킬은 `SkillType`으로 연결 ID 목록을 만들고 importer는 타수와 현재 연결 목록을 저장한다.
- 몬스터 드롭은 아이템 ClassName을 아이템의 원본 ID로 해결한다.
  확률은 `DropRatio / 100`의 퍼센트이며 수량 최소·최대는 정수다.
  미해결 참조는 DB 관계 대신 `unresolved_drops.json`에 문맥을 남긴다.
- 출처 지역·입력 버전은 `item_monster.json`과 `build_provenance.json`에 기록한다.
  입력 버전은 다운로드 revision에서 읽으며 공개 파서 버전과 다를 수 있다.
  출처 필드는 현재 ORM에 별도로 저장되지 않는다.
- 지역 보충 스킬 데이터는 `PATH_INPUT_DATA`의 프로젝트 루트 아래 JSON에서 읽는다.
  임시 원본 테스트가 코드 저장소의 운영 JSON에 의존하지 않도록 한다.

하네스는 반복 실행, 변경 수치와 관계 삭제, 파싱 실패 시 JSON 보존,
importer 실패 시 DB·이전 비교 기준·버전 복원과 재시도를 검사한다.
이는 작은 iTOS 샘플의 검증이며 전체 원본 파이프라인이나 운영 MySQL을 대신하지 않는다.

## 맵·속성·버프 연결

`harness/fixtures/world/`는 아이템·combat 원본에 지도/드롭/생성점·속성·버프 IES와 번역을 더한다.
입력과 계산 근거는 [world fixture 안내](../harness/fixtures/world/README.md)를 참고한다.

- 속성은 스킬 정리 전에 파싱·연결·정리한다. Link_Skills는 스킬 ClassName,
  스킬·직업의 Link_Attributes는 속성 ID이며 보충 연결도 같은 규칙을 쓴다.
- 맵 직접 확률은 일반 맵에서 DropRatio/100, unknownsanctuary는 /10000이다.
  그룹은 같은 기준의 맵 확률에 그룹 내 가중치/합계를 곱한다. 음수 가중치는 실패한다.
  수량은 미제공 호환값 0이고 미해결 아이템은 드롭 관계 대신 문맥과 출처를 남긴다.
- 지도 ID 연결의 미해결 원본은 실패한다. 추가 층 목록에는 2층 이상을 넣고 1층 자기 참조를 만들지 않는다.
- 생성 좌표는 지도 중심·MAP_SCALE·bbox로 변환하고 생성 수를 병합한다.
  RespawnTime(ms)은 JSON TimeRespawn(초)으로 변환한다. importer는 좌표를 평탄한 문자열 배열로 저장한다.
- 버프 네 원본 파일을 정해진 순서로 읽고 같은 ID는 뒤 파일이 우선한다.
  Common_는 제외하고 optional 그룹은 null을 유지하며 ApplyTime은 ms다.
- 반복 맵 관계 구성은 생성점·층·지도 미해결 참조를 새로 만든다. 몬스터 미해결 참조는 보존한다.

하네스는 JSON부터 DB·HTTP까지 단위·관계·수치 변경·관계 삭제·보존과 재시도를 확인한다.
이 경로는 지도 이미지 생성·자르기나 브라우저 canvas를 실행하지 않는다.
전체 지역·모든 유형·속성 Lua 비용/해금 계산·운영 MySQL은 별도 검증이다.

## MySQL과 CI 경계

기본 `make check`는 네트워크나 외부 DB가 필요 없는 SQLite 검증이다.
`make check-mysql-container`는 별도의 MySQL 8.4.11 컨테이너를 만들고 같은 통합 경로를 실행한다.
전용 스키마·계정 권한·루프백 포트를 제한하며 JSON·캐시·미디어는 기존 임시 하네스 경로를 유지한다.
실제 migrations, strict SQL, InnoDB, utf8mb4, ListCharField와 검색 정규식,
DB 오류 발생 후 DB·Version·prev 보존을 확인한다.

`.github/workflows/harness.yml`의 SQLite/MySQL 작업은 각각 새 환경에서 실행하고 결과를 artifact로 보관한다.
고정 서버 프로필과 작은 fixture의 호환성 검증이며 운영 DB 접속·배포·전체 데이터 적재는 수행하지 않는다.
접속 제한·명령·보고서와 운영 환경 차이는 [하네스 사용법](harness.md)을 참고한다.

## 지역별 경로와 추가 원본 유형

`harness/fixtures/regional/`은 직접 작성한 CSV IES·XML/TSV·Lua와 지역별 공유 상수를 사용한다.
5개 지역의 번역/원문 처리, 스킬 보충 JSON과 드롭 데이터셋 출처 규칙을 같은 실행 경로에서 확인한다.
기존 아이템·combat·world 도메인에 마법 무기·방어구·카드·컬렉션을 추가하며
원본 파싱 → JSON → 실제 importer → ORM/HTTP와 실패 시 보존·재시도를 SQLite/MySQL에서 검사한다.

명시한 장비 RefreshScp의 계산 실패는 공개 전 파서 실패로 전파한다.
드롭은 iTOS 데이터셋 디렉터리가 우선이고 개별 파일을 현재 지역에서 섞어 가져오지 않는다.
선택 사유는 현재 지역 데이터셋의 존재 여부를 구분하며 실제 데이터 출처와 revision을 기록한다.
이 검증은 합성 샘플의 경로 검사다. 전체 지역 게임 데이터·schema 차이·게임 계산식을 대신하지 않는다.
입력·기대값·검증 단계별 경계는 [regional fixture 안내](../harness/fixtures/regional/README.md)를 참고한다.
