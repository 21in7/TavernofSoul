# Django 적재와 서빙

- 적재 진입점: `ipfparser/management/commands/importAll.py`.
- 서빙 진입점: `TavernofSoul/urls.py`, 각 앱의 `models.py`, `views.py`, `templates/`.
- 지역별 `manage_<region>.py`와 settings는 해당 DB와 JSON을 사용한다.
- `manage_test.py`/`settings_test.py`도 격리된 테스트 환경이 아니다.
- 기본 검증: 저장소 루트에서 `make check-django`.
- JSON/ID/관계/버전 적재 변경: `make check-pipeline`도 실행한다.
- 하네스 전용 `settings_harness.py`는 런처가 준비한 임시 경로와 메모리 SQLite를 사용한다.
  하네스는 실제 Django migrations, ORM, URL, view, template을 사용한다.
- `importAll`은 DB 적재와 비교 기준 `prev/`를 함께 관리한다.
  실패 후 DB·이전 비교 기준·버전이 일관되는지, 재적재가 중복을 만들지 않는지 확인한다.
- 레시피의 숫자 `$ID` 충돌은 importer의 `recipe-<id>` 정규화가 처리한다.
- 공통 계약 `ipfparser/contracts.py`는 적재할 스냅샷을 DB 쿼리 전에 검사한다.
  계약 변경은 [../docs/data-contracts.md](../docs/data-contracts.md)와 검증을 함께 갱신하고 `make check`로 확인한다.
- `load_import_snapshot`은 모든 JSON을 엄격히 검사하고 적재에 쓰는 컬렉션과 version만 반환한다.
  `load_release`의 version 반환과 첫 오류 순서, `load_json`·`validate_release`의 검사는 유지한다.
  importer는 활성 `handle`의 staging에서만 이 값을 재사용하며 mutable 소비자에게 deep copy를 준다.
  직접 호출과 `prev/`는 매번 읽고, 성공·실패 후 snapshot·참조 인덱스·스킬 이름 상태를 제거한다.
- 스킬·직업 조회 인덱스는 `importSkills` 호출 안에서 canonical 문자열 ID로 만든다.
  중복 ID는 원래 소비 지점의 `get()`으로 확인하여 누락·중복 예외를 유지한다.
  행별 save·created/updated·update=0·삭제 동작을 유지하며 bulk write나 unchanged-save 생략은 하지 않는다.
  아이템 분류 membership은 호출 내 set으로 조회하고 호출자의 목록·분류 우선순위는 보존한다.
  `parser_tidy/tests/test_import_safety.py`의 회귀와 전체 검증은 coordinator가 실행하기 전까지 pending이다.
- SQLite 검증은 운영 MySQL의 정규식·정렬·트랜잭션·전용 필드 동작 검증을 대체하지 않는다.
- MySQL 저장·정규식·정렬·DB 제약 동작 변경은 `make check-mysql-container`로 확인한다.
  일회용 서버와 제한된 계정만 사용하며 접속 설정은 `settings_harness_mysql.py`를 따른다.
  준비된 테스트 서버의 확인은 `make doctor-mysql`, 검증은 `make check-mysql`로 실행한다.
- 스킬·몬스터·드롭 연결은 `harness/combat_tests.py`가 원본부터 HTTP까지 검사한다.
  몬스터 공격력 최소·최대, 스킬 타수, 변경 시 연결 제거, 드롭 삭제와 롤백을 확인한다.
- 맵·속성·버프는 `harness/world_tests.py`가 원본부터 ORM·HTTP·관계 삭제·롤백을 검사한다.
- 560/550 장비와 젬은 `harness/equipment_tests.py`가 원본부터 장비 수치·Gems 스킬 FK·HTTP를 검사한다.
  강화 테이블/재료·젬 소켓 보너스의 적재·삭제·롤백과 HTTP 계산기 데이터를 함께 검사한다.
  실제 계산기 JavaScript는 Node.js와 작은 DOM 어댑터로 입력 이벤트·표시를 확인한다.
  실제 브라우저 엔진/레이아웃과 게임 전체 강화·진화·세트 계산 검증은 구분한다.
- 실제 Chromium 검색·상세·입력·젬·링크 검증은 `make check-browser` 또는 `make check-browser-container`.
  Ubuntu 20.04 ARM 호스트는 컨테이너 명령을 사용한다. 격리 DB·루프백 테스트 서버만 사용하며
  SDK 준비·보고서·trace는 [../docs/harness.md](../docs/harness.md)의 브라우저 절차를 따른다.
- 지역별 번역·추가 장비/카드/컬렉션은 `harness/regional_tests.py`가 5개 지역을 각각
  원본부터 ORM·HTTP·재적재·삭제·보존과 재시도까지 검사한다. SQLite/MySQL 양쪽에서 실행한다.

전체 경계는 [../docs/architecture.md](../docs/architecture.md),
검증 세부 사항은 [../docs/harness.md](../docs/harness.md)를 참고한다.
