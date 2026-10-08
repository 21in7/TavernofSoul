# TavernofSoul 작업 지도

이 저장소는 Tree of Savior 게임 데이터를 수집·파싱하고 Django로 제공한다.
전체 흐름과 책임 경계는 [docs/architecture.md](docs/architecture.md),
검증 범위와 환경 준비는 [docs/harness.md](docs/harness.md)를 먼저 확인한다.

## 영역별 진입점

- 다운로더·압축 해제·번역 준비: `downloader/`와 [downloader/AGENTS.md](downloader/AGENTS.md).
- 파싱·JSON 출력: `parser_tidy/`와 [parser_tidy/AGENTS.md](parser_tidy/AGENTS.md).
- DB 적재·HTTP 서빙: `TavernofSoul/`와 [TavernofSoul/AGENTS.md](TavernofSoul/AGENTS.md).
- 공통 검증: `Makefile`, `harness/`; 실행은 저장소 루트에서 한다.
- 파서·importer 공통 계약: `TavernofSoul/ipfparser/contracts.py`, [docs/data-contracts.md](docs/data-contracts.md).
- 운영 파이프라인: `cron_<region>.sh`; 지역은 `itos`, `ktos`, `ktest`, `jtos`, `twtos`.
- `motion_proto/`, `3dparser/`, `simul/`은 별도 도구다. 해당 문서를 확인한다.

## 작업과 완료 기준

1. 변경 전 작업 트리 상태를 확인하고 기존 사용자 변경을 보존한다.
2. `make doctor`로 하네스 환경을 확인한다. 필요하면 `PYTHON=/path/to/python`을 지정한다.
3. 다운로더 변경은 `make check-downloader`, 파서 변경은 `make check-parser`,
   Django·importer 변경은 `make check-django`를 실행한다.
4. 데이터 계약·연결부·하네스 변경은 `make check`를 실행한다.
5. 결과는 `logs/harness/`에서 확인한다. 선택된 테스트의 skip/xfail은 완료로 처리하지 않는다.
6. 기본 검증에서 제외한 실데이터 테스트와 추가 검증의 수행 여부를 구분해 보고한다.

## 데이터와 실행 경계

- 기본 검증은 작은 고정 입력, 임시 파일, SQLite 메모리 DB를 사용한다.
- `settings_test.py`는 MySQL과 기존 JSON 디렉터리를 가리킨다. 격리 설정으로 간주하지 않는다.
- 검증을 위해 지역별 cron, 다운로더 전체 실행, 운영 `importAll`을 실행하지 않는다.
- `*_patch/`, `*_unpack/`, `Translation/`, `JSON_<region>/`, 버전 CSV는 로컬 실행 상태다.
  소스 수정의 부수 작업으로 초기화하거나 덮어쓰지 않는다.
- `*_unpack/`과 `IPFUnpacker/`에는 별도 Git 소유권이 있다. 작업 범위를 확인한다.
- 데이터 형식·단위·ID 처리 규칙을 바꾸면 경계 문서와 관련 검증을 함께 갱신한다.
