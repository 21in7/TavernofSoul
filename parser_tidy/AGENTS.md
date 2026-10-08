# 파서

- 진입점: `main.py <region>`; 주요 상태·출력은 `DB.py`의 `ToS_DB`가 담당한다.
- 입력: 지역별 unpack 데이터, 번역, `downloader/revision.csv`, `parser_version.csv`.
- 출력: `TavernofSoul/JSON_<region>/*.json`과 `version.json`.
- 평면 모듈 import를 사용한다. 하네스가 `parser_tidy/`를 Python 경로에 추가한다.
- 기본 검증: 저장소 루트의 `make check-parser`.
- 원본 아이템 검증은 `tests/test_source_fixture.py`와
  `../harness/fixtures/parser/`의 작은 CSV IES·XML/TSV·실제 Lua를 사용한다.
  fixture 기대값을 파서 출력에서 자동 생성하지 않는다. 관련 안내는 fixture README에 있다.
- 스킬·몬스터·드롭 원본은 `tests/test_combat_source_fixture.py`와
  `../harness/fixtures/combat/`에서 검증한다. 헤더만 있는 다른 몬스터 유형은 coverage가 아니다.
  지역 보충 데이터도 입력 프로젝트의 임시 JSON을 사용한다.
- 맵·속성·버프 원본은 `tests/test_world_source_fixture.py`와
  `../harness/fixtures/world/`에서 검사한다. 지도 이미지·canvas·속성 Lua 비용/해금 계산은 제외한다.
- 5개 지역과 마법 무기·방어구·카드·컬렉션 원본은 `tests/test_regional_source_fixture.py`와
  `../harness/fixtures/regional/`의 합성 입력을 사용한다. 운영 데이터 전체 검증으로 표현하지 않는다.
  번역은 main.py의 지역 정책을 따르고 명시된 장비 RefreshScp 실패는 공개 전에 전파한다.
- importer 관련 회귀가 이 디렉터리에 있어도 `make check-django`가 실행을 담당한다.
- 560 여신 무기/방어구·550 장신구·젬은 `tests/test_equipment_source_fixture.py`와
  `../harness/fixtures/equipment/`에서 검증한다. 미등록 강화 IES는 경고/진단으로 남기며 자동 등록하지 않는다.
  강화 JSON과 젬 소켓 보너스는 ORM까지 적재한다. Level·UseLv·단계 누적값 계약은
  docs/data-contracts.md와 파서·통합 검증을 함께 갱신한다.
- 로컬 게임 데이터가 필요한 테스트와 역사적 버그 재현은 기본 검증에서 명시적으로 제외한다.
  목록은 [../docs/harness.md](../docs/harness.md)와 `harness/runner.py`에서 확인한다.
- 공개 JSON 출력·버전·실패 재시도 변경은 `make check-pipeline`도 실행한다.
- 정상 참조와 unresolved 참조를 구분하고, ID/단위의 변환 담당 단계를 유지한다.
- `DB.export()`는 공통 `ipfparser/contracts.py`로 메모리·staging을 검사한다.
  계약 변경 시 [../docs/data-contracts.md](../docs/data-contracts.md)와 검증을 갱신하고 `make check`를 실행한다.
- `ToS_DB.build()`는 지역 데이터 경로를 설정한다. 테스트는 임시 경로와 인스턴스별 데이터를 사용한다.

공개 출력은 파일별 교체와 백업·롤백을 사용한다. 디렉터리 전체의 원자 교체로 설명하지 않는다.
자세한 계약은 [../docs/architecture.md](../docs/architecture.md)를 참고한다.
