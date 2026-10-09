# TavernofSoul 작업 지도

이 저장소는 Tree of Savior 게임 데이터를 수집·파싱하고 Django로 제공한다.
전체 흐름과 책임 경계는 [docs/architecture.md](docs/architecture.md),
검증 범위와 환경 준비는 [docs/harness.md](docs/harness.md)를 먼저 확인한다.

## 영역별 진입점

- 다운로더·압축 해제·번역 준비: `downloader/`와 [downloader/AGENTS.md](downloader/AGENTS.md).
- 파싱·JSON 출력: `parser_tidy/`와 [parser_tidy/AGENTS.md](parser_tidy/AGENTS.md).
- DB 적재·HTTP 서빙: `TavernofSoul/`와 [TavernofSoul/AGENTS.md](TavernofSoul/AGENTS.md).
- 공통 검증: `Makefile`, `harness/`; 실행은 저장소 루트에서 한다.
- 개발 에이전트 모델 연결: `harness/agent-models.json`, `harness/agent_models.py`,
  [docs/agent-models.md](docs/agent-models.md). 인증 점검은 `make agent-doctor`로 한다.
- 개발 작업 자동 배정·실행: `harness/workflow.py`, `harness/workflow-config.json`,
  [docs/workflow.md](docs/workflow.md). 실행은 `make agent-workflow`, 진행 확인은 `make agent-workflow-status`.
- GitHub 자동 게시·병합: `harness/git_publish.py`, `harness/git-publish-config.json`.
  Git 역할은 PR 설명을 작성하며, 실제 게시와 머지는 메인 Codex의 GitHub 앱 연결을 사용한다.
- 작업 접수·배정 추천: `harness/triage.py`, `harness/triage-config.json`,
  [docs/triage.md](docs/triage.md). 첫 단계는 shadow 기록이며 `make agent-triage-demo`는 외부 요청이 없다.
- 개발 대화 압축: `harness/compaction/`, `harness/compaction.py`,
  [docs/compaction.md](docs/compaction.md). Claude Code 역할에 적용하며 고정 소스를 사용한다.
- 파서·importer 공통 계약: `TavernofSoul/ipfparser/contracts.py`, [docs/data-contracts.md](docs/data-contracts.md).
- 운영 파이프라인: `cron_<region>.sh`; 지역은 `itos`, `ktos`, `ktest`, `jtos`, `twtos`.
- `motion_proto/`, `3dparser/`, `simul/`은 별도 도구다. 해당 문서를 확인한다.

## 작업과 완료 기준

코드 수정·기능 구현 요청에서는 메인 `/root`가 조정 역할을 맡는다. 관련 파일을 먼저 조사하고,
사용자 요청을 UTF-8 작업 파일로, 외부 모델이 읽거나 수정할 소스·테스트·문서의 **개별 파일 경로**를 범위 파일로
`logs/harness/` 아래에 작성한다. `make agent-workflow TASK_FILE=... FILES_FILE=...`로
Jev 판단 → 필요 시 Codex 계획 → 영역 담당 모델 → Claude 검토 → 하네스 검증 → 반영을 실행한다.
하위 역할은 기존 모델 설정을 사용하며, 실제 출력에 근거해 단계·역할·공급자·모델과 성공/실패를 표시한다.
범위 파일은 외부 모델 읽기 승인 목록이며 `READ_ONLY=1`에도 적용한다. 목록 밖 파일은 모델 사본이나
프롬프트에 자동 추가하지 않는다. 전체 검증 사본과 상세 로그는 로컬 검사에서만 사용한다.
범위 확장이 필요하면 실행기의 실패·검토 내용을 확인하고 기존 승인 범위 안인지 먼저 판단한다.
승인 밖 소스를 외부 모델에 추가 제공해야 하면 구체적인 개별 파일 목록에 대한 승인을 받아 새 실행을 준비한다.
사용자가 직접 처리나 특정 실행 방식을 지정하면 그 지시를 우선한다.

사용자는 요청한 개발 작업의 GitHub 커밋·브랜치 게시·PR 생성·CI 성공 후 머지까지 허용했다.
기본 쓰기 작업은 `git` 역할(Codex `gpt-6.1-sol`, `medium`)까지 실행한다. 보고서가
`awaiting_github`이면 메인 `/root`는 완료로 보고하거나 다시 허락을 묻지 않고 다음을 이어 실행한다.
`make agent-git-request RUN_ID=...`의 JSON `request`에 지정된 GitHub 앱 도구와 인자를 그대로 사용하고,
응답을 private UTF-8 JSON 파일에 저장해 `make agent-git-accept RUN_ID=... REQUEST_ID=... RESPONSE_FILE=...`로
검사한다. 응답 처리에서 반환된 다음 요청을 직접 실행하며 `poll_after_seconds`만큼 기다린다.
이미 반환된 쓰기를 `agent-git-request`로 재발급하지 않는다. 도구 이름은 실행기의
GitHub 허용 목록과 비교하며, 도구 인자를 셸 명령으로 실행하지 않는다. 파일 내용이 포함된 요청은
사용자 터미널에 출력하지 않는다. 새 PR URL은 생성 직후 `codex_app.attach_artifact`로 반드시 연결한다.
커넥터 오류는 `isError=true` 응답으로 실행기에 전달하고, `needs_reconciliation`이나 결과가 모호한
쓰기는 재시도하지 않는다. 원래 요청 ID로 실제 결과를 확인할 때만 이어 실행한다.
`merged`와 merge SHA 확인이 완료 기준이다. CI 실패·누락·skip/neutral, 충돌, 권한 부족은 PR을 유지하고
실제 상태를 보고한다. 30분 제한에서 `awaiting_ci`이면 기존 PR을 `agent-git-resume`으로 이어갈 수 있다.
실행 파일이나 서버 CLI만으로 GitHub 앱 도구를 호출할 수 없으므로 메인 Codex가 없는 단독 실행은
`awaiting_github`에서 대기한다. `READ_ONLY=1`·데모·사용자가 로컬만 요청한 `GIT=0`에서는 게시하지 않는다.
기존 사용자 변경을 포함하는 전체 `git add`, 강제 push, 규칙 우회, 임의 CI 생략은 하지 않는다.
작업 시작 파일과 원격 기준 파일이 다르면 GitHub 쓰기 전에 중단한다. 초기 하네스 등 기존 변경을
처음 게시하려면 그 변경의 구체적인 파일 목록과 게시 범위를 별도 확인한다.

`TAVERN_WORKFLOW_CHILD=1`인 작업자·검토 세션은 자동 실행기를 호출하지 않는다.
작업자는 배정받은 파일만 다루고 다른 에이전트를 재실행하거나 재위임하지 않는다.
검증은 실행기가 담당한다. 설명·진단 질문에는 유료 구현 흐름을 자동 실행하지 않는다.

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
