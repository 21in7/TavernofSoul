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
- GitHub 자동 게시·병합·정리: `harness/git_publish.py`, `harness/git_cleanup.py`, `harness/git-publish-config.json`.
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

[ADR 0010](docs/adr/0010-automatic-post-merge-cleanup.md)에 따라 머지 응답 직후 journal이
새 GitHub 읽기 proof를 요청하고 신뢰한 parent의 `harness/git_cleanup.py`를 자동 실행한다.
기존 `codex/<run_id>` → `master` squash PR과 게시 앱 허용 목록은 유지한다. 삭제 대상은 해당 run의
정확한 작업 브랜치 하나다. `dev` 추가나 누적 브랜치 일괄 정리는 이 흐름에 포함하지 않는다.
머지 성공과 확정 SHA는 영구 보존하며 원격·로컬 삭제/없음, tracking prune, clean base의 ff-only
동기화와 완료 직전 재확인이 모두 끝나야 `report.status=passed`다. proof 대기는 cleanup 단계의
`awaiting_github`, 실패·보류는 대상별 이유를 가진 `cleanup_pending`과 non-success 반환이다.

메인은 accept가 반환한 기존 앱의 fetch 요청을 계속 실행한다. proof는 merged PR의 repository,
base.ref, 고정 head와 확정 merge SHA, 세 CI success와 commit status, 새 repository 조회의 default_branch,
정확한 branch tip/보호 여부 및 같은 head의
열린 PR 부재를 확인한다. 머지 후 base.sha 전진은 허용하지만 불완전 collection·조회 실패는
부재의 증거가 아니다. 기본·보호·작업 중·추가 커밋·다른 worktree 점유 브랜치는 보존한다.

원격 삭제는 기존 인증된 로컬 Git만 사용한다. origin의 raw/effective fetch·push URL이 승인 저장소의
credential-free 단일 대상으로 일치해야 한다. 첫 fetch부터 모든 fetch/prune 전에 표준 origin heads →
origin tracking mapping을 검증하고 다른 mapping은 전송·삭제 전에 unsafe_prune_refspec으로 보류한다.
submodule recursion을 끈 fetch로 확정 merge가
origin/master 이력에 포함되는지 확인하고, 정확한 ref와 expected SHA의 explicit force-with-lease로
compare-and-delete한다. 이 lease는 허용된 ref 삭제의 경쟁 방지 조건이다. 내용/이력 강제 push,
보호 우회·--no-verify·다른 ref push·credential 수집은 허용하지 않는다. 응답/timeout 뒤 실제 ref를
재조회하며, 모호한 삭제를 자동 재전송하지 않는다. 안전한 fetch mapping에서 prune과 tracking 부재를 확인한다.

로컬에서는 모든 worktree·operation·dirty/staged/untracked·로컬 전용 commit·base 점유와
ignored/운영 데이터 충돌을 확인한다. 정상 checkout은 base 전환 → fetch/prune → ff-only 동기화 →
작업 ref 삭제로 이어진다. squash도 PR proof·동일 tip·merge 이력·worktree 미사용을 재확인한
`update-ref -d <정확한 ref> <expected SHA>`로만 삭제한다. reset/clean/stash/전체 add/-D는 사용하지 않는다.
앱 게시 후 승인 변경만 미커밋으로 남으면 github-approved.json의 bytes/POSIX mode·index·baseline HEAD와
merge/base tree의 blob/Git executable mode를 대조한 뒤 private durable snapshot과 파일별 checkpoint로
일시 baseline 복원·ff-only를 수행한다. 다른 편집·symlink·mode/content 불일치·collision은 보존한다.

`make agent-git-resume RUN_ID=...`는 기존 awaiting_ci와 merged cleanup_pending을 구분한다.
정리 재개는 새 모델·commit·branch·PR·merge 없이 새 proof와 실제 상태로 남은 단계를 재조정한다.
`make agent-git-cleanup RUN_ID=...`는 이미 merged된 run을 명시적으로 재확인하는 보조 명령이다.
기존 github-v1 설정/journal은 유지하며 이전 merged → passed 기록은 cleanup 완료로 신뢰하지 않는다.
새 CLI의 request/resume/cleanup 경계에서 안전하게 이행한다. GitHub journal lock 전에 프로젝트 lock을
잡아 apply와 cleanup을 직렬화하지만 외부 편집 경쟁까지 사라지지는 않는다. 복구 실패 시 승인 snapshot과
머지 기록을 보존하고 현재 파일이 승인 after/baseline과 같은 경우에만 재개한다.
상세 상태·복구 절차는 [workflow](docs/workflow.md#머지-후-브랜치-정리)에 둔다. private 원문은 공개하지 않는다.

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
