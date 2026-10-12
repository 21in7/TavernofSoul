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

업무 시작 시 문서 영향을 판단한다. 구조·책임·데이터 계약·격리·검증·실패 복구·GitHub 게시
정책을 바꾸면 관련 설계·경계 문서를 갱신하고, 주요 결정은 신규 ADR 또는 대체 ADR로 남긴다.
[전체 하네스 설계](docs/harness-design.md)와 [ADR 목록·작성 규칙](docs/adr/README.md)을 진입점으로 쓴다.
단순 오타·동작 불변 국소 수정은 문서 갱신이 불필요할 수 있으나 reviewer가 구체적인 이유를 기록한다.
필요한 문서도 개별 읽기 승인 목록에 포함해야 한다. 승인 밖 문서를 자동 열람·복사·생성하지 않는다.
필요 문서가 scope 밖이면 누락 경로를 보고하고 기존 승인 파일에 finding을 귀속해 승인을 거부한다.
메인이 범위를 확인한 뒤 필요한 개별 파일을 승인받아 새 실행을 준비하며 수정 라운드에서 범위를 넓히지 않는다.
매 검토는 필수 `documentation={status, files, reason}` 판단을 반환한다. `updated`는 승인 범위의
실제 변경 `.md` 파일을 하나 이상, `not_required`는 빈 files와 구체적 생략 이유를 요구한다.
`missing`은 `changes_requested`와 승인 파일 finding을 요구한다. 누락·형식 오류·모순은 실패이며
문서의 의미적 완전성은 reviewer가 판단한다. 읽기 전용·데모도 같은 판단 형식을 사용한다.

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
세 CI(`Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`)의 실제 success와
GitHub `merged=true`·merge SHA 확인이 게시·머지 완료 기준이다. CI 실패·누락·skip/neutral, 충돌, 권한 부족은 PR을 유지하고
실제 상태를 보고한다. 30분 제한에서 `awaiting_ci`이면 기존 PR을 `agent-git-resume`으로 이어갈 수 있다.
실행 파일이나 서버 CLI만으로 GitHub 앱 도구를 호출할 수 없으므로 메인 Codex가 없는 단독 실행은
`awaiting_github`에서 대기한다. `READ_ONLY=1`·데모·사용자가 로컬만 요청한 `GIT=0`에서는
원격 게시·삭제나 로컬 refs 정리를 자동 실행하지 않는다.
기존 사용자 변경을 포함하는 전체 `git add`, 강제 push, 규칙 우회, 임의 CI 생략은 하지 않는다.
작업 시작 파일과 원격 기준 파일이 다르면 GitHub 쓰기 전에 중단한다. 초기 하네스 등 기존 변경을
처음 게시하려면 그 변경의 구체적인 파일 목록과 게시 범위를 별도 확인한다.

[ADR 0009](docs/adr/0009-post-merge-branch-cleanup.md)에 따라 기존 `codex/<run_id>` → `master`
squash PR을 유지한다. 별도 릴리스 통합 요구가 없으므로 `dev`는 도입하지 않는다. 매 작업의
머지 뒤 메인 `/root`가 해당 원격·로컬 작업 브랜치와 사라진 원격 추적 ref를 정리한다.
이번 사용자 요청으로 확인된 누적 작업 브랜치도 PR별로 같은 조건을 적용할 수 있다.
대상별 repository/origin/base/head/PR 관계, PR merged 상태·확정 merge SHA·머지 당시 PR head SHA를
확인하고, fetch한 `origin/master` 이력에 merge SHA가 포함돼야 한다. 삭제 직전 원격·로컬 tip을
각각 머지 당시 head SHA와 대조한다. 이후 커밋·로컬 전용 커밋·증거 불명확이면 해당 대상을 보존한다.
`git branch --merged`만으로 squash 머지를 판단하거나 prefix만으로 일괄 삭제하지 않는다.
기본 `master`/`main`, 이미 있는 `dev`, 보호 브랜치, 작업 중·미머지 PR 브랜치,
다른 worktree에서 사용하는 브랜치는 보존한다.

원격 자동 삭제를 가정하지 않고 정확한 ref의 부재를 확인한다. 남아 있으면 안전 조건을 충족한
정확한 브랜치만 기존에 인증된 지원 도구로 삭제한 뒤 재조회한다. 도구·권한 부족, 모호한 결과,
ref 잔존은 `cleanup_pending`과 구체적 사유로 보고한다. 앱 게시·merge journal은 계속 사용하되
브랜치 삭제는 현재 구현돼 있지 않다. 저장소 보호 변경·강제 push·자격증명 수집은 하지 않는다.

로컬 변경·staged·untracked, 로컬 전용 커밋과 모든 worktree 상태를 먼저 확인하며 무조건
checkout/reset/clean/stash하지 않는다. 깨끗한 작업 트리에서 기준 이력·worktree 사용이 안전하면
`master`로 전환하여 `git fetch --prune origin`, `git pull --ff-only origin master`로 동기화한다.
앱에서 게시된 변경만 미커밋으로 남았으면 승인·검증된 manifest와 확정 머지 결과, 현재 파일의
bytes·권한 및 추가·삭제 파일의 존재 여부·index 상태를 개별 대조한 파일만 동기화할 수 있다.
다른 사용자 변경·로컬 전용 커밋·충돌·불명확한 상태는 보존하고 해당 정리·동기화를 보류한다.
로컬 브랜치가 없으면 `없음`으로 기록한다. 안전 조건을 충족하고 해당 브랜치에서 벗어난 뒤
`git branch -d <정확한 작업 브랜치>`를 우선한다. squash 이력 때문에 거부될 때만 PR merged·
merge SHA의 기준 이력 포함·tip 동일성·추가 커밋 없음·모든 worktree에서 미사용을 재확인하여
그 정확한 브랜치에 한해 `-D`를 허용한다. blanket `-D`는 금지한다.

머지와 정리 결과는 분리한다. 별도 private cleanup 기록과 메인 최종 결과에 PR URL·merge SHA,
원격 삭제/이미 없음, 로컬 삭제/없음, prune·기준 브랜치 동기화 결과 및 대상별 보류 이유를 남긴다.
`harness/git_publish.py`의 `report.status=passed`는 머지 확인 결과이며 cleanup을 구현하지 않는다.
이 정책은 JSON 상태 schema나 실행기 동작을 바꾸지 않는다. `cleanup_pending`이면 정리까지
전체 완료했다고 주장하지 않는다. 상세 절차는 [workflow](docs/workflow.md#머지-후-브랜치-정리)에 둔다.
2026-10-12 메인이 제공한 clean `master`·로컬 `master`만 존재, `delete_branch_on_merge=false`,
앱 삭제·설정 수정 도구 부재 및 `/root`의 `make doctor` 통과는 초기 관측일 뿐 자동 삭제 활성화나
실제 정리·check·CI 성공의 증거가 아니다. 실행 시 재확인하며 기본 check·CI는 실행기 책임이다.
private 작업·로그·응답 원문을 공개 문서에 복사하지 않는다.

`TAVERN_WORKFLOW_CHILD=1`인 작업자·검토 세션은 자동 실행기를 호출하지 않는다.
작업자는 배정받은 파일만 다루고 다른 에이전트를 재실행하거나 재위임하지 않는다.
작업자·검토자는 검사·Git·브랜치 정리를 실행하지 않는다. 검증은 실행기, 게시·머지 후 정리는
메인 `/root`가 담당한다. 설명·진단 질문에는 유료 구현 흐름을 자동 실행하지 않는다.

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
