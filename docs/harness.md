# 개발 하네스 사용법

저장소 루트에서 다음 명령을 실행한다.

```bash
make doctor
make check-downloader
make check-parser
make check-django
make check-pipeline
make check
make check-mysql-container
make check-browser-container
make check-live
make check-site-container
```

`make check`는 기본 오프라인 검증을 실행하고, 어느 하나라도 실패하면 0이 아닌 종료 코드를 반환한다.
MySQL과 Chromium은 각각 `make check-mysql-container`, `make check-browser-container`로 별도 실행한다.
CI workflow에는 오프라인(고정 실데이터 샘플 포함)·MySQL·브라우저 작업이 있다. 브랜치 보호에서 세 작업을 required check로
지정하는 것은 저장소 관리자 설정이며 이 파일만으로 설정되지 않는다.
각 검증은 새 프로세스에서 실행한다. 기존 데이터 다운로드·운영 적재·지역별 cron은 실행하지 않는다.

## Python 환경

Makefile은 `harness/.venv/bin/python`, 기존 `TavernofSoul/itos/3.8/bin/python`,
`python3` 순서로 기본 인터프리터를 선택한다. 직접 지정할 수도 있다.

```bash
make doctor PYTHON=/absolute/path/to/python
make check PYTHON=/absolute/path/to/python
```

새 체크아웃에서는 현재 프로젝트의 Python 3.8 실행 환경에 맞춘 별도 venv를 준비한다.
현재 의존성 버전은 `harness/requirements.txt`에 고정되어 있다.
하네스 환경 구성은 프로젝트 전체의 런타임 업그레이드를 의미하지 않는다.

```bash
python3.8 -m venv harness/.venv
harness/.venv/bin/python -m pip install -r harness/requirements.txt
make doctor
make check
```

기본 강화 계산기 DOM 검증에는 Node.js 18 이상이 필요하며 npm 패키지를 설치하지 않는다.
실제 브라우저 검증은 별도 Playwright SDK와 Node.js 20 이상을 사용한다.
CI는 Node.js 22를 별도로 준비한다.
`doctor`는 모듈 import, Python/Node.js 버전, 고정 입력과 설정 파일의 존재 여부를 확인한다.
자동 설치, 버전 CSV 초기화, 운영 DB 접속을 수행하지 않는다.
Make 없이 실행하려면 동일 인터프리터로 `python -m harness check`를 사용한다.

## 실행 범위

| 명령 | 검증 내용 |
| --- | --- |
| `check-downloader` | 로컬 암호화 revision·작은 IPF 대체 입력·실제 PAK 해제·변경 없음·전송/도구/복사 실패·버전 보존·재시도·CLI 종료 코드·cron 중단 |
| `check-parser` | 실제 CSV IES·XML/TSV·Lua → 아이템·combat·맵/속성/버프·5개 지역·560/550 장비·젬 JSON, 공통 계약·공개 차단·수치·참조·재계산·재시도와 기존 회귀 |
| `check-django` | 기존 canonical ID·import 안전성·레시피 복구 테스트와 `Items.tests`의 검색·페이지·쿼리 수 검증 |
| `check-pipeline` | 원본 IES/Lua 및 고정 JSON → 실제 importer·ORM·HTTP, 5개 지역·560/550 장비·젬·추가 유형, 계약 차단·상태 보존·재적재·관계 삭제·롤백 후 재시도 |
| `doctor-mysql` | 명시적인 테스트 서버 접속, 제한된 계정 권한, 실제 서버 버전·SQL 모드·문자셋·격리 수준 확인 |
| `check-mysql` | 실제 MySQL migrations, 전체 고정 입력 통합 경로와 아이템 검색, MySQL 저장·검색·오류 롤백 검증 |
| `check-mysql-container` | 전용 MySQL 컨테이너 생성 → 계정 권한 제한 → `check-mysql` → 컨테이너 정리 |
| `doctor-browser` | 고정 Playwright SDK 버전, Node.js 버전, 실제 Chromium 실행 또는 전용 컨테이너 연결 |
| `check-browser` | 임시 원본 파싱·DB 적재·실제 Django HTTP/정적 파일 → 데스크톱·모바일 Chromium 18개 시나리오 |
| `check-browser-container` | 지원 Ubuntu의 ARM64/amd64 브라우저 컨테이너 → `check-browser` → 컨테이너 정리 |

`check-django`는 `parser_tidy/tests/`의 importer 회귀 세 파일을 별도 프로세스에서 실행한 뒤,
Django test runner로 `Items.tests`를 실행한다. 디렉터리 위치와 검증 책임이 다른 점을 구분한다.

## 격리와 결과

- 기본 런처는 `DJANGO_SETTINGS_MODULE=TavernofSoul.settings_harness`를 강제한다.
- 기본 하네스는 SQLite `:memory:`를 사용한다. MySQL 명령은 `settings_harness_mysql`을 강제한다.
  두 설정 모두 실제 migrations를 적용한다.
- JSON·미디어·캐시·메일은 하네스 환경으로 분리한다. 임시 JSON과 DB는 실행 후 정리된다.
- 기존 환경의 `PYTEST_ADDOPTS`/추가 plugin 설정을 제거하고 하네스 전용 pytest 설정을 사용한다.
- 선택된 pytest/Django 테스트의 skip, xfail, 테스트 미수집은 실패로 처리한다.
- 결과는 Git에서 제외된 `logs/harness/`에 JSON으로 남는다.
  `doctor.json`, `downloader.json`, `parser.json`, `django-regressions.json`, `django.json`, `pipeline.json` 및
  실행 명령별 집계 파일에서 성공 수·실패·오류·skip·제외 목록을 확인한다.
- 같은 명령의 다음 실행은 해당 결과 파일을 갱신한다. 실패나 프로세스 종료가 이전 성공을 재사용하지 않는다.
- 각 검증의 전체 출력은 같은 디렉터리의 `.log`에 저장한다. 실패 시 터미널에도 출력한다.
- 보고서 위치를 바꾸려면 `python -m harness check --report-dir /tmp/tavern-reports`를 사용한다.

## MySQL 검증과 CI

Docker에 접근할 수 있는 환경에서 다음 명령 하나로 실행한다.

```bash
make check-mysql-container
```

`harness/mysql.sh`는 digest로 고정한 공식 MySQL 8.4.11 이미지를 사용한다.
새 컨테이너 이름을 만들고 루프백의 임의 포트로 연결하며 DB 파일은 컨테이너의 tmpfs에 둔다.
기존 컨테이너·호스트 MySQL·운영 볼륨을 사용하지 않는다. 성공·실패·INT/TERM 종료 시 자신이 만든
컨테이너를 정리한다. 강제 종료나 Docker 장애로 정리를 못 한 경우는 예외다.
Docker 명령에 sudo가 필요한 환경에서는 `HARNESS_DOCKER='sudo -n docker'`를 지정할 수 있다.
최초 실행은 이미지 다운로드가 필요하며 다운로드한 이미지는 다음 실행에 재사용한다.

접속 계정은 `tavern_harness`, 연결 DB는 `tavern_harness`, Django가 생성·삭제할 DB는
`test_tavern_harness`로 고정한다. `harness/mysql-init.sql`은 **새 테스트 컨테이너 안에서만** 실행하고
이 계정에 두 스키마의 권한만 준다. SQL grant의 밑줄은 escape하여 다른 DB 이름과 매칭되지 않게 한다.
하네스는 접속 후 실제 권한을 검사하고 전역 권한·다른 스키마·role·GRANT OPTION이 있으면
테스트 DB를 만들기 전에 중단한다. 컨테이너의 root 계정은 권한 준비에만 사용한다.

이미 준비된 별도의 일회용 서버에서는 다음 환경 변수 네 개를 모두 지정한다.

```bash
export HARNESS_MYSQL_HOST=127.0.0.1
export HARNESS_MYSQL_PORT=13306  # 전용 컨테이너의 실제 매핑 포트
export HARNESS_MYSQL_USER=tavern_harness
export HARNESS_MYSQL_PASSWORD=harness-only
make doctor-mysql
make check-mysql
```

루프백 이외의 호스트·기본 3306 포트·다른 사용자·누락 설정을 거부한다.
계정 권한을 위 SQL대로 준비해야 하며 동시 실행은 서로 다른 컨테이너/포트를 사용한다.
서버가 없거나 인증·migration이 실패하면 실패 보고서를 남긴다. SQLite로 대체하거나 skip하지 않는다.
PyMySQL의 MySQL 8 인증에 필요한 `cryptography`도 하네스 의존성에 고정되어 있다.

세션은 `STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION`, InnoDB, utf8mb4, read committed를 사용하고
테스트 DB collation은 `utf8mb4_unicode_ci`다. `mysql.json`과 `mysql-doctor.json`에는
실제 서버 버전과 연결 조건을 기록하며 비밀번호는 기록하지 않는다.
`mysql-container.json`은 서버 준비 단계·종료 코드·컨테이너 정리 여부를 기록한다.
서버 시작 전에 실패해도 이전 성공 결과를 그대로 사용하지 않는다.
원본 fixture부터 ORM·HTTP·재적재·삭제·DB/Version/prev 롤백을 기존 통합 테스트로 다시 검사한다.
`harness/mysql_tests.py`는 다음 MySQL 전용 동작을 추가한다.

- migration이 만든 테이블의 InnoDB·문자셋·collation과 실제 테스트 스키마.
- 한글·4바이트 이모지 저장과 collation에 따른 대소문자/악센트 검색.
- 아이템 직업 필터의 실제 MySQL 정규식 조회.
- ListCharField 정수·좌표 저장, 원소 조회, null과 빈 배열 구분.
- 실제 FK 위반의 이전 변경 롤백.
- 유효한 JSON이 배열의 VARCHAR 저장 한도를 넘을 때 truncation 대신 DB 오류,
  DB·Version·prev 보존과 수정 후 재시도.

JSON 계약 전체에 MySQL 저장 길이 검사를 추가한 것은 아니다. 저장 한도 오류는 strict SQL에서 실패한다.
고정 fixture의 작은 경로를 검증하며 운영 서버의 버전·collation·설정이 같다고 가정하지 않는다.
전체 지역 데이터·모든 계산식·운영 DB 성능은 별도 검증이다.

`.github/workflows/harness.yml`은 push·pull request·수동 실행에 대응한다.
새 Python 3.8 환경에서 고정 의존성을 설치하고 SQLite 오프라인·독립 MySQL 서비스·Chromium 작업을 실행한다.
MySQL 작업도 같은 digest의 서버와 제한된 계정을 사용한다. 결과 JSON·로그는 성공/실패 모두
`harness-offline`, `harness-mysql`, `harness-browser` artifact로 14일 보관하며 실패 시 진단 자료도 수집한다.
기존 서버 구축 workflow·운영 배포·cron은 이 workflow의 실행 범위에 포함하지 않는다.

## 실제 브라우저 검증

Python 하네스 환경 외에 Node.js 20 이상(CI는 22)과 고정 SDK를 준비한다.

```bash
npm ci --prefix harness/browser --ignore-scripts --no-audit --no-fund
```

**Oracle Cloud ARM64·Ubuntu 20.04 헤드리스 서버**에서는 Chromium만 공식 Ubuntu 24.04 컨테이너로 실행한다.
화면이나 X 서버, 운영 OS 업그레이드, 호스트 브라우저 설치가 필요하지 않다.
기존 Docker를 이용하며 Python/Django/Node 테스트 런처는 호스트에서 실행한다.

```bash
make check-browser-container
# Docker 접근에 sudo가 필요한 경우:
HARNESS_DOCKER='sudo -n docker' make check-browser-container PYTHON=/absolute/path/to/python
```

`harness/browser.sh`는 Playwright 1.63.0과 일치하는 공식 이미지의 multiarch digest를 고정한다.
버전을 올릴 때 `package.json`·lockfile·`container-image.txt`를 함께 갱신한다.
호스트 SDK의 `node_modules`만 읽기 전용으로 마운트하며 프로젝트·운영 JSON·환경 파일·DB 볼륨을
컨테이너에 전달하지 않는다. 엔진 연결 포트는 `127.0.0.1`의 임의 포트로 공개한다.
Django도 루프백의 임의 포트를 사용하고, Playwright 연결은 그 테스트 포트만 컨테이너에 전달한다.
클라우드 인바운드 규칙이나 공개 웹서버 설정을 바꿀 필요가 없다.
성공·실패·INT/TERM 때 자신이 생성한 컨테이너를 제거한다. SIGKILL/Docker 장애는 정리 예외다.
이미지 다운로드가 최초 한 번 필요하며 이후 실행에서 재사용한다. Ubuntu 20.04의 native 실행은 명시적으로 실패한다.

지원되는 Ubuntu 22.04/24.04 등의 환경과 CI에서는 native 실행도 가능하다.
브라우저 시스템 의존성 설치는 해당 **개발/CI 환경에서만** 수행한다.

```bash
harness/browser/node_modules/.bin/playwright install --with-deps chromium
make doctor-browser
make check-browser
```

`StaticLiveServerTestCase`가 실제 migrations와 메모리 SQLite를 준비한다.
작은 iTOS 장비 원본을 실제 파서·JSON 출력·importer로 적재하고 실제 URL/view/template/정적 파일을 제공한다.
직접 `settings_test`나 운영 `manage_<region>`을 실행하지 않으며 외부 서버 URL을 인자로 받지 않는다.
고정 입력의 가상 아이콘은 임시 PNG로 제공한다. 다운로드한 실제 아이콘 자산의 호환성은 별도 범위다.
하네스 설정에만 추가한 context processor가 광고·동의 팝업·분석·외부 폰트를 제외한다.
일반 지역 설정에서는 기존 서비스가 유지된다. 브라우저의 예기치 않은 외부 요청·HTTP 오류·console 오류·JavaScript 예외는 실패다.

1440×900 데스크톱과 390×844 모바일 viewport에서 다음 9개 시나리오를 각각 실행한다.

- 검색어·등급 유지, 검색 결과에서 상세 이동, 모바일 메뉴 열기/닫기.
- 검색 결과가 없는 경우.
- 560 무기 +5/+6/+30/0, 확률·재료·공격력 표시, 재료 링크 이동.
- 강화/초월 입력 순서, 음수/상한 입력 처리, 0 초기화와 비용 표시.
- 560 방어구의 물리/마법 방어력과 재료.
- 550 액세서리의 해당 강화 테이블과 재료.
- 일반 장비의 강화·초월 수치와 비용.
- 젬의 레벨별 5개 슬롯 보너스·음수 페널티.
- 스킬 젬에서 연결된 스킬 화면으로 이동.

수치는 hand-authored fixture 기대값이며 실제 게임 밸런스 값으로 주장하지 않는다.
필수 시나리오/viewport 누락·중복, skip/xfail, 재시도로 성공한 flaky 결과, 미수집은 성공으로 처리하지 않는다.
`make check`에는 SDK/브라우저 설치를 요구하지 않고 빠른 Node DOM 검사와 브라우저 결과 판정의 회귀만 포함한다.

`doctor-browser.json`, `browser.json`, `check-browser.json`은 실제 엔진 버전·선택/통과 수를 기록한다.
`browser-container.json`에는 컨테이너 정리 여부, `.log`에는 엔진 로그를 남긴다.
`logs/harness/browser/<run-id>/`에 Playwright JSON·HTML 보고서와 검색/무기/젬 스크린샷이 남으며,
실패 시 해당 화면의 스크린샷·`trace.zip`도 저장한다. 실행별 디렉터리로 이전 성공 자료와 구분한다.

```bash
harness/browser/node_modules/.bin/playwright show-report logs/harness/browser/<run-id>/html
harness/browser/node_modules/.bin/playwright show-trace logs/harness/browser/<run-id>/results/<test>/trace.zip
```

SSH 서버에서 자료를 로컬로 복사해 열 수 있다. 이 검증은 운영 도메인의 TLS/프록시/캐시/광고 동작이나
실제 모바일 기기·Firefox/WebKit·전체 페이지·5개 지역 브라우저 검증을 포함하지 않는다.

## 실제 게임 데이터와 운영 도메인

`make check-live`는 기본 `make check`와 별도로 실행한다. iTOS·kTOS의 550/560 장비 6종,
젬 2종과 재료를 고정한 원본 스냅샷으로 실제 파서부터 임시 SQLite·ORM·HTTP·계산기 JS까지 검사한다.
입력 SHA-256과 unpack revision은 `live.json`에 함께 남는다. skip이나 누락은 성공으로 처리하지 않는다.
캡처/기대값 근거·선택하지 않은 범위는 [실데이터 샘플 안내](../harness/fixtures/live/README.md)를 참고한다.
CI의 `Offline harness (SQLite)` 작업은 `make check`와 `make check-live`가 모두 통과해야 성공한다.

운영 HTTPS·프록시·정적 파일·검색·560 계산기·젬/스킬 연결은 별도 명령으로 확인한다.

```bash
HARNESS_DOCKER='sudo -n docker' make check-site-container PYTHON=/absolute/path/to/python
# 지원 OS에 브라우저를 설치했다면:
make check-site
```

대상은 저장소에 명시된 iTOS·kTOS 공개 도메인 두 곳이다. 데스크톱/모바일에서 각각 4개,
총 16개 시나리오를 실제 Chromium으로 실행한다. TLS 인증서 오류를 무시하지 않으며 HSTS,
검색→상세, 실제 아이콘·jQuery 로드, 560 공격력·강화 입력/초기화, 젬 보너스·스킬 링크를 확인한다.
모든 브라우저 요청은 GET/HEAD만 허용한다. 로그인·운영 적재·DB 변경·배포는 수행하지 않는다.
광고 등 외부 HTTP 오류와 차단한 telemetry는 별도 관측으로 남기고, 자체 사이트 HTTP/네트워크 오류와
JavaScript 예외는 실패다. 외부 광고 서비스 전체의 정상 동작을 보증하는 검증은 아니다.
운영 도메인이 아직 새 계산기/젬 화면을 배포하지 않았다면 해당 시나리오는 실제 실패로 남는다.
고정 데이터 CI와 운영 smoke는 서로 대체하지 않는다. 운영 smoke는 merge 필수 CI에서 제외한다.

`check-site.json`·`site-container.json`, `site-<region>-engine.json`과
`logs/harness/site-<region>/<run-id>/`의 HTML/JSON·스크린샷·trace로 결과를 확인한다.
종료 후 전용 Chromium 컨테이너를 정리하며 운영 컨테이너나 볼륨에 접속하지 않는다.

## 기본 검증에서 의도적으로 제외한 기존 테스트

| 대상 | 이유 |
| --- | --- |
| `test_baseline_json.py` | 지역별 현재 JSON/unpack 출력에 의존하며 역사적 버그 상태를 재현하는 테스트도 포함 |
| `test_package_parser.py::TestKtosRegression` | 로컬 ktos unpack 데이터 필요 |
| `test_package_unresolved.py::TestKtosUnresolvedIntegration` | 로컬 ktos unpack 데이터 필요 |

위 두 클래스는 pytest의 명시적 deselect로 제외하며 개별 테스트 목록도 보고서에 기록한다.
제외는 기본 검증의 성공 근거에 포함되지 않는다. 다른 필수 테스트의 skip은 실패다.
기존 실데이터 검증이 필요하면 환경과 입력을 확인하고 별도로 실행·보고한다.

## 다음 구축 범위

1. 실제 지역 샘플로 schema/패치 차이 확대와 운영 MySQL 프로필 차이 확인.
2. 별도 승인한 운영/스테이징 URL의 읽기 전용 smoke, 지역별 브라우저 시나리오 확대.

SQLite/MySQL 고정 입력 통과는 운영 전체 데이터 호환성이나 모든 페이지의 브라우저 동작을 보장하지 않는다.

## 공통 데이터 계약

[데이터 계약](data-contracts.md)은 15개 importer 컬렉션과 버전의 필수 형식,
ID 중복·참조·수치 범위·단위 담당 단계와 기존 optional/sentinel을 설명한다.
파서 출력 전과 importer의 DB 쿼리 전에 같은 모듈이 검사한다.

`test_release_contract.py`는 실제 파서 출력에 작은 고정 JSON을 더해 누락·타입·중복·참조·범위를 검사한다.
메모리 또는 staging의 계약 오류는 공개 파일·버전을 보존한다.
`harness/contract_tests.py`는 실제 migrations·ORM을 사용해 스냅샷 검증·DB 쿼리 0개·비교 기준 보존,
재시도와 유효한 계약 이후의 적재 실패 롤백을 확인한다.
계약 전용 fixture는 고정 JSON이며 원본 파싱 coverage와 구분한다.
맵·속성·버프 원본은 world, 카드·컬렉션 원본은 regional fixture에서 따로 검사한다.
책·업적 계약의 현재 통합 입력은 고정 JSON이다.

## 파서 원본 검증

[아이템 fixture 안내](../harness/fixtures/parser/README.md)의 작은 입력 7개 아이템으로
실제 `items.parse`와 번역·Lua 계산·JSON 출력을 실행한다.
입력은 직접 작성한 CSV 형식 IES, XML/TSV, Lua이며 바이너리 IES나 운영 게임 계산식은 포함하지 않는다.
소수 무게, 쿨다운과 내구도 단위, 등급 기본값, 레시피 참조, 패키지 options·unresolved·랜덤 묶음,
장비 공격력·강화·초월 비용을 독립적으로 작성한 기대값과 비교한다.

같은 입력의 반복 실행은 JSON을 그대로 유지한다. IES 값과 공유 상수를 바꾸면 Lua 수치를 다시 계산한다.
잘못된 등급, 필수 fixture 누락, Lua 로드 실패는 성공으로 처리하지 않으며 공개 JSON·버전을 보존한다.
실행마다 임시 파일과 새 Lua 런타임을 사용해 파서 전역 상태가 다음 테스트에 섞이지 않도록 한다.

연결 검증은 같은 원본에서 실제 importer·ORM·HTTP 화면까지 실행한다.
재료와 레시피의 숫자 ID 충돌을 `recipe-100`으로 정규화하고,
원본 수치 변경이 기존 장비를 갱신하는지, 반복 적재가 관계를 중복 생성하지 않는지 확인한다.
DB의 `Version`은 고유 버전별 이력이다. 동일 버전 재적재는 이력을 추가하지 않고 새 버전은 추가한다.
오류로 파싱이 끝나지 않으면 이전 공개 파일과 DB·화면 데이터, 적재 비교 기준을 유지한다.

카드·젬·컬렉션, 전체 `main.py`, 바이너리 해제,
자산 생성, 소수 초 쿨다운의 DB 저장은 이 원본 fixture로 검증하지 않는다.

## 스킬·몬스터·드롭 원본 검증

[combat fixture 안내](../harness/fixtures/combat/README.md)의 입력을 아이템 샘플과 함께 읽는다.
직업·스킬트리 연결, 실제 Lua의 레벨별 계수·비율·쿨다운·자원 소비,
비활성 스킬 정리, 몬스터 Lua 수치와 지역 보정, 몬스터 스킬·드롭 관계를 검사한다.
드롭은 확률 퍼센트와 수량, 출처 지역·버전, 미해결 참조를 JSON에서 확인한다.
잘못된 원본 수치·직업 참조, 누락 입력·몬스터 Lua 함수는 공개 JSON·버전을 보존한다.

통합 검증은 스킬·몬스터 검색/상세와 아이템 드롭 역참조까지 실행한다.
비율 0.4는 파서에서 40으로 변환하고 DB에서도 40이다.
물리 공격력의 최소·최대와 EXP·JOBEXP를 서로 다른 값으로 검사한다.
타수·스킬 연결 변경, 드롭 삭제, 반복 적재와 DB 적재 실패 후 롤백·재시도를 포함한다.

이번 검증에서 importer의 몬스터 물리 공격력 최소·최대 역전과 타수 누락을 수정했다.
몬스터 스킬의 연결은 새 목록으로 교체해 제거된 연결이 남지 않도록 했고 상세 HTML도 실제 타수를 출력한다.
스킬의 지역 보충 데이터 경로는 코드 저장소 대신 입력 프로젝트에서 유도한다.
importer의 비교 대상 추가·변경 행에 수정이 적용되며 기존 운영 DB 보정 작업은 실행하지 않는다.

샘플은 iTOS의 작은 선택 범위다. 모든 지역·유형·게임 계산식·브라우저 JavaScript를 검증하지 않는다.
몬스터의 다른 유형과 statbase 헤더만 있는 입력은 해당 유형의 coverage에 포함하지 않는다.
맵 zonedrop/dropgroup과 속성·버프는 아래 world fixture에서 원본부터 검사한다.

## 맵·속성·버프 원본 검증

[world fixture 안내](../harness/fixtures/world/README.md)의 작은 CSV IES·XML/TSV를
아이템·combat 입력에 덧붙여 실제 운영 순서로 파싱한다.
지도 3개·NPC·몬스터/아이템 생성 위치, 직접 드롭·가중치 그룹·f_ 파일·특수 맵 비율,
속성의 기본/보충 스킬·직업 연결과 정리, 네 버프 파일의 수치·번역을 검사한다.
생성 시간은 초, 버프 지속 시간은 ms이고 좌표·병합 인구수는 독립적인 기대값과 비교한다.

잘못된 원본 수치·지도 연결·필수 fixture 누락·중복 관계는 공개 JSON과 버전을 보존한다.
반복 파싱과 같은 DB 객체에서 맵 연결을 재구성해도 생성점·층·미해결 참조가 중복되지 않는다.
같은 입력의 재적재는 데이터와 관계를 유지한다. 스킬 updated 감사 시각은 전진할 수 있다.

통합 검증은 실제 importer·ORM·맵/속성/버프 검색·상세·아이템 맵 역참조를 실행한다.
원본 변경 시 수치·연결 갱신과 삭제, 파싱 실패 시 DB 보존,
적재 도중 오류 시 DB·Version·prev 롤백과 수정 후 재시도를 검사한다.

이번 검증으로 보충 속성 연결의 숫자 ID/스킬 이름 혼용과 역참조 누락,
잘못된 최대 레벨·지도 연결의 예외 숨김, 특수 맵 드롭그룹의 비율,
맵 생성 관계 재구성 중복·1층 자기 참조와 요구 설명이 null인 속성 상세 오류를 수정했다.
새 parser 릴리스와 importer의 추가·변경 비교 대상에 적용되며 운영 DB 일괄 보정은 실행하지 않는다.

맵/속성/버프의 이 경로는 합성 iTOS 샘플이며 MySQL 명령에서도 실행한다.
전체 유형·지역·게임 데이터는 검증하지 않는다.
지도 PNG 생성·자르기와 브라우저 canvas, 속성의 미구현 Lua 비용/해금 계산은 포함하지 않는다.

## 지역별 원본 경로와 추가 유형

[regional fixture 안내](../harness/fixtures/regional/README.md)는 공통 소스에 다섯 지역의 입력을 덧붙인다.
운영 unpack을 복사한 데이터가 아니라 작은 합성 CSV IES·XML/TSV·Lua와 독립 기대값이다.
iTOS·jTOS·twTOS는 English/Japanese/Taiwanese 번역을, kTOS·kTest는 원문의 한국어를 사용한다.
동일 프로세스에서 지역을 바꾸고 재실행해도 이름·계수·Lua 상태가 섞이지 않는지 검사한다.

추가 원본은 마법 지팡이·방어구·카드·컬렉션이다. 실제 Lua로 물리·마법 공격력과 두 방어력,
강화 배열·보너스 floor·음수 보너스·내구도 sentinel·직업 제한을 확인한다.
카드 전투 수치는 JSON까지만 검사하며 카드 유형/이미지와 컬렉션 재료·보너스는 ORM·HTTP까지 확인한다.
지역별 이름·스킬 보충의 kTOS/kTest 우선순위와 iTOS의 외국어 설명 보충 제외,
iTOS/현재 지역 드롭 데이터셋 선택·행별 출처·revision도 검사한다.

파서 5지역 검증은 `test_regional_source_fixture.py`, 통합은 `harness/regional_tests.py`에서 실행한다.
SQLite와 MySQL 양쪽에서 각 지역의 검색·상세·재적재와 수치 갱신·관계 제거·카드 삭제를 검사한다.
번역/IES 누락·손상·Lua 오류는 공개 JSON/버전을 보존하고,
적재 도중 오류는 DB·Version·prev를 보존하며 수정 후 재시도한다.

이번 범위에서 명시된 장비 RefreshScp의 실패를 숨기던 동작을 수정했다.
해당 함수가 없거나 실행에 실패하면 장비와 함수 이름을 포함한 오류로 중단한다.
전체 운영 원본에서 모든 Lua 함수가 실행 가능한지는 이 작은 샘플의 검증 범위 밖이다.
드롭 소스가 양쪽 지역에 있을 때의 사유도 실제 iTOS 우선 선택을 설명하도록 수정했다.
fixture의 `.ipf` 디렉터리는 Git에 포함하며 필수 입력이 Git에서 제외되면 검증을 실패 처리한다.

## 560 여신 장비·550 장신구·젬 원본 검증

[equipment fixture 안내](../harness/fixtures/equipment/README.md)는 regional 입력에
강화 IES·실제 테스트용 Lua·젬 CSV/XML을 추가한다. 운영 데이터에서 생성한 입력은 아니다.
5개 지역에서 560 무기/방어구 기본 수치와 초월 비용, 550 장신구 정수 공격력,
일반 젬 보너스/페널티·합쳐진 슬롯·레벨 0 제외와 스킬 젬 ID 연결을 검사한다.

강화 목록에 560을 등록하고 등록된 IES를 Lua GetClassByType에도 제공한다.
560은 해당 파일이 있을 때만 armor/weapon 재료를 생성하며 acc 그룹은 생략한다.
560의 필수 함수 누락·빈 계산·잘못된 수량과 손상된 강화 IES는 공개 전에 중단한다.
미등록 강화 파일은 경고와 goddess_reinf_unregistered.json에 기록한다. 자동 등록하지 않는다.
550 장신구는 기존 acc 전용 구조를 유지하고 BasicAccAtk를 JSON 정수로 출력한다.

importAll은 Gems 스킬 FK와 레벨/슬롯별 소켓 보너스를 스킬 적재 뒤에 반영한다. Link_Skill의 누락/null은 연결 해제이며
잘못된 참조와 다른 ORM 유형 그룹과의 중복은 공통 계약에서 DB 쿼리 전에 차단한다.
재적재·관계 변경·분류 제거·젬 삭제·적재 도중 실패의 DB/Version/prev 롤백을 확인한다.
SQLite와 MySQL에서 같은 equipment 통합 테스트를 실행한다.

강화 테이블/재료는 GoddessReinforcement에, 젬 소켓 보너스는 Gems.socket_bonuses에 적재한다.
장비 단계별 누적 강화값은 파서의 실제 Lua 결과이며 화면의 고정 여신 배열은 제거했다.
UseLv와 ItemLv를 구분하고 Trinket 배율, 550 장신구와 560 무기/방어구의 차이를 검사한다.
확률·재료만 변경된 릴리스도 DB에 반영하며 누락된 비용과 무료 단계를 구분한다.
반복 적재·젬 레벨 제거·이전 JSON의 Level 누락·강화 보조 파일 생략·DB 유일성 제약 실패의 롤백을 검사한다.
새 컬렉션과 젬 필드의 잘못된 타입/범위·중복·참조는 공통 계약에서 차단한다.

`harness/browser_calculator.js`는 Node.js에서 실제 배포할 JavaScript를 실행한다.
작은 DOM 어댑터로 실제 HTTP 응답의 컨트롤 ID와 JSON 데이터를 연결해 강화/초월 입력 이벤트,
초기화·경계값·이벤트 순서·확률 단위·비용·재료 링크·문자열의 안전한 표시를 확인한다.
`harness/test_enhancement_browser.py`의 독립 기대값 검증은 check-parser에,
5개 지역 HTTP 데이터와의 연결 검증은 SQLite/MySQL 통합 테스트에 포함한다.
실제 브라우저 엔진·레이아웃·모바일 조작·모든 운영 Lua 계산식의 검증은 수행하지 않는다.
기존 초월 비율을 유지하며 진화·세트 효과·다른 착용 장비에 따른 방어구 공격력 전환은 계산하지 않는다.
추가 로컬 확인은 iTOS/kTOS 실제 560 CSV와 네 재료 함수 본문만 읽어서 실행했으며
logs/harness/equipment-live-probe.json에 결과·원본 hash를 기록했다. 전체 운영 파서/실데이터 회귀는 실행하지 않았다.
추가로 `logs/harness/reinforcement-live-probe.json`에는 iTOS/kTOS의 실제 550/560 IES와
추출한 IS_WEAPON_TYPE·SCR_GET_GODDESS_REINFORCE 함수로 새 파서 계산 헬퍼를 확인한 결과를 기록했다.
검·트링킷·갑옷·방패·목걸이·반지의 누적값을 CSV 합계와 대조했다. 이 확인도 전체 Lua 초기화나
운영 파서 빌드/DB 적재를 수행하지 않았으며 기본 하네스와 CI에는 포함하지 않는다.

## 다운로더 검증과 재시도

고정 입력은 [다운로더 fixture 안내](../harness/fixtures/downloader/README.md)를 참고한다.
테스트는 실제 인터넷 연결을 차단하고 `urllib` 응답을 메모리의 고정 데이터로 대체한다.
서버 통신·다운로드 파일 저장·PAK raw deflate 해제·번역 복사·버전 기록은 실제 Python 로직을 사용한다.
IPF는 임시 실행 파일로 도구 호출 순서와 종료 코드 처리를 검증한다.
실제 네이티브 IPF 복호화·IES 변환 정확성과 외부 서버 가용성은 별도 검증이 필요하다.

| 다운로더 CLI 종료 코드 | 의미 | cron 처리 |
| --- | --- | --- |
| 0 | 새 패치 처리 완료 | 다음 단계 진행 |
| 1 | 새 패치 없음 | 기존 지역별 변경 없음 처리 유지 |
| 2 | 네트워크·파일·복호화·압축 해제·복사·버전 기록 실패 | 파싱·DB import 전에 중단 |

다운로드는 `.part`에 저장하고 비어 있거나 Content-Length와 다르면 공개하지 않는다.
완료된 파일만 캐시로 교체하며 도구 실패 시 원본 IPF를 유지한다.
버전 CSV는 개별 패치의 해제·복사 성공 후 임시 파일로 기록하고 교체한다.
release 패치의 경우 번역 복사 성공도 버전 전진 조건에 포함한다.
손상된 PAK은 재사용하지 않고 다음 실행에서 다시 다운로드한다.

복수 패치 중 두 번째 패치가 실패하면 첫 번째 완료 버전은 유지하며,
재실행은 실패한 패치부터 시작한다. 서로 다른 data/release 스트림도 각각 완료 버전을 유지한다.
unpack과 번역 디렉터리 전체를 롤백하는 구조는 아니므로 실패 후 일부 파일이 남을 수 있다.
실패 상태에서 cron의 후속 단계를 차단하고 다음 실행이 해당 패치를 다시 적용하는 방식이다.
