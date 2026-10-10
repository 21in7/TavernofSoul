# 프로젝트 지도와 데이터 경계

TavernofSoul은 다운로더, 파서, Django 적재·서빙의 세 영역으로 구성된다.
`harness/`는 개발 중 이 영역을 검증하는 공통 실행 환경이다.
개발 에이전트는 `harness/agent-models.json`의 역할별 설정으로 Codex/Claude Code CLI를 사용한다.
인증·모델 연결은 [에이전트 모델 연결](agent-models.md)에 있으며 게임 운영 파이프라인과 분리한다.
개발 작업 접수 단계의 [Jev 판단](triage.md)은 경로 규칙에 판단 응답을 더해 배정 추천을 기록한다.
단독 판단 명령은 shadow 모드다. [자동 작업 실행](workflow.md)은 이 추천을 받아
필요 시 계획 → 담당 역할 실행 → Claude 검토 → 필수 하네스 검증 → 범위 내 소스 반영을 연결한다.
기존 사용자 변경을 담은 별도 작업 사본을 사용하며 운영 파이프라인과 분리한다.
Claude Code 기반 구현·검토 역할은 [Jev 대화 기록 압축](compaction.md)을 사용한다.
작업 접수 판단과 별개의 세션 훅이며 기존 TypeSafe 키와 고정된 플러그인 소스를 사용한다.

여신 강화 IES의 발견과 지원 등록은 별개다. `EQUIPMENT_REINFORCE_IES`에 등록한 파일만
강화 수치와 Lua 조회 테이블에 제공하며, 미등록 파일은 별도 JSON 진단과 경고에 남긴다.
명시적으로 등록하지 않은 원본 IES는 파일 발견만으로 자동 지원하지 않는다.
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

운영에서는 로컬 파일인 `cron_<region>.sh`가 다운로드, 파싱, 적재를 순서대로 호출한다.
Git 추적 대상은 5개 지역(`itos`, `jtos`, `ktos`, `ktest`, `twtos`)의
`cron_<region>.sh.example`이며 실제 지역 cron과 settings는 서버의 로컬 운영 파일이다.
파서·import 실패 중단은 `parser_tidy/tests/test_cron_guard.py`가 추적되는 예제를 읽어 검증한다.
다운로더는 변경 0, 변경 없음 1, 실패 2를 반환한다.
모든 지역 예제의 다운로드 실패 중단은 `downloader/tests/test_downloader.py`가 검증한다.
필수 예제가 없으면 skip 대신 실패하며 운영 cron은 실행하지 않는다.
테스트는 로컬 운영 cron으로 대체하지 않는다. 다운로드·import 반환 코드 가드만 분리해
검사하고 파서 실패 가드와 지역 명령 순서를 읽어 확인하므로 운영 파일 없이도 검증할 수 있다.

## 추적되는 설정과 로컬 운영 환경

`TavernofSoul/TavernofSoul/settings_common.py`는 공통 Django 앱·미들웨어·템플릿 등
소스에 포함할 기본 설정을 제공한다. 운영 DB·비밀값·지역 설정 파일은 읽지 않는다.
`settings_harness.py`는 이 common을 가져오며 로컬 운영 `settings_test.py`와 분리된다.
메모리 SQLite, 임시 JSON, `REGION='ktos'`, 오프라인 전용 키와 템플릿 context processor는
하네스에서 재정의한다. `settings_harness_mysql.py`도 추적되는 하네스 설정으로 유지한다.

새 서버에서 원본 운영 파일이 없는 경우에만 `settings_region.py.example`과
해당 지역 `cron_<region>.sh.example`을 `cp -n`으로 복사한다.
설정 파일명과 `TAVERN_REGION`은 같은 지역으로 맞추며, 복사한 로컬 cron의 설치 경로·
인터프리터·가상환경 경로는 새 서버 환경에 맞춰 준비한다.
예를 들어 저장소 루트에서 kTOS를 준비하는 명령은 다음과 같다.

```bash
cp -n TavernofSoul/TavernofSoul/settings_region.py.example TavernofSoul/TavernofSoul/settings_ktos.py
cp -n cron_ktos.sh.example cron_ktos.sh
```

**기존 운영 서버에서는 예제를 복사하거나 기존 파일을 덮어쓰지 않는다.**
새 설치에는 `TAVERN_REGION`, `TAVERN_DJANGO_SECRET_KEY`, `TAVERN_ALLOWED_HOSTS`와
`TAVERN_DB_NAME`, `TAVERN_DB_USER`, `TAVERN_DB_PASSWORD`, `TAVERN_DB_HOST`, `TAVERN_DB_PORT`를
서버 환경에 모두 설정해야 한다. 누락·빈 값은 명확한 설정 오류로 실패한다.
지역은 `itos`, `jtos`, `ktos`, `ktest`, `twtos`, `test`만 허용하며 `DEBUG=False`다.
`JSON_ROOT`는 `BASE_DIR / ('JSON_' + REGION)`, 변경 기록은 `BASE_DIR / 'changes' / REGION`,
정적 출력은 `BASE_DIR / 'staticfiles' / REGION`으로 분리한다.
예제 설정을 읽는 것만으로 실제 DB에 접속하지 않는다. 호스트와 웹훅 등 상세 준비는
[하네스 사용법의 신규 서버 안내](harness.md#신규-서버의-로컬-운영-파일)를 따른다.

운영 INI·지역별 가상환경(`3.8/`, `.venv/`, `venv/`)·`backups/`·빌드 파일의 Git 추적 제거는
실제 디스크 삭제가 아니다. 서버 파일은 그대로 보존하며 새 clone에는 환경 설치가 필요하다.
공통·하네스 설정, `*.example`, `harness/pytest.ini`와 고정 fixture는 계속 추적한다.
이번 정리는 과거 Git 기록을 재작성하지 않는다.
`.gitignore` 추가만으로 이미 추적 중인 파일이 Git 추적에서 해제되지는 않는다.
따라서 이 소스 준비 단계와 서버 파일을 보존하는 후속 추적 해제는 별도 작업이다.
`/challenge.json text eol=lf`는 해당 JSON의 Git 정규화만 지정하며 운영 로컬 CRLF 바이트를
변경하지 않는다. 다른 파일 전체의 줄끝 정책을 바꾸지 않는다.

현재 공개 `origin/master` 작업 사본에는 원본 서버의 개인 설정·cron·가상환경이 제공되지 않았다.
이 단계는 안전한 소스·예제·문서 준비까지이며 보호 파일의 추적 제거와 별도 IPFUnpacker 저장소의
빌드 ignore는 메인 `/root`가 별도 Git PR로 수행한다.
obsolete parsing-server CI 3개도 메인 `/root`에서 로컬에 그대로 보관하고 저장소별 private exclude로
제외할 예정이다. 이 단계에서는 공개 workflow를 만들거나 수정하지 않는다.
실행기가 전체 `make check`를 수행하며 작업자는 테스트·cron·다운로더·운영 import·Git 명령을
실행하지 않는다. 후속 검증·커밋·PR·CI 성공 확인·머지는 현재 작업자 범위 밖이다.

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

## 파서 초기화 비용과 상태 경계

`iesutil.load()`는 한 호출에서 길이 128 이하 문자열 token의 변환 결과인 immutable scalar를
최대 4096개 재사용한다. 변환은 기존 `int` → 실패 시 `float` → 실패 시 원값 순서이며,
NaN·누락 셀의 `None`·초과 필드의 mutable list는 캐시에 넣지 않는다.
문자열 cache hit은 길이 판정과 변환을 생략하며, miss에서 기존 길이 128·용량 4096 제한을 적용한다.
행과 list는 독립적으로 유지하고, 캐시는 반환·오류 시 수명이 끝난다.
매 load는 원본 파일을 다시 읽으며 호출·파일·지역 사이에 캐시를 공유하지 않는다.
이 변환은 raw 장비 CSV의 문자열 UseLv를 Lua로 전달하는 `items.parse_equips` 경로와 별개다.

`items.parse_items`와 `items.parse_equips`는 처리 완료된 원본 CSV 행을 추가 목록에 누적하지 않는다.
필요한 출력 객체와 Lua 참조는 그대로 유지한다.

`items.parse_equips`는 출력 `EQUIPMENT` 이름 목록의 기존 list 객체·순서·중복을 보존하며,
새 이름은 원본 행의 첫 등장 순서로 한 번만 추가한다.
중복 확인은 한 호출 안의 임시 set으로만 수행하고, 다음 호출은 현재 목록에서 set을 다시 구축해
호출·파일·지역 사이에 공유하지 않는다.
이름이 이미 있어도 모든 장비 행과 Lua 수식 처리를 계속 수행하며 후속 행의 값 덮어쓰기를 유지한다.

legacy Lua 줄 전처리는 quoted index → require 제거 → method 변환 순서와 기존 regex/replacement를
유지한다. private compiled regex를 재사용하고 각 단계의 현재 줄에 literal substring guard를
적용해 매칭이 불가능한 경우에만 치환 호출을 생략한다. 이는 전처리 비용만 줄이며,
`luautil.init()`는 매번 새 LuaRuntime을 만들고 실패 가능한 초기화 전에 레지스트리를 reset한다.
원본 로딩·함수 분리·override 보호·whole-module 실행과 필수 함수 실패 전파 계약은 유지한다.
함수 선언 감지도 기존 패턴과 기본 flags를 private compiled regex로 재사용하며,
전처리된 현재 줄에 필수 literal `function`이 없을 때만 매칭을 생략한다.
`harness/parser_fixture.py`의 `isolated_parser_state`도 새 runtime/레지스트리와 격리된
아이템·스킬·몬스터 상태를 사용하고 `finally`에서 기존 상태를 복구한다.

제공된 로컬 kTOS 진단에서 cProfile의 초기화 내 `iesutil.load` 41회는 self 2.84s/total 3.43s,
`init_runtime`은 total 3.99s였다. 이는 profiler를 켠 부분 실행 시간이다.
별도의 profiler 없는 fresh 6-worker 초기화 측정은 기존 중앙값 약 6.008s,
IES/Lua 결합 후보 약 3.002s였으며 매번 새 runtime을 생성했다.
전체 `LUA_SOURCE`와 로드된 IES rows의 digest, functions 12257/tables 32 일치는
제공된 로컬 진단 사실이며 최종 적용 코드의 검증 결과나 전체 pipeline wall 성능 보장이 아니다.
알려진 CSV quoting 오류 한 행은 명시된 로컬 diagnostic 복사본에서만 대체했다.
원본 게임 데이터·진단 스크립트·전체 로그는 이번 승인 문맥에 제공되지 않았으며,
최종 코드의 독립 benchmark는 `/root`가 별도로 확인한다.

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
- 스킬 `TypeAttack`의 중복 제거는 후보의 첫 등장 순서를 보존한다.
  이는 기존 set 순회에서 발생하던 Python hash seed별 `TypeAttack` 배열 순서와
  `skills.json`·`skills_by_name.json`의 변동을 제거한다.
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
  같은 WorldMap 묶음의 1층 좌표가 없으면 파일·지도 이름·해당 좌표를 경고하고 optional floor grouping만 생략한다.
  실제 지도·ID·WorldMap·물리 연결은 유지하며 다른 ground를 추측하거나 지도를 생성하지 않는다.
  알 수 없는 PhysicalLinkZone 참조는 계속 실패한다.
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

Vaivora 툴팁 XML 인덱스는 표준 `xml.etree.ElementTree.XMLParser`의 custom target으로
전체 파일을 끝까지 파싱하며, 전체 트리 대신 필요한 `dic_data` 속성만 저장한다.
시작 태그의 문서 순서(preorder)로 같은 이름·숫자 인덱스의 뒤 항목을 우선하고,
이름의 삽입 순서와 숫자 인덱스순 텍스트 결합을 유지한다.
`ktos`·`ktest`는 `kr` 원문을 그대로 사용하고, `itos`·`jtos`·`twtos`는 기존 TSV 번역을
사용하되 번역이 없거나 비어 있으면 `kr`로 대체한다. 앞서 유효한 툴팁을 읽었더라도
파일 뒤쪽의 XML 파싱 오류는 `ET.ParseError`로 전파한다.

정적 장비 계산에는 실제 플레이어·착용자 상태가 없으며, `GetItemOwner`는 Lua의 `nil`을 반환한다.
소유자 상태에 의존하는 맵 효과는 계산에 포함하지 않는다.
명시한 장비 RefreshScp의 계산 실패는 공개 전 파서 실패로 전파한다.
등록된 class table의 없는 ID와 table 자체가 없는 경우의 `GetClassByType` 결과는 `nil`이다.
이는 조회 대상의 부재 표현이며 원본 Lua가 자체 수식 분기를 선택하게 한다. 계산 성공을 강제하지 않으며,
기존 ID의 `math.floor` 처리·잘못된 numeric ID 오류와 필수 의존성 누락·존재하는 IES 손상 예외는 유지한다.
드롭은 iTOS 데이터셋 디렉터리가 우선이고 개별 파일을 현재 지역에서 섞어 가져오지 않는다.
선택 사유는 현재 지역 데이터셋의 존재 여부를 구분하며 실제 데이터 출처와 revision을 기록한다.
이 검증은 합성 샘플의 경로 검사다. 전체 지역 게임 데이터·schema 차이·게임 계산식을 대신하지 않는다.
입력·기대값·검증 단계별 경계는 [regional fixture 안내](../harness/fixtures/regional/README.md)를 참고한다.
