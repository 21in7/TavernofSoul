# TavernofSoul 작업 지도

현재 자동 검증은 [ADR0031](docs/adr/0031-change-scoped-automatic-validation.md)이 우선한다.
실제 diff로 검사하고 master push·PR·수동 CI, 핵심 회귀·수동 targets와 기존 권한 경계를 유지한다.

재개된 Git 성공의 추가 보관은 [ADR0028](docs/adr/0028-resumed-run-result-archives.md)을 따른다.
trusted parent의 `python -m harness.archive --run-id 원래_run --resume-failed-to-passed`만
원래 검토·diff·검증과 완료 Git/cleanup 증거를 연결해 별도 고정 세대에 보관한다. 최초 실패는
불변이며 일반 archive는 changed-result를 계속 거부한다. worker/discovery는 storage 전 거절하고
CLI/환경을 인간 신원 증명으로 쓰지 않는다. 모델·검사·Git·승인·스케줄을 재실행하지 않는다.
44개 승인과 runtime 연구37개 scope·128KiB/전체1.5MiB 상한은 별개다. 최종 새 Claude 의미 검토·
기본 GIT=1 full make check·scoped apply·기존 Git 역할과 실제 보관/readback은 parent 책임이다.

잠금·진단은 [ADR0027](docs/adr/0027-inspection-lock-isolation-and-diagnostics.md),
진행 보존은 [ADR0025](docs/adr/0025-progress-preserving-improvement-reviews.md), 실제 Read와
제안 보존은 [ADR0026](docs/adr/0026-source-verified-retained-improvement-reports.md)을 따른다.
각 ADR의 과거 실행·관측과 실패 기록은 보존하며 새 성공 증거로 재사용하지 않는다.
workflow 실행 소유권과 source capture/apply/cleanup 잠금을 분리하고 모델·검증은 격리한다.
source busy는 no-call이며 sealed 검토는 live 승인 권한이 아니다. 원본 baseline 전체 충돌·
signed claim freshness·rollback의 외부 사용자 편집 보존, 기존 lock inode/ownership을 유지한다.
오전 freeze는 admission 전, publication은 state/source 잠금 밖에서 frozen digest POST/GET을 쓴다.
unknown 자동 POST·fallback 저장·잠금 밖 state 쓰기·추가 scan/자동 retry는 없다.
private 최초 실패의 정제 detail은 scan/slot/9단계 owner·call_started_at/call_finished_at에 연결해 참여·history·
status·bounded feedback에 보존한다. cloud192건과 별도 local192건은 같은 state 트랜잭션에 있다.
후속 성공은 이전 실패를 지우지 않는다. legacy 상세는 unknown/unavailable이며 과거 원인을 추정하지 않는다.
runtime37개·128KiB/1.5MiB·9단계·예산/auth·승인/실행 scope와 스케줄·frozen 보고는 유지한다.
전체 diff의 새 Claude 의미 검토·GIT=1 full make check·scoped apply·기존 Git 역할 및 parent의
GitHub 게시/CI3/merge/cleanup·실제 hourly 관측은 별도 필수다. worker는 검사하지 않는다.

이 저장소는 Tree of Savior 게임 데이터를 수집·파싱하고 Django로 제공한다.
전체 흐름과 책임 경계는 [docs/architecture.md](docs/architecture.md),
검증 범위와 환경 준비는 [docs/harness.md](docs/harness.md)를 먼저 확인한다.

2026-10-19 저장·검증 정책: 사용자 직접 요청에 따라 명시 v2는 개발 작업·검증을 로컬 active
artifacts/temporary에서 수행하고 remote archive에는 terminal 결과 allowlist 묶음만 보관한다.
[ADR0021](docs/adr/0021-local-work-and-result-archives.md),
[ADR0022](docs/adr/0022-documentation-only-validation.md)이 아래 역사적 NFS 유지 지시를
**개발 작업 저장 선택에 한해서** 대체한다. v1/no-config·기존 explicit 설정은 호환 유지하며
옛 NFS 기록·absolute journal은 보존한다. 원래 v1 config를 명시 선택해 옛 run을 조회·재개한다.
archive를 status/find_run/progress 검색 root나 active journal 대체물로 사용하지 않는다.
daily/hourly·게임 cron·approval 기록과 모델/역할/인증 설정은 바꾸지 않는다. 실제 private 기본값
전환은 코드 검토·검증 후 parent가 담당하며 worker에게 private 설정·credential을 제공하지 않는다.

## 영역별 진입점

- 다운로더·압축 해제·번역 준비: `downloader/`와 [downloader/AGENTS.md](downloader/AGENTS.md).
- 파싱·JSON 출력: `parser_tidy/`와 [parser_tidy/AGENTS.md](parser_tidy/AGENTS.md).
- DB 적재·HTTP 서빙: `TavernofSoul/`와 [TavernofSoul/AGENTS.md](TavernofSoul/AGENTS.md).
- 공통 검증: `Makefile`, `harness/`; 실행은 저장소 루트에서 한다.
- 개발 에이전트 모델 연결: `harness/agent-models.json`, `harness/agent_models.py`,
  [docs/agent-models.md](docs/agent-models.md). 인증 점검은 `make agent-doctor`로 한다.
- 개발 작업 자동 배정·실행: `harness/workflow.py`, `harness/workflow-config.json`,
  [docs/workflow.md](docs/workflow.md). 실행은 `make agent-workflow`, 진행 확인은 `make agent-workflow-status`.
- 승인 대기 개선 연구·오전 보고: `harness/improvement_loop.py`, `harness/local_model.py`,
  `harness/improvements.py`, `harness/improvement_report.py`, [docs/improvements.md](docs/improvements.md),
  [docs/local-models.md](docs/local-models.md). 시간별 연구·09:00 한 번 보고·사람의 승인/실행을 분리한다.
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
후속 수리 검토에서도 매번 최종 코드와 문서의 의미적 완전성을 새로 판단한다. 앞선
`documentation.updated`나 Markdown 확장자 검사를 다음 검토의 승인 근거로 재사용하지 않는다.

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

사용자는 직접 요청한 개발 작업의 GitHub 커밋·브랜치 게시·PR 생성·CI 성공 후 머지까지 허용했다.
이 허가는 에이전트가 자율 발견한 개선 제안에는 적용하지 않는다. 이번 승인 게이트 기반 기능의
구현과 GitHub 전달은 명시적으로 승인되었지만 이후 발견된 제안은 각각 별도 승인 대상이다.
자동 점검은 승인된 개별 파일만 읽고 서로 검토하여 한국어 비유를 담은 한 장 보고서를 만든다.
점검 중 소스 수정·검사·Git·workflow 실행·운영 파이프라인·cron 설치를 하지 않는다.
보고서의 `eligible`이나 '제안 <ID> 승인' 문구는 실행 허가가 아니다. 메인은 사용자의 구체적인
제안 ID별 명시적 지시를 확인하고 private 0600 UTF-8 instruction 파일로 `approve`를 호출한 뒤,
그 승인에 묶인 정확한 파일·내용만 `execute`로 실행한다. task/files 덮어쓰기나 approve-all은 없다.
7일 이내 승인도 읽은 소스의 bytes·mode·존재, scope/config, 독립 검토가 바뀌면 사용할 수 없다.
loop 제안은 loop/local/agent/workflow 설정 digest까지 freshness와 서명 승인에 결합한다.
같은 후보가 바뀐 설정에서 재발견되어도 이전 승인을 재사용하지 않는다.
일회성 claim 이후 실패·중단·대기는 재실행 허가가 아니다. 기존 run/journal을 먼저 조정하고,
필요하면 새 명시적 승인으로 복구한다. 직접 요청한 일반 개발 작업의 기존 권한은 유지한다.

신뢰한 parent만 사람의 지시를 승인으로 기록한다. CLI·환경 변수·보고서는 사람의 신원을 증명하지
못하며 같은 OS 계정을 장악한 공격자까지 방어하는 경계가 아니다. scheduler는 반드시
`TAVERN_IMPROVEMENT_UNATTENDED=1`로 새 `tick`만 호출하며 approve/reject/execute를 호출하지 않는다.
`TAVERN_WORKFLOW_CHILD` 또는 `TAVERN_IMPROVEMENT_DISCOVERY` 세션은 개선 orchestration을 금지한다.
owner-private Sites 보고함에는 두 정제 계약만 전달한다. 불변 오전 보고는 `improvement-web-v1`,
사용자가 별도로 전송을 허용한 승인 제안 완료는 `improvement-completion-v1`이다. 승인 지시·키·절대 호스트
경로·소스·diff·프롬프트·원문 응답·로그는 보내지 않는다. credential은 메인만 관리하며 모델에 제공하지 않는다.
사용자 최신 선택은 [ADR 0017](docs/adr/0017-budgeted-continuous-improvement.md)의 bounded hourly
tick이다. 기존 daily-only/하루 5회/one-pass 정책을 이 자동 탐색에 한해 대체한다. 각 tick은 모델
최대 1회, 로컬 포함 KST 하루 최대 24회, Claude 추정 ledger 하루 US$1·reviewer cap US$0.20이다.
구현 workflow 비용은 별도이며 CLI cap은 실제 청구 강제상한 보장이 아니다. GLM은 기존 Coding Lite
인증을 유지하고 매 admission 전에 trusted parent가 quota를 조회한다. model limit>=80% 또는
실패/unknown/malformed이면 GLM을 보류해 명목 20% 개발 여유를 남긴다. 유료 fallback은 없다.
TOKENS_LIMIT/CREDIT_LIMIT 모두 인식된5h window의 정확한 finite numeric0%(bool 제외)만
absent/null reset을 idle로 허용하며 private null을 미상·미활성으로 유지한다. weekly에는 이
예외가 없고 잘못된 reset·실패 envelope·model limit 부재를0%로 해석하지 않는다.
기본 단계는 local(coordinator)→coordinator→local(downloader)→downloader→local(parser)→parser→
local(django)→django→Claude 독립 검토다. local은 작은 연속 line window와 정제 feedback만 받고,
초안은 기존 specialist 근거 확인 전까지 정식 proposal이 아니다. local 실패/빈 초안에도 관련
specialist와 최종 reviewer는 각 정규 slot에서 승인 소스를 독립 점검한다. 기존 37개 읽기 승인과 ownership/shared는 확대하지 않는다.
로컬 초안의 최종 프로토콜은 mlx-vlm 0.7.8 네이티브 JSON Schema constrained generation이다.
`local-model-config-v2`의 provider는 `mlx-vlm`, `api_model`은 `model`의 상대 repository ID와
정확히 같아야 한다. `default_model` 별칭이나 절대 호스트 경로를 요청하지 않으며 v1 mlx-lm
설정을 자동 변환하지 않고 `config_invalid`로 보류한다. config digest의 프로토콜 전환은 기존
loop fingerprint와 승인을 무효화한다. Linux 어댑터는 Python3.8 표준라이브러리만 사용한다.
전체 요청에는 `response_format={"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":...}}`와
top-level `enable_thinking=false`를 넣는다. 서버는 llguidance logits processor로 스키마를 강제한다.
스키마는 정확한 `{candidates:[...]}`와 기존 후보 계약, owner 승인 edit_files, 실제 한 window의
evidence 경로·원문 줄 범위를 표현한다. benefit.evidence도 같은 범위다. 전송 전 전달 window와
승인 목록에서 canonical schema를 다시 구성해 대조하며 schema 제거·완화나 window/scope/
enable_thinking 변조를 거절한다. schema를 포함한 전체 HTTP 요청 상한24576bytes 안에서
whole-line window를 선택하며 스키마만으로 넘으면 `context_too_large`로 호출하지 않는다.
기존 strict parser·공유 후보 검증·실제 읽은 줄 검증이 최종 권위다. 스키마는 의미 오류를 모두
막지 못하며 서버가 무시하거나 위반해도 거절한다. 경로/줄 보정·근거 합성·재시도·fallback은 없다.
편집 목록의 고정 진단 `candidate_edit_files_invalid`, `candidate_edit_files_duplicate`,
`candidate_edit_files_outside_scope`를 유지한다. 노출은 allowlist 코드만 허용하고 원문·프롬프트·소스·절대 호스트 경로를
로그·보고서·public web-v1에 넣지 않는다. 상세 요청·배포 계약은 [로컬 모델 문서](docs/local-models.md)를 따른다.
hourly 실패 진단의 API·allowlist·provenance와 저장/복구 계약은 ADR0027을 따른다.
신뢰한 실제 adapter/validator 발생 경계에서만 원인을 만들고 allowlist에 속한 runner reason도 표식 없이 믿지 않는다.
runner diagnostic/예외문이나
stdout의 인증/readonly/401 문구를 실패 근거로 삼지 않는다. CLI 경고와 실제 실패를 구별하며
명확한 증거가 없으면 cli_failed/unavailable이다. 공유 후보 검증의 field/rule과 기존 편집 목록
세 reason을 유지하고 원문·소스·prompt·credential·절대 경로·provider 자유 문자열을 새 진단에 넣지 않는다.
private 참여/slot/history/status/다음-round feedback만 상세를 전달하고 public web-v1/completion-v1·
digest·journal·과거 frozen 보고는 그대로다. 최초 예외/진단·identity/context/비용/중단 의미와 기존
후보·review·한국어/근거 검증을 보존한다. fake/Lab 회귀는 작성만 하며 실제 hourly 성공은 미관측이다.

잔액 판정은 reviewer admission에 적용한다. 그 차례 전 역할은 다른 gate 내 진행하지만 예산
보류는 stage를 유지하므로 이후 새 slot에서도 reviewer를 재판단하고 다음 local/구독 역할도
대기가 풀릴 때까지 멈춘다. 09:00 보고 확정은 이 대기와 독립적이다.
보고는 전날09:00~당일09:00의 현재 전체 의존성 일치 검증된 완료 회차에서 ID별 최신 verdict를 모아 당일
09:00 이후 첫 tick에 불변 확정한다. 기존 day는 보존하고 그날 다시 생성·중복 게시하지 않는다.
최대8 후보/3카드 web-v1을 유지하고 local 참여·endpoint·비용은 private에만 둔다. 미완료는
partial/failed로 표시한다. 전송 unknown은 자동 재시도하지 않고 메인이 같은 digest만 조정한다.
2026-10-16 정정: 최초 로컬 초안은 JSON 파싱 뒤 `candidate_invalid`로 검증 거절됐다.
형식 검증에서 제외된 것이 아니며 원문 미보존으로 당시 정확한 실패 필드·값은 알 수 없다.
별도 재현의 edit_files 거절과 evidence window 위반은 최초 응답의 확정 원인이 아니다.
과거 약19.54초 합성 추론 성공과 메인이 제공한 mlx-vlm 네이티브 schema 프로토타입 관측은
최종 어댑터 검증과 구분한다. prompt/order 수리 두 실행은 Claude 검토 뒤 실제 추론에서 다시
승인 밖 edit_files를 냈고 full check 중 중단되어 모두 `applied=[]`다. 성공·완료가 아니며
마지막 승인 범위의 복원 초안은 참고용으로 새 검토·전체 검증이 필요하다. 숫자 파일 ID/window
evidence 합성 실험은 실패했고 구현하지 않는다. canonical 경로와 원문 줄 번호 계약을 유지한다.
최종 어댑터의 신규 서버 실제 추론·전체 make check·실제 repository 첫9단계·다음 아침 게시
성공은 메인의 관측 전까지 주장하지 않는다. 서버 설치·SSH·서비스·실제 추론·private config
전환은 메인이 담당하며 작업자·검토자는 검사·네트워크·Git·SSH·서비스·재위임·workflow를 실행하지 않는다.
메인의 서버 compiler/null metadata·실제입력/합성입력 및 특정 미검토 초안의 사전 추론 관측은
[로컬 관측](docs/local-models.md#메인이-제공한-서버-호환-관측과-남은-검증)의 근거 수준으로 한정한다.
정상 assistant의 tool_calls:null/tool_call_id:null만 무동작 metadata로 받고 non-null/다른 도구
필드는 거절한다. uniqueItems는 서버 미지원이므로 client 중복 검증을 유지한다.
현재 승인21개는 coordinator 작업1개로 완성한다. 검증 사본 재사용은 parent의 NFS 원본 baseline
동일성 재확인 후 준비 절차이며 성공이나 local fallback이 아니다. 새 Claude 의미검토·full make
check·두 umask077/022 권한 fixture 검증·scoped apply와 메인의 최종 추론/서비스·private config
전환은 별도 필수다. 다른 jobs·게임 cron·명시 daily local storage·persistent NFS default를 보존한다.
메인 제공 기존 상태는 hourly wrapper 활성·2026-10-16 09:00 partial/제안0개 보고1회 전달이며
확정 보고는 재생성하지 않는다. 신규 프로토콜의 최종9단계·다음 아침 게시 성공과 구분한다.
tick의 설정 로드·Store 생성·저장소 readiness 실패는 bounded 정제 paused로 처리하고 모델·키 조회·
보고 확정·publisher·fallback을 하지 않는다. child/discovery 거부는 이 처리 바깥에 유지한다.
설정된 저장소 readiness 실패 시 자동 fallback하거나 점검을 재시도하지 않는다. 정확한 CLI·
자정/legacy 이행·journal 복구·main 관측/미검증 상태는 [운영 문서](docs/improvements.md)에 둔다.

기본 쓰기 작업은 `git` 역할(Codex `gpt-6.1-sol`, `medium`)까지 실행한다. 보고서가
`awaiting_github`이면 메인 `/root`는 완료로 보고하거나 다시 허락을 묻지 않고 다음을 이어 실행한다.
표준 parent 경로는 [ADR0024](docs/adr/0024-immediate-batched-github-transport.md)의
`harness/git_bridge.js`를 workflow 시작 전에 읽어 eval하고 tools·private load/store·artifact 연결·
sleep/yield를 주입하는 것이다. 이미 시작한 exec 결과를 `bridge.handoff(result,
{readOnly:false,demo:false,git:true})`에 넘기면 정상 종료와 마지막 실제 awaiting_github summary를
확인한 같은 async 흐름에서 즉시 게시를 잇는다. [호출 예시·복구](docs/workflow.md#trusted-parent-bridge와-즉시-handoff)를 따른다.
bridge는 `python3 -m harness.git_transport request|accept`로 기존 native main 전체를 호출한다.
accept 한 shell 호출 안에서 stdin 응답 저장·fsync·native 검증·다음 요청 반환을 처리한다.
32KiB까지 inline, 초과 결과만 private payload의 bounded chunk·size/hash 검증으로 읽는다.
응답 처리에서 반환된 다음 요청을 직접 실행하며 `poll_after_seconds`만큼 기다린다.
기존 `make agent-git-request`/`agent-git-accept`/resume/cleanup은 명시 복구 경로로 보존한다.
이미 반환된 쓰기를 `agent-git-request`로 재발급하지 않는다. 도구 이름은 실행기의
GitHub 허용 목록과 비교하며, 도구 인자를 셸 명령으로 실행하지 않는다. 파일 내용이 포함된 요청은
사용자 터미널에 출력하지 않는다. 새 PR URL은 생성 직후 `codex_app.attach_artifact`로 반드시 연결한다.
커넥터 오류는 `isError=true` 응답으로 실행기에 전달하고, `needs_reconciliation`이나 결과가 모호한
쓰기는 재시도하지 않는다. 원래 요청 ID로 실제 결과를 확인할 때만 이어 실행한다.
receipt·unknown dispatch·잘림·invalid JSON은 새 request 또는 쓰기 재전송의 근거가 아니다.
기존 receipt가 있으면 자동 cached 요청 반환도 하지 않고 private saved response/native journal을
parent가 대조한다. worker/reviewer·child/discovery에는 transport/bridge·앱 실행 권한이 없다.
이번 harness 변경은 기존 publisher 회귀와 함께 full `make check`가 필수이며 parent가 실행한다.
parent는 후속 실제 bridge 사용과 구현 PR·별도 문서 PR의 required CI·merge·cleanup/archive,
PR54와 동일 구간의 시간을 관측한다. synthetic 테스트를 실제 PR 개선으로 보고하지 않는다.
세 CI(`Offline harness (SQLite)`, `MySQL harness`, `Chromium browser harness`)의 실제 success와
GitHub `merged=true`·merge SHA 확인이 게시·머지 완료 기준이다. required의 skip/neutral·실패는 계속 거부한다.
[ADR0022](docs/adr/0022-documentation-only-validation.md)의 예정 heavy skip 예외는 정확히
`Offline execution (SQLite)`, `MySQL execution`, `Chromium browser execution`의 completed/skipped뿐이다.
각 skip과 같은 SHA·GitHub Actions·동일한 양의 정수 check_suite.id 안의 최신 selection success,
세 required success와 세 execution의 계획상 success/skipped 전체를 요구하며 전체 이름별 최신 selection/required도 success여야 한다.
최신 selection/required의 suite metadata도 유효해야 하며 잘못된 metadata를 옛 성공으로 보완하지 않는다.
다른 suite의 성공을 합치거나 최신 failure/pending을 우회하지 않는다. 먼저 도착한 skip은 증거가
완성될 때까지 `waiting_for_ci`로 대기하며 불명 suite도 성공이 아니다. 임의 skip과 실제 실패는 거부하고
추가 실행 중인 job도 기다린다. 충돌·권한 부족은 실제 상태를 보고한다.
30분 제한에서 `awaiting_ci`이면 기존 PR을 `agent-git-resume`으로 이어갈 수 있다.
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
fresh cleanup CI에도 같은 예정 skip 증거를 새로 요구한다. 미완료·잘못된 proof는 정리를 막고
확정 merge SHA를 보존하며 기존 cleanup 재개 절차를 따른다.

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

[ADR0020](docs/adr/0020-automatic-proposal-completion.md)에 따라 `git_publish`의
request/accept/resume/cleanup은 최종 save와 project/GitHub lock 해제 후에만 lazy import로
`improvement_completion.complete_run`을 호출한다. signed claim의 정확한 run 연결·signed approval·
제안/독립 검토·실제 구현 review/validation·편집 범위·CI 3종·merged SHA·verified cleanup proof와
cleanup complete를 검증한 뒤 private durable outbox를 전달한다. 완료 시점에는 실행 전의 freshness/
만료 검사를 다시 적용하거나 승인을 소비하지 않는다. 여러 signed claim도 각각 검증하며 일반 bundle
승인 권한을 추가하지 않는다. claim 없는 일반 작업은 키/credential/HTTP 없는 no-op이다.
child/discovery/unattended·read_only/simulated/GIT=0/local-only에는 전송하지 않는다.
POST만으로 delivered가 되지 않으며 동일 frozen payload/digest의 GET readback이 필요하다.
unknown/sending 자동 재호출은 GET만 수행한다. `make agent-improve-completion RUN_ID=... RECONCILE=1`은
GET absent 확인 뒤에만 같은 digest POST를 허용하고 conflict는 보존한다. 전달 실패는 별도 completion
결과이며 passed/merge/cleanup을 바꾸지 않는다. 새 모델·승인·execute·Git·cron/tick 연결은 없다.
Sites API/UI 구현·배포와 credential 관리는 메인 책임이며 저장소의 offline 명세는 실제 배포 성공이 아니다.

`TAVERN_WORKFLOW_CHILD=1`인 작업자·검토 세션은 자동 실행기를 호출하지 않는다.
작업자는 배정받은 파일만 다루고 다른 에이전트를 재실행하거나 재위임하지 않는다.
작업자·검토자는 검사·Git·브랜치 정리를 실행하지 않는다. 검증은 실행기, 게시·머지 후 정리는
메인 `/root`가 담당한다. 설명·진단 질문에는 유료 구현 흐름을 자동 실행하지 않는다.

1. 변경 전 작업 트리 상태를 확인하고 기존 사용자 변경을 보존한다.
2. 최종 baseline→candidate 변경으로 검증을 선택한다. full 경로에서는 `make doctor`로 환경을
   확인하고 필요하면 `PYTHON=/path/to/python`을 지정한다. docs-only에는 game dependency doctor를 요구하지 않는다.
3. 다운로더 변경은 `make check-downloader`, 파서 변경은 `make check-parser`,
   Django·importer 변경은 `make check-django`를 실행한다.
4. 데이터 계약·연결부·하네스·CI·정책 변경은 기존 필수 검증을 유지한다. 실제 변경이 허용 prose
   (`README.md`, `docs/**/*.md`)뿐이면 `check-docs`를 선택할 수 있다. `AGENTS.md`,
   `docs/workflow.md`, `docs/harness-design.md`, 공통 설정/CI/Makefile, mode/type/symlink 변화,
   불명/빈 증거는 full이다. 영역 코드는 실제 변경의 경로·설정·추천으로 기존 영역 검사를 선택한다. 읽기 scope나 모델 주장은 선택 근거가 아니다.
   repair마다 다시 판단하며 삭제·rename의 양쪽 경로와 남은 역참조를 검사한다.
5. 결과는 선택된 active artifact root에서 확인한다(설정 없으면 `logs/harness/`). 선택된 검사는
   positive selected/passed와 zero skip/failure/error를 요구하며 빈/옛 보고서는 완료로 처리하지 않는다.
6. 기본 검증에서 제외한 실데이터 테스트와 추가 검증의 수행 여부를 구분해 보고한다.

v2는 remote work/active/report를 거부하고 local floor/no-follow/lock을 유지한다. archive 파싱은
lexical/type/overlap만, 실제 mount/floor/private는 ARCHIVE에서 검사한다. Git 최종 save→두 lock
해제→completion hook 뒤 terminal 결과를 보관한다. awaiting_github/awaiting_ci/cleanup_pending은
거부한다. 실패/중단/GIT=0도 성공으로 바꾸지 않으며 archive pending/nonzero는 merge/cleanup과
별개다. 일반 `make archive-run RUN_ID=... KIND=workflows`는 frozen/current 불일치를 거부한다.
workspace/.git/model context/credential/lock/private config/승인 지시는 제외한다. 원본·검증
workspace/backup/journal은 보존하며 owned 임시 context cleanup만 한다. 명시 추가 보관은0028이다.

docs checker는 Python 3.8 표준라이브러리로 링크·heading/fragment·역참조 등을 오프라인 검증한다.
복잡한 Markdown의 지원 한계와 최종 내용의 의미적 완전성은 Claude 검토 책임으로 남긴다.
공개 Git 관리 소스 [.github/workflows/harness.yml](.github/workflows/harness.yml) 참조는 credential
접근이 아니며 CI 파일 수정 자체는 full이다. CI complete PR diff는 docs-only일 수 있다.
[ADR0031](docs/adr/0031-change-scoped-automatic-validation.md)에 따라 작업 branch push는 자동 실행하지 않는다.
ADR0023의 완전한 새 branch 비교 구현은 직접 호출 호환용으로 보존한다. unknown/workflow_dispatch는
전체 CI이며 세 required check는 계획과 모든 실제 실행 또는 기존 docs 증거를 확인한다.
skipped/neutral을 success로 취급하거나 branch protection·권한·lock·CI를 우회하지 않는다.

이번 저장/검증 구현은 harness·CI 변경이므로 docs-only 대상이 아니다. 이전 run
`1792414748889186714-9305b2`의 900초 coordinator timeout과 `applied=[]`, 복원 초안·미실행
테스트는 성공 근거가 아니다. parent가 새 실제 Codex 작업·Claude 의미 검토·전체 `make check`·
CI·GitHub 전달 증거를 확보한다. 작업자·검토자는 실행하거나 통과했다고 주장하지 않는다.

## 데이터와 실행 경계

- 기본 검증은 작은 고정 입력, 임시 파일, SQLite 메모리 DB를 사용한다.
- `settings_test.py`는 MySQL과 기존 JSON 디렉터리를 가리킨다. 격리 설정으로 간주하지 않는다.
- 검증을 위해 지역별 cron, 다운로더 전체 실행, 운영 `importAll`을 실행하지 않는다.
- `*_patch/`, `*_unpack/`, `Translation/`, `JSON_<region>/`, 버전 CSV는 로컬 실행 상태다.
  소스 수정의 부수 작업으로 초기화하거나 덮어쓰지 않는다.
- `*_unpack/`과 `IPFUnpacker/`에는 별도 Git 소유권이 있다. 작업 범위를 확인한다.
- 데이터 형식·단위·ID 처리 규칙을 바꾸면 경계 문서와 관련 검증을 함께 갱신한다.

### 원격 archive 완료 계약 (2026-10-19)

로컬 freeze의 directory no-replace rename과 원격 게시를 구분한다. NFS archive는 exclusive
private 결과 디렉터리·로컬 transfer receipt·bounded 파일 준비/검증과 no-replace 파일 link를
사용한다. 마지막 commit.json과 정확한 inventory/hash·최종 0600/nlink=1 readback 전에는 완료가
아니다. receipt에 고정된 임시/최종 이름의 동일 inode/nlink=2 전이만 정리하며 알 수 없는
hardlink·충돌·조작을 덮어쓰거나 삭제하지 않는다. prefix가 정확한 부분 파일만 append한다.
mkdir 뒤 receipt 전 중단은 pending으로 남겨 main이 판단한다. 일반 rename fallback은 금지한다.
main의 directory rename EINVAL/파일 link probe는 최종 어댑터 통과가 아니다. 이번 구현은 새
Claude 의미 검토·full make check·실제 NFS 검증·GitHub/CI가 필요하며 workers는 실행하지 않는다.
